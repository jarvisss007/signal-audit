"""The rules run_trial and friends enforce for a model caller: each test is one way to cheat, and it must be refused."""
import gzip
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from signal_audit import audit, governed as G  # noqa: E402

TID = 'SAMPLE-001/v1'
RULE = 'buy the next open after an A/A+ short label, sell 20 bars later'


@pytest.fixture
def work(tmp_path):
    (tmp_path / 'data').mkdir()
    shutil.copy(ROOT / 'examples' / 'data' / 'sample.csv.gz', tmp_path / 'data' / 'sample.csv.gz')
    spec = json.loads((ROOT / 'examples' / 'spec_sample.json').read_text())
    spec.update(boot=500, placebo_reps=3)
    (tmp_path / 'spec.json').write_text(json.dumps(spec))
    (tmp_path / 'PREREG.md').write_text(f'# {TID}: PRE-REGISTRATION\n\n{RULE}\n')
    G.set_root(tmp_path)
    yield tmp_path
    G._root = None


def register_and_freeze():
    G.register_trial(TID, RULE, 18)
    return G.freeze_rule('PREREG.md', 'spec.json', 'prereg.lock.json')


def test_the_loop_records_the_verdict_it_returns(work):
    lock = register_and_freeze()
    assert 'data/sample.csv.gz' in lock['frozen']                       # the data is part of the rule
    out = G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    spec = audit.Spec.load(work / 'spec.json')
    independent = audit.run(audit.Spec(**{**spec.__dict__, 'data': str(work / 'data' / 'sample.csv.gz')}))
    assert out['verdict'] == independent['verdict']
    led = G.read_ledger()
    assert led['ok'] and [r['kind'] for r in led['rows']] == ['register', 'result']
    assert led['rows'][-1]['body']['verdict'] == out['verdict'] and led['trials_total'] == 1
    assert led['open_trials'] == []


def test_a_trial_is_scored_once(work):
    register_and_freeze()
    G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    with pytest.raises(G.Refused, match='already scored'):
        G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    assert G.read_ledger()['lines'] == 2


def test_no_score_before_registration(work):
    register_and_freeze()
    with pytest.raises(G.Refused, match='not registered'):
        G.run_trial('OTHER-001/v1', 'spec.json', 'prereg.lock.json')
    assert G.read_ledger()['lines'] == 1


@pytest.mark.parametrize('change', ['spec', 'data'])
def test_a_change_after_the_freeze_is_refused_and_nothing_is_recorded(work, change):
    register_and_freeze()
    if change == 'spec':
        p = work / 'spec.json'
        p.write_text(p.read_text().replace('"hold": 20', '"hold": 10'))
    else:
        p = work / 'data' / 'sample.csv.gz'
        rows = gzip.decompress(p.read_bytes()).decode().splitlines()
        p.write_bytes(gzip.compress('\n'.join(rows[:-500]).encode()))   # quietly drop the last 500 bars
    with pytest.raises(G.Refused, match='freeze is broken'):
        G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    led = G.read_ledger()
    assert led['lines'] == 1 and led['open_trials'] == [TID]
    assert G.check_freeze('prereg.lock.json')['ok'] is False


def test_a_lock_is_written_once(work):
    register_and_freeze()
    with pytest.raises(G.Refused, match='frozen once'):
        G.freeze_rule('PREREG.md', 'spec.json', 'prereg.lock.json')


def test_only_a_frozen_spec_can_be_scored(work):
    register_and_freeze()
    shutil.copy(work / 'spec.json', work / 'spec2.json')
    with pytest.raises(G.Refused, match='not one of the files frozen'):
        G.run_trial(TID, 'spec2.json', 'prereg.lock.json')


def test_paths_outside_the_root_are_refused(work):
    with pytest.raises(G.Refused, match='outside the audit root'):
        G.describe_data('../elsewhere.csv')
    with pytest.raises(G.Refused, match='outside the audit root'):
        G.register_trial(TID, RULE, 1, ledger_path=str(work.parent / 'trials.jsonl'))
    spec = json.loads((work / 'spec.json').read_text())
    spec['data'] = '../outside.csv.gz'
    (work / 'spec.json').write_text(json.dumps(spec))
    with pytest.raises(G.Refused, match='outside the audit root'):
        G.freeze_rule('PREREG.md', 'spec.json', 'prereg.lock.json')


def test_an_edited_ledger_blocks_scoring(work):
    register_and_freeze()
    p = work / 'trials.jsonl'
    p.write_text(p.read_text().replace('"k_looks": 18', '"k_looks": 1'))  # shrink the mining tax after the fact
    with pytest.raises(G.Refused, match='ledger .* is broken'):
        G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    assert G.read_ledger()['ok'] is False


def test_a_correction_appends_and_never_edits(work):
    register_and_freeze()
    G.run_trial(TID, 'spec.json', 'prereg.lock.json')
    G.record_correction(TID, 'the sample is synthetic; the verdict says nothing about a real indicator')
    led = G.read_ledger(trial_id=TID)
    assert [r['kind'] for r in led['rows']] == ['register', 'result', 'correction'] and led['trials_total'] == 1
    with pytest.raises(G.Refused, match='never registered'):
        G.record_correction('NEVER-001/v1', 'x')


def test_describe_data_reports_shape_not_returns(work):
    d = G.describe_data('data/sample.csv.gz')
    assert d['symbols'] == 12 and set(d['signal_codes']) >= {'-3', '-2'}
    assert not any('return' in k or 'excess' in k for k in d)
