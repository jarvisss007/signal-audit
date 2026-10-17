"""Test the tester: how often does each yardstick say SUPPORTED when nothing is there, and when something is?

Generates many seeded worlds (null and planted), scores each with both yardsticks using the Q1 rule WITHOUT the placebo
gate (95% interval above 0 and both halves above 0), and counts passes.

  python examples/calibration.py [--seeds 25] [--symbols 80] [--years 16] [--workers 4]     # a few minutes

A correct test passes about 2.5% of null worlds (a one-sided 95% interval) and most planted ones.
"""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'examples'))

from make_synthetic import make            # noqa: E402
from signal_audit import forward           # noqa: E402

CODES = [-2, -3]


def one(job):
    world, seed, symbols, years = job
    d = make(world, symbols=symbols, years=years, seed=seed)
    d['date'] = pd.to_datetime(d['date'])
    d['eligible'] = True
    f = forward.features(d, 20)
    out = {'world': world, 'seed': seed}
    for base in ('same_year', 'full_history'):
        r, _ = forward.score(f, CODES, 20, 0.001, base, None, boot=1000, seed=11)
        passed = bool(r['excess_ci'] and r['excess_ci'][0] > 0 and r['early']['excess'] > 0 and r['late']['excess'] > 0)
        out[base] = {'excess': r['excess_after_cost'], 'lo': r['excess_ci'][0], 'passed': passed, 'n': r['n']}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seeds', type=int, default=25)
    ap.add_argument('--symbols', type=int, default=80)
    ap.add_argument('--years', type=int, default=16)
    ap.add_argument('--workers', type=int, default=4)
    a = ap.parse_args()
    jobs = [(w, 1000 + s, a.symbols, a.years) for w in ('null', 'planted') for s in range(a.seeds)]
    with ProcessPoolExecutor(a.workers) as ex:
        res = list(ex.map(one, jobs))
    summary = {}
    for w in ('null', 'planted'):
        for base in ('same_year', 'full_history'):
            rows = [r[base] for r in res if r['world'] == w]
            summary[f'{w} / {base}'] = {'worlds': len(rows), 'passed': int(sum(r['passed'] for r in rows)),
                                         'pass_rate': float(np.mean([r['passed'] for r in rows])),
                                         'mean_excess': float(np.mean([r['excess'] for r in rows])),
                                         'mean_signals': float(np.mean([r['n'] for r in rows]))}
    print(f"{a.seeds} seeds per world, {a.symbols} symbols x {a.years} years, Q1 rule without the placebo gate")
    print(f"{'world / yardstick':<28}{'passed':>10}{'mean excess':>14}")
    for k, v in summary.items():
        print(f"{k:<28}{v['passed']:>4} of {v['worlds']:<4}{100 * v['mean_excess']:>+13.2f}%")
    out = ROOT / 'results' / 'calibration.json'
    out.write_text(json.dumps({'args': vars(a), 'summary': summary, 'worlds': res}, indent=1) + '\n')
    print(f'wrote {out.relative_to(ROOT)}')


if __name__ == '__main__':
    main()
