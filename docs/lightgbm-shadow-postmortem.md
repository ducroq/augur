# LightGBM-Quantile Shadow — M4 outcome

**Status**: Final (2026-05-29 — review-by deadline; verdict run six days past the
originally pre-staged 2026-05-23 session due to user availability).
**Run window evaluated**: 2026-05-14 → 2026-05-27 (most-recent 14 contiguous
nightly cron rows per the pre-committed Method's "ignore earlier rows from
cron-shake-out" clause). Cron-effective start was 2026-05-08; the early rows
(05-08 to 05-13) age out of the trailing window.
**Outcome**: **Parked — Path B.** Criterion (a) and (b) failed; (c) passed cleanly.
**Hypothesis tested**: `docs/hypothesis-log.md` "LightGBM-Quantile shadow will
pass plan §6 over a 14-day window" (open since 2026-04-30, mid-window preview
2026-05-18 already flagged structural (a) failure).

This is a neutral postmortem. The shadow design did the job it was scoped to
do — produce daily forecasts, log per-day metrics, and let us read a falsifiable
verdict from the pre-committed Method. The verdict is what it is; this document
records it and points at the next bet.

---

## 1. What the shadow was meant to prove

`docs/lightgbm-quantile-shadow-plan.md` §6 set three promotion gates over 14
contiguous days:

| Criterion | Threshold |
|---|---|
| (a) MAE on hours where realised < 30 EUR/MWh | LightGBM beats ARF by ≥ 25% relative |
| (b) P10/P90 band empirical coverage | Mean in [0.75, 0.85] AND <3 days <0.60 |
| (c) Weekday-evening-peak (16–19 UTC) MAE | LightGBM no more than +10% worse than ARF |

All three had to hold to justify replacing ARF on the dashboard. The plan
explicitly: "Doesn't auto-promote on the 14-day mark — promotion is a manual
decision after reading the eval log." This file is that manual decision.

## 2. Results — 14-day window 2026-05-14 → 2026-05-27

Numbers from `scripts/m4_method_run.py` (executed 2026-05-29 against a fresh
local `ml/shadow/eval_log.jsonl`, 20 total rows; trailing-14 window per Method):

| Criterion | Value | Threshold | Verdict |
|---|---|---|---|
| (a) ratio = lgbm_low / arf_low | **1.610** | ≤ 0.75 | **FAIL** |
| (a) n_low_price_hours (sum) | 69 | ≥ 50 | pass (guard) |
| (b) mean P80 coverage | **0.696** | [0.75, 0.85] | **FAIL** |
| (b) days < 0.60 coverage | **3** | < 3 | **FAIL** |
| (c) mean peak-hour ratio | 0.450 | ≤ 1.10 | **PASS** |
| Informational: overall LGBM/ARF MAE | 24.32 / 39.04 EUR/MWh | (n/a) | (LGBM −38%) |

**Headline**: PROMOTE = False. Criterion (a) failed *in the wrong direction* —
LGBM was 61% worse than ARF on the low-price slice, not 25% better. Criterion
(b) failed both guards. (c) crushed it. The overall MAE win (LGBM −38%) is real
but irrelevant to the promotion question — §6 chose its slices deliberately
because the structural ARF retirement motivation was negative-price prediction.

### Supplementary — horizon-decomposed (a)

Per the 2026-05-18 mid-window preview, criterion (a)'s 72-hour aggregation
means the low-price slice is dominated by long-horizon hours. The supplementary
horizon decomposition from `shadow_state.json:calibration_history`:

| Horizon group | n_low hours | LGBM `|p50 − realized|` mean | median |
|---|---|---|---|
| h ≤ 24 | **0** | n/a | n/a |
| h > 24 | 200 | 71.21 EUR/MWh | 76.57 EUR/MWh |

**Why n_low=0 at h ≤ 24 isn't a bug**: `calibration_history` retains entries
h=22..93 from each `eval_day`'s 00:00 UTC prediction (72-hour rolling window).
Low-price hours in NL spring concentrate at the **midday solar trough** —
realized<30 entries cluster at h=30-39 (next-day midday), h=54-63 (day+2),
h=78-87 (day+3). None fall in the h=22-24 band (late-evening/night, where
prices structurally never crash). This means **criterion (a) as defined cannot
test LGBM's short-horizon low-price skill** — it is intrinsically a long-horizon
test. The mean/median similarity (71.2 vs 76.6) confirms structural error, not
spike-driven outliers.

## 3. Diagnosis — which failure-mode signal fired

Hypothesis-log Alternatives (named pre-commitment):

1. **Live exogenous freshness skew** — signal: 14-day mean `lightgbm_mae` >
   15.85 EUR/MWh (>20% worse than backtest h+1 of 13.21).
   **Observed: 24.32 EUR/MWh, fired YES.** Live overall MAE is 84% above
   backtest h+1. This argues `consolidate.py` overwrite semantics (augur#12
   territory) are part of the story, but n_low ≥ 50 means we can't blame
   freshness alone — the model also has structural long-horizon weakness.
2. **Bimodal coverage breaks the aggregate** — signal: ≥3 days below 0.60.
   **Observed: 3 days (05-17 cov=0.04, 05-18 cov=0.50, 05-21 cov=0.38), fired YES.**
   The 05-17 collapse (cov=0.04) is striking — that day's overall MAE was 46.5
   EUR/MWh (highest in the window) with bands far too tight for the regime.
   Argues for adaptive calibration (ACI, Gibbs & Candès 2021) in any next-bet
   shadow.
3. **Power deficit on (a)** — signal: n_low < 30.
   **Observed: 69, did NOT fire.** Sample size was adequate to detect a 25%
   relative win; the failure isn't statistical.

**Primary diagnosis**: criterion (a) failed for the **structural reason
anticipated by the 2026-05-18 mid-window preview**: 72-hour aggregation forces
the low-price slice into long-horizon hours where LGBM cannot extrapolate to
midday negative/sub-30 EUR/MWh prices from a feature set whose weather/load
signal thins at h>24. ARF "wins" the slice not by skill but by clustering near
a mean-reverting baseline (~50-80 EUR/MWh) that happens to be less wrong than
LGBM's confidently-incorrect midday forecasts — see §6 below on the
metric-design implication. Criterion (b)'s second guard tripping reinforces
this: the days where coverage collapses (05-17, 05-18, 05-21) are regime-shift
days where the CQR window's trailing 7-day calibration cannot anticipate the
shift. (c) passing despite (a)/(b) failing tells us the model class isn't
broken — it's the feature set + horizon design that can't reach into negative
midday territory.

**Known Method limitation (for completeness, not a re-litigation)**: criterion
(a) ratio_a is the mean of per-day `lightgbm_mae_at_low_price` values divided
by the mean of per-day `arf_mae_at_low_price` values. Each per-day MAE is
already an average over that day's low-price hours, so the ratio is an
unweighted mean of per-day averages — a day with 1 low-price hour weighs the
same as a day with 10. The pre-committed Method is identical
(`hypothesis-log.md:46-48`), so this is not a re-evaluation. Hours-weighted
spot check: `sum(mae_i * n_i) / sum(n_i)` over the 11 days with n_low>0 gives
lgbm=42.6 / arf=27.4 → ratio 1.55, same direction same conclusion. Not
borderline; the unweighted Method ratio of 1.61 is robust.

### Companion hypothesis — Live shadow MAE vs backtest h+1 MAE

The second open entry in `docs/hypothesis-log.md` predicted `overall_lgbm_mae`
in [13.5, 16.0] EUR/MWh (ratio vs backtest h+1 MAE of 13.21 in [1.0, 1.20]).

| Quantity | Observed | Interpretation |
|---|---|---|
| `overall_lgbm_mae` | 24.32 EUR/MWh | (from Method block) |
| ratio = observed / 13.21 | **1.84** | **Position refuted (ratio > 1.20).** |

Position refuted: freshness skew dominates more than expected (or the
horizon-mix effect is larger than the +5-10% allowance). Argues for
prioritising augur#12 (cron→systemd + run-after-EDH for fresh exogenous)
before any next-bet shadow experiment — there's no point shadowing a new model
class on parquet rows that are silently overwritten with later forecast vintages.

## 4. Why this is not Path C (extend window)

Criterion (a) failed and n_low = 69 ≥ 50, so the failure isn't sample-size,
it's structural. The horizon-decomposed split (§2) makes this concrete: the
framework places all 200 in-window low-price evaluation hours at h>24, where
LGBM mean error is 71.2 EUR/MWh on the |p50 − realized| metric. More days
won't fix a model-design + framework-design limit. Path C would be the right
call only if n_low < 30 (Alternative 3 fired), which it did not.

## 5. What carries forward

- ✅ Shadow infrastructure (`ml/shadow/`, CQR, eval_log, secure_pickle) is
  proven by 20 days of nightly operation across cron-effective dates
  2026-05-08 → 2026-05-27 (no silent failures after the 2026-05-08 observability
  hardening; row 14 of original window recovered via manual backfill 2026-05-21
  after Tailscale outage). Code stays in tree, cron is disabled (not deleted) —
  re-enableable by uncommenting the shadow block in `scripts/daily_update.sh`.
- ✅ Conformal calibration (EXP-010) earned its keep on the well-behaved days
  but its 7-day trailing window cannot react to single-day regime shifts —
  3 of 14 days had coverage <0.60 (05-17 0.04, 05-18 0.50, 05-21 0.38) and
  pulled the mean to 0.696. Adaptive conformal (ACI) is a clean follow-up.
- ✅ Healthchecks.io + dynamic commit-message observability survived the M4
  window without false negatives (recall the 2026-05-01..07 silent-failure
  episode this hardening was designed to prevent).
- ❌ The multi-horizon-as-feature stacking did not deliver low-price extrapolation
  at h > 24. Treat this as a constraint on the next bet, not a critique of LGBM.

## 6. The next bet

Two seeds, ranked by likely impact:

1. **Metric redesign before model redesign.** Criterion (a) as MAE on the
   low-price slice is methodologically weak for the question "can the model
   express negative prices at all?" — ARF wins by being timid in the right
   direction (clustering near a baseline that's less wrong than a bad
   extrapolation), not by being right. A probabilistic metric like **pinball
   loss at p10** (or **CRPS** for the whole distribution) directly tests "does
   the lower band reach negative territory when it should?" — and ARF, whose
   lower band is hard-clamped at 0 in `ml/update.py`, loses by construction.
   A focused literature review (Nowotarski & Weron 2018; Lago et al. 2021;
   Gneiting & Ranjan 2011; Lerch et al. 2017 on the forecaster's dilemma)
   was done 2026-05-29 and is filed as
   `docs/metric-redesign-literature-review.md`. It recommends a three-part
   criterion: aggregate skill score (CRPS / mean quantile score), threshold-
   weighted CRPS with pre-committed left-tail threshold (the propriety-
   preserving replacement for our fixed-30-EUR slice), and pinball-at-p10
   plus lower-side coverage as a calibration diagnostic. The whole package is
   tested for significance with Diebold-Mariano.

   **EXP-012 ran 2026-05-29 to validate this criterion on the existing M4
   window data** (see `docs/exp-012-results.md` and EXP-012 in
   `experiments/registry.jsonl`). **Outcome: hypothesis refuted with
   nuance.** LGBM wins decisively on aggregate skill (MQS 10.22 vs ARF MAE
   35.13, DM p < 0.0001) — that part of the criterion redesign is
   validated. But ARF *also* wins on twCRPS (p=0.94) and pinball-at-p10
   (p=0.92): the literature-review prediction "ARF loses by construction
   because its lower band is clamped at 0" doesn't hold in the M4 data —
   the clamp wasn't binding and ARF's EWM-derived band lands in a hard-to-
   beat zone. **Updated next-bet design**: use CRPS / mean quantile score
   as the primary skill criterion (validated), treat tail metrics as
   *descriptive not promotion-gating* until the long-horizon mechanism is
   understood, lower-side coverage as a guardrail only. EXP-013 candidate:
   9-quantile backtest on a longer window to confirm overall-skill picture
   at finer resolution and characterise tail behaviour.
2. **Fix exogenous freshness (augur#12) before shadowing a new model class.**
   Companion-hypothesis ratio 1.84 means the freshness skew is empirically
   real, not theoretical. Any next-bet shadow that doesn't fix this is testing
   model class through a layer of confounding data staleness.

Two **lower**-priority follow-ups, conditional on (1) and (2):
- Adaptive conformal intervals (ACI / Gibbs & Candès 2021) to handle the
  single-day regime shifts that broke (b).
- Either (i) separate model heads per horizon group (instead of horizon-as-
  feature stacking) or (ii) explicit long-horizon solar-forecast features to
  give h>24 predictions structural signal.

EXP-012 (or wherever the registry numbers fall) should not be a model swap —
it should be the metric review. Model work is EXP-013+.

## 7. Decisions logged

- `experiments/registry.jsonl` — append EXP-011 outcome row (decision: parked,
  rationale references this file).
- `docs/hypothesis-log.md` — moved the "LightGBM-Quantile shadow will pass §6"
  entry to ## Resolved with outcome: refuted, primary signal = structural (a)
  failure (long-horizon low-price extrapolation, with bimodal-coverage and
  freshness-skew Alternatives also firing).
- `scripts/daily_update.sh` — shadow block commented out, leave the code in tree.
- `CLAUDE.md` — ML Pipeline section updated to "ARF still in production,
  LGBM-shadow parked pending next-bet experiment".
- `memory/MEMORY.md` — `arf-retired.md` entry updated to close the M4 chapter.
- augur#13 — closing comment posted, issue closed.

## 8. References

- `docs/lightgbm-quantile-shadow-plan.md` — the plan being evaluated
- `docs/hypothesis-log.md` — pre-committed Method and Alternatives
- `docs/model-progress-log.md` 2026-05-18 entry — mid-window preview that
  flagged the structural (a) failure
- `docs/river-arf-retrospective.md` — the prior model's retirement; useful
  template for what a postmortem looks like when the model genuinely worked
- `experiments/registry.jsonl` EXP-009, EXP-010 — backtest evidence that led
  to the shadow window in the first place
- `ml/shadow/eval_log.jsonl` — primary evidence; 20 rows 2026-05-08 → 2026-05-27,
  Method used trailing 14 (05-14 → 05-27)
- `scripts/m4_method_run.py` — verdict generator
