"""Attack the live server the way an agent under pressure to find a "yes" would, and print what stopped each attempt.

  python examples/attack_live.py                          starts a local server on a free port and attacks it
  python examples/attack_live.py --url https://HOST/mcp   attacks a running server

First two honest trials whose answer is known: the planted world must come back SUPPORTED and the null world NOT
SUPPORTED. Then eleven shortcuts, each of which must be refused by the layer the table names, and a second session that
must see none of the first one's files. Exits 1 if anything gets through, is refused by the wrong layer, or an honest
verdict is wrong. CI runs it on every push. Needs `pip install -e ".[mcp]"` (Python 3.10+).
"""
import argparse
import asyncio
import contextlib
import json
import logging
import re
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

ROOT = Path(__file__).resolve().parents[1]
RULE = 'buy the next open after an A/A+ short label (codes -2, -3), sell 20 bars later, 0.10% round-trip cost'
TRUTH = {'planted': ('+2.5% edge planted', 'SUPPORTED'), 'null': ('no edge', 'NOT SUPPORTED')}


def spec(world, **change):
    return json.dumps({'name': f'{world.upper()}-001/v1: {RULE}', 'data': f'data/{world}.csv.gz', 'codes': [-2, -3],
                       'hold': 20, 'cost': 0.001, 'baseline': 'full_history', 'entry': 'next_open',
                       'split': '2016-01-01', 'boot': 2000, 'placebo_reps': 10, **change}, indent=1)


def prereg(tid, world):
    return (f'# {tid}: PRE-REGISTRATION\n\nRule: {RULE}.\nData: data/{world}.csv.gz, the whole file.\n'
            'Looks at the data before this: 0 (describe_data only).\nScored once; a change is a new trial id.\n')


def outcome(res):
    """('allowed', payload) or (layer, reason) for a refusal."""
    if not res.is_error:
        return 'allowed', res.structured_content or json.loads(res.content[0].text)
    text = res.content[0].text
    m = re.search(r'REFUSED by the (gate|rules): (.*)', text, re.S)
    return (m.group(1), m.group(2).strip()) if m else ('error', text)


async def attack(url):
    out = {'url': url, 'honest': [], 'shortcuts': []}
    async with streamable_http_client(url) as (read, write, *_), ClientSession(read, write) as s:
        info = await s.initialize()
        out['server'] = f'{info.server_info.name} {info.server_info.version}'

        async def call(name, **args):
            try:
                return outcome(await s.call_tool(name, args))
            except Exception as e:            # refused before the server saw it (a proxy, a firewall): not our layers
                return 'transport', f'{type(e).__name__}: {e}'

        files = (await call('list_files'))[1]['files']
        out['seeded'] = [f['path'] for f in files]

        for world in ('planted', 'null'):
            tid = f'{world.upper()}-001/v1'
            await call('describe_data', data=f'data/{world}.csv.gz')
            await call('write_file', path=f'prereg_{world}.md', text=prereg(tid, world))
            await call('write_file', path=f'spec_{world}.json', text=spec(world))
            await call('register_trial', trial_id=tid, rule=RULE, k_looks=0)
            await call('freeze_rule', prereg=f'prereg_{world}.md', spec=f'spec_{world}.json', lock=f'lock_{world}.json')
            kind, r = await call('run_trial', trial_id=tid, spec=f'spec_{world}.json', lock=f'lock_{world}.json')
            rec = r['recorded'] if kind == 'allowed' else {}
            out['honest'].append({'trial': tid, 'world': world, 'truth': TRUTH[world][0], 'expected': TRUTH[world][1],
                                  'verdict': r['verdict'] if kind == 'allowed' else f'{kind}: {r}',
                                  'excess': rec.get('excess_after_cost'), 'ci': rec.get('excess_ci'),
                                  'signals': rec.get('signals')})

        async def shortcut(what, expected, name, **args):
            layer, reason = await call(name, **args)
            out['shortcuts'].append({'attempt': what, 'expected': expected, 'refused_by': layer,
                                     'reason': reason if layer != 'allowed' else 'IT RAN'})

        run = {'spec': 'spec_planted.json', 'lock': 'lock_planted.json'}
        await shortcut('Score a trial that was never registered', 'rules', 'run_trial', trial_id='GHOST-001/v1', **run)
        await shortcut('Score the same trial again, hoping for a different answer', 'rules', 'run_trial',
                       trial_id='PLANTED-001/v1', **run)
        await shortcut('Edit the frozen spec after seeing the result (hold 10 bars)', 'gate', 'write_file',
                       path='spec_null.json', text=spec('null', hold=10))
        await shortcut('Forge a lock with fresh hashes', 'gate', 'write_file', path='lock_forged.json',
                       text=json.dumps({'frozen_at': '2026-01-01T00:00:00+00:00', 'files': {}}))
        await shortcut('Rewrite the trial ledger', 'gate', 'write_file', path='trials.jsonl', text='')
        await shortcut('Re-freeze over the old lock', 'rules', 'freeze_rule', prereg='prereg_null.md',
                       spec='spec_null.json', lock='lock_null.json')
        await call('write_file', path='spec_swap.json', text=spec('planted', name='NULL-001/v2'))
        await call('register_trial', trial_id='NULL-001/v2', rule=RULE + ', on the planted data', k_looks=1)
        await shortcut('Score a new spec under the old lock (swap the data)', 'rules', 'run_trial',
                       trial_id='NULL-001/v2', spec='spec_swap.json', lock='lock_null.json')
        await shortcut('Read the raw rows before registering (peek at the outcome)', 'gate', 'read_file',
                       path='data/null.csv.gz')
        await shortcut('Write a script into the sandbox', 'gate', 'write_file', path='run.py', text='import os\n')
        await shortcut("Read another session's ledger (a path outside the sandbox)", 'rules', 'read_ledger',
                       ledger='../../another-session/work/trials.jsonl')
        await call('write_file', path='spec_big.json', text=spec('null', boot=10_000_000))
        await call('register_trial', trial_id='BIG-001/v1', rule=RULE + ', ten million bootstrap draws', k_looks=1)
        await shortcut('Ask for 10 million bootstrap draws', 'gate', 'freeze_rule', prereg='prereg_null.md',
                       spec='spec_big.json', lock='lock_big.json')

        out['ledger'] = (await call('read_ledger'))[1]
        out['gate_log'] = (await call('read_gate_log', limit=200))[1]

    async with streamable_http_client(url) as (read, write, *_), ClientSession(read, write) as s:
        await s.initialize()
        other = outcome(await s.call_tool('read_ledger', {}))[1]
        out['second_session_ledger_lines'] = other.get('lines')
    return out


def report(out):
    lines = [f"{out['server']} at {out['url']}", '', 'Honest trials, answer known in advance']
    ok = True
    for h in out['honest']:
        good = h['verdict'] == h['expected']
        ok &= good
        ex = '' if h['excess'] is None else (f"excess {100 * h['excess']:+.2f}% "
                                              f"[{100 * h['ci'][0]:+.2f}, {100 * h['ci'][1]:+.2f}], {h['signals']} signals")
        lines.append(f"  {h['trial']:<15} truth: {h['truth']:<19} verdict: {h['verdict']:<14} {ex}"
                     f"{'' if good else '   <-- WRONG'}")
    lines += ['', f"  {'#':>2}  {'shortcut':<62}{'refused by':<12}"]
    for i, a in enumerate(out['shortcuts'], 1):
        good = a['refused_by'] == a['expected']
        ok &= good
        lines.append(f"  {i:>2}  {a['attempt']:<62}{a['refused_by']:<12}{'' if good else '<-- expected ' + a['expected']}")
        lines.append(f"      {a['reason'][:110]}")
    led, log = out['ledger'], out['gate_log']
    ok &= led.get('ok', False) and log.get('ok', False) and out['second_session_ledger_lines'] == 0
    refused = {k: sum(r['event'] == f'refused_by_{k}' for r in log.get('rows', [])) for k in ('gate', 'rules')}
    lines += ['', f"Ledger: {led.get('lines')} lines, {led.get('trials_total')} trials counted (two honest, two "
                  f"registered during the shortcuts: trying again is counted), chain ok: {led.get('ok')}",
              f"Gate log: {log.get('entries')} calls, chain ok: {log.get('ok')}, refused by the gate "
              f"{refused['gate']}, by the rules {refused['rules']}",
              f"A second session sees {out['second_session_ledger_lines']} ledger lines: its own sandbox.", '']
    n = sum(a['refused_by'] == a['expected'] for a in out['shortcuts'])
    lines.append(f"{n} of {len(out['shortcuts'])} shortcuts refused by the expected layer; honest verdicts "
                 f"{'match' if all(h['verdict'] == h['expected'] for h in out['honest']) else 'DO NOT match'} the truth."
                 + ('' if ok else '  FAILED'))
    return '\n'.join(lines), ok


@contextlib.contextmanager
def local_server(base=None, per_minute=10_000):
    """Serve the live app on a free local port in a thread; yields the /mcp URL."""
    import uvicorn
    sys.path.insert(0, str(ROOT))
    from signal_audit.live.server import build_app
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(build_app(base=base, per_minute=per_minute), host='127.0.0.1', port=port,
                                        log_level='warning', access_log=False))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    try:
        yield f'http://127.0.0.1:{port}/mcp'
    finally:
        srv.should_exit = True
        t.join(timeout=10)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--url', help='MCP endpoint of a running server, e.g. https://HOST/mcp (default: start one locally)')
    ap.add_argument('--json', help='also write the raw results to this file')
    a = ap.parse_args()
    for name in ('httpx', 'httpx2', 'mcp'):
        logging.getLogger(name).setLevel(logging.WARNING)
    if a.url:
        out = asyncio.run(attack(a.url))
    else:
        with local_server() as url:
            out = asyncio.run(attack(url))
    text, ok = report(out)
    print(text)
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str) + '\n')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
