import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'examples'))

from make_synthetic import make                                  # noqa: E402
from signal_audit import audit, bracket, forward, ledger, placebo, prereg  # noqa: E402
from signal_audit.data import load                               # noqa: E402

CODES = [-2, -3]


def frame(world, **kw):
    d = make(world, **kw)
    d['date'] = pd.to_datetime(d['date'])
    d['eligible'] = True
    return d


@pytest.fixture(scope='module')
def null_world():
    return frame('null', symbols=60, years=12, seed=11)


def test_forward_returns_are_aligned_and_never_look_back():
    n, hold = 40, 5
    c = np.arange(1, n + 1, dtype=float) * 10
    o = c - 1
    d = pd.DataFrame({'symbol': 'X', 'date': pd.bdate_range('2020-01-01', periods=n), 'open': o, 'high': c + 1,
                      'low': o - 1, 'close': c, 'signal': 0, 'eligible': True})
    f = forward.features(d, hold).reset_index(drop=True)
    k = 7
    assert f.loc[k, 'fwd_open'] == pytest.approx(c[k + hold] / o[k + 1] - 1)      # buy next open, sell close k+hold
    assert f.loc[k, 'fwd_close'] == pytest.approx(c[k + hold] / c[k] - 1)
    assert f.loc[k, 'trail'] == pytest.approx(c[k] / c[k - hold] - 1)             # the move INTO bar k
    assert f['fwd_open'].iloc[-hold:].isna().all()                                 # no future bars, no return


def test_signal_days_of_any_code_stay_out_of_the_baseline():
    d = pd.DataFrame({'symbol': 'X', 'date': pd.bdate_range('2020-01-01', periods=6), 'signal': [0, -1, 2, 0, 0, -2]})
    d['fwd_open'] = [1.0, 100.0, 100.0, 3.0, 5.0, 100.0]
    b = forward.baseline(d, d['signal'] == 0, 'fwd_open', 'full_history')
    assert b.iloc[0] == pytest.approx(3.0)


def test_same_year_yardstick_is_biased_and_full_history_is_not(null_world):
    f = forward.features(null_world, 20)
    biased = placebo.placebo(f, CODES, 20, 0.001, 'same_year', reps=4)
    fair = placebo.placebo(f, CODES, 20, 0.001, 'full_history', reps=4)
    assert biased['tail'] == 'bottom'                    # the short labels follow falls
    assert biased['mean'] > 0.005                        # +0.5% or more of pure method bias on shuffled prices
    assert abs(fair['mean']) < 0.003                     # inside the gate


def test_null_world_is_not_supported_and_the_biased_run_is_void(null_world):
    fair = audit.run(audit.Spec(data='null', codes=CODES, boot=1000), null_world)
    assert fair['verdict'] == 'NOT SUPPORTED'
    assert fair['verdict_q2'].startswith('NOT READ')
    biased = audit.run(audit.Spec(data='null', codes=CODES, baseline='same_year', boot=1000), null_world)
    assert biased['verdict'] == 'VOID (placebo gate)'


def test_planted_edge_is_found_and_attributed_to_the_label():
    d = frame('planted', symbols=60, years=12, seed=11, plant=0.04)
    r = audit.run(audit.Spec(data='planted', codes=CODES, boot=1000), d)
    assert r['verdict'] == 'SUPPORTED'
    assert r['verdict_q2'] == 'ADDS VALUE'


def test_far_stops_fake_a_hit_rate_edge_that_matching_removes(null_world):
    r = bracket.score(null_world, CODES, side=-1, boot=1000)
    assert r['median_stop_atr_signal'] > r['median_stop_atr_ordinary'] + 0.3
    assert r['edge_unmatched_ci'][0] > 0                 # looks like an edge ...
    lo, hi = r['edge_same_stop_ci']
    assert lo < 0 < hi                                   # ... until days with the same stop are the yardstick


def test_decide_rules():
    p = {'excess_ci': [0.001, 0.01], 'early': {'excess': 0.002}, 'late': {'excess': 0.003}, 'q2': {'ci': [-0.01, 0.01]}}
    assert audit.decide(p, {'mean': 0.0}, 0.003) == ('SUPPORTED', 'NOTHING BEYOND THE MOVE', 'SUPPORTED')
    assert audit.decide(p, {'mean': 0.002}, 0.003)[0] == 'NOT SUPPORTED'           # bar is max(0, placebo)
    assert audit.decide(p, {'mean': 0.004}, 0.003)[0] == 'VOID (placebo gate)'
    p['late']['excess'] = -0.001
    assert audit.decide(p, {'mean': 0.0}, 0.003)[0] == 'NOT SUPPORTED'             # both halves must be positive


def test_freeze_refuses_a_changed_file(tmp_path):
    spec = tmp_path / 'spec.json'
    spec.write_text(json.dumps({'hold': 20}))
    lock = tmp_path / 'lock.json'
    prereg.freeze([spec], lock)
    prereg.verify(lock)
    spec.write_text(json.dumps({'hold': 10}))
    with pytest.raises(prereg.FrozenFileChanged):
        prereg.verify(lock)


def test_ledger_counts_trials_and_detects_tampering(tmp_path):
    p = tmp_path / 'trials.jsonl'
    with pytest.raises(ValueError):
        ledger.append(p, 'result', 'T-1/v1')                                       # no result without a registration
    ledger.append(p, 'register', 'T-1/v1', {'rule': 'x'}, k_looks=18)
    e = ledger.append(p, 'result', 'T-1/v1', {'verdict': 'NOT SUPPORTED'})
    assert (e['trials_before'], e['trials_after']) == (1, 1)                       # a result is not a trial
    with pytest.raises(ValueError):
        ledger.append(p, 'register', 'T-1/v1')                                     # a change needs a new id
    assert ledger.append(p, 'register', 'T-1/v2')['trials_after'] == 2
    p.write_text(p.read_text().replace('NOT SUPPORTED', 'SUPPORTED'))
    with pytest.raises(ledger.LedgerBroken):
        ledger.verify(p)
    lines = (tmp_path / 'trials.jsonl').read_text().splitlines()
    (tmp_path / 'cut.jsonl').write_text('\n'.join(lines[:1] + lines[2:]) + '\n')
    with pytest.raises(ledger.LedgerBroken):
        ledger.verify(tmp_path / 'cut.jsonl')                                      # a deleted line is detected too


def test_loader_reads_a_folder_of_per_symbol_files(tmp_path):
    for sym in ('AAA', 'BBB'):
        pd.DataFrame({'date': ['2020-01-02', '2020-01-03'], 'open': [1, 2], 'high': [2, 3], 'low': [0.5, 1.5],
                      'close': [1.5, 2.5], 'signal': [0, -2], 'eligible': ['true', 'False']}).to_csv(
            tmp_path / f'{sym}.csv', index=False)
    d = load(tmp_path)
    assert sorted(d['symbol'].unique()) == ['AAA', 'BBB']
    assert d['eligible'].tolist() == [True, False, True, False]
