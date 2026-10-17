# <TEST ID>/v1: PRE-REGISTRATION

Written <date, time, timezone>, BEFORE any outcome on the test data was computed or looked at.
Freeze it with `python -m signal_audit freeze --out prereg.lock.json PREREG.md spec.json [universe.txt]`.
Anything not written here is exploratory and gets labelled that way in the results.

## 1. Where the idea came from (discovery: already seen, NOT evidence)

What was looked at, on which data, and how many looks it took to find the idea (cells x horizons x variants).
That number is K, the mining tax, and goes into the ledger with the registration.
If the idea already fails on its own discovery data under the corrected method, say so here: that is the honest prior.

## 2. The rule (frozen)

- Signal: what produces it, which codes are under test (`codes`), and which other codes exist (all non-zero codes stay
  out of every baseline).
- Trade: when you could actually act on it (a label printed at a close can only be traded at the next open), how long
  it is held (`hold`), the cost (`cost`, charged on the signal trade only).
- Signals with fewer than `hold` bars after them are "still running" and not scored.

## 3. The test data

Which symbols and dates, why nobody has scored the signal on them, and whether this is new TIME or only new SYMBOLS
(a replication across stocks over the same years is not a test on new time). The holdout is used up after one run.

## 4. How it is scored

- Excess per signal = signal trade return - cost - mean return of the SAME symbol's ordinary days over its WHOLE
  history (ordinary = eligible and no signal of any code). Not the same calendar year: see docs/reviewer_report.md.
- 95% interval: bootstrap over calendar months (`boot` draws, `seed`).
- Placebo gate: shuffled returns, pseudo-signals after a move like the real signals' (`placebo_tail`, `placebo_pct`),
  same baseline and cost. Beyond +/- `placebo_gate`: the run is VOID.

## 5. Verdict rules (fixed now)

- Q1, the single trial: SUPPORTED only if the 95% interval of the mean excess is entirely above max(0, placebo mean)
  AND the mean excess is above 0 in both halves of time (split at `split`). Otherwise NOT SUPPORTED.
- Q2, attribution, read only if Q1 passes: the same signals against ordinary days with the same 1-day and trailing
  `hold`-day move deciles. ADDS VALUE only if that interval is entirely above 0; otherwise NOTHING BEYOND THE MOVE.

## 6. Reported, never verdicts, never promoted

Sub-grades, other holds, other entries, medians, sub-periods. A pass in one of these lines is not a finding.

## 7. Known biases, stated before the result

Survivorship (today's index members are survivors), adjustment (split- vs dividend-adjusted prices), anything the
placebo shows the baseline still carries.

## 8. What each outcome leads to

- NOT SUPPORTED: the line closes. No variants of it.
- SUPPORTED, NOTHING BEYOND THE MOVE: the finding is about moves in general, not this signal; a new registered question.
- SUPPORTED, ADDS VALUE: an adversarial review before anything is called an edge; only then, and only if the owner says
  so, a forward paper test.
- In every case: no tuning after the result. A change is a new registered variant with a new id.

Trials: 1 (Q1). Registered in the ledger at this freeze with K = <looks>.
