"""signal-audit as an MCP server: the governance loop as tools an agent can call but cannot bend.

Run:   signal-audit-mcp --root /path/to/work        (after `pip install -e ".[mcp]"`)
  or:  python -m signal_audit.mcp_server --root /path/to/work
Claude Code:  claude mcp add signal-audit -- signal-audit-mcp --root /path/to/work

Eight tools. Four only read. Four write, and none of them can overwrite or delete anything: the ledger is append-only,
a lock is written once, and run_trial records its own result. The rules are in signal_audit/governed.py, in code, so
no prompt can talk them away. Every path stays inside --root (default: $SIGNAL_AUDIT_ROOT, else the working folder).
"""
import argparse
import functools
import os

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import __version__, governed as G

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
APPEND = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)

server = MCPServer(
    name='signal-audit',
    version=__version__,
    instructions=(
        'Test whether a trading signal beats an honest baseline, under rules enforced in code. The loop: '
        'describe_data -> write PREREG.md and spec.json (get_templates) -> register_trial -> freeze_rule -> run_trial. '
        'run_trial scores a trial once and records the verdict in the ledger itself; a second run, a run on a changed '
        'spec or data, or a run before registration is refused. A change after seeing a result is a NEW trial id '
        '(e.g. /v2) with a new lock, and it raises the trial count. Report the verdict as the tool returns it.'
    ),
)


def refusals(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except G.Refused as e:
            raise ToolError(f'REFUSED: {e}') from e
    return wrapper


@server.tool(annotations=READ, description='The pre-registration template, the spec fields, the loop, and the audit root.')
@refusals
def get_templates() -> dict:
    return G.get_templates()


@server.tool(annotations=READ, description='Shape of a data set: rows, symbols, date range, signal codes and their counts. '
                                           'Computes no returns, so it is not a look at the outcome.')
@refusals
def describe_data(data: str) -> dict:
    return G.describe_data(data)


@server.tool(annotations=APPEND, description='Count a trial in the append-only ledger BEFORE anything is scored. rule = the '
                                             'rule in one or two sentences. k_looks = how many looks at the data produced '
                                             'the idea (cells x horizons x variants; 0 if none). An id registers once.')
@refusals
def register_trial(trial_id: str, rule: str, k_looks: int, ledger: str = 'trials.jsonl') -> dict:
    return G.register_trial(trial_id, rule, k_looks, ledger)


@server.tool(annotations=APPEND, description="SHA-256 the written pre-registration, the spec, the spec's data and the "
                                             "scorer's own source into a new lock file. Refuses to overwrite a lock.")
@refusals
def freeze_rule(prereg: str, spec: str, lock: str, extra_files: list[str] | None = None) -> dict:
    return G.freeze_rule(prereg, spec, lock, extra_files)


@server.tool(annotations=READ, description='Check that every file in a lock still matches its frozen hash.')
@refusals
def check_freeze(lock: str) -> dict:
    return G.check_freeze(lock)


@server.tool(annotations=APPEND, description='Score a registered, frozen trial ONCE: checks the ledger chain, the '
                                             'registration and the freeze, runs the placebo gate and the verdict rules, '
                                             'and appends the result to the ledger before returning it.')
@refusals
def run_trial(trial_id: str, spec: str, lock: str, ledger: str = 'trials.jsonl') -> dict:
    return G.run_trial(trial_id, spec, lock, ledger)


@server.tool(annotations=APPEND, description='Append a correction to a registered trial. Nothing in the ledger is ever '
                                             'edited; the correction points at the trial and says what changed and why.')
@refusals
def record_correction(trial_id: str, note: str, ledger: str = 'trials.jsonl') -> dict:
    return G.record_correction(trial_id, note, ledger)


@server.tool(annotations=READ, description='Verify the ledger hash chain and list its lines, the running trial count, '
                                           'and trials registered but not yet scored. Optional trial_id filter.')
@refusals
def read_ledger(ledger: str = 'trials.jsonl', trial_id: str | None = None, limit: int = 50) -> dict:
    return G.read_ledger(ledger, trial_id, limit)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='signal-audit-mcp', description='signal-audit MCP server (stdio)')
    ap.add_argument('--root', default=os.environ.get('SIGNAL_AUDIT_ROOT') or os.getcwd(),
                    help='folder every path must stay inside')
    a = ap.parse_args(argv)
    G.set_root(a.root)
    server.run('stdio')


if __name__ == '__main__':
    main()
