"""The whole audit on synthetic data whose truth is known. About a minute.

  python examples/demo.py            # generates three worlds (seeded), audits them, prints the table, writes docs/demo.png

  world     truth set by the generator                 what a correct audit must say
  null      labels predict nothing                     NOT SUPPORTED, and the biased yardstick must be caught
  planted   +2.5% drift after every A/A+ short label   SUPPORTED, ADDS VALUE
  reversal  every sharp fall partly reverses           SUPPORTED, but NOTHING BEYOND THE MOVE (the label adds nothing)
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'examples'))

from make_synthetic import make                       # noqa: E402
from signal_audit import audit, bracket               # noqa: E402
from signal_audit.data import load                    # noqa: E402

GEN = ROOT / 'examples' / 'data' / 'generated'
WORLDS = {'null': ('labels predict nothing', {}),
          'planted': ('+2.5% after A/A+ shorts', {'plant': 0.025}),
          'reversal': ('every sharp fall partly reverses', {'reversal': 0.4})}
RUNS = [('null', 'same_year'), ('null', 'full_history'), ('planted', 'full_history'), ('reversal', 'full_history')]
CODES = [-2, -3]     # the "A" and "A+" short labels; -1 ("B") and all long labels stay out of the baselines


def world(name):
    GEN.mkdir(parents=True, exist_ok=True)
    path = GEN / f'{name}.csv.gz'
    if not path.exists():
        print(f'generating {name} world (80 symbols x 16 years) ...', flush=True)
        make(name, symbols=80, years=16, seed=2026, **WORLDS[name][1]).to_csv(path, index=False)
    return load(path)


def pct(x):
    return f'{100 * x:+.2f}%'


def main():
    data = {w: world(w) for w in WORLDS}
    rows = []
    for w, base in RUNS:
        spec = audit.Spec(data=f'examples/data/generated/{w}.csv.gz', codes=CODES, baseline=base, name=f'{w} / {base}')
        r = audit.run(spec, data[w])
        p = r['primary']
        rows.append({'world': w, 'truth': WORLDS[w][0], 'baseline': base, 'n': p['n'], 'excess': p['excess_after_cost'],
                     'ci': p['excess_ci'], 'placebo': r['placebo']['mean'], 'placebo_range': [r['placebo']['min'],
                     r['placebo']['max']], 'verdict': r['verdict'], 'without_gate': r.get('verdict_without_gate'),
                     'q2': r['verdict_q2'], 'q2_excess': p['q2'].get('excess')})
    br = bracket.score(data['null'], CODES, side=-1)

    print('\nForward test: buy the next open after an A/A+ short label, sell 20 bars later, 0.10% cost')
    print(f"{'world':<9}{'truth':<35}{'yardstick':<14}{'signals':>8}  {'excess [95%]':<24}{'placebo':>9}  verdict")
    for r in rows:
        ci = f"[{100 * r['ci'][0]:+.2f}, {100 * r['ci'][1]:+.2f}]"
        v = r['verdict'] + (f" (no gate: {r['without_gate']})" if r['without_gate'] else '')
        q2 = '' if r['q2'].startswith('NOT READ') else f" / Q2 {r['q2']}"
        print(f"{r['world']:<9}{r['truth']:<35}{r['baseline'].replace('_', '-'):<14}{r['n']:>8,}  "
              f"{pct(r['excess']) + ' ' + ci:<24}{pct(r['placebo']):>9}  {v}{q2}")
    print('\nBracket test on the null world (short labels, stop 0.5 ATR beyond the bar, target 1.5 ATR, 30 bars)')
    print(f"  target before stop: labels {100 * br['hit']:.1f}% vs ordinary days {100 * br['ordinary_hit_any_stop']:.1f}%"
          f" -> 'edge' {100 * br['edge_unmatched']:+.1f} pts [{100 * br['edge_unmatched_ci'][0]:+.1f}, "
          f"{100 * br['edge_unmatched_ci'][1]:+.1f}]")
    print(f"  same stop distance: labels {100 * br['hit_matched_sample']:.1f}% vs {100 * br['ordinary_hit_same_stop']:.1f}%"
          f" -> edge {100 * br['edge_same_stop']:+.1f} pts [{100 * br['edge_same_stop_ci'][0]:+.1f}, "
          f"{100 * br['edge_same_stop_ci'][1]:+.1f}]")
    print(f"  why: labels' stops sit {br['median_stop_atr_signal']:.2f} ATR away vs {br['median_stop_atr_ordinary']:.2f} "
          f"on an ordinary day (median)")

    out = ROOT / 'results' / 'demo_results.json'
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({'forward': rows, 'bracket_null_short': br}, indent=1) + '\n')
    chart(rows, ROOT / 'docs' / 'demo.png')
    print(f'\nwrote {out.relative_to(ROOT)} and docs/demo.png')


def chart(rows, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels = [f"{r['world']} world ({r['truth']})\nyardstick: {r['baseline'].replace('_', ' ')}" for r in rows]
    col = {'VOID (placebo gate)': '#d6a03f', 'NOT SUPPORTED': '#8a93a6', 'SUPPORTED': '#2f6fd6'}
    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=150)
    for i, r in enumerate(rows):
        y = -i
        v, lo, hi = (100 * x for x in (r['excess'], *r['ci']))
        ax.errorbar(v, y, xerr=[[v - lo], [hi - v]], fmt='o', color=col[r['verdict']], ms=7, capsize=4, lw=2)
        ax.plot(100 * r['placebo'], y - 0.28, marker='x', color='#c2410c', ms=7, mew=2)
        tag = r['verdict'] + ('' if r['q2'].startswith('NOT READ') else f" · {r['q2']}")
        ax.text(hi + 0.12, y, tag, va='center', fontsize=8.5, color='#1d2433')
    ax.axvline(0, color='#1d2433', lw=1)
    ax.set_yticks([-i for i in range(len(rows))])
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlim(-1.8, 5.2)
    ax.set_xlabel('excess 20-day return after the label, %, after 0.10% cost\n'
                  'dot = mean · bar = 95% month-cluster range · x = the same method on shuffled prices (should be 0)',
                  fontsize=8, color='#6b7385')
    ax.grid(axis='x', color='#e6e8ee')
    ax.set_axisbelow(True)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.tick_params(labelsize=8, colors='#4a5163')
    ax.set_title('Synthetic worlds with known truth: the audit finds the planted edge and refuses the fake one',
                 fontsize=10, loc='left', color='#1d2433')
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


if __name__ == '__main__':
    main()
