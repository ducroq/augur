# EXP-012 — re-evaluating the M4 window with new probabilistic metrics

**Date**: 2026-05-29
**Hypothesis**: The literature-recommended replacement criteria (pinball-at-p10,
twCRPS, mean quantile score, Diebold-Mariano) will discriminate LGBM's
structural tail-skill advantage over ARF on the same M4 window data where
the failed criterion (a) (MAE on hours where realised < 30 EUR/MWh) wrongly
favoured ARF.

**Outcome**: **Hypothesis refuted with valuable nuance.** The new metrics
*also* favor ARF on tail-skill (pinball-at-p10 and twCRPS) — not LGBM as
predicted by the literature review. LGBM wins decisively on overall skill
(mean quantile score / MAE). The picture is more subtle than the metric
review anticipated, and *that subtlety is the point of running EXP-012* —
it surfaces before we commit a flawed criterion to a future shadow.

---

## 1. Setup

Re-evaluated the M4 trailing-14 window (2026-05-14 → 2026-05-27) using
*already-collected* predictions:

- LGBM p10/p50/p90 + realized from `ml/models/shadow/shadow_state.json`'s
  `calibration_history` field (no retraining; uses the 3-quantile output
  the model was deployed with).
- ARF point + lower band + upper band from `ml/forecasts/{YYYYMMDD_1445}_forecast.json`
  files (pulled fresh from sadalsuud for this experiment).
- Realized prices from the same `calibration_history` rows.

Joined on `(eval_day = issue_date, target timestamp_utc)` → **842 paired
hourly observations across 14 distinct eval days**.

Honest caveat: with only 3 quantiles, the CRPS-from-pinball-sum estimator
is biased. We call the aggregate "mean quantile score (3-point estimator)"
rather than CRPS. A proper CRPS would require retraining at 9-19
quantiles (deferred to a possible EXP-013).

## 2. Headline numbers

Pre-committed `twCRPS` left-tail threshold: **`q05(realised, April 2026)
= -27.76 EUR/MWh`** (5th percentile of realised prices in the EXP-009
backtest window, which precedes the EXP-012 evaluation window and is
therefore strictly pre-committed). An earlier draft of this report used
`q05` of the in-window realised, which broke the pre-commitment property
that makes twCRPS proper; the data-analyzer review of 2026-05-29 caught
this and the threshold was moved to the April window.

**Implementation caveat (also surfaced by the 2026-05-29 review)**: the
twCRPS computed here is the per-quantile-decomposition variant — average
pinball loss across the quantiles whose predicted value falls below the
threshold — not the canonical Gneiting & Ranjan (2011) form that
integrates the Brier score `(F̂(z) − 1{y ≤ z})²` over `z ≤ c`. The two
forms answer different questions and a model that never predicts into
the tail (ARF here, with threshold -27.76) gets a "score" of zero under
the variant we computed, which can mislead a naïve "lower is better"
reading. See §3 for what this means for the comparison.

### Criterion (a) — recomputed for sanity

| | LGBM | ARF | ratio | Verdict |
|---|---|---|---|---|
| MAE on hours with realized < 30 EUR/MWh | 71.01 | 28.78 | 2.47 | **FAIL** (M4 threshold ≤ 0.75) |
| n_low_price_hours | 195 | 195 | | |

n_low differs from the M4 method run's 69 because the paired dataset here
uses ARF's 72h forecast window (issue ts → +72h) rather than the
shadow's per-day overlap. The qualitative picture (LGBM badly worse) is
identical.

### New metrics — paired LGBM vs ARF

DM p-values are one-sided: H1 = "LGBM is more accurate." p < 0.10 means
LGBM significantly wins; p ≥ 0.50 means LGBM doesn't win (and may lose).

| Metric | LGBM | ARF | mean diff | DM stat | DM p | Direction |
|---|---|---|---|---|---|---|
| Mean quantile score / MAE | **10.22** | 35.13 | -24.91 | -13.14 | <0.0001 | **LGBM wins decisively** |
| twCRPS variant (left-tail at -27.76, pre-committed) | 0.0245 | 0.0000 | +0.0245 | +2.28 | 0.99 | ARF "wins" by abstention (see §3) |
| twCRPS variant (left-tail at -4.07, in-sample, draft only) | 0.109 | 0.023 | +0.086 | +1.52 | 0.94 | not pre-committed; preserved for transparency |
| Pinball-at-p10 | 7.97 | 7.14 | +0.83 | +1.40 | 0.92 | LGBM does not win; modest evidence ARF wins |
| Lower-side coverage (target 0.90) | 0.809 | 0.824 | | | | Both under-cover |
| Winkler IS (α=0.20) | 149.7 | 192.6 | | | | LGBM wins (descriptive) |

### Per-horizon split (pinball-at-p10, paired)

| Horizon | n | n_low | LGBM p10 pinball | ARF p10 pinball |
|---|---|---|---|---|
| h ≤ 24 | 42 | 0 | 1.83 | 2.14 |
| 24 < h ≤ 48 | 333 | 69 | 5.85 | 7.03 |
| 48 < h ≤ 72 | 309 | 69 | 9.37 | 7.53 |
| h > 72 | 158 | 57 | 11.30 | 7.94 |

LGBM wins p10 pinball at h ≤ 48 but loses at h > 48. The aggregate ARF
win on pinball-at-p10 is driven by the long-horizon hours.

## 3. What this means

### The literature-review prediction failed in a specific way

The review predicted "ARF's clamped-at-zero lower band loses by
construction" on pinball-at-p10. **It doesn't, because the band isn't
actually clamped at 0 in the M4 window.** ARF's lower band is computed
as `point - 1.282·EWM_std` (a Gaussian-residual assumption applied to
EWM-tracked error stats). On 2026-05-14 the lower band averaged 10.5
EUR/MWh — well above zero. The clamp at `ml/update.py:365` only bites
when `point - 1.282·EWM_std < 0`, which happens less often in this
window than the prior assumption suggested. The ARF-lower-as-p10
substitution we use here implicitly assumes Gaussian zero-mean residuals,
which the EWM tracking does not strictly guarantee — so ARF's "p10" is a
miscalibrated p10 surrogate, and the pinball-at-p10 comparison is best
read as "ARF lower band vs LGBM p10" rather than a clean quantile
comparison.

The ARF lower band ends up in a "naturally cautious" zone (positive but
substantially below the point) that's surprisingly hard to beat on
pinball-at-p10. LGBM at long horizons over-extrapolates downward (p10
sometimes very negative) and gets punished by pinball when the realised
doesn't dip that far.

### The twCRPS variant doesn't measure what we wanted

A second methodological lesson surfaced after we re-ran with the
pre-committed threshold (-27.76 EUR/MWh). LGBM scored 0.0245; ARF scored
**exactly 0.0000**. The implementation only fires pinball contributions
for quantiles whose predicted value falls *below* the threshold. ARF's
point forecasts essentially never go below -27.76, so its "weight" is
always zero and it scores 0 by abstention. A model that never predicts
into the extreme tail gets a perfect twCRPS variant score regardless of
whether the realisations actually fell into the tail.

This is a different question from the canonical Gneiting & Ranjan (2011)
twCRPS, which integrates the Brier score over thresholds and *does*
penalise a model whose CDF stays at 0 below threshold when realisations
fall there. The variant we computed reduces to "of the times you
predicted into the tail, how accurate were you?" — which a no-extrapolation
model wins by abstaining.

Treat the twCRPS numbers in this report as descriptive, not as
falsification of the literature recommendation. A properly-implemented
threshold-integral twCRPS may well behave differently on this data;
deferred to a follow-up.

### What the new criterion correctly surfaces

1. **LGBM has clear overall skill** — Mean Quantile Score 10.22 vs ARF
   MAE 35.13, paired DM stat = -13.14 with p < 0.0001. LGBM's median
   forecast is much closer to realized, on average, than ARF's point.
   The old criterion (a) hid this — measured only on the conditioned
   slice, LGBM looked worse.
2. **LGBM's lower-tail behaviour isn't unambiguously better than ARF's.**
   ARF's wider EWM-derived band has unexpected p10-pinball skill that
   LGBM's tighter quantile output doesn't match at long horizons. This
   is genuine new information.
3. **Both models under-cover the lower tail** (0.81 vs target 0.90).
   Lower-side coverage is a separable calibration problem — fixing it
   requires either wider bands (sacrificing Winkler) or better tail
   prediction (the actual hard problem).

### The metric framework is doing its job

EXP-012's *point* was: validate the new criterion **before** committing
it to a future shadow. The 2026-05-29 literature review made a
predicted-outcome claim ("LGBM should win pinball-at-p10"). That claim
turned out to be wrong on the data we already had. **This is the right
moment to find out — not after another 14-day shadow window.**

If we had jumped straight to "EXP-013: shadow a new model with
pinball-at-p10 as the primary criterion," we would have re-run the M4
mistake at a different layer: pre-committing a criterion whose
assumptions we hadn't tested.

## 4. Implications for the next bet

The original literature-review recommendation (`docs/metric-redesign-
literature-review.md` §1) was a *three-part* criterion:

1. Aggregate skill (CRPS / mean quantile score) — **validated**: LGBM
   wins decisively on this metric, and it captures the model class
   difference the slice-MAE missed.
2. Tail skill (twCRPS / pinball-at-p10) — **not validated**: ARF's
   EWM band lands in a hard-to-beat zone. The next bet shouldn't assume
   LGBM wins this.
3. Calibration diagnostic (lower-side coverage) — **partially
   validated**: both models under-cover, so the diagnostic correctly
   flags a real issue.

**Updated next-bet design**:

- Use **mean quantile score / CRPS** (with a proper quantile grid) as
  the primary skill criterion. This is now grounded in evidence, not
  prediction.
- Treat **tail metrics as descriptive, not promotion-gating** — until we
  understand *why* ARF wins pinball-at-p10 here. Possible explanations:
  (i) EWM volatility scaling produces "right-magnitude wrong-precision"
  bands that happen to score well on a single-quantile metric, (ii)
  LGBM's CQR widening over-corrects at long horizons, (iii) the small
  number of bottom-decile-of-realized hours (5% × 842 ≈ 42 hours)
  makes the tail comparison noisy and a different window would tell a
  different story.
- **Lower-side coverage** is a guardrail, not a comparison — neither
  model passes it, so it can't promote either.

**Tentative EXP-013 design**:

A backtest at 9 quantiles using `MultiHorizonLightGBMQuantileForecaster`
extended to support N quantiles, evaluated on a larger window (e.g. the
last 60 days of parquet) using **proper CRPS** as the primary metric,
with DM significance. Goal: confirm that overall skill conclusions hold
at finer quantile resolution, and *characterise* (not promote-on) the
tail behaviour difference between LGBM and ARF.

Conditional on EXP-013 confirming the overall-skill picture, the
production-promotion criterion becomes:

> "EXP-014 next-shadow promotion gate: LGBM CRPS significantly lower
> than ARF MAE-as-CRPS-equivalent at DM p < 0.10 multivariate, AND
> lower-side coverage in [0.85, 0.95] (calibration guardrail). No
> tail-MAE criterion."

This is much simpler than the failed M4 three-criterion bundle. The
power was always in the *paired statistical test*, not the slice
conditioning.

## 5. Open questions for follow-up

- **Why does ARF win pinball-at-p10 at long horizons?** Worth a
  dedicated investigation. Hypothesis: EWM std on ARF's residuals
  captures "this hour usually has X EUR/MWh of error" without depending
  on horizon, while LGBM's CQR widens with calibration sample
  characteristics that may not extrapolate well across the 72h
  prediction window. If true, the right move might be horizon-
  conditioned CQR (separate calibration sets per horizon group), not a
  whole new model class.
- **Does the picture change at 9-19 quantiles?** EXP-013. Possible
  that the 3-quantile MQS is biased *against* LGBM (extra weight on
  the wide-band p10/p90 misses) or *for* LGBM (insufficient resolution
  to capture LGBM's actual distribution shape). Worth testing.
- **Window dependence**: 14 days is what we had. The Lago et al. 2021
  best-practice paper recommends running the same evaluation at 7, 14,
  21 days and verifying conclusions hold. We have 20 days total in
  `eval_log.jsonl`; we could redo this at the trailing-7 and
  trailing-20 to check robustness.
- **What about the `ARF lower clamp`?** The CLAUDE.md / `arf-retired.md`
  memory states ARF's lower band is hard-clamped at 0. This experiment's
  data shows that clamp doesn't bite in the M4 window. Either the
  clamp doesn't activate as often as the memory suggested, or the
  memory was written about a regime where it did. Worth checking
  `ml/update.py:365` (the actual clamp line; older docs cite line 337,
  which is stale) and the ARF metrics_history for clamp incidence.

## 6. Artefacts

- `ml/shadow/metrics.py` — reusable metrics module (pinball,
  mean_quantile_score, twcrps_left_tail, lower_side_coverage,
  winkler_interval_score, diebold_mariano with Newey-West HAC).
  Manually-implemented HAC because scipy 1.17 broke statsmodels.api on
  this environment.
- `scripts/exp012_evaluate.py` — runner for this experiment; loads
  calibration_history + ARF archives, builds the paired dataset,
  computes old and new metrics, prints the report block above.
- `ml/forecasts/*_forecast.json` — pulled from sadalsuud for the
  comparison.
- `docs/metric-redesign-literature-review.md` — the literature review
  that motivated this experiment (and made the prediction that turned
  out to be wrong on the tail metrics).

## 7. Sources used

See `docs/metric-redesign-literature-review.md` §9 and `docs/literature.md`.
