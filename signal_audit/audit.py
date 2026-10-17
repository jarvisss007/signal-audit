"""One audit = one frozen spec, one placebo gate, one verdict. The verdict rules live here, in code, not in a prompt.

Q1 (the single trial): SUPPORTED only if the 95% interval of the mean excess is entirely above max(0, placebo mean)
    AND the mean excess is above 0 in both halves of time. A placebo beyond +/- placebo_gate makes the run VOID.
Q2 (attribution): read only if Q1 passes. "ADDS VALUE" only if its 95% interval is entirely above 0; otherwise
    "NOTHING BEYOND THE MOVE": whatever happened belongs to every day with that kind of move, not to the signal.
"""
import json
from dataclasses import asdict, dataclass, field

from . import forward, placebo


@dataclass
class Spec:
    data: str
    codes: list
    hold: int = 20
    cost: float = 0.0010           # round trip, charged on the signal trade only (the baseline is an average, not a trade)
    baseline: str = 'full_history'
    entry: str = 'next_open'       # a label printed at the close can only be traded at the next open
    split: str = None              # date that cuts the sample into two halves; default = middle of the data's dates
    boot: int = 5000
    seed: int = 11
    q2_min_cell: int = 20
    placebo_gate: float = 0.0030
    placebo_reps: int = 10
    placebo_seed: int = 7
    placebo_tail: str = 'auto'
    placebo_pct: float = 5.0
    name: str = ''
    notes: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path):
        return cls(**json.load(open(path)))


def decide(primary, plc, gate):
    """Return (verdict, q2_verdict, verdict_if_there_were_no_gate)."""
    ci = primary['excess_ci']
    halves = all(primary[h]['excess'] is not None and primary[h]['excess'] > 0 for h in ('early', 'late'))
    raw = 'SUPPORTED' if (ci and ci[0] > max(0.0, plc['mean']) and halves) else 'NOT SUPPORTED'
    verdict = 'VOID (placebo gate)' if abs(plc['mean']) > gate else raw
    if verdict == 'SUPPORTED':
        q = primary['q2']['ci']
        q2 = 'ADDS VALUE' if (q and q[0] > 0) else 'NOTHING BEYOND THE MOVE'
    else:
        q2 = 'NOT READ (Q1 did not pass)'
    return verdict, q2, raw


def run(spec, d=None):
    """Score a spec. `d` = an already-loaded frame (else spec.data is loaded). Returns the result dict."""
    from .data import load
    d = load(spec.data) if d is None else d
    f = forward.features(d, spec.hold)
    primary, _ = forward.score(f, spec.codes, spec.hold, spec.cost, spec.baseline, spec.split, spec.boot, spec.seed,
                               spec.q2_min_cell, spec.entry)
    plc = placebo.placebo(f, spec.codes, spec.hold, spec.cost, spec.baseline, spec.placebo_tail, spec.placebo_pct,
                          spec.placebo_reps, spec.placebo_seed)
    verdict, q2, raw = decide(primary, plc, spec.placebo_gate)
    res = {'spec': asdict(spec), 'symbols': int(f['symbol'].nunique()), 'ordinary_days': int((f['signal'] == 0).sum()),
           'placebo': plc, 'primary': primary, 'verdict': verdict, 'verdict_q2': q2}
    if verdict.startswith('VOID'):
        res['verdict_without_gate'] = raw
    if not verdict == 'SUPPORTED':
        res['primary']['q2'] = {'not_read': True, 'diagnostic_only': res['primary']['q2']}
    return res


def pct(x, d=2):
    return 'n/a' if x is None else f'{100 * x:+.{d}f}%'


def summary(res):
    p = res['primary']
    ci = p['excess_ci']
    rng = f'[{100 * ci[0]:+.2f}, {100 * ci[1]:+.2f}]' if ci else ''
    lines = [f"{res['spec'].get('name') or res['spec']['data']}",
             f"  signals {p['n']:,} on {p['symbols']} symbols, {p['months']} months; still running {p['still_running']}",
             f"  signal {pct(p['signal_return'])} vs ordinary {pct(p['ordinary_return'])}  ->  excess after cost "
             f"{pct(p['excess_after_cost'])} {rng}",
             f"  halves (split {p['split']}): {pct(p['early']['excess'])} / {pct(p['late']['excess'])}",
             f"  placebo ({res['placebo']['baseline']}, {res['placebo']['tail']} {res['placebo']['pct']:g}%): "
             f"{pct(res['placebo']['mean'])} (range {pct(res['placebo']['min'])}..{pct(res['placebo']['max'])}), "
             f"gate +/-{100 * res['spec']['placebo_gate']:.2f}%",
             f"  VERDICT Q1: {res['verdict']}" + (f"  (without the gate it would read: {res['verdict_without_gate']})"
                                                   if 'verdict_without_gate' in res else ''),
             f"  VERDICT Q2: {res['verdict_q2']}"]
    if res['verdict'] == 'SUPPORTED':
        q = p['q2']
        lines.append(f"  Q2 excess vs same-move days {pct(q['excess'])} "
                     f"[{100 * q['ci'][0]:+.2f}, {100 * q['ci'][1]:+.2f}] n={q['n']:,}" if q['ci'] else '')
    return '\n'.join(lines)
