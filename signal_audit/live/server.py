"""signal-audit, live: the MCP server over HTTP, open to anyone, each session in its own sandbox.

Two layers stand between a caller and the files, and examples/attack_live.py tries to get past both:

  the gate    default-deny on WHAT a call is: agent-verification-lab's PolicyGate, unchanged. A call runs only if its
              action is on ALLOW below. Writing a ledger, a lock or a frozen file is blocked by name, reading the rows
              of the data is blocked (that is looking at the outcome before registering), and anything unlisted is
              denied without a rule having to name it. The session budgets (calls, writes, scores, spec size) are the
              gate's too.
  the rules   signal_audit/governed.py, the same code the stdio server runs: register before scoring, score once,
              a lock is written once, the freeze must hold, every path stays inside the session's own folder.

Every call the gate sees, allowed or refused, is appended to the session's hash-chained log, kept outside the folder
the caller can touch (read_gate_log shows it). Nothing is kept after a session: its folder is deleted after 30 idle
minutes. No caller text leaves the session; /stats counts outcomes only.

  signal-audit-live                   http://127.0.0.1:8000  (pip install -e ".[mcp]")
  claude mcp add --transport http signal-audit http://127.0.0.1:8000/mcp
"""
import argparse
import html
import json
import os
import threading
import time
from collections import Counter, deque
from datetime import datetime, timezone

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from starlette.responses import HTMLResponse, JSONResponse

from .. import __version__, governed as G
from .page import PAGE
from .policy_gate import PolicyGate, RiskTier
from .sandbox import LIMITS, Boxes, Full

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
APPEND = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
DRAFT = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True, open_world_hint=False)

READS = ('get_templates', 'describe_data', 'check_freeze', 'read_ledger', 'list_files', 'read_gate_log')
APPENDS = ('register_trial', 'freeze_rule', 'run_trial', 'record_correction')
ALLOW = {
    **{name: RiskTier.AUTO for name in READS + APPENDS},
    'read_file:text': RiskTier.AUTO,
    'write_file:.md': RiskTier.AUTO,      # a draft pre-registration
    'write_file:.json': RiskTier.AUTO,    # a draft spec
    'write_file:ledger': RiskTier.BLOCKED,
    'write_file:lock': RiskTier.BLOCKED,
    'write_file:frozen': RiskTier.BLOCKED,
    'read_file:data': RiskTier.BLOCKED,
}
WHY = {
    'write_file:ledger': 'the ledger is written only by register_trial, run_trial and record_correction, one line at a time',
    'write_file:lock': 'a lock is written only by freeze_rule, once',
    'write_file:frozen': 'this file is frozen in a lock. A change is a new file, a new trial id and a new lock',
    'read_file:data': 'the rows of the data are not readable: reading outcomes before registering is looking at the '
                      'answer. describe_data gives the shape',
}
GATE = PolicyGate(ALLOW)
TEXT = ('.md', '.json', '.jsonl', '.txt')

BOXES = None
HEAVY = threading.BoundedSemaphore(1)     # one scoring or hashing pass at a time: 512 MB, 0.1 CPU
STATS = Counter()
STATS_LOCK = threading.Lock()
STARTED = datetime.now(timezone.utc).isoformat(timespec='seconds')

server = MCPServer(
    name='signal-audit-live',
    version=__version__,
    log_level='WARNING',
    instructions=(
        'Test whether a trading signal beats an honest baseline, under rules enforced in code, in a sandbox that is '
        'yours for this session. Start with list_files and get_templates. The loop: describe_data -> write PREREG.md '
        'and spec.json (write_file) -> register_trial -> freeze_rule -> run_trial. run_trial scores a trial once and '
        'records the verdict in the ledger itself. A refusal says which layer refused it: the gate (what the call is) '
        'or the rules (what the loop allows). Report the verdict as the tool returns it.'
    ),
)


def _count(*keys):
    with STATS_LOCK:
        STATS.update(keys)


def _shown(args):
    """What the log keeps of a call's arguments: names and short values, never the text of a written file."""
    out = {}
    for k, v in args.items():
        if k == 'text':
            out[k] = f'<{len(str(v).encode())} bytes>'
        elif isinstance(v, str) and len(v) > 80:
            out[k] = v[:77] + '...'
        else:
            out[k] = v
    return out


def _budget(box, action, args):
    if box.calls > LIMITS['calls']:
        return f'this session has used its {LIMITS["calls"]} calls; open a new session'
    if action.startswith('write_file'):
        if box.writes >= LIMITS['writes']:
            return f'this session has used its {LIMITS["writes"]} writes'
        if len(args['text'].encode()) > LIMITS['write_bytes']:
            return f'a written file is at most {LIMITS["write_bytes"]:,} bytes'
    if action == 'run_trial' and box.scores >= LIMITS['scores']:
        return f'this session has used its {LIMITS["scores"]} scores'
    if action in ('freeze_rule', 'run_trial'):
        try:
            spec = json.loads(G._inside(args['spec']).read_text())
        except (OSError, ValueError, G.Refused):
            return None                       # the rules will say what is wrong with it
        for k in ('boot', 'placebo_reps', 'hold'):
            v = spec.get(k) if isinstance(spec, dict) else None
            if isinstance(v, (int, float)) and v > LIMITS[k]:
                return f'{k}={v} is over this server\'s budget ({LIMITS[k]}): same scorer, shared CPU'
    return None


def _refuse(box, layer, action, reason, shown):
    box.log.append(f'refused_by_{layer}', {'action': action, 'reason': reason, 'args': shown})
    _count('calls', f'refused_by_{layer}')
    raise ToolError(f'REFUSED by the {layer}: {reason}')


def _session_id(ctx):
    """The MCP session id the transport issued. A client cannot pick one: an id the server did not issue is refused
    by the transport before any tool runs, so a session can only ever reach its own sandbox."""
    rc = ctx.request_context
    request = getattr(rc, 'request', None)
    sid = getattr(rc, 'session_id', None) or (request.headers.get('mcp-session-id') if request is not None else None)
    if not sid:
        raise ToolError('REFUSED by the gate: no MCP session id; connect over streamable HTTP')
    return sid


def _call(ctx, name, fn, args, classify=None, heavy=False):
    """The one path every tool takes: find the session's sandbox, ask the gate, then let the rules run."""
    try:
        box = BOXES.get(_session_id(ctx))
    except Full:
        _count('calls', 'busy')
        raise ToolError(f'BUSY: the server holds its {LIMITS["sessions"]} sessions; try again in a few minutes')
    shown = _shown(args)
    with box.lock, G.rooted(box.work):
        box.calls += 1
        action = name
        try:
            action = classify(**args) if classify else name
            over = _budget(box, action, args)
            if over:
                _refuse(box, 'gate', action, over, shown)
            decision = GATE.evaluate(action)
            if not decision.allowed_to_execute:
                _refuse(box, 'gate', action, f'{decision.reason}' + (f': {WHY[action]}' if action in WHY else ''), shown)
            box.writes += action.startswith('write_file')
            box.scores += action == 'run_trial'
            if heavy and not HEAVY.acquire(timeout=90):
                raise ToolError('BUSY: another session is scoring; try again in a minute')
            try:
                out = fn(box, **args)
            finally:
                if heavy:
                    HEAVY.release()
        except G.Refused as e:
            reason = str(e).replace(str(box.work) + '/', '').replace(str(box.work), '(your sandbox)')
            _refuse(box, 'rules', action, reason, shown)
        except ToolError:
            raise
        except Exception as e:                # a bug, not an outcome: logged, and no path or trace leaves the server
            box.log.append('error', {'action': action, 'error': type(e).__name__, 'args': shown})
            _count('calls', 'error')
            raise ToolError(f'ERROR: {type(e).__name__} in {action}') from None
        kept = {k: out[k] for k in ('verdict', 'registered', 'lock', 'line', 'ledger_line') if k in out}
        box.log.append('allowed', {'action': action, 'args': shown, **kept})
        _count('calls', 'allowed', *([f'verdict {out["verdict"]}'] if name == 'run_trial' else []))
        return out


def _kind(p):
    if p.suffix == '.jsonl':
        return 'ledger'
    if p.suffix == '.json' and p.exists() and _is_lock(p.read_text()):
        return 'lock'
    return 'data' if p.name.endswith(('.csv', '.csv.gz')) else 'draft'


def _is_lock(text):
    try:
        d = json.loads(text)
    except ValueError:
        return False
    return isinstance(d, dict) and 'frozen_at' in d and 'files' in d


def _frozen():
    files = set()
    for p in G.root().rglob('*.json'):
        if _kind(p) == 'lock':
            files |= set(json.loads(p.read_text())['files'])
    return files


def _write_action(path, text):
    p = G._inside(path, must_exist=False)
    if p.suffix == '.jsonl':
        return 'write_file:ledger'
    if _kind(p) == 'lock' or _is_lock(text):
        return 'write_file:lock'
    if str(p) in _frozen():
        return 'write_file:frozen'
    return f'write_file:{p.suffix or "(no suffix)"}'          # .md and .json are listed; nothing else is


def _read_action(path):
    p = G._inside(path)
    if p.name.endswith(('.csv', '.csv.gz', '.gz')):
        return 'read_file:data'
    return 'read_file:text' if p.suffix in TEXT else f'read_file:{p.suffix or "(no suffix)"}'


@server.tool(annotations=READ, description='The pre-registration template, the spec fields, the loop, and this '
                                           "sandbox's files and budget.")
def get_templates(ctx: Context) -> dict:
    def fn(box):
        out = G.get_templates()
        out.update(root='your sandbox (this session only)', sandbox=(box.work / 'README.md').read_text(),
                   limits=LIMITS)
        return out
    return _call(ctx, 'get_templates', fn, {})


@server.tool(annotations=READ, description="Every file in this session's sandbox: data, drafts, locks and ledgers, "
                                           'with sizes and whether a lock has frozen it.')
def list_files(ctx: Context) -> dict:
    def fn(box):
        frozen = _frozen()
        files = [{'path': str(p.relative_to(box.work)), 'bytes': p.stat().st_size, 'kind': _kind(p),
                  'frozen': str(p) in frozen} for p in sorted(box.work.rglob('*')) if p.is_file()]
        return {'files': files}
    return _call(ctx, 'list_files', fn, {})


@server.tool(annotations=READ, description='Read a text file in the sandbox (.md, .json, .jsonl, .txt). The rows of '
                                           'the data are not readable: describe_data gives their shape.')
def read_file(path: str, ctx: Context) -> dict:
    def fn(box, path):
        p = G._inside(path)
        return {'path': str(p.relative_to(box.work)), 'text': p.read_text()[:64_000]}
    return _call(ctx, 'read_file', fn, {'path': path}, classify=_read_action)


@server.tool(annotations=DRAFT, description='Write a draft pre-registration (.md) or spec (.json) in the sandbox, '
                                            'creating or replacing it. A file frozen in a lock, a lock, a ledger and '
                                            'any other kind of file cannot be written.')
def write_file(path: str, text: str, ctx: Context) -> dict:
    def fn(box, path, text):
        p = G._inside(path, must_exist=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return {'written': str(p.relative_to(box.work)), 'bytes': len(text.encode())}
    return _call(ctx, 'write_file', fn, {'path': path, 'text': text}, classify=_write_action)


@server.tool(annotations=READ, description='Shape of a data set: rows, symbols, date range, signal codes and their '
                                           'counts. Computes no returns, so it is not a look at the outcome.')
def describe_data(data: str, ctx: Context) -> dict:
    return _call(ctx, 'describe_data', lambda box, data: G.describe_data(data), {'data': data}, heavy=True)


@server.tool(annotations=APPEND, description='Count a trial in the append-only ledger BEFORE anything is scored. rule '
                                             '= the rule in one or two sentences. k_looks = how many looks at the data '
                                             'produced the idea (0 if none). An id registers once.')
def register_trial(trial_id: str, rule: str, k_looks: int, ctx: Context, ledger: str = 'trials.jsonl') -> dict:
    return _call(ctx, 'register_trial', lambda box, **a: G.register_trial(**a),
                 {'trial_id': trial_id, 'rule': rule, 'k_looks': k_looks, 'ledger_path': ledger})


@server.tool(annotations=APPEND, description="SHA-256 the written pre-registration, the spec, the spec's data and the "
                                             "scorer's own source into a new lock file. Refuses to overwrite a lock.")
def freeze_rule(prereg: str, spec: str, lock: str, ctx: Context) -> dict:
    return _call(ctx, 'freeze_rule', lambda box, **a: G.freeze_rule(a['prereg'], a['spec'], a['lock']),
                 {'prereg': prereg, 'spec': spec, 'lock': lock}, heavy=True)


@server.tool(annotations=READ, description='Check that every file in a lock still matches its frozen hash.')
def check_freeze(lock: str, ctx: Context) -> dict:
    return _call(ctx, 'check_freeze', lambda box, lock: G.check_freeze(lock), {'lock': lock}, heavy=True)


@server.tool(annotations=APPEND, description='Score a registered, frozen trial ONCE: checks the ledger chain, the '
                                             'registration and the freeze, runs the placebo gate and the verdict '
                                             'rules, and appends the result to the ledger before returning it.')
def run_trial(trial_id: str, spec: str, lock: str, ctx: Context, ledger: str = 'trials.jsonl') -> dict:
    return _call(ctx, 'run_trial', lambda box, **a: G.run_trial(a['trial_id'], a['spec'], a['lock'], a['ledger']),
                 {'trial_id': trial_id, 'spec': spec, 'lock': lock, 'ledger': ledger}, heavy=True)


@server.tool(annotations=APPEND, description='Append a correction to a registered trial. Nothing in the ledger is '
                                             'ever edited; the correction says what changed and why.')
def record_correction(trial_id: str, note: str, ctx: Context, ledger: str = 'trials.jsonl') -> dict:
    return _call(ctx, 'record_correction', lambda box, **a: G.record_correction(**a),
                 {'trial_id': trial_id, 'note': note, 'ledger_path': ledger})


@server.tool(annotations=READ, description='Verify the ledger hash chain and list its lines, the running trial count, '
                                           'and trials registered but not yet scored. Optional trial_id filter.')
def read_ledger(ctx: Context, ledger: str = 'trials.jsonl', trial_id: str | None = None, limit: int = 50) -> dict:
    return _call(ctx, 'read_ledger', lambda box, **a: G.read_ledger(**a),
                 {'ledger_path': ledger, 'trial_id': trial_id, 'limit': min(int(limit), 200)})


@server.tool(annotations=READ, description="This session's gate log: every call the gate saw, allowed or refused, "
                                           'and by which layer, with the hash chain checked. Kept outside the '
                                           'sandbox, so no call can edit it.')
def read_gate_log(ctx: Context, limit: int = 50) -> dict:
    def fn(box, limit):
        try:
            rows = box.log.replay(lambda acc, e: acc + [{'event': e['event_type'], **e['payload']}], [])
        except Exception as e:                # TamperDetected, or a line that is not JSON
            return {'ok': False, 'problem': str(e)}
        return {'ok': True, 'entries': len(rows), 'rows': rows[-min(int(limit), 200):]}
    return _call(ctx, 'read_gate_log', fn, {'limit': limit})


@server.custom_route('/', methods=['GET'], include_in_schema=False)
async def page(request):
    url = html.escape(f'{request.url.scheme}://{request.headers.get("host", "localhost")}/mcp')
    return HTMLResponse(PAGE.replace('{{MCP_URL}}', url).replace('{{VERSION}}', __version__))


@server.custom_route('/health', methods=['GET'], include_in_schema=False)
async def health(request):
    return JSONResponse({'ok': True, 'version': __version__})


@server.custom_route('/stats', methods=['GET'], include_in_schema=False)
async def stats(request):
    with STATS_LOCK:
        counts = dict(STATS)
    return JSONResponse({'version': __version__, 'since': STARTED, 'sessions_open': len(BOXES), **counts})


class RateLimit:
    """At most `per_minute` requests a minute per client on /mcp, so one caller's loop cannot take the instance."""

    def __init__(self, app, per_minute=120):
        self.app, self.per_minute, self.hits = app, per_minute, {}

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and scope['path'].startswith('/mcp'):
            now, who = time.monotonic(), (scope.get('client') or ('?',))[0]
            q = self.hits.setdefault(who, deque())
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                _count('rate_limited')
                await JSONResponse({'error': f'rate limit: {self.per_minute} requests a minute'}, 429)(scope, receive, send)
                return
            q.append(now)
            if len(self.hits) > 10_000:
                self.hits = {k: v for k, v in self.hits.items() if v}
        await self.app(scope, receive, send)


def build_app(hosts=(), base=None, per_minute=120):
    """The ASGI app. `hosts` = public host names the server answers to; DNS-rebinding protection stays on and every
    other Host header is refused (default-deny again)."""
    global BOXES
    BOXES = Boxes(base)
    allowed = ['127.0.0.1:*', 'localhost:*', '[::1]:*'] + [x for h in hosts for x in (h, f'{h}:*')]
    origins = ['http://127.0.0.1:*', 'http://localhost:*', 'http://[::1]:*'] + [f'https://{h}' for h in hosts]
    security = TransportSecuritySettings(enable_dns_rebinding_protection=True, allowed_hosts=allowed,
                                         allowed_origins=origins)
    return RateLimit(server.streamable_http_app(json_response=True, transport_security=security), per_minute)


def main(argv=None):
    ap = argparse.ArgumentParser(prog='signal-audit-live', description='signal-audit MCP server over HTTP, one sandbox '
                                                                       'per session')
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8000)))
    ap.add_argument('--public-host', action='append', default=[],
                    help='a host name the server answers to (repeatable); also $SIGNAL_AUDIT_PUBLIC_HOSTS, comma-separated, '
                         'and $RENDER_EXTERNAL_HOSTNAME on Render')
    a = ap.parse_args(argv)
    hosts = a.public_host + [h for h in os.environ.get('SIGNAL_AUDIT_PUBLIC_HOSTS', '').split(',') if h]
    behind_proxy = bool(os.environ.get('RENDER_EXTERNAL_HOSTNAME'))
    if behind_proxy:
        hosts.append(os.environ['RENDER_EXTERNAL_HOSTNAME'])
    import uvicorn
    uvicorn.run(build_app(hosts), host=a.host, port=a.port, access_log=False, log_level='warning',
                proxy_headers=behind_proxy, forwarded_allow_ips='*' if behind_proxy else None)


if __name__ == '__main__':
    main()
