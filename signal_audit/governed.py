"""The governance loop as plain functions, for a caller that is a model.

Same engine as the CLI, plus three rules the CLI leaves to the person at the keyboard:

  1. Every path stays inside one root folder. A path that resolves outside it is refused.
  2. A lock is written once. freeze_rule will not overwrite an existing lock, so a rule can't be re-frozen after the
     caller has seen a result. A change is a new trial id with a new lock.
  3. A trial is scored once, and the scorer records the result itself. run_trial checks the ledger, the registration
     and the freeze, scores, and appends the result line before it returns: no score without a record, and a second
     call for the same trial is refused.

The data file is frozen with the rule, so the test set can't be swapped after the freeze either.
Every function returns a plain dict; a refusal raises Refused with the reason, which the MCP server hands back.
"""
import contextvars
import hashlib
import json
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from . import audit, ledger, prereg
from .data import load

TEMPLATE = Path(__file__).resolve().parents[1] / 'examples' / 'PREREG_TEMPLATE.md'
SPEC_FIELDS = {
    'name': 'trial id and a one-line description of the rule',
    'data': 'CSV (or folder of CSVs) relative to the spec: symbol, date, open, high, low, close, signal[, eligible]',
    'codes': 'signal codes under test, e.g. [-2, -3]; every non-zero code stays out of every baseline',
    'hold': 'bars held after the signal (default 20)',
    'cost': 'round-trip cost charged on the signal trade (default 0.001)',
    'entry': 'next_open (default; a label printed at a close can only be traded at the next open) or close',
    'split': 'date cutting the sample into two halves; the excess must be above 0 in both',
    'placebo_gate': 'a placebo mean beyond +/- this voids the run (default 0.003)',
}

_root = None
_call_root = contextvars.ContextVar('signal_audit_call_root', default=None)


class Refused(Exception):
    pass


def set_root(path):
    global _root
    p = Path(path).expanduser().resolve()
    if not p.is_dir():
        raise Refused(f'{path}: the audit root must be an existing folder')
    _root = p
    return p


@contextmanager
def rooted(path):
    """Run the calls inside this block under their own root, whatever the process-wide root is. The live server gives
    every session its own folder this way, so two sessions scoring at once never see each other's files."""
    token = _call_root.set(Path(path).resolve())
    try:
        yield
    finally:
        _call_root.reset(token)


def root():
    return _call_root.get() or _root or Path.cwd().resolve()


def _inside(path, must_exist=True, suffix=None):
    r = root()
    p = Path(path).expanduser()
    p = (p if p.is_absolute() else r / p).resolve()
    if p != r and r not in p.parents:
        raise Refused(f'{path}: outside the audit root {r}')
    if suffix and not p.name.endswith(suffix):
        raise Refused(f'{path}: must end in {suffix}')
    if must_exist and not p.exists():
        raise Refused(f'{path}: not found under {r}')
    return p


def _rel(p):
    return str(Path(p).relative_to(root()))


def _short(msg):
    return str(msg).replace(str(root()) + '/', '')


def _spec(path):
    """Load a spec and resolve its data path against the spec's own folder, inside the root."""
    try:
        spec = audit.Spec.load(path)
    except (TypeError, ValueError) as e:
        raise Refused(f'{_rel(path)}: not a valid spec ({e}); fields: {", ".join(SPEC_FIELDS)}')
    data = spec.data if Path(spec.data).is_absolute() else str(Path(path).parent / spec.data)
    return replace(spec, data=str(_inside(data)))


def _data_files(spec):
    p = Path(spec.data)
    return sorted([*p.glob('*.csv'), *p.glob('*.csv.gz')]) if p.is_dir() else [p]


def _ledger_rows(path):
    try:
        return ledger.verify(path)
    except ledger.LedgerBroken as e:
        raise Refused(f'ledger {_rel(path)} is broken: {e}')


def get_templates():
    text = TEMPLATE.read_text() if TEMPLATE.exists() else 'See examples/PREREG_TEMPLATE.md in the signal-audit repo.'
    return {'prereg_template': text, 'spec_fields': SPEC_FIELDS,
            'loop': ['describe_data', 'write PREREG.md and spec.json', 'register_trial', 'freeze_rule', 'run_trial'],
            'root': str(root())}


def describe_data(data):
    """Shape of a data set: rows, symbols, dates, signal codes and counts. Computes no returns."""
    p = _inside(data)
    try:
        d = load(p)
    except (ValueError, FileNotFoundError) as e:
        raise Refused(str(e))
    codes = d.loc[d['signal'] != 0, 'signal'].value_counts().sort_index()
    return {'data': _rel(p), 'rows': int(len(d)), 'symbols': int(d['symbol'].nunique()),
            'first': str(d['date'].min().date()), 'last': str(d['date'].max().date()),
            'signal_codes': {str(int(k)): int(v) for k, v in codes.items()},
            'ordinary_days': int((d['signal'] == 0).sum()), 'eligible_share': float(d['eligible'].mean())}


def register_trial(trial_id, rule, k_looks, ledger_path='trials.jsonl'):
    """Count the trial before anything is scored. k_looks = looks at the data that produced the idea."""
    if not str(rule).strip():
        raise Refused('rule: write the rule down; an empty registration counts nothing')
    if not isinstance(k_looks, int) or k_looks < 0:
        raise Refused('k_looks: a whole number, the looks at the data that produced the idea (0 if none)')
    p = _inside(ledger_path, must_exist=False, suffix='.jsonl')
    try:
        e = ledger.append(p, 'register', trial_id, {'rule': rule}, k_looks)
    except (ValueError, ledger.LedgerBroken) as err:
        raise Refused(str(err))
    return {'registered': trial_id, 'ledger': _rel(p), 'line': e['seq'], 'trials_before': e['trials_before'],
            'trials_after': e['trials_after'], 'k_looks': k_looks}


def freeze_rule(prereg_path, spec_path, lock_path, extra_files=None):
    """Hash the written rule, the spec, the data and the scorer's own source. A lock is written once."""
    lock = _inside(lock_path, must_exist=False, suffix='.json')
    if lock.exists():
        raise Refused(f'{_rel(lock)} already exists: a rule is frozen once. A change is a new trial id with a new lock.')
    pre, spec_p = _inside(prereg_path), _inside(spec_path)
    spec = _spec(spec_p)
    files = [pre, spec_p, *_data_files(spec), *(_inside(f) for f in extra_files or [])]
    out = prereg.freeze([str(f) for f in files], str(lock))
    return {'lock': _rel(lock), 'frozen_at': out['frozen_at'], 'files': len(out['files']),
            'frozen': [_rel(f) for f in files] + ['signal_audit/*.py (the scorer)']}


def check_freeze(lock_path):
    p = _inside(lock_path, suffix='.json')
    try:
        lock = prereg.verify(p)
    except prereg.FrozenFileChanged as e:
        return {'ok': False, 'lock': _rel(p), 'problems': _short(e).split('; ')}
    return {'ok': True, 'lock': _rel(p), 'frozen_at': lock['frozen_at'], 'files': len(lock['files'])}


def run_trial(trial_id, spec_path, lock_path, ledger_path='trials.jsonl'):
    """Score a registered, frozen trial exactly once and record the result in the ledger before returning it."""
    led = _inside(ledger_path, suffix='.jsonl')
    rows = _ledger_rows(led)
    if not any(r['id'] == trial_id and r['kind'] == 'register' for r in rows):
        raise Refused(f'{trial_id} is not registered in {_rel(led)}: register_trial comes before any score')
    done = [r for r in rows if r['id'] == trial_id and r['kind'] == 'result']
    if done:
        raise Refused(f'{trial_id} was already scored (ledger line {done[0]["seq"]}, verdict '
                      f'{done[0]["body"].get("verdict")}). A trial is scored once; a change is a new trial id.')
    lock_p = _inside(lock_path, suffix='.json')
    try:
        lock = prereg.verify(lock_p)
    except prereg.FrozenFileChanged as e:
        raise Refused(f'the freeze is broken, nothing scored: {_short(e)}')
    spec_p = _inside(spec_path)
    if str(spec_p) not in lock['files']:
        raise Refused(f'{_rel(spec_p)} is not one of the files frozen in {_rel(lock_p)}')
    spec = _spec(spec_p)
    loose = [_rel(f) for f in _data_files(spec) if str(f) not in lock['files']]
    if loose:
        raise Refused(f'data not frozen with the rule: {", ".join(loose)}')
    try:
        res = audit.run(spec)
    except Exception as e:  # a failed run is not an outcome: nothing is recorded and the trial stays open
        raise Refused(f'scoring failed, nothing recorded: {type(e).__name__}: {e}')
    p = res['primary']
    body = {'verdict': res['verdict'], 'verdict_q2': res['verdict_q2'], 'signals': p['n'], 'symbols': p['symbols'],
            'excess_after_cost': p['excess_after_cost'], 'excess_ci': p['excess_ci'],
            'halves': [p['early']['excess'], p['late']['excess']], 'placebo_mean': res['placebo']['mean'],
            'spec': _rel(spec_p), 'lock': _rel(lock_p),
            'lock_sha256': hashlib.sha256(lock_p.read_bytes()).hexdigest()}
    if 'verdict_without_gate' in res:
        body['verdict_without_gate'] = res['verdict_without_gate']
    e = ledger.append(led, 'result', trial_id, body)
    return {'trial_id': trial_id, 'verdict': res['verdict'], 'verdict_q2': res['verdict_q2'],
            'summary': audit.summary(res), 'recorded': body, 'ledger_line': e['seq'], 'trials_total': e['trials_after']}


def record_correction(trial_id, note, ledger_path='trials.jsonl'):
    """Nothing in the ledger is edited: a correction is a new line pointing at the trial it corrects."""
    if not str(note).strip():
        raise Refused('note: say what is corrected and why')
    p = _inside(ledger_path, suffix='.jsonl')
    try:
        e = ledger.append(p, 'correction', trial_id, {'note': note})
    except (ValueError, ledger.LedgerBroken) as err:
        raise Refused(str(err))
    return {'corrected': trial_id, 'ledger': _rel(p), 'line': e['seq'], 'trials_total': e['trials_after']}


def read_ledger(ledger_path='trials.jsonl', trial_id=None, limit=50):
    p = _inside(ledger_path, must_exist=False, suffix='.jsonl')
    try:
        rows = ledger.verify(p)
    except ledger.LedgerBroken as e:
        return {'ok': False, 'ledger': _rel(p), 'problem': str(e)}
    scored = {r['id'] for r in rows if r['kind'] == 'result'}
    open_ = [r['id'] for r in rows if r['kind'] == 'register' and r['id'] not in scored]
    shown = [r for r in rows if trial_id in (None, r['id'])][-limit:]
    return {'ok': True, 'ledger': _rel(p), 'lines': len(rows), 'trials_total': rows[-1]['trials_after'] if rows else 0,
            'open_trials': open_, 'rows': [{k: r[k] for k in ('seq', 'ts', 'kind', 'id', 'trials_after', 'k_looks', 'body')}
                                           for r in shown]}
