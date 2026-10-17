"""Bracket test: does a signal reach its target before its stop more often than an ordinary day with the SAME stop distance?

Entry = the signal bar's close. Stop = the bar's low - stop_atr x ATR (long) / high + stop_atr x ATR (short).
Target = entry +/- target_atr x ATR. Walk the next `horizon` bars:
  open beyond the stop or the target -> out at that open (a real gap);
  a bar touching both                 -> counted as the STOP (the order inside a daily bar is unknown);
  neither in `horizon` bars           -> time exit at the last close.

Why match on stop distance: a signal bar that closes at its extreme puts the stop far away, while the target is a fixed
ATR multiple. A far stop alone raises the "target first" rate. In the real study, labels' stops sat a median 1.46 ATR
away against 0.89 on an ordinary day, and a +7.8-point hit-rate "edge" vanished once days were compared with days of the
same stop distance. Ordinary days are binned by risk/ATR within each symbol (whole history); bins with fewer than
`min_cell` days are dropped.
"""
import numpy as np
import pandas as pd

from .stats import cluster_ci

RISK_BINS = [0, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.5, 3.0, 99]


def atr_wilder(h, l, c, n=14):
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.r_[np.nan, c[:-1]]), np.abs(l - np.r_[np.nan, c[:-1]])))
    tr[0] = h[0] - l[0]
    atr = np.full(len(c), np.nan)
    if len(c) >= n:
        atr[n - 1] = tr[:n].mean()
        for i in range(n, len(c)):
            atr[i] = (atr[i - 1] * (n - 1) + tr[i]) / n
    return atr


def outcomes(o, h, l, c, atr, side, stop_atr, target_atr, horizon):
    """Every bar as a hypothetical entry at its close. Returns kind (+1 target first, -1 stop first, 0 time exit,
    nan = no entry or still running), R multiple, risk/ATR, and a same-bar-ambiguity flag."""
    n = len(c)
    E = c.copy()
    if side > 0:
        SL, TP = l - stop_atr * atr, E + target_atr * atr
        risk = E - SL
    else:
        SL, TP = h + stop_atr * atr, E - target_atr * atr
        risk = SL - E
    kind, exitp, amb = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, bool)
    live = np.isfinite(atr) & (risk > 0)
    idx = np.arange(n)
    for j in range(1, horizon + 1):
        k = np.minimum(idx + j, n - 1)
        valid = live & (idx + j < n)
        if not valid.any():
            break
        oj, hj, lj = o[k], h[k], l[k]
        if side > 0:
            gap_sl, gap_tp, hit_sl, hit_tp = oj <= SL, oj >= TP, lj <= SL, hj >= TP
        else:
            gap_sl, gap_tp, hit_sl, hit_tp = oj >= SL, oj <= TP, hj >= SL, lj <= TP
        m = valid & gap_sl
        kind[m], exitp[m] = -1, oj[m]
        live &= ~m
        m = valid & ~gap_sl & gap_tp
        kind[m], exitp[m] = 1, oj[m]
        live &= ~m
        rest = valid & ~gap_sl & ~gap_tp
        amb |= rest & hit_sl & hit_tp
        m = rest & hit_sl
        kind[m], exitp[m] = -1, SL[m]
        live &= ~m
        m = rest & ~hit_sl & hit_tp
        kind[m], exitp[m] = 1, TP[m]
        live &= ~m
    m = live & (idx + horizon < n)
    kind[m], exitp[m] = 0, c[np.minimum(idx + horizon, n - 1)][m]
    R = np.where(np.isfinite(exitp), side * (exitp - E) / risk, np.nan)
    return kind, R, risk / atr, amb


def score(d, codes, side, stop_atr=0.5, target_atr=1.5, horizon=30, min_cell=20, boot=5000, seed=11):
    parts = []
    for _, g in d.groupby('symbol', sort=False):
        o, h, l, c = (g[x].to_numpy(float) for x in ('open', 'high', 'low', 'close'))
        kind, R, risk_atr, amb = outcomes(o, h, l, c, atr_wilder(h, l, c), side, stop_atr, target_atr, horizon)
        parts.append(g.assign(kind=kind, R=R, risk_atr=risk_atr, amb=amb))
    f = pd.concat(parts, ignore_index=True)
    f = f[f['eligible'] & f['kind'].isin([-1, 0, 1])].copy()
    f['hit'] = (f['kind'] == 1).astype(float)
    f['bin'] = pd.cut(f['risk_atr'], RISK_BINS)
    ordn = f[f['signal'] == 0]
    lab = f[f['signal'].isin(codes)].copy()
    lab['base_any'] = lab['symbol'].map(ordn.groupby('symbol')['hit'].mean())
    cells = ordn.groupby(['symbol', 'bin'], observed=True).agg(base_hit=('hit', 'mean'), base_R=('R', 'mean'),
                                                                 base_n=('hit', 'size')).reset_index()
    m = lab.merge(cells, on=['symbol', 'bin'], how='left')
    m = m[m['base_n'] >= min_cell]
    return {'side': 'long' if side > 0 else 'short', 'n': int(len(lab)), 'n_matched': int(len(m)),
            'hit': float(lab['hit'].mean()), 'ordinary_hit_any_stop': float(lab['base_any'].mean()),
            'edge_unmatched': float((lab['hit'] - lab['base_any']).mean()),
            'edge_unmatched_ci': cluster_ci(lab['date'], lab['hit'] - lab['base_any'], boot, seed)[0],
            'hit_matched_sample': float(m['hit'].mean()), 'ordinary_hit_same_stop': float(m['base_hit'].mean()),
            'edge_same_stop': float((m['hit'] - m['base_hit']).mean()),
            'edge_same_stop_ci': cluster_ci(m['date'], m['hit'] - m['base_hit'], boot, seed)[0],
            'R': float(m['R'].mean()), 'ordinary_R_same_stop': float(m['base_R'].mean()),
            'R_gap_ci': cluster_ci(m['date'], m['R'] - m['base_R'], boot, seed)[0],
            'median_stop_atr_signal': float(lab['risk_atr'].median()),
            'median_stop_atr_ordinary': float(ordn['risk_atr'].median()),
            'same_bar_stop_and_target': int(lab['amb'].sum())}
