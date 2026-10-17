"""Freeze a pre-registration: SHA-256 every file that defines the test BEFORE any outcome is computed, then refuse to
score if any of them changed.

What gets frozen is whatever decides the answer: the written prereg, the spec (codes, hold, cost, baseline, gate),
the scorer's own source, and the universe list. In the real study five hashes were frozen at 09:55 and checked at
10:31, before the holdout was scored.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def scorer_files():
    """The scorer's own code is part of the rule: a silent edit to it is a silent edit to the test."""
    return sorted(str(p) for p in PACKAGE.glob('*.py'))


def freeze(files, out, include_scorer=True):
    paths = list(files) + (scorer_files() if include_scorer else [])
    lock = {'frozen_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'files': {str(Path(p)): sha256(p) for p in paths}}
    Path(out).write_text(json.dumps(lock, indent=1) + '\n')
    return lock


class FrozenFileChanged(Exception):
    pass


def verify(lock_path):
    """Raise FrozenFileChanged naming every file that is missing or no longer matches its frozen hash."""
    lock = json.loads(Path(lock_path).read_text())
    bad = []
    for p, want in lock['files'].items():
        if not Path(p).exists():
            bad.append(f'{p}: missing')
        elif sha256(p) != want:
            bad.append(f'{p}: changed since {lock["frozen_at"]}')
    if bad:
        raise FrozenFileChanged('; '.join(bad))
    return lock
