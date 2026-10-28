"""The live server: every shortcut refused by the layer that should refuse it, honest verdicts that match the planted
truth, sessions that cannot see each other, and a rate limit that holds. Runs a real server over streamable HTTP."""
import asyncio
import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip('mcp')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'examples'))

import attack_live as A  # noqa: E402
from signal_audit import governed as G  # noqa: E402
from signal_audit.live import server as S  # noqa: E402


def test_each_call_runs_under_its_own_root(tmp_path):
    roots, seen = [tmp_path / 'a', tmp_path / 'b'], {}
    barrier = threading.Barrier(2)

    def worker(r):
        r.mkdir()
        with G.rooted(r):
            barrier.wait()                    # both threads are inside their block at the same time
            seen[r.name] = G.root()

    threads = [threading.Thread(target=worker, args=(r,)) for r in roots]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert seen == {'a': roots[0].resolve(), 'b': roots[1].resolve()}
    assert G.root() == Path.cwd().resolve()   # nothing leaks out of the block


def test_the_gate_classifies_writes_by_what_they_touch(tmp_path):
    (tmp_path / 'data').mkdir()
    shutil.copy(ROOT / 'examples' / 'data' / 'sample.csv.gz', tmp_path / 'data' / 'sample.csv.gz')
    (tmp_path / 'spec.json').write_text((ROOT / 'examples' / 'spec_sample.json').read_text())
    (tmp_path / 'PREREG.md').write_text('# T\n')
    allowed = lambda action: S.GATE.evaluate(action).allowed_to_execute  # noqa: E731
    with G.rooted(tmp_path):
        assert S._write_action('notes.md', 'x') == 'write_file:.md' and allowed('write_file:.md')
        assert S._write_action('spec.json', '{}') == 'write_file:.json' and allowed('write_file:.json')
        assert S._write_action('trials.jsonl', '') == 'write_file:ledger' and not allowed('write_file:ledger')
        assert S._write_action('new.json', json.dumps({'frozen_at': 'x', 'files': {}})) == 'write_file:lock'
        assert S._write_action('run.py', 'x') == 'write_file:.py' and not allowed('write_file:.py')   # never listed
        assert S._write_action('run', 'x') == 'write_file:(no suffix)' and not allowed('write_file:(no suffix)')
        assert S._read_action('data/sample.csv.gz') == 'read_file:data' and not allowed('read_file:data')
        G.register_trial('T/v1', 'a rule', 0)
        G.freeze_rule('PREREG.md', 'spec.json', 'lock.json')
        assert S._write_action('spec.json', '{}') == 'write_file:frozen'                          # frozen now
        assert S._write_action('lock.json', '{}') == 'write_file:lock'
        with pytest.raises(G.Refused):
            S._write_action('../outside.md', 'x')


def test_every_shortcut_is_refused_by_the_layer_that_should_refuse_it(tmp_path):
    with A.local_server(base=tmp_path) as url:
        out = asyncio.run(A.attack(url))
    text, ok = A.report(out)
    assert ok, text
    assert [h['verdict'] for h in out['honest']] == ['SUPPORTED', 'NOT SUPPORTED']      # the planted truth, found
    assert len(out['shortcuts']) == 11
    assert all(a['refused_by'] == a['expected'] for a in out['shortcuts']), text
    assert out['ledger']['trials_total'] == 4                                           # retries are counted
    assert out['gate_log']['ok'] and out['second_session_ledger_lines'] == 0
    assert {'data/null.csv.gz', 'data/planted.csv.gz', 'data/sample.csv.gz'} <= set(out['seeded'])


def test_tools_say_what_they_can_change(tmp_path):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async def tools(url):
        async with streamable_http_client(url) as (r, w, *_), ClientSession(r, w) as s:
            await s.initialize()
            return {t.name: t.annotations for t in (await s.list_tools()).tools}

    with A.local_server(base=tmp_path) as url:
        found = asyncio.run(tools(url))
    assert set(found) == set(S.READS + S.APPENDS) | {'read_file', 'write_file'}
    for name, a in found.items():
        assert a.read_only_hint is (name in S.READS or name == 'read_file'), name
        assert a.destructive_hint is (name == 'write_file'), name                   # it replaces an unfrozen draft


def test_the_rate_limit_holds(tmp_path):
    with A.local_server(base=tmp_path, per_minute=3) as url:
        codes = []
        for _ in range(5):
            try:
                urllib.request.urlopen(url, timeout=5)
                codes.append(200)
            except urllib.error.HTTPError as e:
                codes.append(e.code)
        health = urllib.request.urlopen(url.replace('/mcp', '/health'), timeout=5).status
    assert codes[3:] == [429, 429] and 429 not in codes[:3]
    assert health == 200                                                  # only /mcp is metered
