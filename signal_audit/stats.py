"""Cluster bootstrap for the mean of per-signal values.

Signals cluster in time (many stocks fire in the same sell-off) and a 20-day hold spans about a month, so signals are
resampled in whole calendar MONTHS, never one by one. Blocks much longer than the hold make the interval narrower,
not wider, because a crash and its rebound cancel inside one block; a month is the shortest block that covers a hold.
"""
import numpy as np
import pandas as pd


def cluster_ci(dates, values, boot=5000, seed=11, freq='M', min_n=10):
    """95% interval of mean(values), resampling whole calendar periods. Returns ([lo, hi] or None, n_clusters)."""
    v = np.asarray(values, float)
    ok = np.isfinite(v)
    v = v[ok]
    if len(v) < min_n:
        return None, 0
    keys = pd.Series(pd.to_datetime(dates)).dt.to_period(freq).astype(str).to_numpy()[ok]
    uniq, inv = np.unique(keys, return_inverse=True)
    sums = np.bincount(inv, weights=v)
    counts = np.bincount(inv).astype(float)
    pick = np.random.default_rng(seed).integers(0, len(uniq), (boot, len(uniq)))
    means = sums[pick].sum(1) / counts[pick].sum(1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))], int(len(uniq))
