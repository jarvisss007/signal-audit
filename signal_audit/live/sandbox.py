"""One folder per MCP session, seeded with data whose truth is known, with a budget on everything a stranger could use up.

Each session's folder holds `work/` (the only folder its calls can touch: the audit root) and, beside it, `gate.jsonl`:
the hash-chained log of every call the gate saw. The log sits outside `work/`, so no tool call can reach it to edit
its own record. A folder untouched for LIMITS['idle_minutes'] is deleted; nothing outlives the session.

The seeded data:
  data/sample.csv.gz    the repo's sample (the README's worked example)
  data/null.csv.gz      synthetic: the labels predict nothing. A SUPPORTED verdict here would be a bug in the audit.
  data/planted.csv.gz   synthetic: the price drifts up 2.5% over the 20 bars after every A/A+ short label (codes -2, -3)
Both synthetic worlds come from examples/make_synthetic.py (40 symbols x 12 years, seed 2026), small enough for a
0.1-CPU instance to score in seconds.
"""
import importlib.util
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .event_log import EventLog

EXAMPLES = Path(__file__).resolve().parents[2] / 'examples'
WORLDS = {'null': {}, 'planted': {'plant': 0.025}}

LIMITS = {
    'sessions': 40,         # sandboxes alive at once
    'idle_minutes': 30,     # a sandbox untouched this long is deleted
    'calls': 300,           # tool calls per session
    'writes': 40,           # write_file calls per session
    'write_bytes': 32_000,  # size of one written file
    'scores': 10,           # run_trial calls per session
    'boot': 5000,           # a spec over these is refused before it costs CPU
    'placebo_reps': 20,
    'hold': 250,
}

README = """# Your sandbox

This folder exists for this MCP session only and is deleted after {idle_minutes} idle minutes.

data/sample.csv.gz    the sample from the signal-audit README
data/null.csv.gz      synthetic, labels predict nothing (truth: no edge)
data/planted.csv.gz   synthetic, +2.5% over 20 bars after every A/A+ short label, codes -2 and -3 (truth: an edge)
PREREG_TEMPLATE.md    the pre-registration template
spec_example.json     a spec for the sample; copy it, point "data" at another file, keep the budget

The loop: describe_data -> write PREREG.md and spec.json (write_file) -> register_trial -> freeze_rule -> run_trial.
Budget per session: {calls} calls, {writes} writes of up to {write_bytes:,} bytes, {scores} scores;
a spec may ask for at most boot={boot}, placebo_reps={placebo_reps}, hold={hold}.
""".format(**LIMITS)


class Full(Exception):
    pass


def _make_synthetic():
    spec = importlib.util.spec_from_file_location('make_synthetic', EXAMPLES / 'make_synthetic.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.make


def prepare_seed(seed):
    """Build the files every sandbox starts with, once per process. The data is made read-only: sandboxes hard-link it."""
    data = seed / 'data'
    data.mkdir(parents=True, exist_ok=True)
    make = None
    for world, kw in WORLDS.items():
        p = data / f'{world}.csv.gz'
        if not p.exists():
            make = make or _make_synthetic()
            tmp = data / f'{world}.tmp.csv.gz'
            make(world, symbols=40, years=12, seed=2026, **kw).to_csv(tmp, index=False)
            tmp.rename(p)
    if not (data / 'sample.csv.gz').exists():
        shutil.copy(EXAMPLES / 'data' / 'sample.csv.gz', data / 'sample.csv.gz')
    for p in data.iterdir():
        p.chmod(0o444)
    spec = json.loads((EXAMPLES / 'spec_sample.json').read_text())
    spec.update(boot=2000)
    (seed / 'spec_example.json').write_text(json.dumps(spec, indent=1) + '\n')
    shutil.copy(EXAMPLES / 'PREREG_TEMPLATE.md', seed / 'PREREG_TEMPLATE.md')
    (seed / 'README.md').write_text(README)
    return seed


class Box:
    """One session's sandbox and its counters. `lock` makes a session's calls run one at a time, so its ledger is
    appended in the order the calls arrived."""

    def __init__(self, path, seed):
        self.path, self.work = path, path / 'work'
        (self.work / 'data').mkdir(parents=True)
        for f in (seed / 'data').iterdir():
            try:
                os.link(f, self.work / 'data' / f.name)
            except OSError:
                shutil.copy(f, self.work / 'data' / f.name)
        for name in ('README.md', 'PREREG_TEMPLATE.md', 'spec_example.json'):
            shutil.copy(seed / name, self.work / name)
        self.log = EventLog(path / 'gate.jsonl')
        self.lock = threading.Lock()
        self.calls = self.writes = self.scores = 0
        self.last = time.time()


class Boxes:
    def __init__(self, base=None):
        self.base = Path(base or os.environ.get('SIGNAL_AUDIT_LIVE_DIR')
                         or Path(tempfile.gettempdir()) / 'signal-audit-live').resolve()
        shutil.rmtree(self.base / 's', ignore_errors=True)        # sandboxes never outlive the process that made them
        self.seed = prepare_seed(self.base / 'seed')
        self._boxes = {}
        self._lock = threading.Lock()

    def __len__(self):
        return len(self._boxes)

    def get(self, key):
        with self._lock:
            self._sweep()
            box = self._boxes.get(key)
            if box is None:
                if len(self._boxes) >= LIMITS['sessions']:
                    raise Full()
                box = self._boxes[key] = Box(self.base / 's' / secrets.token_hex(8), self.seed)
            box.last = time.time()
            return box

    def _sweep(self):
        cutoff = time.time() - 60 * LIMITS['idle_minutes']
        for key, box in list(self._boxes.items()):
            if box.last < cutoff:
                del self._boxes[key]
                shutil.rmtree(box.path, ignore_errors=True)
