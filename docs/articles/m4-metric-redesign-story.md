# How a pre-committed promotion criterion failed twice, and what we learned

*Draft. Audience: applied ML practitioners and energy-forecasting folk. Tone:
case study, honest about the mistakes. Style: polish later, capture now.*

**One-line summary.** We set up a structured pre-committed promotion criterion
for an electricity-price forecasting model. It failed in a way that pointed
at a methodological flaw in the criterion itself, not the model. We
researched the literature, got a recommended fix, and tested the fix on the
same data before committing it to another shadow window. The literature's
prediction was *also* wrong, in an interesting and instructive way. The
framework — pre-commit, test on existing data, iterate — caught both
mistakes before either could damage a production decision.

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
started accumulating data. The file explicitly stated: *"Don't loosen Method
when the answer arrives; if you want to redefine the bet, open a new entry."*
This is the discipline that makes a falsifiable test mean anything.

Criterion (a) was the deliberate one. ARF's structural failure was on
negative midday prices, so the natural test of the replacement was: *does
the new model fix that*. Translating "fix that" into a number, we wrote
"MAE on the slice where realised was low". The 25% margin was an
engineering judgment about effect size worth promoting on; the 30 EUR/MWh
threshold reflected the regime we cared about.

## 3. The M4 verdict, May 29 2026

After 20 days of nightly cron predictions (the first 6 days of which were
discarded as cron-shake-out per the pre-committed window-selection rule), we
ran the Method on the trailing 14:

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

## 4. Forecaster's dilemma

The answer turns out to be a known trap in forecast evaluation, named in a
2017 paper by Lerch, Thorarinsdottir, Ravazzolo and Gneiting: the
*forecaster's dilemma*. When you condition your evaluation slice on the
realised outcome, you bias the comparison.

Concretely. ARF's forecasts during the May 2026 window clustered in a
mean-reverting band around 50–80 EUR/MWh during midday hours. The realised
midday prices crashed to −20. ARF's errors on those hours were 70–100
EUR/MWh wide — *all systematically positive*. LightGBM, trying to forecast
the crash, swung its p50 prediction much lower — toward 0 or sometimes
slightly negative — but at long horizons couldn't reach down to the
realised −20. Its errors were also 70–100 EUR/MWh wide, but with a
different sign structure.

MAE on a low-realised slice treats both equally. But ARF and LightGBM are
failing differently. ARF is *timid in the right direction*: it doesn't
predict the crash, but it's positioned closer to a baseline that's
asymmetrically less wrong on the conditioning event we selected. LightGBM
attempts the forecast and over- or under-shoots in ways that look bad
under absolute error.

Worse, MAE on a *condition-on-y-extreme* slice isn't a proper scoring rule.
You can construct trivial forecasters — predict the climatological mean
forever — that beat genuine forecasters on extreme-realisation slices,
because the conditioning step plants a bias toward whoever is closest to a
constant. The literature has known this since at least the early 2010s. We
re-derived it from scratch, the hard way, by losing 14 days of shadow time
to a criterion that couldn't tell us what we thought it was telling us.

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
literally the warning against the trap we walked into.

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

## 6. The second surprise

Before committing this to another 14-day shadow window, we did one more
thing. The shadow had already collected 14 days of LightGBM p10/p50/p90
predictions and ARF point + EWM-band forecasts on the same timestamps. We
could *apply the new metrics to the existing data* and see if they
discriminated the way the literature predicted.

This is the test of a metric against itself. If the recipe is right, then
recomputing M4 with the new metrics should reveal LightGBM's real skill
that the old criterion (a) hid. Specifically, the literature review made a
crisp prediction: ARF's lower confidence band is *clamped at 0 in the
source code*, so it can never reach into negative territory, so it should
*lose by construction* on pinball-at-p10 — which is exactly the metric that
asks "did your lower tail reach low enough?"

We ran it. 842 paired observations across 14 days. Here's what happened.

| Metric | LightGBM | ARF | DM p (LightGBM wins?) |
|---|---|---|---|
| Mean quantile score / MAE-equiv | **10.22** | 35.13 | < 0.0001 |
| twCRPS, left-tail at −4.07 | 0.109 | 0.023 | 0.94 |
| Pinball-at-p10 | 7.97 | 7.14 | 0.92 |
| Lower-side coverage (target 0.90) | 0.81 | 0.82 | (both under) |
| Winkler IS (α = 0.20) | 149.7 | 192.6 | (LightGBM lower) |

The aggregate skill story is exactly what we expected and exactly what the
old criterion hid. LightGBM's mean quantile score is **3.4× better** than
ARF's MAE-as-CRPS-equivalent, with Diebold-Mariano significance through the
floor. Its median forecast is *much* closer to realised, on average, than
ARF's point forecast. The model is genuinely better at the modal task. Old
criterion (a) hid this because the conditioning slice happened to favour
ARF's positioning.

But the tail metrics didn't go the way the literature predicted. ARF wins
twCRPS, ARF wins pinball-at-p10. The DM p-values are 0.94 and 0.92 — well
*above* the 0.50 line that would mean "LightGBM doesn't significantly
win". They mean LightGBM significantly *loses*.

Why? Because the "ARF lower band is clamped at 0" prediction turned out to
be **wrong on the May 2026 data**. We checked the actual ARF forecast files
for the window: on 2026-05-14 the lower band averaged 10.52 EUR/MWh, not 0.
The clamp in the source code only bites when *point - 1.282·EWM_std* goes
negative, which apparently happens less often in this window than the
prior assumption suggested.

So ARF's lower band lands in a "naturally cautious" zone — positive but
substantially below the point forecast. That zone turns out to be
surprisingly hard to beat on pinball-at-p10. LightGBM's quantile output
sometimes swings its p10 quite negative at long horizons (h > 48), and
when the realised price doesn't dip that far, pinball punishes the over-
extrapolation. Per-horizon decomposition:

| Horizon group | LightGBM p10 pinball | ARF lower-band pinball |
|---|---|---|
| h ≤ 24 | 1.83 | 2.14 |
| 24 < h ≤ 48 | 5.85 | 7.03 |
| 48 < h ≤ 72 | 9.37 | 7.53 |
| h > 72 | 11.30 | 7.94 |

LightGBM wins p10 pinball at horizons where it has signal (h ≤ 48). It
loses where its features have thinned out and the model is essentially
guessing (h > 48). On aggregate, the long-horizon losses dominate.

This is a genuine finding about both models that the original criterion
(a) couldn't see and that the literature review's prediction had missed.

## 7. Why the framework works

Two pre-committed criteria failed in a row. The first one — fixed-threshold
MAE-on-slice — was methodologically wrong in a way we didn't appreciate
until the data hit us. The second one — pinball-at-p10 — was based on a
literature recommendation that contained an assumption ("ARF clamp binds")
that didn't hold on our actual data.

Neither failure was a disaster, because the framework caught both before
they damaged a production decision:

- **M4** caught the first one because the criterion was pre-committed in a
  hypothesis log and run mechanically against the trailing window. The
  decision wasn't "look at the numbers and decide" — it was a script that
  printed PROMOTE = True or False. There was no room to fudge "but
  qualitatively LightGBM seems better, let's promote it anyway." The
  framework forced the question: *if our criterion says no, do we trust
  our criterion or our gut?* In this case, the criterion turned out to be
  more right than our gut suggested — the gut wanted to promote LightGBM
  because of its overall MAE win, but the *failure mode* the criterion
  detected (long-horizon low-price weakness) is real and would have shown
  up on the dashboard a week after promotion. Park was correct, even
  though our reason for parking was wrong.

- **EXP-012** caught the second one because before committing the
  literature-recommended replacement criterion to another 14-day shadow
  window, we asked "does this criterion work on data we already have?"
  We had 20 days of paired LightGBM-vs-ARF predictions sitting in a JSON
  file. Re-scoring them with the new metrics cost an hour of work and
  prevented running a second shadow on a criterion whose assumptions
  hadn't been tested.

The pattern is: pre-commit a criterion, test it against falsifiable data,
update the criterion when you have evidence that it's wrong, do not update
it when you don't. Then go around again. Both times, the cycle saved us
from a worse failure.

## 8. What we'd do differently

The lessons translate into a smaller, simpler promotion criterion for the
next shadow.

**Use only what's been validated**. Mean quantile score (or proper CRPS at
a finer quantile grid) was validated on the EXP-012 re-evaluation: it
distinguishes LightGBM from ARF correctly, with statistical significance,
and the conclusion isn't sensitive to slicing tricks. *That's* the
promotion metric. One number, paired DM test, done.

**Demote tail metrics to descriptive**. Pinball-at-p10 and twCRPS are
useful diagnostics for understanding where a model wins and loses, but
they shouldn't be promotion gates. We don't yet understand why ARF's EWM
band wins them. Until we do — and we have a hypothesis or two, but they
need their own experiment — they're characterisation tools, not gates.

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

**Does the picture change at 9–19 quantiles?** Our LightGBM was trained at
only 3 quantiles (p10/p50/p90), which makes any "CRPS from pinball-sum"
estimator biased. The MQS we reported is honestly a 3-point quantile-score
average, not CRPS proper. Retraining at 9 or 19 quantiles is cheap (just
more LGBMRegressor instances) and would tell us whether the 3-quantile
result generalises.

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
retrain at 9 quantiles, use mean quantile score as the primary promotion
criterion, and treat tail metrics as diagnostic rather than gating. If
that experiment validates the overall-skill picture and we can fix the
freshness skew, we'll shadow the new design and decide whether to swap on
the dashboard.

The takeaway isn't a particular model or a particular metric. It's the
discipline of pre-committing a falsifiable criterion, running it
mechanically, and *then doing one more cycle* when the answer is suspicious
— testing the new criterion on existing data before committing it to a new
window. That second cycle saved us from a worse failure. It will probably
save the next one too.

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
