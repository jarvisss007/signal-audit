"""Append-only trial ledger.

Every registered test is a TRIAL and raises the running count; the count is what any later "significant" result is
judged against (try 20 things and one will pass by luck). A result is NOT a new trial. Nothing is ever edited or
deleted: a correction is a new entry that points at the old one.

Each line is a JSON object chained to the previous line by hash, so an edited or deleted line is detectable:

  {"seq": 3, "ts": ..., "kind": "register" | "result" | "correction", "id": "BOUNCE-001/v1",
   "trials_before": 55, "trials_after": 56, "k_looks": 18, "body": {...}, "prev": "<hash of line 2>", "hash": "..."}

k_looks = how many looks at the data produced the idea (the "mining tax"): an idea found by scanning 18 cells has
already had 18 chances to look good.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

KINDS = ('register', 'result', 'correction')


def _digest(entry):
    body = {k: v for k, v in entry.items() if k != 'hash'}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def read(path):
    p = Path(path)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def append(path, kind, id, body=None, k_looks=None):
    if kind not in KINDS:
        raise ValueError(f'kind must be one of {KINDS}')
    rows = verify(path)
    last = rows[-1] if rows else None
    if kind != 'register' and not any(r['id'] == id and r['kind'] == 'register' for r in rows):
        raise ValueError(f'{id} was never registered; register it before recording a {kind}')
    if kind == 'register' and any(r['id'] == id and r['kind'] == 'register' for r in rows):
        raise ValueError(f'{id} is already registered; a change is a NEW variant id (e.g. /v2), never a re-registration')
    before = last['trials_after'] if last else 0
    entry = {'seq': (last['seq'] + 1) if last else 1, 'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'),
             'kind': kind, 'id': id, 'trials_before': before, 'trials_after': before + (kind == 'register'),
             'k_looks': k_looks, 'body': body or {}, 'prev': last['hash'] if last else None}
    entry['hash'] = _digest(entry)
    with open(path, 'a') as fh:
        fh.write(json.dumps(entry) + '\n')
    return entry


class LedgerBroken(Exception):
    pass


def verify(path):
    """Check the chain: every hash matches its line, every line points at the one before, the count never jumps."""
    rows = read(path)
    prev_hash, count = None, 0
    for i, r in enumerate(rows, 1):
        if r.get('seq') != i:
            raise LedgerBroken(f'line {i}: seq {r.get("seq")} (a line was removed or inserted)')
        if r.get('prev') != prev_hash:
            raise LedgerBroken(f'line {i}: does not point at line {i - 1}')
        if _digest(r) != r.get('hash'):
            raise LedgerBroken(f'line {i}: content does not match its hash (edited after writing)')
        if r['trials_before'] != count or r['trials_after'] != count + (r['kind'] == 'register'):
            raise LedgerBroken(f'line {i}: trial count does not follow from the lines before it')
        prev_hash, count = r['hash'], r['trials_after']
    return rows
