# Three iterations of a promotion criterion, and what each one taught us

*Draft. Audience: applied ML practitioners and energy-forecasting folk. Tone:
case study, honest about the mistakes. Style: polish later, capture now.*

**One-line summary.** We set up a structured pre-committed promotion criterion
for an electricity-price forecasting model. It failed in a way that pointed
at a methodological flaw in the criterion itself, not the model. We
researched the literature, applied the recommended replacement, found *its*
headline prediction was also wrong on our data — and then, after a review
battery flagged a propriety violation in our own implementation, found that
the recommended replacement's *implementation* needs more care than the
literature review suggested. Three iterations, each one narrower and more
honest than the last. The existing pre-commit-and-test discipline (already
in the project's hypothesis-log structure) made each iteration legible; a
discretionary review battery between iterations caught what the discipline
alone could not.

---

## 1. The setting

Augur is a day-ahead electricity-price forecasting platform for the
Netherlands. Hourly resolution, 72-hour horizon, EUR/MWh wholesale prices,
producing point + 80% confidence interval forecasts that drive a public
dashboard. The Dutch market has a feature that complicates the modelling:
about 20% of quarter-hourly prices in spring 2026 went *negative* during
solar-surplus midday hours, with a minimum recorded around −413 EUR/MWh.
Forecasts have to express prices that cross zero, span two orders of
magnitude, and shift regime over weeks.

The production model from 2025 through April 2026 was River ARF — an online
adaptive random-forest regressor producing a point forecast plus a Gaussian-
assumption confidence band from EWM-tracked residual statistics. It worked
well in winter. In April 2026 it failed structurally on negative midday
prices: trees can only predict means of leaf-bound training samples, and no
leaf contained negative-price data, so ARF's predictions on the 09–13 UTC
solar trough sat at +55 to +80 EUR/MWh while realised prices crashed to −20
to −30. The lower confidence band was code-clamped at 0, so the uncertainty
channel was also blind to the regime.

ARF was retired on 2026-04-28 with a formal retrospective. The replacement
candidate: LightGBM-Quantile, a multi-horizon model with separate
LGBMRegressors at p10, p50, p90 for each of three horizon groups (h+1..h+6,
h+7..h+24, h+25..h+72), totalling 9 models. The quantile-regression
formulation naturally produces a predictive interval rather than a point
forecast + parametric band, and gradient-boosted trees can extrapolate to
prices outside any leaf's training set.

We backtested the replacement on April 2026 data and got encouraging
results: LightGBM beat River ARF on 14 of 14 evaluable days, with mean MAE
46% lower. Even on the extreme regime-shift days when realised prices hit
−413, LightGBM won by 12–21% MAE. We added a split-conformal calibration
layer (CQR) to bring the empirical 80% band coverage into target.

Time to shadow it for real.

## 2. The bet

The shadow plan §6 set three promotion criteria, all to be evaluated over a
14-day contiguous window of nightly cron predictions:

- **(a)** MAE on hours where realised < 30 EUR/MWh: LightGBM beats ARF by ≥
  25% relative
- **(b)** P10/P90 band empirical coverage: mean in [0.75, 0.85] AND fewer
  than 3 days below 0.60
- **(c)** Weekday-evening-peak (16–19 UTC) MAE: LightGBM no more than +10%
  worse than ARF

All three had to hold to justify replacing ARF on the dashboard. The
criteria were pre-committed in a hypothesis log file before the shadow
started accumulating data, following the project's existing process for
provisional positions: a `Position / Alternative / Method / Revisit
trigger / Review-by` template that predates this experiment. That file
explicitly stated: *"Don't loosen Method when the answer arrives; if you
want to redefine the bet, open a new entry."* We didn't invent this
discipline for the M4 bet — but we did rely on it.

Criterion (a) was the deliberate one. ARF's structural failure was on
negative midday prices, so the natural test of the replacement was: *does
the new model fix that*. Translating "fix that" into a number, we wrote
"MAE on the slice where realised was low". The 25% margin was an
engineering judgment about effect size worth promoting on; the 30 EUR/MWh
threshold reflected the regime we cared about.

## 3. The M4 verdict, May 29 2026

After 20 days of nightly cron predictions, we ran the Method on the
trailing-14 window (2026-05-14 → 2026-05-27). The pre-committed
window-selection rule was "most-recent 14 days only, ignore earlier
rows from cron-shake-out" — taking the trailing 14 of 20 leaves the
first 6 unused as an arithmetic consequence, not because of a named
6-day discard clause.

| Criterion | Value | Threshold | Verdict |
|---|---|---|---|
| (a) ratio (LGBM/ARF) on realised < 30 EUR/MWh | **1.61** | ≤ 0.75 | **FAIL** |
| (a) n_low_price_hours | 69 | ≥ 50 | (power adequate) |
| (b) mean P80 coverage | **0.696** | [0.75, 0.85] | **FAIL** |
| (b) days < 0.60 coverage | **3** | < 3 | **FAIL** |
| (c) mean weekday-peak ratio | **0.450** | ≤ 1.10 | **PASS** |

PROMOTE = False. Park the model.

Criterion (a) was particularly striking: LightGBM was **61% *worse*** than
ARF on the low-price slice — opposite direction of the predicted 25%
*better*. Criterion (c) crushed it the other way: LightGBM was 55% better
than ARF on weekday peak hours.

And here's the puzzle. The *overall* MAE on the same window: LightGBM 24.32
EUR/MWh, ARF 39.04. **LightGBM is 38% better on the unsliced average.**

How can a model be 38% better overall, 55% better on evening peaks, and 61%
*worse* on the low-price slice?

## 4. Two interpretations, both partly right

The puzzle admits two readings, and a careful diagnosis has to entertain
both before picking.

**Reading A: metric artefact.** When you condition an evaluation slice on
the *realised* outcome and then score with a non-strictly-proper
comparison, you bias the result. This is the *forecaster's dilemma*
named by Lerch, Thorarinsdottir, Ravazzolo and Gneiting (2017, *Statistical
Science* 32: 106-127). MAE is a point-forecast loss, not a scoring rule
in the Gneiting-Raftery sense — but the elicitation logic still applies:
conditioning on `Y < c` and then ranking models by absolute error within
that slice can favour a model whose predictions cluster near a
climatological mean over one whose predictions try to forecast the
extreme regime. A trivially-constant "predict the climatological mean
forever" forecaster can win this kind of slice by being closest to the
conditioning event in expectation. The fix is to use a *propriety-
preserving* slice — a threshold-weighted score with the threshold fixed
*before* the realised data is seen — not a condition-on-y comparison.
This trap has been known in the forecast-evaluation literature since at
least the early 2010s. We re-derived it the hard way.

**Reading B: ARF's prior is actually closer to truth here.** This is the
sympathetic-to-ARF objection. ARF's forecasts during the May 2026 window
clustered around 50–80 EUR/MWh during midday hours; realised crashed to
−20. ARF didn't predict the crash but it also wasn't *wildly* off — its
errors were 70–100 EUR/MWh, systematically positive. LightGBM tried to
forecast the crash, swung its p50 toward 0 or slightly negative, and at
long horizons couldn't reach down to the realised −20. Its errors were
also 70–100 EUR/MWh, with mixed signs. *On absolute error alone*,
they're comparable; on the conditioning slice ARF is closer. But this
isn't only a metric bias — at long horizons (h > 48), the features
LightGBM uses thin out, and there's a real case that a mean-reverting
prior *is* the better point estimate when the model has no informative
signal. Per-horizon evidence we'll see in §6 supports this reading.

The two readings aren't mutually exclusive, and we don't have to pick
just one. The honest summary is: the *metric* was rigged against a
non-baseline-clinging model in a way the literature has named, *and* at
the horizons where LightGBM lacks signal, a baseline-clinging model
may genuinely be the better point estimate. Either way, criterion (a)
as MAE on a fixed-threshold realised-conditioned slice can't tell us
which it is — it just says "ratio 1.61, fail."

(Worth flagging the rhetoric: an earlier draft of this article called
ARF "timid in the right direction." That phrasing gives ARF agency it
doesn't have. ARF's tree leaves contain no negative-price training
data, so its predictions can't reach low. Calling that "timid" is
generous; it's structural inability that happens to be on the right
side of the conditioning slice we picked.)

## 5. Literature review

Once the meta-insight clicked, we wanted to know what the field actually
does. A focused literature pass surfaced the standard answer.

For point forecasts of electricity prices in markets with negative prices:
**MAE and rMAE only**. MAPE and sMAPE are explicitly discouraged in the
modern best-practice paper (Lago, Marcjasz, De Schutter & Weron, *Applied
Energy*, 2021) because they're unstable around zero and undefined at zero.

For probabilistic forecasts: **pinball loss per quantile**, plus **CRPS** as
a single density score (Nowotarski & Weron, *Renewable and Sustainable
Energy Reviews*, 2018). Empirical coverage and interval width for
calibration. PIT histograms for visual reliability assessment.

For slice evaluation on extreme regimes without the forecaster's dilemma
trap: **threshold-weighted CRPS** (Gneiting & Ranjan, *JBES*, 2011). twCRPS
integrates the Brier score over thresholds with a fixed weight function —
crucially, the threshold is *pre-committed before seeing data*, which makes
it proper. The 2017 forecaster's dilemma paper from the same group is
literally the warning against the trap we walked into. (Caveat surfaced
by the literature review: de Punder et al. 2025 raise a propriety
concern for some weight functions; the simple left-tail indicator with
fixed `c` is the form used in essentially all published EPF/weather
applications and is the form we use here.)

For comparing a probabilistic forecast to a point forecast: CRPS reduces
exactly to MAE when the predictive distribution is a point mass (Gneiting &
Raftery, *JASA*, 2007). So ARF and LightGBM can be compared in the same
unit without unfairly advantaging either.

For statistical significance: **Diebold-Mariano paired-loss tests** with
Newey-West HAC variance, with Giacomini-White generalisations for rolling-
retraining setups.

So the literature gives a clean recipe. The new criterion design:

1. Aggregate skill: mean quantile score (or proper CRPS at a finer grid)
2. Tail skill: twCRPS at a pre-committed left-tail threshold
3. Calibration: lower-side coverage of the 80% band

All compared with DM. Done.

## 6. The second iteration, on existing data

Before committing the new criterion to another 14-day shadow window, we
applied it to the data we already had. The shadow had collected 14 days
of LightGBM p10/p50/p90 predictions and ARF point + EWM-band forecasts
on the same timestamps. Re-scoring them with the new metrics cost an
hour of work and let us see whether the literature's prediction held up
*before* burning another shadow window on it.

This second iteration wasn't part of the framework — it was a
discretionary "let's check first" move. That distinction matters and
we'll return to it.

The literature review made a crisp prediction: ARF's lower confidence
band is *clamped at 0 in the source code* (`ml/update.py:365`), so it
can never reach into negative territory, so it should *lose by
construction* on pinball-at-p10 — which is exactly the metric that asks
"did your lower tail reach low enough?"

We ran it. 842 paired observations across 14 days.

| Metric | LightGBM | ARF | DM p (one-sided, LightGBM wins?) |
|---|---|---|---|
| Mean quantile score (3-pt) / MAE-equiv | **10.22** | 35.13 | < 0.0001 |
| twCRPS variant, left-tail at −27.76 (pre-committed) | 0.0245 | **0.0000** | 0.99 |
| Pinball-at-p10 | 7.97 | 7.14 | 0.92 |
| Lower-side coverage (target 0.90) | 0.81 | 0.82 | (both under) |
| Winkler IS (α = 0.20) | 149.7 | 192.6 | (LightGBM lower) |

### Aggregate skill: validated, with one honest caveat

LightGBM's mean quantile score is **3.4× lower** than ARF's
MAE-as-CRPS-equivalent (Gneiting & Raftery 2007 §4.2 — CRPS reduces to
absolute error for a point forecast), with Diebold-Mariano significance
of `p < 0.0001`. Its median forecast is *much* closer to realised, on
average, than ARF's point forecast. The model is genuinely better at the
modal task. Criterion (a) hid this because its conditioning slice
favoured ARF's positioning.

**Caveat we have to flag here, not bury in §9.** LightGBM was trained at
only 3 quantiles (p10/p50/p90), so the "mean quantile score" reported is
a 3-point quantile-pinball average, *not* a properly-estimated CRPS. CRPS
from a finite quantile grid converges as the grid densifies; at 3
quantiles the estimate is biased and the direction depends on the
predictive distribution's shape. The DM significance on the 3-point
score is statistically valid (we're paired-testing the same metric on
both models) but the "3.4× better" headline shouldn't be quoted as a
CRPS ratio. A follow-up at 9 or 19 quantiles is queued.

### Tail metrics: the prediction didn't hold, in two ways

ARF wins twCRPS, ARF wins pinball-at-p10. DM p-values of 0.99 and 0.92
under H1 = "LightGBM wins" are equivalent to ~0.01 and ~0.08 under H1 =
"ARF wins." The first is statistically significant evidence for ARF; the
second is modest. Neither matches the literature review's prediction.

Two distinct things happened, both worth understanding.

**The "clamped at 0" assumption didn't hold on this data.** We checked
the actual ARF forecast files for the window: on 2026-05-14 the lower
band averaged 10.52 EUR/MWh, not 0. The clamp at `ml/update.py:365` only
bites when `point − 1.282·EWM_std` goes negative, which happens less
often in this window than the prior memory note assumed. The
"ARF-lower-as-p10" substitution we use here also implicitly assumes
Gaussian zero-mean residuals (the 1.282 factor is the standard-normal
10th percentile); the EWM tracking doesn't strictly guarantee this, so
ARF's "p10" is a miscalibrated p10 surrogate. The comparison is best
read as "ARF lower band vs LightGBM p10" rather than a clean
quantile-vs-quantile comparison. On the per-horizon evidence (next), the
result holds either way.

| Horizon group | LightGBM p10 pinball | ARF lower-band pinball |
|---|---|---|
| h ≤ 24 | 1.83 | 2.14 |
| 24 < h ≤ 48 | 5.85 | 7.03 |
| 48 < h ≤ 72 | 9.37 | 7.53 |
| h > 72 | 11.30 | 7.94 |

LightGBM wins p10 pinball at h ≤ 48 — the horizons where it has signal.
It loses at h > 48, where its features thin out and the model is
essentially guessing. On aggregate, the long-horizon losses dominate.
This is the Reading-B "ARF's prior is genuinely better at long horizons"
story showing up in the data, not just a metric artefact.

**The twCRPS implementation doesn't measure what we wanted it to.** A
review battery on this article (data-analyzer + code-reviewer +
skeptical-EPF reviewer, run after a first draft) caught a third issue.
Our `twcrps_left_tail` implementation is the per-quantile-decomposition
variant: average pinball loss across the quantiles whose predicted value
falls below the threshold. With the pre-committed threshold of −27.76,
ARF's point forecast essentially never goes below the threshold — so its
weight is *always zero* and its twCRPS variant scores 0.0000 by
abstention. A model that never predicts into the extreme tail gets a
"perfect" twCRPS variant score regardless of whether realisations
actually fell into the tail.

This is a different question from the canonical Gneiting & Ranjan (2011)
twCRPS, which integrates the Brier score `(F̂(z) − 1{y ≤ z})²` over `z
≤ c` and *does* penalise a CDF that stays at 0 below the threshold when
realisations fall there. Our variant reduces to "of the times you
predicted into the tail, how accurate were you?" — which a
no-extrapolation model wins by abstaining.

Treat the twCRPS numbers here as descriptive, not as falsification of
the literature recommendation. A properly-implemented threshold-integral
twCRPS may well behave differently on this data. We've documented this
in `ml/shadow/metrics.py` and deferred a canonical implementation to a
follow-up. The pinball-at-p10 finding is robust to this issue (no
threshold weighting); the per-horizon table above stands.

### Where it leaves us

So the second iteration left us with three things:
1. Aggregate skill is real — LightGBM's MQS is decisively better (with
   the 3-quantile bias caveat).
2. At long horizons (h > 48), ARF's mean-reverting prior may genuinely
   be the better point estimate — per-horizon pinball-at-p10 supports
   this.
3. The twCRPS variant we implemented doesn't honestly measure tail
   skill — it rewards abstention. A canonical implementation is
   future work.

## 7. What the framework caught, and what it didn't

Three iterations, three different kinds of error. It's worth being
honest about which the framework caught and which were caught by
discretion.

**Iteration 1 — the criterion-design error.** The first failure
(fixed-threshold MAE on a realised-conditioned slice) was caught by the
framework, in the proper sense. The criterion was pre-committed in a
hypothesis log and run mechanically against the trailing window. The
decision wasn't "look at the numbers and decide" — it was a script that
printed PROMOTE = True or False. There was no room to fudge "but
qualitatively LightGBM seems better, let's promote it anyway." If we
had ignored the verdict and shipped LightGBM on the strength of its
overall MAE win, the long-horizon low-price weakness the per-horizon
table eventually surfaced would have shown up on the dashboard a week
after promotion. Park was correct, *for reasons we partly misdiagnosed
at the time*.

**Iteration 2 — the literature-prediction error.** The second failure
(the "ARF clamp binds, so it loses pinball-at-p10 by construction"
prediction) was *not* caught by the framework. It was caught by a
discretionary decision to apply the new metrics to existing data before
committing them to a new shadow window. That's not part of the
hypothesis-log discipline; it was a "let's check first" move that
could just as easily have been skipped. If we had committed to another
14-day shadow on the new criterion as written, we'd have come back at
the end of it with the same surprise the existing data already showed.

**Iteration 3 — the implementation error.** The third failure (twCRPS
variant rewarding abstention) was caught by neither the framework nor
the EXP-012 first run. It was caught by a review battery — data-analyzer,
code-reviewer, and a skeptical EPF practitioner reviewer — fired *after*
the article draft. The framework's pre-committed criteria don't audit
their own implementation; that's a different kind of check.

Put together, the lesson is narrower than "the framework caught
everything." It's:

1. *Pre-commitment to a falsifiable criterion* (the framework) prevents
   ad-hoc post-hoc redefinition. That's table-stakes and it earned its
   keep at iteration 1.
2. *Discretionary "test on existing data before the next window"*
   (between iterations) catches a class of errors the framework can't —
   wrong assumptions baked into the criterion itself. This needs to be
   habit, not heroism.
3. *Independent review of the implementation* (multi-model review
   battery) catches a third class — propriety violations and
   implementation drift that neither the framework nor the developer can
   reliably self-audit.

All three matter. The pattern is: pre-commit, test the criterion
against existing data, review the implementation. *Then* go around
again on the actual decision.

## 8. What we'd do differently

The lessons translate into a smaller, simpler promotion criterion for the
next shadow.

**Use only what's been validated**. Mean quantile score (or proper CRPS at
a finer quantile grid) was validated on the EXP-012 re-evaluation: it
distinguishes LightGBM from ARF correctly, with statistical significance,
and the conclusion isn't sensitive to slicing tricks. *That's* the
promotion metric. One number, paired DM test, done.

**Demote tail metrics to descriptive**. Pinball-at-p10 and (canonically-
implemented) twCRPS are useful diagnostics for understanding where a
model wins and loses, but they shouldn't be promotion gates as we
currently understand them. We don't yet understand why ARF's EWM band
wins pinball-at-p10, and our twCRPS variant doesn't yet measure tail
skill the way we wanted it to. Both are characterisation tools, not
gates, until the implementations and interpretations are cleaner.

**Coverage stays a guardrail.** Lower-side coverage failing for both
models (0.81 vs 0.90) is a real problem and should block any promotion of
either model. But a guardrail says "block if this fails", it doesn't say
"promote if this passes". It's a one-sided gate.

**Drop the multi-criterion bundle.** The M4 design was: three criteria, all
must hold. With proper-scoring single-number criteria backed by DM tests,
the bundle is unnecessary. One skill criterion plus one calibration
guardrail is enough, and is much harder to game accidentally.

If we had been running this design from the start, we would have parked
the model anyway — overall MQS is fine but coverage is failing, so it
couldn't have promoted. But the *reason* would have been honest: not
"failed an arbitrary slice", but "two months of insufficient lower-tail
calibration". Which is a much more actionable diagnosis.

## 9. Open questions

A few threads we haven't pulled on, recorded for whoever picks this up
next.

**Why does ARF's EWM band win pinball-at-p10 at long horizons?** Our
hypothesis: EWM-tracked residual std is a "this hour's worth of error" estimate
that doesn't depend on the forecast horizon. CQR widens the LightGBM band
based on whatever the trailing 7-day calibration set says, which may not
extrapolate well across the 72h window when the calibration set is
dominated by one regime. If that's right, the fix might be *horizon-
conditioned CQR* — separate calibration sets per horizon group — rather
than a different model class.

**Does the picture change at 9–19 quantiles?** Our LightGBM was trained
at only 3 quantiles (p10/p50/p90); the MQS we reported is a 3-point
quantile-pinball average, not CRPS proper (as flagged in §6).
Retraining at 9 or 19 quantiles is cheap (just more LGBMRegressor
instances) and would tell us whether the 3-quantile result generalises
— and would also let us compute a canonical Gneiting-Ranjan twCRPS
properly, addressing the implementation issue our review battery
surfaced.

**Window dependence.** 14 days is what we had. Best-practice EPF papers
recommend running the same evaluation at 7, 14, 21 days and confirming
conclusions hold. We have 20 days of eval log now; trailing-7 and
trailing-20 are within reach.

**The companion finding about freshness skew**. The live overall MAE was
84% higher than the backtest h+1 MAE we'd used to motivate the shadow.
Some of that is horizon-mix, but not all of it. There's a known
infrastructure issue where the cron runs before the energyDataHub
collector each day, so the LightGBM training parquet sees a 24h-stale
exogenous forecast vintage. Fixing that requires a systemd migration that
we've deferred but is now arguably the next-most-important infrastructure
ticket — any future shadow benefits from exogenous data freshness matching
what the backtest assumed.

## 10. Closing

The Augur replacement story isn't over. ARF is still driving the dashboard.
LightGBM is parked but its code is in the tree. The next experiment will
retrain at 9 or more quantiles, use mean quantile score as the primary
promotion criterion (with a properly-implemented canonical twCRPS as a
descriptive tail diagnostic), and treat any non-aggregate tail-skill
metric as diagnostic rather than gating until we trust both its
implementation and its interpretation. If that experiment validates the
overall-skill picture and we can fix the freshness skew, we'll shadow
the new design and decide whether to swap on the dashboard.

The takeaway isn't a particular model or metric. It's that promoting a
production model on a non-trivial criterion is a multi-layer problem,
and *different* practices catch *different* errors:

- Pre-commitment to a falsifiable criterion (the hypothesis-log
  discipline) catches post-hoc redefinition.
- "Test the new criterion on existing data before the next window" (a
  habit, not a framework feature) catches assumptions baked into the
  criterion.
- Independent review of the implementation (a multi-model review
  battery here) catches propriety violations and implementation drift.

The first one is the cheapest and the easiest to skip; the third is the
slowest and the one most likely to be skipped under time pressure. All
three earned their keep on this arc. The honest summary isn't "the
framework caught the mistakes." It's "the framework caught the first
mistake, the second was caught by a discretionary check that wasn't
part of the framework, and the third was caught by a discretionary
review battery that wasn't part of the framework either." All three
mistakes were instructive. Two of them are the kind of thing the
literature has been warning about for over a decade and we just hadn't
internalised yet.

---

## Artefacts and references

In-repo:

- `docs/lightgbm-shadow-postmortem.md` — M4 verdict, full diagnosis
- `docs/metric-redesign-literature-review.md` — focused literature pass
- `docs/exp-012-results.md` — re-evaluation on existing data
- `docs/literature.md` — topic-indexed bibliography
- `docs/hypothesis-log.md` — pre-committed M4 criteria, resolved 2026-05-29
- `experiments/registry.jsonl` — EXP-008 (ARF retirement), EXP-009/010
  (LightGBM design + CQR), EXP-011 (M4 verdict), EXP-012 (metric
  validation)
- `ml/shadow/metrics.py` — reusable metrics module (pinball, twCRPS, DM)
- `scripts/m4_method_run.py` — M4 verdict runner
- `scripts/exp012_evaluate.py` — EXP-012 runner

Key literature:

- Lerch, Thorarinsdottir, Ravazzolo & Gneiting (2017). "Forecaster's
  dilemma: Extreme events and forecast evaluation." *Statistical Science*
  32: 106-127.
- Gneiting & Ranjan (2011). "Comparing density forecasts using threshold-
  and quantile-weighted scoring rules." *JBES* 29: 411-422.
- Gneiting & Raftery (2007). "Strictly proper scoring rules, prediction,
  and estimation." *JASA* 102: 359-378.
- Nowotarski & Weron (2018). "Recent advances in electricity price
  forecasting: A review of probabilistic forecasting." *RSER* 81:
  1548-1568.
- Lago, Marcjasz, De Schutter & Weron (2021). "Forecasting day-ahead
  electricity prices: A review of state-of-the-art algorithms, best
  practices and an open-access benchmark." *Applied Energy* 293: 116983.
- Diebold & Mariano (1995). "Comparing predictive accuracy." *JBES* 13:
  253-263.

Full bibliography in `docs/literature.md`.
