"""Render the one-page case study (docs/one_pager.html -> .pdf + .png) with headless Chrome. Aggregate numbers only.

  python docs/make_one_pager.py [--out DIR] [--stem NAME]        # CHROME=/path/to/chrome to override the browser
"""
import argparse
import base64
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
W, H = 1400, 1700


def img(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def page():
    cal = json.loads((ROOT / 'results' / 'calibration.json').read_text())['summary']
    demo = json.loads((ROOT / 'results' / 'demo_results.json').read_text())['bracket_null_short']
    cn, cf = cal['null / same_year'], cal['null / full_history']
    pn, pf = cal['planted / same_year'], cal['planted / full_history']
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
@page {{ size: {W}px {H}px; margin: 0 }}
* {{ box-sizing: border-box }}
body {{ margin: 0; width: {W}px; font: 15px/1.5 -apple-system, 'Helvetica Neue', Arial, sans-serif; color: #1d2433; background: #fff }}
.wrap {{ padding: 44px 52px 30px }}
h1 {{ font-size: 30px; margin: 0 0 4px; letter-spacing: -0.3px }}
.sub {{ color: #6b7385; font-size: 13.5px; margin-bottom: 18px }}
ol {{ margin: 0 0 16px; padding-left: 24px }} ol li {{ margin: 0 0 7px }}
.why {{ background: #f2f4f8; border-left: 5px solid #1d2433; padding: 12px 18px; margin: 0 0 20px; font-size: 15px }}
h2 {{ font-size: 16px; margin: 18px 0 8px }}
.row {{ display: flex; gap: 26px; align-items: flex-start }}
.chart img {{ width: 760px; display: block }}
.loop {{ flex: 1; font-size: 12.5px }}
.step {{ border: 1.5px solid #b9c0ce; border-radius: 7px; padding: 6px 10px; margin: 0 0 4px; background: #fff }}
.step b {{ font-size: 13px }} .step.rev {{ border-color: #d6a03f; background: #fdf6e8 }}
.step.gate {{ border-color: #2f6fd6; background: #eef4fd }} .step.human {{ border-color: #1d2433; background: #f2f4f8 }}
.arrow {{ text-align: center; color: #8a93a6; font-size: 12px; line-height: 1; margin: 0 0 4px }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px }}
th {{ text-align: left; color: #6b7385; font-weight: 600; border-bottom: 1.5px solid #d5d9e2; padding: 6px 8px }}
td {{ border-bottom: 1px solid #e6e8ee; padding: 6px 8px; vertical-align: top }}
.bad {{ color: #b45309; font-weight: 600 }} .good {{ color: #1d4ed8; font-weight: 600 }}
.two {{ display: flex; gap: 26px }} .two > div {{ flex: 1 }}
.notes {{ color: #4a5163; font-size: 12.5px; margin-top: 16px }} .notes li {{ margin: 0 0 4px }}
code {{ font: 12.5px Menlo, monospace; background: #f2f4f8; padding: 1px 4px; border-radius: 3px }}
</style></head><body><div class="wrap">
<h1>An indicator its user trusted, tested by agents that couldn't bend the rules</h1>
<div class="sub">signal-audit · a case study in agent-governed research · Anupam Patil · 2026-10-17 ·
github.com/jarvisss007/signal-audit · research and engineering, not investment advice</div>

<ol>
<li><b>The claim.</b> "IE Pro", a TradingView indicator, grades its buy/sell labels A+, A or B, and its user trusted the A
labels. Agents ran it on TradingView's own engine, headless, and scored 7,476 daily A labels on 153 symbols, 2002–2026.</li>
<li><b>First answer: no.</b> A labels reach their target before their stop no more often than an ordinary day of the same
stock. NOT SUPPORTED, both directions.</li>
<li><b>A second idea looked real, and wasn't.</b> "Stocks bounce after an A short" scored +1.88% on the first method (entered at the signal close). A
reviewer agent ran that method on shuffled prices, where there is nothing to find, and it still found +1.45%. The
yardstick made the "yes".</li>
<li><b>Fixed, frozen, run once on 408 fresh S&amp;P 500 stocks:</b> +0.29%, 95% range −0.72% to +1.15%. NOT SUPPORTED.
The holdout is used up and the research line is closed, as the written plan said it would be.</li>
<li><b>The fix is tested, not assumed.</b> On 25 synthetic worlds with no edge, the old yardstick said "SUPPORTED"
{cn['passed']} times; the fixed one {cf['passed']} times. With a real edge planted, the fixed one found it {pf['passed']} times in {pf['worlds']}.</li>
<li><b>Mistakes are corrected in the open.</b> The test was registered before it ran (trial 56 in the ledger); earlier
runs that were never entered are disclosed there, not back-filled; the first study's "worse than a random day" claim was
withdrawn by an appended correction, not an edit.</li>
</ol>

<div class="why"><b>Why this is in a portfolio:</b> the null result is not the point. The loop is: agents doing real
work, rules enforced in code rather than in prompts, a second agent whose only job is to find what the first got wrong,
and a human who decides at the gates. Swap "indicator" for "model", "pricing rule" or "dispatch policy" and the loop is
the same.</div>

<div class="row">
 <div class="chart"><h2 style="margin-top:0">The same question, four ways</h2><img src="data:image/png;base64,{img(ROOT / 'docs' / 'case_study_compact.png')}"></div>
 <div class="loop"><h2 style="margin-top:0">The loop</h2>
  <div class="step"><b>Idea</b> · found in 18 looks at old data; the 18 are recorded with it as its "mining tax"</div><div class="arrow">▼</div>
  <div class="step"><b>Written plan</b> · rule, yardstick and pass/fail rule fixed before any result</div><div class="arrow">▼</div>
  <div class="step rev"><b>Reviewer agent</b> · no edit tools, barred from the test data · "NOT READY, 7 fixes" → plan rewritten</div><div class="arrow">▼</div>
  <div class="step gate"><b>Freeze</b> · fingerprints (SHA-256) of 5 files, all checked again before scoring</div><div class="arrow">▼</div>
  <div class="step gate"><b>Score once</b> · placebo gate in code voids a biased yardstick</div><div class="arrow">▼</div>
  <div class="step gate"><b>Ledger</b> · append-only; a test is a trial, a result is not; gaps disclosed, not back-filled</div><div class="arrow">▼</div>
  <div class="step human"><b>Owner decides</b> · go-ahead before the test; what follows after it</div>
 </div>
</div>

<div class="two">
<div><h2>Two bugs that looked like an edge</h2>
<table><tr><th>Bug</th><th>Fake result</th><th>After the fix</th></tr>
<tr><td><b>Yardstick moved with the signal.</b> Labels follow a fall; comparing with the same stock's same calendar year drags
the yardstick down.</td><td class="bad">+1.45% on shuffled prices</td><td class="good">+0.19% on the same shuffled prices (whole-history yardstick)</td></tr>
<tr><td><b>The stop was further away.</b> Labels print on bars that close at an extreme: stop 1.46 ATR away vs 0.89 on an
ordinary day, target fixed.</td><td class="bad">+7.8 pts "hit rate edge"</td><td class="good">−0.9 pts [−3.3, +1.4] at the same stop distance</td></tr>
<tr><td>Same stop bug, synthetic data with no edge</td><td class="bad">+{100 * demo['edge_unmatched']:.1f} pts</td>
<td class="good">{100 * demo['edge_same_stop']:+.1f} pts [{100 * demo['edge_same_stop_ci'][0]:+.1f}, {100 * demo['edge_same_stop_ci'][1]:+.1f}]</td></tr>
</table></div>
<div><h2>Testing the tester (25 synthetic worlds each)</h2>
<table><tr><th></th><th>old yardstick</th><th>fixed yardstick</th></tr>
<tr><td>No edge exists: falsely "SUPPORTED"</td><td class="bad">{cn['passed']} of {cn['worlds']}</td><td class="good">{cf['passed']} of {cf['worlds']}</td></tr>
<tr><td>Mean result when there is nothing</td><td class="bad">{100 * cn['mean_excess']:+.2f}%</td><td class="good">{100 * cf['mean_excess']:+.2f}%</td></tr>
<tr><td>+2.5% edge planted: found</td><td>{pn['passed']} of {pn['worlds']} ({100 * pn['mean_excess']:+.2f}%, inflated)</td><td class="good">{pf['passed']} of {pf['worlds']} ({100 * pf['mean_excess']:+.2f}%)</td></tr>
</table>
<p style="font-size:12.5px;color:#4a5163;margin:8px 0 0">A test whose whole 95% range must clear zero false-alarms about once in 40.
A third world, where every sharp fall partly reverses, passes the first question and is then correctly told the label
adds nothing beyond the fall.</p></div>
</div>

<h2>Who did what</h2>
<table><tr><th>Role</th><th>What it is</th><th>What keeps it honest</th></tr>
<tr><td>Orchestrator</td><td>Claude Code session running the research end to end</td><td>Works only from the written plan; a change after the freeze must be a new registered test</td></tr>
<tr><td>Engine runner</td><td>Computes the indicator on TradingView's servers in a hidden chart session</td><td>Read-only; parity check first (70 of 70 labels reproduced); the user's own chart is never touched</td></tr>
<tr><td>Reviewer</td><td>Subagent with no file-editing tools and an adversarial brief</td><td>Told not to open the test data while it was collected, and reported it never did; returns a verdict and fixes, never edits</td></tr>
<tr><td>Scorer + ledger</td><td>Python; pass/fail rule and placebo gate are code</td><td>Ran only after the hashes checked out; the repo's version also refuses changed files, re-registrations and edited history on its own</td></tr>
<tr><td>Owner</td><td>Anupam</td><td>Approves the test before it runs; decides what follows</td></tr>
</table>

<ul class="notes">
<li><b>In the repo:</b> the scorer, placebo gate, freeze check and ledger, generalised to any price + signal CSV; a small
synthetic dataset; a one-minute demo; 10 tests; the reviewer's full report; aggregate results of the real study.</li>
<li><b>Kept out:</b> all market data and per-stock output (TradingView data, personal-use licence), the indicator's code,
the headless runner, and any trading or account information. The Firm is a paper-only research operation; nothing here trades.</li>
<li><b>Limits:</b> the 408 stocks replicate across stocks, not time (their labels span the same years, 2000–2026); they are today's S&amp;P 500
members, which favours a buy-after-a-fall rule, and it failed anyway; prices split- but not dividend-adjusted on both sides.</li>
</ul>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'docs'))
    ap.add_argument('--stem', default='one_pager')
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    html, png, pdf = out / f'{a.stem}.html', out / f'{a.stem}.png', out / f'{a.stem}.pdf'
    html.write_text(page())
    profile = Path(os.environ.get('TMPDIR', '/tmp')) / 'signal-audit-chrome'
    base = [CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run', f'--user-data-dir={profile}']
    subprocess.run(base + [f'--window-size={W},{H}', f'--screenshot={png}', html.resolve().as_uri()], check=True,
                   capture_output=True, timeout=90)
    subprocess.run(base + ['--no-pdf-header-footer', f'--print-to-pdf={pdf}', html.resolve().as_uri()], check=True,
                   capture_output=True, timeout=90)
    print(f'wrote {html}, {png}, {pdf}')


if __name__ == '__main__':
    main()
