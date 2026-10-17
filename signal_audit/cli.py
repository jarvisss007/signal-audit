"""Command line.

  python -m signal_audit freeze  --out prereg.lock.json PREREG.md spec.json [universe.txt ...]
  python -m signal_audit verify  prereg.lock.json
  python -m signal_audit score   --spec spec.json [--lock prereg.lock.json] [--out result.json]
  python -m signal_audit bracket --data DATA --codes -2,-3 --side short [--stop-atr 0.5 --target-atr 1.5 --horizon 30]
  python -m signal_audit ledger  register|result|correction --ledger trials.jsonl --id ID [--k-looks N] [--body JSON]
  python -m signal_audit ledger  verify|show --ledger trials.jsonl
"""
import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from . import audit, bracket, ledger, prereg
from .data import load


def _codes(s):
    return [int(x) for x in s.split(',') if x.strip()]


def cmd_score(a):
    spec_path = Path(a.spec).resolve()
    if a.lock:
        lock = prereg.verify(a.lock)
        if str(Path(a.spec)) not in lock['files'] and str(spec_path) not in lock['files']:
            sys.exit(f'refusing to score: {a.spec} is not one of the frozen files in {a.lock}')
        print(f'freeze check OK: {len(lock["files"])} files unchanged since {lock["frozen_at"]}')
    spec = audit.Spec.load(spec_path)
    if not Path(spec.data).is_absolute():
        spec = replace(spec, data=str((spec_path.parent / spec.data).resolve()))
    res = audit.run(spec)
    print(audit.summary(res))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, default=str) + '\n')


def cmd_bracket(a):
    side = 1 if a.side == 'long' else -1
    r = bracket.score(load(a.data), _codes(a.codes), side, a.stop_atr, a.target_atr, a.horizon, a.min_cell, a.boot)
    f = lambda c: f'[{100 * c[0]:+.1f}, {100 * c[1]:+.1f}]' if c else ''
    print(f"{r['side']} signals {r['n']:,}: target before stop {100 * r['hit']:.1f}%\n"
          f"  vs ordinary days (any stop)  {100 * r['ordinary_hit_any_stop']:.1f}%  edge {100 * r['edge_unmatched']:+.1f} pts "
          f"{f(r['edge_unmatched_ci'])}\n"
          f"  vs ordinary days, SAME stop  {100 * r['ordinary_hit_same_stop']:.1f}%  edge {100 * r['edge_same_stop']:+.1f} pts "
          f"{f(r['edge_same_stop_ci'])}  (n {r['n_matched']:,})\n"
          f"  median stop distance: signal {r['median_stop_atr_signal']:.2f} ATR vs ordinary {r['median_stop_atr_ordinary']:.2f}")
    if a.out:
        Path(a.out).write_text(json.dumps(r, indent=1) + '\n')


def cmd_ledger(a):
    if a.action == 'verify':
        rows = ledger.verify(a.ledger)
        print(f'ledger OK: {len(rows)} lines, trials {rows[-1]["trials_after"] if rows else 0}')
    elif a.action == 'show':
        for r in ledger.verify(a.ledger):
            k = '' if r['k_looks'] is None else f"  K={r['k_looks']}"
            print(f"{r['seq']:>3} {r['ts']} {r['kind']:<10} {r['id']:<22} trials {r['trials_before']}->{r['trials_after']}"
                  f"{k}  {json.dumps(r['body'])[:90]}")
    else:
        body = json.loads(a.body) if a.body else {}
        if a.body_file:
            body.update(json.loads(Path(a.body_file).read_text()))
        e = ledger.append(a.ledger, a.action, a.id, body, a.k_looks)
        print(f"{e['kind']} {e['id']}: trials {e['trials_before']} -> {e['trials_after']} (line {e['seq']})")


def main(argv=None):
    ap = argparse.ArgumentParser(prog='signal_audit', description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('freeze')
    p.add_argument('--out', required=True)
    p.add_argument('--no-scorer', action='store_true', help="don't freeze this package's own source")
    p.add_argument('files', nargs='+')
    p = sub.add_parser('verify')
    p.add_argument('lock')
    p = sub.add_parser('score')
    p.add_argument('--spec', required=True)
    p.add_argument('--lock')
    p.add_argument('--out')
    p = sub.add_parser('bracket')
    p.add_argument('--data', required=True)
    p.add_argument('--codes', required=True)
    p.add_argument('--side', choices=('long', 'short'), required=True)
    p.add_argument('--stop-atr', type=float, default=0.5)
    p.add_argument('--target-atr', type=float, default=1.5)
    p.add_argument('--horizon', type=int, default=30)
    p.add_argument('--min-cell', type=int, default=20)
    p.add_argument('--boot', type=int, default=5000)
    p.add_argument('--out')
    p = sub.add_parser('ledger')
    p.add_argument('action', choices=('register', 'result', 'correction', 'verify', 'show'))
    p.add_argument('--ledger', required=True)
    p.add_argument('--id')
    p.add_argument('--k-looks', type=int)
    p.add_argument('--body')
    p.add_argument('--body-file')
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'freeze':
            lock = prereg.freeze(a.files, a.out, include_scorer=not a.no_scorer)
            print(f'frozen {len(lock["files"])} files at {lock["frozen_at"]} -> {a.out}')
        elif a.cmd == 'verify':
            lock = prereg.verify(a.lock)
            print(f'OK: {len(lock["files"])} files unchanged since {lock["frozen_at"]}')
        elif a.cmd == 'score':
            cmd_score(a)
        elif a.cmd == 'bracket':
            cmd_bracket(a)
        elif a.cmd == 'ledger':
            if a.action in ('register', 'result', 'correction') and not a.id:
                ap.error('--id is required')
            cmd_ledger(a)
    except (prereg.FrozenFileChanged, ledger.LedgerBroken, ValueError) as e:
        sys.exit(f'REFUSED: {e}')


if __name__ == '__main__':
    main()
