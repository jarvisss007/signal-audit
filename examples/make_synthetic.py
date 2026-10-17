"""Generate synthetic OHLCV + signal data with KNOWN truth, so every part of the audit can be checked against it.

Prices: one market factor plus per-symbol noise, daily, with gaps and intraday ranges. Signals copy the situation of the
real study's labels without its logic: a "short label" prints when the price has fallen hard over 20 days and the bar
closes near its low (codes -2 = "A", -3 = "A+", -1 = "B"); a "long label" mirrors it after a rise (2 / 3 / 1). Labels
are at least 20 bars apart per side.

Worlds (the truth is set here, then the audit has to find it):
  null      labels predict nothing. Any "edge" the audit reports is a bug in the audit.
  planted   after every A/A+ short label the price drifts up by --plant over the next 20 bars. A real, label-specific edge.
  reversal  EVERY sharp 20-day fall partly reverses, label or not. Q1 should pass, and Q2 should say the label adds
            nothing beyond the fall.

  python examples/make_synthetic.py --world null --out examples/data/null.csv.gz
"""
import argparse
import math

import numpy as np
import pandas as pd

HOLD = 20


def one_symbol(rng, mkt, dates, world, plant, reversal, beta, vol):
    n = len(mkt)
    # every random number is drawn up front; the loop only does arithmetic (and lets planted drift react to labels)
    eps = rng.standard_t(5, n) * vol / np.sqrt(5 / 3)
    base = (beta * mkt + eps).tolist()
    gap_share, gap_noise = rng.uniform(0.0, 0.5, n).tolist(), rng.normal(0, 0.25 * vol, n).tolist()
    up_wick, down_wick = np.abs(rng.normal(0, 0.45 * vol, n)).tolist(), np.abs(rng.normal(0, 0.45 * vol, n)).tolist()
    grade_u = rng.random(n).tolist()
    close, o, h, lo, sig = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n, [0] * n
    drift = [0.0] * (n + HOLD + 1)
    step = math.log1p(plant) / HOLD
    last_s = last_l = -10 ** 9
    prev = 100.0
    band = 1.5 * vol * math.sqrt(HOLD) * 1.25          # "a hard 20-day move" for this symbol
    for t in range(n):
        lr = base[t] + drift[t]
        if world == 'reversal' and t > HOLD:
            trail = close[t - 1] / close[t - 1 - HOLD] - 1
            if trail < -band:
                lr += -reversal * trail / HOLD           # every sharp fall gives back part of itself
        c = prev * math.exp(lr)
        o[t] = prev * math.exp(lr * gap_share[t] + gap_noise[t])
        h[t] = max(o[t], c) * math.exp(up_wick[t])
        lo[t] = min(o[t], c) * math.exp(-down_wick[t])
        close[t] = prev = c
        if t <= HOLD:
            continue
        trail = c / close[t - HOLD] - 1
        pos = (c - lo[t]) / max(h[t] - lo[t], 1e-12)  # where the bar closed inside its range
        u = grade_u[t]
        if trail < -band and pos < 0.35 and t - last_s >= HOLD:
            sig[t] = -3 if u < 0.2 else (-2 if u < 0.75 else -1)
            last_s = t
            if world == 'planted' and sig[t] in (-2, -3):
                for k in range(t + 1, t + 1 + HOLD):
                    drift[k] += step
        elif trail > band and pos > 0.65 and t - last_l >= HOLD:
            sig[t] = 3 if u < 0.2 else (2 if u < 0.75 else 1)
            last_l = t
    return pd.DataFrame({'date': dates, 'open': o, 'high': h, 'low': lo, 'close': close, 'signal': sig})


def make(world='null', symbols=40, years=12, seed=2026, plant=0.025, reversal=0.25):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range('2010-01-04', periods=252 * years)
    n = len(dates)
    # market factor with calm and stressed spells, so signals cluster in sell-offs as they do in real data
    regime_vol = np.where(np.sin(np.arange(n) / 90.0) + rng.normal(0, 0.6, n) > 1.1, 0.022, 0.009)
    mkt = 0.0003 + rng.normal(0, 1, n) * regime_vol
    frames = []
    for i in range(symbols):
        df = one_symbol(rng, mkt, dates, world, plant, reversal, beta=rng.uniform(0.7, 1.4), vol=rng.uniform(0.012, 0.022))
        df.insert(0, 'symbol', f'SYN{i:02d}')
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    for c in ('open', 'high', 'low', 'close'):
        out[c] = out[c].round(4)
    out['date'] = out['date'].dt.strftime('%Y-%m-%d')
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--world', choices=('null', 'planted', 'reversal'), default='null')
    ap.add_argument('--symbols', type=int, default=40)
    ap.add_argument('--years', type=int, default=12)
    ap.add_argument('--seed', type=int, default=2026)
    ap.add_argument('--plant', type=float, default=0.025, help='planted 20-bar drift after A/A+ shorts (planted world)')
    ap.add_argument('--reversal', type=float, default=0.25, help='share of a sharp fall that reverses (reversal world)')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    df = make(a.world, a.symbols, a.years, a.seed, a.plant, a.reversal)
    df.to_csv(a.out, index=False)
    s = df['signal']
    print(f'{a.out}: {len(df):,} rows, {df.symbol.nunique()} symbols, short labels A/A+ {int(s.isin([-2, -3]).sum())}, '
          f'all labels {int((s != 0).sum())}')
