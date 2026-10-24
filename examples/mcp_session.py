"""The governance loop driven through the MCP server, the way an agent would drive it, in a scratch folder.

Spawns `python -m signal_audit.mcp_server` over stdio with the official MCP client, runs one honest trial, then tries
the shortcuts an agent under pressure to find a "yes" might take. Needs `pip install -e ".[mcp]"` (Python 3.10+).

  python examples/mcp_session.py
"""
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def show(step, res):
    if res.is_error:
        text = res.content[0].text
        print(f'{step}\n   {text[text.find("REFUSED"):]}')
        return None
    out = res.structured_content or json.loads(res.content[0].text)
    print(step)
    return out


async def main(work):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'signal_audit.mcp_server', '--root', str(work)],
                                   cwd=str(ROOT))
    async with stdio_client(params, errlog=open('/dev/null', 'w')) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            call = s.call_tool
            run = {'trial_id': 'SAMPLE-001/v1', 'spec': 'spec.json', 'lock': 'prereg.lock.json'}

            d = show('== describe_data: what is in the file (no returns computed)',
                     await call('describe_data', {'data': 'data/sample.csv.gz'}))
            print(f"   {d['rows']:,} rows, {d['symbols']} symbols, {d['first']}..{d['last']}, codes {d['signal_codes']}")

            r = show('== register_trial: count it before anything is scored',
                     await call('register_trial', {'trial_id': 'SAMPLE-001/v1', 'k_looks': 18,
                                                   'rule': 'buy the next open after an A/A+ short label, hold 20 bars'}))
            print(f"   trials {r['trials_before']} -> {r['trials_after']}, mining tax K = {r['k_looks']}")

            f = show('== freeze_rule: hash the prereg, the spec, the data and the scorer',
                     await call('freeze_rule', {'prereg': 'PREREG.md', 'spec': 'spec.json', 'lock': 'prereg.lock.json'}))
            print(f"   {f['files']} files frozen at {f['frozen_at']}")

            t = show('== run_trial: scored once, result written to the ledger by the scorer', await call('run_trial', run))
            print('   ' + t['summary'].replace('\n', '\n   '))

            show('== shortcut 1: run it again and hope for a different answer', await call('run_trial', run))

            spec = work / 'spec.json'
            spec.write_text(spec.read_text().replace('"hold": 20', '"hold": 10'))
            show('== shortcut 2: edit the spec to hold 10 bars, re-freeze over the old lock',
                 await call('freeze_rule', {'prereg': 'PREREG.md', 'spec': 'spec.json', 'lock': 'prereg.lock.json'}))

            r = show('== shortcut 3: call it v2 and score it under the old lock',
                     await call('register_trial', {'trial_id': 'SAMPLE-001/v2', 'k_looks': 19,
                                                   'rule': 'same, held 10 bars (chosen after seeing v1)'}))
            show('   (registered, so the trial count is now 2)', await call('run_trial', {**run, 'trial_id': 'SAMPLE-001/v2'}))

            show('== shortcut 4: read a file outside the audit folder', await call('describe_data', {'data': '../../.ssh/id_rsa'}))

            led = show('== read_ledger: what anyone reviewing this will see', await call('read_ledger', {}))
            for row in led['rows']:
                print(f"   {row['seq']}  {row['kind']:<8} {row['id']:<15} trials {row['trials_after']}"
                      f"  {row['body'].get('verdict') or row['body'].get('rule', '')}")
            print(f"   open (registered, never scored): {led['open_trials']}")


if __name__ == '__main__':
    w = Path(tempfile.mkdtemp())
    (w / 'data').mkdir()
    shutil.copy(ROOT / 'examples' / 'data' / 'sample.csv.gz', w / 'data' / 'sample.csv.gz')
    shutil.copy(ROOT / 'examples' / 'spec_sample.json', w / 'spec.json')
    shutil.copy(ROOT / 'examples' / 'PREREG_TEMPLATE.md', w / 'PREREG.md')
    asyncio.run(main(w))
    print(f'scratch folder: {w}')
