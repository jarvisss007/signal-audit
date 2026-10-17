# The reviewer agent's report (2026-10-17, before the holdout was scored)

This is the review that caught the biased yardstick. It is reproduced verbatim except that local file paths are
replaced by short names, the Firm's internal rule numbers are replaced by what they say or dropped, and markdown is
tidied. The numbers in it are the
reviewer's own, measured on the discovery data; the final v2 numbers differ slightly, because v2 also changed the entry
and the bootstrap (see the README).

## The brief it was given

The orchestrating agent wrote this brief and launched the reviewer, a subagent with no file-editing tools (Read, Grep,
Glob, Bash) whose standing instructions are to return a verdict and never make the change itself.

> Review a NEW pre-registration and its scoring code BEFORE it is frozen and run on holdout data. Be adversarial: find
> anything that would let the result be wrong, flattering, or fished.
>
> Files: the prereg (`IE_PRO_BOUNCE_PREREG.md`), the scorer (`ie_pro_bounce_score.py`), the discovery study it came from
> (its prereg and results), and the instrumented indicator that produces the signals.
>
> HARD RULE: do NOT read, list, or compute anything from the holdout folder or its collection log. That is the holdout
> being collected right now and nobody may see its outcomes before the freeze. You MAY run the scorer on the discovery
> data to check the code does what the prereg says.
>
> Check specifically:
> 1. Look-ahead or alignment bugs in the scorer: 20-day return indexing, next-open variant indexing, the decile of the
>    day's own 1-day move (is it computed only on eligible days per symbol; is using full-history deciles a leak that
>    matters?), year matching, label days excluded from baselines.
> 2. Whether the verdict rules can pass for the wrong reason, or are worded so the code and the text disagree.
> 3. Whether the bootstrap (calendar-week clusters) is adequate for 20-day holds that overlap across stocks and across
>    adjacent weeks. Recommend a concrete fix if not and say whether it changes the discovery interval materially.
> 4. Survivorship and any other bias that should be stated or controlled.
> 5. Anything in "what each outcome leads to" that is inconsistent with a firm whose rules are: no tuning after seeing
>    results, a change = a new registered variant, an adversarial skeptic panel before any edge claim, the owner's
>    ruling before any paper book.
>
> Return: a verdict READY / READY-AFTER-FIXES / NOT READY, then a numbered list of concrete fixes, most important first.
> Under 500 words. Do not edit the files yourself.

## What it returned

**Verdict: NOT READY.** Q1 can pass when no bounce exists.

**Class:** a new research registration. It edits no live rule and rewrites nothing already scored. Still, leave the
earlier results file as it is and append a note. I never opened the holdout folder or its log.

**What checks out:** the 20-day return (close 20 bars later over the signal close), the next-open version (open of the
next bar to the same 20th close), and the 1-day move are all indexed correctly. Deciles are ranked per stock on
bias-present days only. Every signal of any grade or side is kept out of both baselines. One stock's holds can't overlap
because all signals share the same 20-bar gap. On discovery data the scorer reproduces section 1 exactly.

**Fixes, most important first:**

1. **The same-stock, same-year baseline is biased in Q1's favour.** Labels come after a fall. The 20 days before a label
   average −6.8% over their next 20 days, against +3.7% for other days, and they sit in the label's own year. I ran a
   placebo: each stock's daily returns shuffled (so nothing can predict anything), "labels" fired after a bottom-5%
   20-day fall, 20-bar gap. The prereg baseline still reports **+1.45%** (range +1.11 to +1.85). With 408 stocks the
   interval is narrow enough for that alone to pass Q1.
   - Fix: baseline = the stock's ordinary days over its full history (`groupby('symbol')`). That scores +0.19% in the placebo.
   - Freeze the placebo into the scorer as a gate: if it comes out beyond ±0.3%, the run is void.
   - Discovery under the fix: +0.83% [−0.27, +1.91]. The discovery bounce doesn't survive, and section 1 must say so.
   - Leaving out pre-label days instead does not work: it picks days by whether a label comes later, and the placebo
     goes to −1.4% to −2.8%.
2. **Q2 matches the wrong drop.** What actually precedes a label is a multi-week fall (−9.6% over 20 days). Even within
   the bottom decile of 1-day moves, labels average −5.38% against −4.27% for ordinary days.
   - Match on the stock's 1-day-move decile **and** its trailing 20-day-return decile. Discovery: −0.07% [−1.18, +1.01].
   - Section 5 should say the 0.10% cost is charged to the label leg only.
   - When Q1 fails, the code should print Q2 as "NOT READ".
3. **Bootstrap:** use calendar-month clusters (`.dt.to_period('M')`), at least as long as the 20-day hold. On discovery the standard error rises
   from 0.54 to 0.61 and the lower bound moves from +0.80 to +0.62 (a 4-week moving block gives +0.61). Not material, but
   correct. Don't go longer: 8- to 26-week blocks *narrow* the interval, because crash weeks and their rebound weeks
   cancel inside one block.
4. **Make the primary entry the next open.** The label only exists once the bar closes (the Firm's doctrine: publish only
   numbers you could have traded). It costs little: discovery goes from +1.88% to +1.75%.
5. **This is not a test on new time.** The holdout runs over the same 2002–2026 market as discovery; the biggest label
   week, 2025-03-31, alone holds 61 labels. Call it a replication across stocks only. A beta-adjusted return against SPY (+1.10%
   [+0.59, +1.65] on discovery) can be reported as context, never as a verdict: it shows +0.74% in the placebo, because
   survivors outperform.
6. **Survivorship pushes Q1 toward SUPPORTED.** Add a sensitivity line using only labels dated after each stock joined
   the S&P 500 (the free Wikipedia changes table). State that stocks removed from the index can't be recovered.
7. **Section 8:**
   - Add: "Section 6 lines are never promoted. An A+-only or 10-day 'pass' is not a finding. The S&P holdout is used up
     after one run."
   - Count this trial in the evolution ledger (trials 55 to 56) and note the 18 discovery looks (the mining tax).
   - Quote the standing rule exactly: "no new desk, lab or arm is created before 2027-01-01 unless Anupam names it in chat."

## What happened to each fix

| # | Fix | Where it landed |
|---|---|---|
| 1 | Whole-history yardstick; placebo gate frozen in code; discovery restated | prereg v2 §1, §4; scorer `PLACEBO_GATE`; here: `signal_audit/placebo.py`, `audit.decide` |
| 2 | Q2 matched on 1-day AND trailing 20-day deciles; cost leg stated; "NOT READ" in code | prereg v2 §2 (cost leg), §5 (Q2); here: `forward.score` (q2), `audit.decide` |
| 3 | Calendar-month cluster bootstrap | here: `signal_audit/stats.py` |
| 4 | Next-open entry is primary | here: `Spec.entry = 'next_open'` |
| 5 | Called a replication across stocks, not time | prereg v2 §3 |
| 6 | Survivorship sensitivity (labels after S&P 500 entry date) | prereg v2 §7; result +0.21% [−0.88, +1.12] |
| 7 | Section 8 wording; trial counted with K = 18 | prereg v2 §3 (holdout used up), §6 (never promoted), §8; ledger trials 55 → 56 |

All seven were applied before the freeze. The holdout was then scored once.
