"""End to end over the real stdio transport with the official MCP client: spawn the server, list its tools, run the
loop, and check that a second run comes back as a refusal, not a score."""
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip('mcp')
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
READ_ONLY = {'get_templates', 'describe_data', 'check_freeze', 'read_ledger'}
WRITES = {'register_trial', 'freeze_rule', 'run_trial', 'record_correction'}


def payload(res):
    return res.structured_content or json.loads(res.content[0].text)


async def session_run(work):
    params = StdioServerParameters(command=sys.executable, args=['-m', 'signal_audit.mcp_server', '--root', str(work)],
                                   cwd=str(ROOT), env={**os.environ, 'PYTHONPATH': str(ROOT)})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            init = await s.initialize()
            tools = (await s.list_tools()).tools
            call = s.call_tool
            out = {'server': init.server_info.name, 'tools': {t.name: t.annotations for t in tools}}
            out['outside'] = await call('describe_data', {'data': '../elsewhere.csv'})
            await call('register_trial', {'trial_id': 'SAMPLE-001/v1', 'rule': 'buy after A/A+ short', 'k_looks': 18})
            await call('freeze_rule', {'prereg': 'PREREG.md', 'spec': 'spec.json', 'lock': 'prereg.lock.json'})
            out['first'] = await call('run_trial', {'trial_id': 'SAMPLE-001/v1', 'spec': 'spec.json',
                                                    'lock': 'prereg.lock.json'})
            out['second'] = await call('run_trial', {'trial_id': 'SAMPLE-001/v1', 'spec': 'spec.json',
                                                     'lock': 'prereg.lock.json'})
            out['ledger'] = await call('read_ledger', {})
            return out


def test_the_server_enforces_the_loop_over_stdio(tmp_path):
    (tmp_path / 'data').mkdir()
    shutil.copy(ROOT / 'examples' / 'data' / 'sample.csv.gz', tmp_path / 'data' / 'sample.csv.gz')
    spec = json.loads((ROOT / 'examples' / 'spec_sample.json').read_text())
    spec.update(boot=500, placebo_reps=3)
    (tmp_path / 'spec.json').write_text(json.dumps(spec))
    (tmp_path / 'PREREG.md').write_text('# SAMPLE-001/v1\n')

    out = asyncio.run(session_run(tmp_path))

    assert out['server'] == 'signal-audit'
    assert set(out['tools']) == READ_ONLY | WRITES
    for name, a in out['tools'].items():
        assert a.read_only_hint is (name in READ_ONLY), name
        assert a.destructive_hint is False, name                       # nothing can overwrite or delete

    assert out['outside'].is_error and 'outside the audit root' in out['outside'].content[0].text
    first = payload(out['first'])
    assert not out['first'].is_error and first['verdict'] in ('SUPPORTED', 'NOT SUPPORTED', 'VOID (placebo gate)')
    assert out['second'].is_error and 'REFUSED: SAMPLE-001/v1 was already scored' in out['second'].content[0].text
    led = payload(out['ledger'])
    assert [r['kind'] for r in led['rows']] == ['register', 'result'] and led['rows'][1]['body']['verdict'] == first['verdict']
