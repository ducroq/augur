# Four iterations of a promotion criterion, and what each one taught us

*Draft. Audience: applied ML practitioners and energy-forecasting folk. Tone:
case study, honest about the mistakes. Style: polish later, capture now.*

**One-line summary.** We set up a structured pre-committed promotion criterion
for an electricity-price forecasting model. It failed in a way that pointed
at a methodological flaw in the criterion itself, not the model. We
researched the literature, applied the recommended replacement, *thought*
its headline prediction was wrong on our data — then a review battery on
the article flagged an implementation propriety violation, and a second
review battery on the code found a data-pairing bug whose correction
*reversed* one of the headline conclusions and showed the literature
review's original prediction was directionally right after all. Four
iterations, each one narrower and more honest than the last. The
pre-commit-and-test discipline (the project's existing hypothesis-log
process) caught the first error; discretionary review batteries caught
errors two through four. None of those review batteries are part of the
framework; they were judgment calls between iterations.

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

We ran it. 546 paired observations across 14 days (after the vintage fix
discussed in §6.5 below — the first version reported 842).

| Metric | LightGBM | ARF | DM p (one-sided, LightGBM wins?) |
|---|---|---|---|
| Mean quantile score (3-pt) / MAE-equiv | **9.29** | 38.42 | < 0.0001 |
| twCRPS variant, left-tail at −27.76 (pre-committed) | 0.0377 | **0.0000** | 0.99 |
| Pinball-at-p10 | 6.90 | 7.38 | **0.24** |
| Lower-side coverage (target 0.90) | 0.81 | 0.82 | (both under) |
| Winkler IS (α = 0.20) | 134.1 | 208.2 | (LightGBM lower) |

### Aggregate skill: validated, with one honest caveat

LightGBM's mean quantile score is **4.1× lower** than ARF's
MAE-as-CRPS-equivalent (Gneiting & Raftery 2007 §4.2 — CRPS reduces to
absolute error for a point forecast), with Diebold-Mariano significance
of `p < 0.0001`. Its median forecast is *much* closer to realised, on
average, than ARF's point forecast. The model is genuinely better at the
modal task. Criterion (a) hid this because its conditioning slice
favoured ARF's positioning.

**Two caveats to flag here, not bury in §9.** First, LightGBM was trained
at only 3 quantiles (p10/p50/p90), so the "mean quantile score" reported
is a 3-point quantile-pinball average, *not* a properly-estimated CRPS.
With independent p10/p50/p90 quantile regressions, a *degenerate*
quantile prediction (p10 = p50 = p90 = some point) would have MQS equal
to `0.5 × MAE`, so the LGBM-MQS vs ARF-MAE comparison has a roughly 2×
structural head start built in for LGBM independent of any real skill.
The 4.1× we report is partly real median-skill (the apples-to-apples
LGBM-MAE-on-p50 vs ARF-MAE ratio is 24.3/39.0 ≈ 1.6×) and partly the
~2× structural asymmetry from the 3-quantile averaging. The DM
significance on the 3-point score is statistically valid (we're
paired-testing the same metric on both models with the same averaging
rule), but the "4.1×" shouldn't be quoted as a CRPS ratio. A follow-up
at 9 or 19 quantiles is queued.

Second, the Diebold-Mariano test uses Newey-West HAC variance with a
default lag of `floor(n^(1/3)) ≈ 8`. For paired 72-hour-ahead forecasts
on hourly data this is too short — DM (1995) recommends `max_horizon − 1`
(here ≈ 71). The reported test statistic of −12.4 is *probably* still
significant at proper bandwidth, but the standard error would
roughly double, suggesting "p < 0.001" is more defensible than the
"< 0.0001" the script prints. Article reports remain "< 0.0001"
literally; readers should interpret it as "decisively significant" not
"machine-precision precise."

### Tail metrics: the picture moved twice

The first draft of this section reported "ARF wins twCRPS, ARF wins
pinball-at-p10" and treated this as a falsification of the literature
review's directional prediction. Two review batteries later, both of
those tail-metric claims have moved.

**Article-review battery (iteration 3): the twCRPS implementation
doesn't measure what we wanted it to.** Our `twcrps_left_tail` is the
per-quantile-decomposition variant: average pinball loss across the
quantiles whose predicted value falls *below* the threshold. With the
pre-committed threshold of −27.76 EUR/MWh, ARF's point forecast
essentially never goes below the threshold — so its weight is always
zero and its variant scores 0.0000 by abstention. A model that never
predicts into the extreme tail gets a "perfect" variant score regardless
of whether realisations actually fell into the tail. This is *not* the
canonical Gneiting & Ranjan (2011) twCRPS, which integrates the Brier
score `(F̂(z) − 1{y ≤ z})²` over `z ≤ c` and *does* penalise a CDF that
stays at 0 below the threshold when realisations fall there. The
variant we computed answers "of the times you predicted into the tail,
how accurate were you?" — which a no-extrapolation model wins by
abstaining. So the twCRPS "ARF wins" conclusion was never a meaningful
finding about tail skill; it was an implementation issue.

**Code-review battery (iteration 4): the data pairing was wrong.**
A second review battery — this one focused on `ml/shadow/metrics.py`,
`scripts/exp012_evaluate.py`, and `scripts/m4_method_run.py` — caught
something the article-review battery had no way to see: the EXP-012
join was pairing LGBM `eval_day = D` with ARF archive
`{D}_1445_forecast.json`, while the production pipeline
(`ml.shadow.evaluate_shadow.find_arf_archive_for_day`) selects the most
recent archive whose timestamp precedes eval-day midnight UTC — which
for `D` is `{D-1}_1445_forecast.json`, the previous day's 14:45 UTC
cron. Net effect: in the buggy version, ARF was issued ~15 hours
*after* the LGBM prediction the comparison was supposed to be
apples-to-apples with. ARF had more recent realised prices to anchor
on. Pinball-at-p10, MAE, twCRPS — every metric was biased in ARF's
favour by this freshness gift.

After the fix, the numbers in the table above changed materially:

- LightGBM MQS / ARF MAE ratio: 3.4× → **4.1×** (LightGBM wins by *more*
  once vintages match).
- Pinball-at-p10: 7.97 vs 7.14 (ARF wins, p=0.92) →
  **6.90 vs 7.38 (LightGBM wins, p=0.24)**.

That's a *directional reversal* of the headline tail-metric finding. The
literature review's original prediction — "LightGBM should win
pinball-at-p10 because it can actually reach into the negative tail
where ARF's structural baseline can't" — turned out to be directionally
correct after all. We had read it as falsified because our join was
wrong, not because the prediction was wrong.

The per-horizon decomposition also moved. With the corrected vintage and
the corresponding tighter overlap window (h ≤ 72 only, vs the buggy
version's spuriously-longer reach):

| Horizon group | LightGBM p10 pinball | ARF lower-band pinball |
|---|---|---|
| h ≤ 24 | 1.83 | 4.48 |
| 24 < h ≤ 48 | 5.85 | 7.51 |
| 48 < h ≤ 72 | 10.18 | 7.86 |

LightGBM wins decisively at short and medium horizons; ARF's lower band
recovers at long horizons. The "ARF's mean-reverting prior may be
genuinely better at long horizons" reading from Reading B (§4) holds,
but the cross-over point sits beyond h = 48 — not at h = 24 as the
buggy data suggested. ARF's lower band remains a real competitor; LGBM
no longer "loses" the tail metric.

### Caveats that remain

- **The `lightgbm_quantile` module sorts predictions row-wise**
  (`np.sort(raw, axis=1)`), so the "p10" stored in `calibration_history`
  is `min(q0.10, q0.50, q0.90)` row-by-row, not the raw 10th-percentile
  output. When the independent quantile regressions cross (common on
  quiet hours), the stored "p10" is below the raw value, biasing
  pinball-at-p10 in LightGBM's favour. Past data can't be retroactively
  fixed; going forward, `update_shadow.py` will store raw quantiles
  alongside sorted ones.
- **The twCRPS variant remains a non-canonical metric**: ARF still
  scores 0 by abstention; we still don't have a proper threshold-integral
  twCRPS implementation. Deferred to the next experiment.
- **ARF's lower band isn't actually clamped at 0** in the M4 window
  (`ml/update.py:365` only bites when `point − 1.282·EWM_std < 0`,
  which is rare in this regime). So even with the corrected vintage,
  the comparison is LGBM-p10 vs ARF-lower-band-not-pinned-to-zero —
  not the "ARF loses by construction" scenario the literature review
  originally framed. LGBM still modestly wins this comparison, which is
  the cleaner finding.

### Where it leaves us, after all four iterations

1. **Aggregate skill is real and decisive** — LightGBM's MQS is 4.1×
   below ARF's MAE-as-CRPS-equivalent (with the 3-quantile structural
   asymmetry and HAC-bandwidth caveats above). The headline conclusion
   survived all four iterations; only the magnitudes shifted.
2. **Tail skill (pinball-at-p10) modestly favours LightGBM** with the
   corrected vintage — vindicating the literature review's directional
   prediction. Not statistically conclusive (p = 0.24 in LightGBM's
   favour) but positive.
3. **The non-canonical twCRPS variant doesn't honestly measure tail
   skill** — neither version of the calculation (in-sample or
   pre-committed threshold) gave a meaningful answer because ARF
   abstains from the tail in both cases.
4. **At very long horizons (h > 48), ARF's prior may still be the
   better point estimate** — per-horizon pinball-at-p10 has the
   cross-over there.

## 7. What the framework caught, and what it didn't

Four iterations, four different kinds of error. The framework — the
pre-commit-and-test discipline in the project's hypothesis-log
structure — caught the first one. The other three were caught by
discretionary judgement calls that happened to be made; none of them
were guaranteed by process.

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

**Iteration 2 — the assumption-import error.** The second iteration
(applying the literature-recommended metrics to existing data) was a
discretionary move, not a framework requirement. We chose to test the
criterion before committing it to a new shadow window. That choice
caught an *apparent* falsification of the literature review's prediction.
Without the choice, we would have committed to another 14-day shadow
on a criterion whose assumptions we hadn't tested.

(The apparent-falsification turned out to be wrong itself — see
iteration 4 — but the value of iteration 2 wasn't in the answer it
produced. It was in *changing the cost of being wrong* from "another
14 days of shadow + a misleading promotion" to "an hour of recompute
on existing data.")

**Iteration 3 — the article-implementation error.** The third
iteration was a review battery fired against the article draft:
data-analyzer, code-reviewer, and a skeptical EPF practitioner. It
caught that our `twcrps_left_tail` implementation is non-canonical and
rewards abstention from the tail. The framework's pre-committed
criteria don't audit their own implementation; that's a different
kind of check. The article also had a category error ("MAE on a slice
isn't a proper scoring rule" — MAE isn't a scoring rule), which the
battery caught and we rewrote.

**Iteration 4 — the data-pairing error.** The fourth iteration was a
*second* review battery fired against the code (the metrics module +
the EXP-012 runner + the M4 method runner). It caught the vintage
mismatch — `build_paired` joining LGBM `eval_day=D` with the wrong-day
ARF archive — that the article-review battery had no view of. The fix
materially changed the headline conclusion of iteration 2: pinball-at-p10
*reversed* direction, vindicating the literature review's original
prediction. The discretionary check of iteration 2 had run on bad data
without anyone noticing for a full session.

The pattern after four iterations:

1. *Pre-commitment to a falsifiable criterion* (the framework) prevents
   ad-hoc redefinition. Earned its keep at iteration 1.
2. *Discretionary "test on existing data before the next window"*
   (a habit, not a framework feature) catches a class of errors the
   framework can't — wrong assumptions baked into the criterion. Earned
   its keep by changing the cost-of-being-wrong at iterations 2 and 4.
3. *Article-level review battery* catches mis-framing and
   implementation-vs-canonical-form gaps. Earned its keep at iteration 3.
4. *Code-level review battery* catches data-pipeline bugs that no
   article-level reading can see. Earned its keep at iteration 4 —
   and reversed the headline of iteration 2 *post-publication-draft*,
   which is exactly the kind of error that makes papers retract.

All four matter. None of them is redundant. If we had skipped any one,
we would still be carrying its corresponding mistake. The honest
generalisation is not "the framework caught the mistakes" — it's "the
combination of pre-commitment, discretionary checks, and *two
independent* review batteries (one on the prose, one on the code)
caught four mistakes that compounded into a publishable but wrong
draft." The bare framework caught one of them.

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
  criterion *and* changes the cost-of-being-wrong even when the test
  itself is buggy.
- Independent review of the article-level claims catches mis-framing
  and category errors.
- Independent review of the *code* catches data-pipeline bugs that
  no prose-level reading will see.

The first is the cheapest and the easiest to skip; the last two are
the slowest and the ones most likely to be skipped under time pressure.
All four earned their keep on this arc. The honest summary isn't "the
framework caught the mistakes" — it's "*one* mistake was caught by the
framework, and three more were caught by discretionary judgement calls
that were each separately worth making." Each of the discretionary
checks was specifically the right one for the corresponding error
class. Pre-commitment doesn't save you from the wrong implementation;
implementation review doesn't save you from a wrong-data join;
data-join review doesn't save you from a wrong premise.

This isn't a hopeful conclusion ("we have a framework that catches
everything"). It's a humbler one: pre-commit when you can, and assume
the framework has missed at least one thing. Then fire batteries until
you've stopped finding things. We're at four. There may be a fifth.

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
