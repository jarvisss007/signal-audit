"""Placebo gate: run the SAME baseline and cost on data where nothing can predict anything.

Each symbol's daily returns are shuffled (which destroys every time pattern but keeps the return distribution and the
calendar), pseudo-signals are placed where the shuffled price just made a move as extreme as the one the real signals
follow, and they are scored exactly like the real ones. The answer must be about zero. If it is not, the method has a
bias of that size, whatever the real signals show, and the run is VOID.

The pseudo-signal rule copies the real signals' situation, not their logic:
  tail='bottom'  trailing `hold`-day move in the symbol's bottom `pct`% (signals that follow a fall)
  tail='top'     trailing move in the top `pct`% (signals that follow a rise)
  tail='auto'    whichever side the real signals' average trailing move is on
Pseudo-signals are at least `hold` bars apart, like real signals with a minimum gap.
"""
import numpy as np
import pandas as pd


def pick_tail(f, codes):
    lab = f.loc[f['signal'].isin(codes), 'trail'].mean()
    ordn = f.loc[f['signal'] == 0, 'trail'].mean()
    return 'bottom' if lab < ordn else 'top'


def placebo(f, codes, hold, cost, baseline_kind='full_history', tail='auto', pct=5.0, reps=10, seed=7,
            min_days=300):
    """Mean excess of pseudo-signals on shuffled prices, one number per shuffle. `f` comes from forward.features()."""
    if tail == 'auto':
        tail = pick_tail(f, codes)
    rng = np.random.default_rng(seed)
    groups = []
    for _, g in f.groupby('symbol', sort=False):
        g = g[np.isfinite(g['r1'])]
        if len(g) >= min_days:
            groups.append((g['r1'].to_numpy(), g['date'].dt.year.to_numpy()))
    reps_out = []
    for _ in range(reps):
        ex = []
        for r1, years in groups:
            c = np.cumprod(1 + rng.permutation(r1))
            n = len(c)
            fwd = np.full(n, np.nan)
            fwd[:-hold] = c[hold:] / c[:-hold] - 1
            trail = np.full(n, np.nan)
            trail[hold:] = c[hold:] / c[:-hold] - 1
            thr = np.nanpercentile(trail, pct if tail == 'bottom' else 100 - pct)
            hit = np.where(trail <= thr)[0] if tail == 'bottom' else np.where(trail >= thr)[0]
            lab = np.zeros(n, bool)
            last = -10 ** 9
            for j in hit:
                if j - last >= hold:
                    lab[j] = True
                    last = j
            ordinary = ~lab & np.isfinite(fwd)
            if baseline_kind == 'full_history':
                base = np.full(n, fwd[ordinary].mean())
            else:
                ym = pd.Series(fwd[ordinary]).groupby(years[ordinary]).mean()
                base = pd.Series(years).map(ym).to_numpy(float)
            k = lab & np.isfinite(fwd) & np.isfinite(base)
            ex.append(fwd[k] - cost - base[k])
        reps_out.append(float(np.mean(np.concatenate(ex))) if ex else float('nan'))
    return {'mean': float(np.mean(reps_out)), 'min': float(np.min(reps_out)), 'max': float(np.max(reps_out)),
            'reps': reps, 'tail': tail, 'pct': pct, 'baseline': baseline_kind}
