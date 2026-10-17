"""Render docs/case_study.png from results/ie_pro_aggregate.json (aggregate numbers only).

  python docs/make_figures.py
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
INK, MUTED, GRID = '#1d2433', '#6b7385', '#e6e8ee'
COLOR = {'method': '#8a93a6', 'placebo': '#d6a03f', 'test': '#2f6fd6'}


def four_ways(path):
    rows = json.loads((ROOT / 'results' / 'ie_pro_aggregate.json').read_text())['study_2_bounce_holdout']['same_question_four_ways']
    fig, ax = plt.subplots(figsize=(10, 3.6), dpi=150)
    for i, r in enumerate(rows):
        y = -i
        v, lo, hi = 100 * r['mean'], 100 * r['lo'], 100 * r['hi']
        ax.errorbar(v, y, xerr=[[v - lo], [hi - v]], fmt='o', color=COLOR[r['kind']], ms=8, capsize=4, lw=2.2)
        ax.text(hi + 0.08, y, f'{v:+.2f}%', va='center', fontsize=9, color=INK)
    ax.axvline(0, color=INK, lw=1)
    ax.set_yticks([-i for i in range(len(rows))])
    ax.set_yticklabels([r['label'] for r in rows], fontsize=8.5)
    ax.set_xlabel('extra 20-day return after an A/A+ short label vs the same stock\'s ordinary days, %, after 0.10% cost\n'
                  'dot = mean · bar = 95% range (orange: range over 10 shuffles)', fontsize=8, color=MUTED)
    ax.grid(axis='x', color=GRID)
    ax.set_axisbelow(True)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.tick_params(labelsize=8, colors='#4a5163')
    ax.set_ylim(-len(rows) + 0.4, 0.6)
    ax.set_title('The same question, four ways: the first "yes" was the yardstick, not the indicator', fontsize=10,
                 loc='left', color=INK)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def four_ways_compact(path):
    """The same chart sized for the one-pager: short labels, larger type."""
    rows = json.loads((ROOT / 'results' / 'ie_pro_aggregate.json').read_text())['study_2_bounce_holdout']['same_question_four_ways']
    short = ['first method, discovery stocks', 'first method, SHUFFLED prices', 'fixed method, discovery stocks',
             'fixed method, 408 FRESH stocks\n(the test)']
    fig, ax = plt.subplots(figsize=(7.6, 3.5), dpi=200)
    for i, r in enumerate(rows):
        y = -i
        v, lo, hi = 100 * r['mean'], 100 * r['lo'], 100 * r['hi']
        ax.errorbar(v, y, xerr=[[v - lo], [hi - v]], fmt='o', color=COLOR[r['kind']], ms=8, capsize=4, lw=2.4)
        ax.text(hi + 0.08, y, f'{v:+.2f}%', va='center', fontsize=10.5, color=INK, weight='bold' if r['kind'] == 'test' else None)
    ax.axvline(0, color=INK, lw=1)
    ax.set_yticks([-i for i in range(len(rows))])
    ax.set_yticklabels(short, fontsize=10)
    ax.set_xlim(-1.0, 3.5)
    ax.set_xlabel('extra 20-day return after an A/A+ short vs the same stock\'s ordinary days, %, after cost\n'
                  'bar = 95% range (orange: range over 10 shuffles) · top row entered at the signal close', fontsize=8.5,
                  color=MUTED)
    ax.grid(axis='x', color=GRID)
    ax.set_axisbelow(True)
    ax.spines[['top', 'right', 'left']].set_visible(False)
    ax.tick_params(labelsize=9, colors='#4a5163')
    ax.set_ylim(-len(rows) + 0.4, 0.6)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


if __name__ == '__main__':
    four_ways(ROOT / 'docs' / 'case_study.png')
    four_ways_compact(ROOT / 'docs' / 'case_study_compact.png')
    print('wrote docs/case_study.png, docs/case_study_compact.png')
