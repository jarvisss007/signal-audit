"""Load OHLCV + signal data.

Accepts either one long CSV (with a `symbol` column) or a folder of one-CSV-per-symbol files (the symbol is then the
file name). `.csv.gz` works too.

Required columns: date, open, high, low, close, signal
Optional columns: symbol, eligible

  signal    integer code; 0 = no signal. Any non-zero code is a signal day and is kept out of every baseline,
            whichever codes are under test (e.g. -3/-2/-1 for graded short labels, 1/2/3 for long labels).
  eligible  True on days the signal COULD have fired (e.g. its higher-timeframe filter had data). Baselines and
            signals are both restricted to eligible days. Defaults to True everywhere.
"""
from pathlib import Path

import pandas as pd

REQUIRED = ('date', 'open', 'high', 'low', 'close', 'signal')


def _read(f):
    d = pd.read_csv(f)
    d.columns = [c.strip().lower() for c in d.columns]
    if 'symbol' not in d.columns:
        d['symbol'] = Path(f).name.split('.')[0]
    missing = [c for c in REQUIRED if c not in d.columns]
    if missing:
        raise ValueError(f'{f}: missing columns {missing}')
    return d


def load(path):
    p = Path(path)
    files = sorted([*p.glob('*.csv'), *p.glob('*.csv.gz')]) if p.is_dir() else [p]
    if not files:
        raise FileNotFoundError(f'no CSV files at {p}')
    d = pd.concat([_read(f) for f in files], ignore_index=True)
    d['symbol'] = d['symbol'].astype(str)
    d['date'] = pd.to_datetime(d['date'].astype(str).str[:10])
    d['signal'] = d['signal'].fillna(0).astype(int)
    if 'eligible' in d.columns:
        d['eligible'] = d['eligible'].astype(str).str.strip().str.lower().isin(('1', 'true', 'yes', 't'))
    else:
        d['eligible'] = True
    for c in ('open', 'high', 'low', 'close'):
        d[c] = d[c].astype(float)
    return d.sort_values(['symbol', 'date']).drop_duplicates(['symbol', 'date'], keep='last').reset_index(drop=True)
