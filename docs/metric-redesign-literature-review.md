# Metric redesign — literature review

**Purpose**: Input to the next-bet decision following the M4 Path B park
(2026-05-29, see `docs/lightgbm-shadow-postmortem.md` §6). Researches what the
academic + industry electricity-price-forecasting (EPF) literature recommends
for evaluating probabilistic forecasts on markets with frequent negative
prices — i.e. what should replace the failed "MAE on hours where realised <
30 EUR/MWh" criterion (a).

Compiled 2026-05-29 from a focused web research pass. All citations verified
against linked sources; if a claim cannot be sourced, it is marked as such.

---

## 1. Headline recommendation

Replace the single-threshold MAE-on-slice criterion (a) with a three-part
probabilistic criterion, all evaluated *paired* (LGBM vs ARF on the same
timesteps) and tested for significance with **Diebold-Mariano** on hourly
loss differentials:

1. **Aggregate CRPS** (estimated from the quantile predictions via the
   pinball-sum approximation) as the primary skill score. ARF receives a
   CRPS-equivalent score equal to its MAE under the point-forecast
   degeneracy of CRPS (Gneiting & Raftery 2007 §4.2 — this is the
   field-standard fair-comparison trick).
2. **Threshold-weighted CRPS (twCRPS)** with a left-tail weight
   `w(z) = 1{z < c}` where `c` is the bottom-decile of realised prices in
   the evaluation window, as the rare-regime criterion. This replaces the
   fixed-30-EUR slice and is the Gneiting & Ranjan (2011) tool for
   evaluating extreme-regime skill *without* the "forecaster's dilemma"
   trap that bit criterion (a).
3. **Pinball loss at p10** plus **empirical lower-side coverage** of the
   80% CQR band as a calibration diagnostic — the literal mathematical
   answer to "did the lower tail reach into negative territory when it
   should?"

## 2. The methodological flaw in criterion (a)

The promotion criterion "MAE on hours where realised price < 30 EUR/MWh,
LightGBM beats ARF by ≥25%" failed because it walks straight into the
**forecaster's dilemma** described by Lerch, Thorarinsdottir, Ravazzolo &
Gneiting (2017) *Statistical Science* 32: 106-127. The dilemma: when you
*condition on the realised outcome being extreme* and compute a non-proper
metric on that subset, you reward forecasters whose predictions happen to be
closer-to-realised-conditional-on-realised-being-low — which is whoever is
nearest a climatological mean, regardless of whether they made a genuine
forecast of the extreme regime.

ARF on the M4 window had: forecasts clustered ~50-80 EUR/MWh during the NL
midday solar trough; realised prices crashed to -20 to -30 EUR/MWh. ARF's
errors were 50-100 EUR/MWh wide. LGBM (the new model) actually tried to
forecast a midday drop but at h>24 horizons couldn't reach low enough; its
errors were ~70-100 EUR/MWh. **MAE penalised both, but ARF was timid in the
right direction.** LGBM was confidently incorrect.

The structural ARF retirement motivation was: "trees can't extrapolate to
negative prices because no training-leaf sample is negative." A metric that
*tests* this question must reward "did your predictive distribution put
probability mass on negative realisations?" — which MAE on a point forecast
cannot do.

twCRPS with left-tail indicator weight is propriety-preserving (integrates
the Brier score over a *pre-selected* threshold range, not over a
selected-on-y subset) and is the standard solution.

## 3. What the literature says

### Probabilistic EPF metrics under negative prices

The canonical reference is **Nowotarski & Weron (2018)**, "Recent advances
in electricity price forecasting: A review of probabilistic forecasting,"
*Renewable and Sustainable Energy Reviews* 81: 1548-1568. They lay out the
standard paradigm — **maximise sharpness subject to reliability** (Gneiting,
Balabdaoui & Raftery 2007) — and rank metrics by preference:

- Pinball loss (= quantile score) per quantile and averaged
- CRPS as a single comprehensive density score
- Empirical coverage (PICP) + interval width (PINAW) for sharpness
- Kupiec / Christoffersen tests for unconditional/conditional coverage
- PIT histograms / reliability diagrams for visual calibration

**Lago, Marcjasz, De Schutter & Weron (2021)**, "Forecasting day-ahead
electricity prices: A review of state-of-the-art algorithms, best practices
and an open-access benchmark," *Applied Energy* 293: 116983, is the modern
best-practice paper. Key findings:

- **MAPE and sMAPE are explicitly discouraged** for electricity prices —
  unstable around zero, undefined at zero. Use MAE and rMAE (relative MAE
  vs naive).
- **Diebold-Mariano significance testing should always be reported** in
  both univariate (per-hour) and multivariate (joint) forms.
- **Giacomini-White** preferred over plain DM when the forecasting
  *procedure* (model + rolling estimation window) is what's tested rather
  than a fixed model — which applies to both Augur ARF and LGBM.

For European markets with frequent negative prices, **Marcjasz, Narajewski,
Weron & Ziel (2023)** "Distributional neural networks for electricity price
forecasting" (arXiv:2207.02832) and **Uniejewski & Weron (2021)** "Regularized
quantile regression averaging" evaluate models exclusively on pinball +
CRPS + coverage + GW significance — never MAPE or fixed-threshold MAE
slices. CRPS and pinball are scale-invariant to sign because they operate
on signed residuals; this is the standard reason the EPF literature
abandoned MAPE.

### Comparing a quantile model to a point model

**CRPS reduces exactly to MAE when the predictive distribution is a point
mass** (Gneiting & Raftery 2007 §4.2). This is the field-standard fair-
comparison move: give the point model a CRPS score equal to its absolute
error per timestep. The probabilistic model is *not* unfairly advantaged —
it's only better if it places probability mass productively around the
realisation. A confidently-wrong probabilistic forecast is *correctly*
penalised by CRPS, and a wide-but-poorly-positioned one likewise.

ARF's EWM band can technically be scored at p10 and p90 by assuming
Gaussian residuals (ARF p10 ≈ point − 1.282·EWM_std). But the cleaner
default is to score ARF on MAE only, treat that as the CRPS-equivalent,
and do not score it on per-quantile pinball. Then LGBM's tail-skill
criterion is: LGBM p10 pinball significantly lower than ARF MAE on the
bottom-decile slice.

### Pinball loss at p10 specifically

Pinball is **the elicitable scoring rule for individual quantiles**
(Gneiting 2011, "Making and Evaluating Point Forecasts"). Evaluating p10
in isolation is exactly the right way to ask "did the lower tail behave
correctly?" GEFCom2014 (Hong et al. 2016) evaluated 99 quantiles with mean
pinball; Nowotarski & Weron (2018) recommend per-quantile pinball for
diagnostics.

Known caveat (Chung et al. 2021, "Beyond Pinball Loss," OpenReview): aggregate-
pinball *training* may leave individual quantiles miscalibrated. This is a
training concern, not an evaluation concern. Pinball is still the right
*scoring* rule for a fitted p10.

### Threshold-weighted CRPS for the slice question

**Gneiting & Ranjan (2011)**, "Comparing density forecasts using threshold-
and quantile-weighted scoring rules," *Journal of Business and Economic
Statistics* 29: 411-422 — the canonical solution to the slice-evaluation
problem. twCRPS integrates the Brier score over thresholds with a weight
function `w(z)` instead of conditioning on `y`:

  `twCRPS = ∫ (F̂(z) − 1{y ≤ z})² · w(z) dz`

For left-tail focus, `w(z) = 1{z ≤ c}` with `c` pre-committed (not chosen
after seeing y). This preserves propriety — unlike conditioning on
{realised: y < c}, which biases toward timid forecasters.

A recent critique (de Punder et al. 2025, referenced in
arxiv.org/html/2407.15900) notes twCRPS may not be strictly proper under
all weight functions. The indicator-weighted left-tail version with a
fixed pre-committed threshold is the form used in essentially all
published EPF and weather applications and is fine for Augur's purposes.

### Statistical significance

**Diebold-Mariano (1995)** is the field default. The EPF-specific
implementation in `epftoolbox` (github.com/jeslago/epftoolbox) provides
both univariate (per-hour DM, gives 24 statistics) and multivariate
(joint across hours) variants. Univariate diagnoses where the new model
wins/loses; multivariate is the single-number promotion test.

**Giacomini & White (2006)**, "Tests of conditional predictive ability,"
*Econometrica* 74: 1545-1578, is the recommended generalisation for
rolling-retraining setups — i.e. our LGBM's 56-day rolling window. The
multivariate GW (Borup et al. 2022) jointly tests over horizons.

For our sample size (~14 days × ~50 overlapping hours × 3 quantiles ≈ 2100
paired observations), DM/GW has adequate power for medium effect sizes.
Per-hour DM is best read as direction, not significance.

## 4. Concrete metric definitions

**Pinball loss** at quantile `τ` (predicted quantile `q̂_τ`, realised `y`):

  `ρ_τ(y, q̂_τ) = max((y − q̂_τ)·τ, (q̂_τ − y)·(1 − τ))`

At τ = 0.5, pinball = 0.5 × |y − q̂|. At τ = 0.1, asymmetrically punishes
over-prediction — exactly what's wrong with ARF on midday solar troughs.

**CRPS from a finite quantile grid** (pinball-average estimator):

  `CRPS ≈ 2 · mean over τ in Q of ρ_τ(y, q̂_τ)`

With only τ ∈ {0.1, 0.5, 0.9} this is a 3-point Riemann sum — biased.
For honest CRPS, train at 9-19 quantiles (cheap in LightGBM) or report
the three pinball losses directly under the name "mean quantile score"
rather than calling it CRPS.

**For ARF (point + EWM band)**: use the point-mass CRPS-equivalent
`CRPS_ARF(y, ŷ) = |y − ŷ|`. Skip per-quantile scoring unless you
explicitly choose to treat the EWM band as a Gaussian (ARF p10 = point −
1.282·EWM_std). Document the choice.

**Threshold-weighted CRPS** with left-tail indicator weight at `c`:

  `twCRPS(F̂, y) = ∫ (F̂(z) − 1{y ≤ z})² · 1{z ≤ c} dz`

In practice, a discrete approximation using the predicted quantiles and a
small numerical integration grid works fine.

**Winkler / interval score** at level α (1-α coverage, lower L, upper U):

  `IS_α(y, L, U) = (U − L) + (2/α)·max(0, L − y) + (2/α)·max(0, y − U)`

Proper for interval forecasts (Gneiting & Raftery 2007 §6.2). For α =
0.20 (80% band) the penalty factor is 10.

**Empirical lower-side coverage**: fraction of realisations falling above
L. Report separately from upper-side coverage — Augur's structural worry
is specifically lower-side under-reach.

**Diebold-Mariano statistic** on loss differential `d_t = L(ε_A_t) −
L(ε_B_t)`:

  `DM = mean(d) / sqrt(Var̂(d̄))`

with Newey-West HAC variance, bandwidth ≈ forecast horizon − 1. One-sided
H1: `mean(d) < 0` means A's loss is lower.

## 5. Application plan for Augur

Concrete computation, given existing data (`ml/shadow/eval_log.jsonl`,
`ml/forecasts/{ts}_forecast.json`, `ml/models/shadow/shadow_state.json`):

1. **Per (issue_date, h ∈ 1..72) tuple, compute**:
   - LGBM: `pinball_p10`, `pinball_p50`, `pinball_p90`, `MAE` = |y − p50|,
     `winkler80`
   - ARF: `MAE` = |y − point|, plus optional `pinball_p10/p90` via the
     Gaussian-EWM assumption

2. **Aggregate to promotion-criterion vector** (pre-committed *before*
   the next window starts, in a new `docs/hypothesis-log.md` entry):
   - **Primary (skill)**: mean over (issue_date, h) of LGBM's three-
     pinball-average vs ARF's MAE-as-CRPS-equivalent, DM-tested
     multivariate. Threshold: skill ratio ≤ 0.95 AND DM p < 0.10.
   - **Tail skill (the structural test)**: twCRPS with `c = q_05`(realised
     prices in window), LGBM vs ARF. Threshold: LGBM ≤ 0.80 × ARF.
     Equivalent computable form: mean of `pinball_p10_LGBM − |y −
     point_ARF|` on (issue_date, h) pairs where `y < c`, weighted by
     `(c − y)`.
   - **Calibration gate** (guardrail, not comparison): empirical lower-
     side coverage of CQR-corrected 80% band in [0.07, 0.13]. Fail = park
     regardless of other criteria.

3. **Asymmetry note**: ARF is point + parametric band; LGBM is quantile.
   The honest comparison is quantile-vs-MAE-equivalent unless we are
   willing to assume Gaussian for ARF — which we should not, because the
   EWM half-life of 24h doesn't fit a stationary Gaussian assumption
   (Augur memory notes this).

4. **Per-hour breakdown**: report (but don't promote on) per-hour DM
   matrices. The May 2026 result "LGBM crushes ARF at weekday peak hours
   (ratio 0.45) but loses at long-horizon midday low-price hours" is
   substantively important and gets diluted by aggregate metrics.

## 6. What to drop or modify

**Drop**:

- **Fixed-threshold "MAE on hours with y < 30 EUR/MWh" criterion** — the
  forecaster's-dilemma trap. Replaced by twCRPS with pre-committed
  threshold, OR by bottom-decile stratification.
- **The 25% relative-improvement bar applied to a single MAE-on-slice**
  — bars on non-proper conditionally-selected metrics don't generalise.
- **MAPE / sMAPE anywhere** — undefined at zero, meaningless with
  negative prices. (Not currently used in Augur, but worth flagging for
  any incoming pipeline contributor.)

**Modify**:

- Replace "is X% better" thresholds with **DM p-values plus minimum
  effect size** (pre-commit both: e.g. "p < 0.10 multivariate-DM AND skill
  ratio ≤ 0.95").
- Replace MAE-on-slice with pinball-loss-at-p10 on slice (or twCRPS).
  Pinball mechanically rewards "your lower band reached low enough"
  rather than "your point forecast happened to be near the realised
  value."

**Keep**:

- 14-day evaluation window (Lago et al. 2021 recommend running multi-window
  robustness checks — i.e. evaluate at 7, 14, 21 days and verify
  conclusions are stable).
- 80% nominal coverage target for bands.
- Pre-committing the criterion in `docs/hypothesis-log.md` before the
  window opens — methodological best practice; the M4 process was right,
  only the metric choice was wrong.

## 7. Open questions and caveats

- **Augur currently only has 3 quantiles (p10/p50/p90).** "Aggregate CRPS"
  from a 3-point pinball sum is biased. For honest CRPS, retrain at
  9-19 quantiles (cheap in LightGBM via separate models per τ, no
  architectural change). If a 3-quantile CRPS estimate is reported,
  label it "mean quantile score (3-point estimator)" — *not* CRPS. This
  is the most important practical caveat.

- **Propriety of twCRPS**: de Punder et al. (2025) raise a propriety
  concern for some weight functions. The simple left-tail indicator
  `w(z) = 1{z ≤ c}` with `c` fixed before the window is fine — that's
  the form used in essentially all published EPF and weather
  applications.

- **Economic value vs statistical accuracy**: Lago et al. (2021) and the
  Maciejowska et al. (2022) review (arXiv:2204.11735) stress that
  statistical metrics are only the first step — the real test is whether
  the forecast improves a downstream decision (battery dispatch, EV
  charge timing, consumer guidance). For Augur as a dashboard product,
  "does the band visually convey uncertainty correctly?" is partly
  calibration (pinball/coverage/Winkler) and partly UX (no metric
  resolves this). Decide explicitly whether the next promotion criterion
  is statistical accuracy or product value; the two can diverge.

- **DM with rolling-window retraining**: GW is technically more correct
  than DM. In practice it's rarely a deciding factor for our sample
  sizes; DM with a footnote noting the caveat is acceptable.
  `epftoolbox` provides both.

- **Negative-price climatology is shifting**: NL is heading toward more
  (not fewer) negative-price hours in spring as solar grows. A criterion
  calibrated on 2025-2026 distributions may decay; build in
  re-validation every ~90 days.

## 8. Suggested next-bet sequencing

1. **EXP-012: metric redesign + retrain at finer quantile grid**. Train
   LGBM with 9 or 19 quantiles (no architecture change, just more
   `LGBMRegressor` instances). Backtest against ARF on the M4 window
   data using the new metrics. Goal: demonstrate the metrics
   *discriminate correctly* on already-collected data — i.e. on the
   bottom-decile slice, LGBM should now score better than ARF if (and
   only if) it actually placed lower-tail probability mass productively.
   This is the meta-test: does the new criterion behave as intended?

2. **EXP-013 (conditional on EXP-012 + augur#12)**: shadow a new model
   class with the redesigned criterion, after augur#12 fixes the
   exogenous freshness skew (companion-hypothesis ratio of 1.84 says
   freshness skew is material — a new shadow on unfixed parquet
   semantics tests model class through a confounding layer).

3. Only after (1) and (2) consider model-architecture changes: separate
   heads per horizon group, explicit long-horizon solar features, or
   ACI for the regime-shift coverage failures.

## 9. Sources

Primary references (verified):

- Nowotarski, J. & Weron, R. (2018). "Recent advances in electricity price
  forecasting: A review of probabilistic forecasting." *Renewable and
  Sustainable Energy Reviews* 81: 1548-1568.
  https://www.sciencedirect.com/science/article/abs/pii/S1364032117308808
- Lago, J., Marcjasz, G., De Schutter, B. & Weron, R. (2021). "Forecasting
  day-ahead electricity prices: A review of state-of-the-art algorithms,
  best practices and an open-access benchmark." *Applied Energy* 293:
  116983.
  https://www.sciencedirect.com/science/article/pii/S0306261921004529
- epftoolbox (Lago et al.) — reference implementation of DM/GW for EPF.
  https://github.com/jeslago/epftoolbox
- Gneiting, T. & Raftery, A. E. (2007). "Strictly proper scoring rules,
  prediction, and estimation." *Journal of the American Statistical
  Association* 102: 359-378.
- Gneiting, T. & Ranjan, R. (2011). "Comparing density forecasts using
  threshold- and quantile-weighted scoring rules." *Journal of Business
  and Economic Statistics* 29: 411-422.
- Gneiting, T. (2011). "Making and evaluating point forecasts." *Journal
  of the American Statistical Association* 106: 746-762.
- Lerch, S., Thorarinsdottir, T. L., Ravazzolo, F. & Gneiting, T. (2017).
  "Forecaster's dilemma: Extreme events and forecast evaluation."
  *Statistical Science* 32: 106-127.
- Diebold, F. X. & Mariano, R. S. (1995). "Comparing predictive accuracy."
  *Journal of Business and Economic Statistics* 13: 253-263.
- Giacomini, R. & White, H. (2006). "Tests of conditional predictive
  ability." *Econometrica* 74: 1545-1578.
- Marcjasz, G., Narajewski, M., Weron, R. & Ziel, F. (2023).
  "Distributional neural networks for electricity price forecasting."
  arXiv:2207.02832. https://arxiv.org/pdf/2207.02832
- Hong, T. et al. (2016). "Probabilistic energy forecasting: Global
  Energy Forecasting Competition 2014 and beyond." *International Journal
  of Forecasting* 32: 896-913.
- Chung, Y. et al. (2021). "Beyond Pinball Loss: Quantile Methods for
  Calibrated Uncertainty Quantification." OpenReview.
  https://openreview.net/pdf?id=QbVza2PKM7T

Compiled by Claude (agent-driven research) on 2026-05-29. Sources verified
via WebFetch; no fabricated citations.
