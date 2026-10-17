"""Forward-return test: after a signal, does price move more than it does on the same symbol's ordinary days?

Per signal:  excess = (buy next open, sell the close `hold` bars after the signal bar) - cost - baseline
Ordinary day = an eligible day on which no signal of ANY code fired.

Two baselines are implemented on purpose:

  full_history  mean forward return of the symbol's ordinary days over its whole history (default; the corrected method)
  same_year     mean forward return of the symbol's ordinary days in the signal's calendar year (the biased method; kept
                so the bias can be reproduced. Signals that follow a move share their calendar year with the days of
                that move, whose own forward returns cover it, so the yardstick is tilted against the signal's side.
                On shuffled prices it scored +1.45% for "signals" after a fall. See docs/reviewer_report.md.)

Attribution (Q2): the same signals against ordinary days of the same symbol whose 1-day move AND trailing `hold`-day
move fall in the same deciles (deciles of that symbol's own history; cells with at least `q2_min_cell` days). It asks
whether the signal adds anything beyond "the price just moved a lot".
"""
import numpy as np
import pandas as pd

from .stats import cluster_ci

BASELINES = ('full_history', 'same_year')


def _decile(x):
    return np.minimum((x.rank(pct=True) * 10).fillna(0).astype(int), 9)


def features(d, hold):
    """Per-bar forward/trailing returns on each symbol's own bars, then restricted to eligible days."""
    parts = []
    for _, g in d.groupby('symbol', sort=False):
        g = g.copy()
        o, c = g['open'].to_numpy(float), g['close'].to_numpy(float)
        n = len(c)
        fwd_open, fwd_close = np.full(n, np.nan), np.full(n, np.nan)
        if n > hold:
            fwd_open[:n - hold] = c[hold:] / o[1:n - hold + 1] - 1      # next open -> close `hold` bars after the signal
            fwd_close[:n - hold] = c[hold:] / c[:n - hold] - 1          # signal close -> same close
        r1, trail = np.full(n, np.nan), np.full(n, np.nan)
        r1[1:] = c[1:] / c[:-1] - 1
        if n > hold:
            trail[hold:] = c[hold:] / c[:-hold] - 1                     # the move INTO the signal bar
        g['fwd_open'], g['fwd_close'], g['r1'], g['trail'] = fwd_open, fwd_close, r1, trail
        parts.append(g)
    f = pd.concat(parts, ignore_index=True)
    f = f[f['eligible']].copy()
    f['d1'] = f.groupby('symbol')['r1'].transform(_decile)
    f['dtrail'] = f.groupby('symbol')['trail'].transform(_decile)
    return f


def baseline(f, ordinary, col, kind):
    """Per-row baseline: mean of `col` over the symbol's ordinary days (whole history, or the row's calendar year)."""
    if kind not in BASELINES:
        raise ValueError(f'baseline must be one of {BASELINES}')
    o = f[ordinary]
    if kind == 'full_history':
        return f['symbol'].map(o.groupby('symbol')[col].mean())
    m = o.groupby([o['symbol'], o['date'].dt.year])[col].mean().rename('_b').reset_index()
    m.columns = ['symbol', '_year', '_b']
    key = pd.DataFrame({'symbol': f['symbol'].to_numpy(), '_year': f['date'].dt.year.to_numpy()})
    return pd.Series(key.merge(m, on=['symbol', '_year'], how='left')['_b'].to_numpy(), index=f.index)


def score(f, codes, hold, cost, baseline_kind='full_history', split=None, boot=5000, seed=11, q2_min_cell=20,
          entry='next_open'):
    """Score the signals with the given codes. `f` comes from features(). Returns a dict of plain numbers."""
    col = 'fwd_open' if entry == 'next_open' else 'fwd_close'
    ordinary = f['signal'] == 0
    f = f.assign(base=baseline(f, ordinary, col, baseline_kind))
    lab = f[f['signal'].isin(codes)]
    s = lab[lab[col].notna() & lab['base'].notna()].copy()
    s['excess'] = s[col] - cost - s['base']
    ci, months = cluster_ci(s['date'], s['excess'], boot, seed)
    out = {'n': int(len(s)), 'still_running': int(lab[col].isna().sum()), 'symbols': int(s['symbol'].nunique()),
           'months': months, 'first': str(s['date'].min().date()) if len(s) else None,
           'last': str(s['date'].max().date()) if len(s) else None,
           'signal_return': float(s[col].mean()) if len(s) else None,
           'ordinary_return': float(s['base'].mean()) if len(s) else None,
           'excess_after_cost': float(s['excess'].mean()) if len(s) else None, 'excess_ci': ci,
           'median_excess': float(s['excess'].median()) if len(s) else None,
           'signal_up': float((s[col] > 0).mean()) if len(s) else None,
           'ordinary_up': float(s['symbol'].map(f.loc[ordinary].groupby('symbol')[col].apply(
               lambda x: (x.dropna() > 0).mean())).mean()) if len(s) else None,
           'trailing_move_before_signal': float(s['trail'].mean()) if len(s) else None}
    split = pd.Timestamp(split) if split else f['date'].min() + (f['date'].max() - f['date'].min()) / 2
    out['split'] = str(split.date())
    for name, part in (('early', s[s['date'] < split]), ('late', s[s['date'] >= split])):
        out[name] = {'n': int(len(part)), 'excess': float(part['excess'].mean()) if len(part) else None}
    # Q2: same symbol, same 1-day-move decile AND same trailing-move decile
    o = f[ordinary]
    cells = o.groupby(['symbol', 'd1', 'dtrail'])[col].agg(['mean', 'count']).reset_index()
    cells.columns = ['symbol', 'd1', 'dtrail', 'q2_base', 'q2_n']
    q = s.merge(cells, on=['symbol', 'd1', 'dtrail'], how='left')
    q = q[q['q2_n'] >= q2_min_cell]
    e2 = q[col] - cost - q['q2_base']
    out['q2'] = {'n': int(len(q)), 'excess': float(e2.mean()) if len(q) else None,
                 'ci': cluster_ci(q['date'], e2, boot, seed)[0]}
    return out, s
