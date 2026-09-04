# Experiment Backlog

Designed-but-not-run experiments, each written as a **pre-commitment under ADR-007**: Position, Alternatives with falsification signals, Method with gates fixed *before* the data is seen, and cost.

Different from its neighbours:

- **`docs/hypothesis-log.md`** — positions actively awaiting evidence, with a `Review by:` date. An entry here is *promoted into* that file when work starts.
- **`experiments/registry.jsonl`** — experiments already run and decided.
- **GitHub issues** — tasks with an owner, ready to execute.

**The promotion rule, which is what makes these pre-commits rather than notes:** when one of these is picked up, copy the entry into `hypothesis-log.md` `## Open` **verbatim**, adding only the run date. If the Method needs changing before running, that is a *new* entry with a new date — never an edit to this one. A Method fixed on 2026-08-29 and executed in October is still fixed-before-data; a Method edited in October after a peek at the data is not. Provisional `EXP-0NN` numbers below are indicative only; take the next free id from the registry at run time.

**Amendment 2026-08-30 (workflow only — no Method is touched).** The copy-into-`## Open` step assumed a slow one-at-a-time cadence. Seven entries were run in one night on 2026-08-29/30, and the rule was simply skipped — a real process failure, recorded rather than papered over. The rule is therefore widened: pre-commitment may be evidenced **either** by copying the entry into `hypothesis-log.md` `## Open` before the run, **or** — for batch runs — by leaving the Method here untouched and citing the git revision, with a dated entry in `hypothesis-log.md` `## Resolved` once the arc closes. The second route is the stronger evidence, because `scripts/audit_registry.py` check 5 verifies by sha256 that every Method body is byte-identical to its pre-commit revision and exits non-zero otherwise. What remains absolutely fixed is unchanged: **a Method is never edited after its data is seen.**

**Written 2026-08-29**, immediately after EXP-021 (foundation model beats the incumbent by 20.3% QS) and EXP-022 (~12 of those points are pretrained prior, ~8 are context volume; the calibration half is *entirely* prior). Every entry below descends from those two results.

**Standing calendar these must not collide with** (dates revised 2026-09-04 — **count vintages, do not read dates**; the 2026-08-30..09-04 EDH publish outage cost five vintages and moved every threshold-based trigger by ≥5 days): EXP-018a Stage 1 fires **≈2026-09-14 at the earliest** and has priority on the fresh-vintage window (`t0 ≥ 2026-08-25`); EXP-021a Stage 1 runs after it; EXP-028a ≈09-28; the t0-guard review is ≈2026-09-11 and is *unaffected*, since its criteria concern `calibration_history` gaps having a matching alarm and the outage days are legitimate data for that. These are floors, not estimates — EDH published on 31 of 35 days over 2026-07-25..08-28, so a further miss moves them again. See the warning block at the top of `docs/hypothesis-log.md` `## Open` for the vintage-count one-liner. **Everything in this backlog runs on the existing 260-vintage historical window and consumes none of those fresh vintages.**

**Suggested order** — by decision value per unit cost, and by what blocks what:

| # | Entry | Cost | Runs on | Status |
|---|---|---|---|---|
| 1 | EXP-025 transplanted calibration prior | minutes | CPU | **RUN 2026-08-29 — `rejected`**, but forced a correction to the EXP-021/022 calibration claim |
| 2 | EXP-023 window-length sweep | ~3h | jwasys | **RUN 2026-08-29 — `parked`**, 112d beats 56d by 3.0% QS, all four gates pass |
| 3 | EXP-024 lag richness | ~1h | jwasys | **RUN 2026-08-30 — `rejected`**; matched control shows count *and* kind both matter |
| 4 | EXP-029 FM-residual exogenous pre-screen | minutes | CPU | **RUN 2026-08-29 — `rejected` as a gate**; it would have vetoed EXP-028's true positive |
| 5 | EXP-028 Chronos-2 with covariates | GPU min | jwasys | **RUN 2026-08-29 — `parked`**, +8.3% QS, Augur's first positive exogenous result |
| 6 | EXP-026 model-size ladder | GPU min + bench | jwasys | **RUN 2026-08-29 — `kept`**; latency half completed by proxy 2026-08-30 (EXP-030): base 0.52s, ~115× headroom |
| 7 | EXP-027 fine-tuning dissociation | GPU hours | jwasys | **RUN 2026-08-30 — `rejected`**; both halves degrade, zero-shot is the deployment mode |
| 8 | EXP-034 fragility-conditioned bands | minutes | CPU | **Added 2026-08-31, not run.** Queued *after* EXP-018a Stage 1 — see its own sequencing note |

**Entry 8 was added 2026-08-31 and is not part of the 2026-08-29 batch** — it descends from the EXP-015/016 calibration arc rather than from EXP-021/022, and its Method was fixed on 2026-08-31 before any data was seen. The seven-entry framing below refers to the original batch.

**Run status: ALL SEVEN EXECUTED (2026-08-29 overnight + 2026-08-30).** Originally five of seven executed on `b650-gpu`, with environment parity verified bit-identically against situla before any result was trusted. Results are in `experiments/registry.jsonl` (EXP-023/025/026/028/029) and `docs/model-progress-log.md`. **EXP-024 and EXP-027 have since been run (2026-08-30), both `rejected`.** Every Method below is preserved exactly as written on 2026-08-29, before any data was seen; none was edited after a result landed. The entries below are kept verbatim as written on 2026-08-29 *before* any data was seen; where a Method's cost estimate proved wrong (EXP-023 predicted ~150 usable vintages, actual 95) that is recorded in the registry rather than corrected here, because editing a pre-commit after the fact is exactly what the promotion rule forbids.

**On feeding features to the foundation model** (added 2026-08-29): EXP-021's Chronos-**Bolt** is architecturally univariate — `predict(inputs, prediction_length, limit_prediction_length)`, a 1-D series in — so *no amount of retraining* gives it covariates. **`amazon/chronos-2` (Apache-2.0, already installed) takes `past_covariates` and `future_covariates` at inference time with no retraining**, and Augur's exogenous are the favourable known-future case. EXP-028 is that test; EXP-029 is the near-free screen that should gate it. Note EXP-028 carries a contamination constraint EXP-021 did not: Chronos-2's weights were modified **2026-06-05, inside the evaluation window**, so it can only be scored on `t0 > 2026-06-05`.

---

## EXP-025 — The calibration prior is separable from the point forecast, and can be transplanted onto the incumbent

**Priority: 1.** Cheapest entry here and the most directly actionable against augur#19.

**Question.** EXP-022 showed Chronos's band advantage is *pure pretrained prior*: coverage is flat at 0.811 / 0.804 / 0.813 / 0.823 across 56d / 28d / 14d / 7d contexts, i.e. it does not depend on information at all. If the spread prior is genuinely independent of the point forecast, it should be transplantable — Chronos's *spread* wrapped around the incumbent's *median*. That is the concrete form of the fallback EXP-021a Stage 2 already contemplates ("infeasible on latency → the FM becomes an offline band source rather than the production forecaster").

**Position (provisional).** Applying Chronos's quantile spread around the incumbent's median lifts band coverage from **0.611 to ≥0.76** while costing **<3% quantile score** relative to the full FM — i.e. most of the calibration win survives separation from the point forecast.

**Mechanism.** The incumbent's p10/p90 are estimated from ~1344 rows with pinball loss, split across 3 horizon groups, so each tail quantile is fit on the sparsest part of a small sample — which is why EXP-022 found the pinball gain largest at p10 (26.3%) and smallest at the median (16.3%). Spread is the part a small sample estimates worst and a pretrained prior supplies best. Point forecasting is the part the incumbent is *least* bad at.

**Alternatives (falsification signals).**

1. **Spread is calibrated only to its own median.** The FM's band is conditioned on the FM's point forecast, so transplanting it onto a different median mis-covers asymmetrically. **Signal:** transplanted lower- and upper-side coverage differ by >0.08 from each other, or band coverage lands below 0.70. Then the two halves are not separable and it is all-or-nothing — which strengthens the case for deploying the FM whole.
2. **A weighted median blend beats both.** EXP-021 found a 50/50 blend (MAE 23.69) worse than the FM alone (23.24), but 50/50 was never optimised and the errors do decorrelate (r=0.753). **Signal:** some w ∈ (0,1) beats the FM alone on QS. Then ensembling is back on the table and should be its own entry.
3. **CQR already gets there.** Production wraps a conformal layer around the incumbent that this comparison omits. **Signal:** the incumbent + production CQR reaches coverage comparable to the transplant. Then the pretrained prior adds nothing over the layer we already run, and the calibration half of EXP-021 was an artifact of comparing a pre-conformal band to a post-conformal one. **This arm also discharges EXP-021a's Alternative 4 and must be run even if the others are skipped.**

**Method (pre-committed 2026-08-29).** Pure post-processing of prediction parquets that already exist — no refit, no GPU, no new data. All arms on the same 260 paired vintages, same functions, HAC 71.

```
arm A  incumbent median + FM spread      (p50_lean, p50_lean ± (FM spread))
arm B  FM median + incumbent spread      control; expected to be poor
arm C  weighted median blend w ∈ {0, .25, .5, .75, 1} × {own spread, FM spread}
arm D  incumbent + production CQR        the honest comparator (Alternative 3)
```

Spread is applied as the FM's *asymmetric* half-widths (`p50−p10`, `p90−p50`) so the transplant preserves skew rather than assuming symmetry. Report per-side coverage, band coverage, median width, Winkler, and paired DM on QS against both `lean` and the full FM.

**Gates.** (1) band coverage ≥0.76; (2) per-side coverage within 0.08 of each other (guards Alternative 1); (3) QS no more than 3% worse than the full FM; (4) Winkler ≤ the incumbent's. Passing all four makes arm A a live candidate for augur#19 **independent of whether the FM is ever deployed as the forecaster.**

**What it would change.** A pass gives augur#19 a fix that needs no production torch dependency — the FM runs offline, its spread is cached, and the nightly path stays LightGBM. That is a far smaller operational surface than EXP-021a Stage 3, and it is available much sooner.

---

## EXP-023 — The incumbent's 56-day window is too short, and part of the FM's context advantage is available for free

**Priority: 2.** The lever EXP-020 named and nobody has yet pulled.

**Question.** EXP-020 closed features and left two levers: window length and model class. EXP-021/022 resolved model class and showed context length is worth ~8 percentage points *to the FM* (−12.5% QS at a 7-day context, −20.3% at 56-day). The incumbent's 56-day window is simultaneously its training set and its context, and **it has never been tuned** — it is an artifact of when the pipeline was built.

**Position (provisional).** LightGBM's quantile score improves monotonically with window length out to at least **112 days**, and the optimum is **≥5% better** than 56 days. The gain concentrates in the tail quantiles (p10/p90) rather than the median.

**Mechanism.** Nine models (3 horizon groups × 3 quantiles) are fit on ~1344 rows. Quantile estimation is far more sample-hungry than mean estimation — the p10 head is effectively fit on the sparse lower tail of a small sample. EXP-022's per-quantile decomposition (gain 26.3% at p10 vs 16.3% at p50) says precisely this is where the incumbent is starved. More window = more tail observations, at no architectural cost.

**Alternatives (falsification signals).**

1. **56 days is already near-optimal.** The curve is an inverted U peaking at or near 56. **Signal:** no rung beats 56d by ≥3%. Then the window was well chosen, the FM's context advantage does not transfer to a tabular model, and this lever closes for good — which is itself worth knowing, because it would leave model class as the *only* remaining lever.
2. **Monotone all the way to the data limit.** No optimum inside the ~9 months available. **Signal:** the longest rung is the best rung. Then the window is purely a data-availability artifact; ship the longest feasible and re-test as history accumulates. Note this would also mean the parquet's length is now a binding constraint on model quality — a new and actionable fact.
3. **Window and feature set are not separable.** **Signal:** the optimum differs between `lean` and `full`. Then EXP-018a's conclusion is window-conditional and its Stage 2 needs re-deriving at the new window.
4. **Gains are tail-only.** **Signal:** p10/p90 pinball improves ≥5% while p50 improves <2%. That *confirms* the mechanism and redirects this at augur#19 rather than at point skill — and makes it complementary to EXP-025 rather than redundant.

**Method (pre-committed 2026-08-29).** The EXP-018 harness with `WINDOW_DAYS` promoted from a module constant to a `--window-days` flag (a small patch; the constant is currently read by `run_vintage` in both `exp018_stage0_ablation.py` and `exp020_fundamentals_ablation.py`, so patch it in one place and import).

Rungs: **28 / 56 / 84 / 112 / 168 days**, feature set `lean`, same parquet.

**Critical confound, controlled by construction:** a longer window needs more history *before* the first vintage, so the rungs would otherwise be scored on different vintage sets. Fix the vintage set to those where the **168-day** window is fully available, and run every rung on that identical set. This costs the earliest ~112 days of vintages (leaving ~150 of 260) and is not optional — comparing a 168d rung on 150 vintages against a 56d rung on 260 would confound window length with evaluation period.

**Gates.** Paired DM on per-observation QS vs the 56-day rung, H1 longer-is-better, one-sided p<0.10, HAC 71; treatment QS ≥3% better; per-side coverage not more than 0.02 worse; Winkler ≤1.05×. Report the full curve and the per-quantile pinball decomposition regardless of gate outcome — the shape of the curve is the deliverable even if no rung passes.

**Cost.** CPU on situla, ~35 min per rung at 10 workers, ~3h total. No GPU. Consumes no fresh vintages.

---

## EXP-024 — The bottleneck is *derived* features, not feature count: more raw lags should help where rolling stats hurt

**Priority: 3.** Sharpens EXP-018's conclusion into something more precise and more useful.

**Question.** There is a real tension in the record. EXP-018 found that *removing* features improves skill (lean 15 beats full 24 by 7-8% QS, replicated on three windows). EXP-022 found that the FM's edge is partly **information the incumbent never receives** — it predicts all 72 horizons from a single ~14-number feature row while the FM reads 1343 raw points. Both cannot be naively true: either more input helps or it hurts.

**Position (provisional).** The resolution is that **kind matters, not count**. Adding raw price lags out to 168h (from the current 8) recovers **≥4 of the ~8 percentage points** EXP-022 attributed to context volume, *without* changing model class — while adding the same number of *derived* columns would not.

**Mechanism.** EXP-019 already established the distinction and this entry only extends it: raw price lags are absolute levels and are **harmless**, whereas smoothed level columns (`price_rolling_mean_168h`) **cost significantly**, read as redundant smoothed-level columns diluting the split search. EXP-020 then generalised the harm to exogenous level columns (TTF gas, +3.2% QS). Nothing in that record predicts harm from *raw, non-redundant* lags — they are the one input type that has never been shown to hurt. If split-search dilution is about redundancy rather than dimensionality, raw lags are safe and informative.

**Alternatives (falsification signals).**

1. **Dilution is about dimensionality per se.** **Signal:** the richer lag set degrades QS like the rolling stats did (p>0.5 in the wrong direction). Then "fewer features" is about count after all, the bottleneck is not closable inside LightGBM, and model class is confirmed as the *only* remaining lever — a clean and valuable negative.
2. **Gains saturate at 24h.** **Signal:** lags 1..24 capture essentially all of the gain; extending to 168h adds <1%. Then diurnal structure is the whole story and weekly structure is already carried by the calendar features.
3. **Tail-only gains.** **Signal:** p10/p90 improve while p50 does not. Same reading as EXP-023 Alternative 4; the two entries then jointly point at sample starvation in the quantile heads.
4. **Short-horizon only.** **Signal:** gains confined to `h1_6`/`h7_24`, nothing at `h25_72`. Then lag information decays as expected and the FM's *long*-horizon edge (−22.8% at h65-72) is confirmed as prior rather than context — which would make EXP-023 and this entry both insufficient, and strengthen the FM case.

**Method (pre-committed 2026-08-29).** EXP-018 harness, extended to *add* lag columns rather than only drop them (the same extension EXP-020 made for added columns; reuse `VARIANT_SPECS`). Arms:

```
lean                         current 8 lags               (base)
lean_lag24     lean + price lags 2..24h
lean_lag168    lean + price lags 2..24h, 48, 72, 96, 120, 144, 168h
lean_lag168_derived   CONTROL: lean + an equal COUNT of rolling/derived columns
```

The fourth arm is the load-bearing one and must not be skipped: it separates "more input helps" from "more *raw* input helps" by matching dimensionality exactly. Without it a positive result is uninterpretable. Same 260 vintages, fixed row set across arms, no CQR, HAC 71.

**Gates.** Primary `lean_lag168` vs `lean`: DM p<0.10, QS ≥3% better, per-side coverage not >0.02 worse, Winkler ≤1.05×. **Interpretive requirement:** the control arm must *not* pass. If both the raw-lag and the derived-column arms pass, the mechanism claim is wrong even though the Position's number is right, and this must be recorded as such rather than reported as a win.

**Cost.** CPU on situla, ~1h. Consumes no fresh vintages.

---

## EXP-026 — The advantage is a cheap prior: a small Chronos keeps most of it and makes CPU deployment trivial

**Priority: 4.** Resolves EXP-021's Alternative 2, which was left open because it was conditioned on the FM *losing*, and it de-risks EXP-021a's Stage 2 feasibility gate directly.

**Question.** EXP-021a Stage 2 gates deployment on **median CPU latency ≤60s** on sadalsuud, which has no GPU. `chronos-bolt-base` is 205M parameters. If a much smaller model retains the advantage, the feasibility gate becomes trivial and the "a 205M-parameter model in our nightly path" objection largely dissolves.

**Position (provisional).** `chronos-bolt-small` retains **≥80% of base's QS advantage** over `lean` (i.e. ≥16.2 of the 20.3 points) and completes one 1343-point / 72h forecast on sadalsuud CPU in **≤10s** median.

**Mechanism.** EXP-022 showed the advantage is a prior over shape and spread, largely insensitive to context length. Priors of that kind — daily and weekly seasonality, plausible h-step spread — are low-complexity relative to 205M parameters. There is no obvious reason they need the largest checkpoint.

**Alternatives (falsification signals).**

1. **Skill scales strongly with size.** **Signal:** a monotone ladder with `small` retaining <60%. Then `base` is a floor rather than a ceiling, larger models (or Chronos-2) are worth testing, and CPU deployment probably fails — pushing EXP-021a toward the offline-band-source fallback, i.e. toward EXP-025.
2. **`tiny` ≈ `base`.** **Signal:** `tiny` retains ≥90%. Then the whole advantage is a cheap prior, deployment is easy, and it becomes worth asking what the *minimum* model that captures it is — a genuinely interesting question about how much of EPF quantile forecasting is just seasonality-plus-spread.
3. **Skill and calibration scale differently.** **Signal:** `tiny` holds coverage (~0.81) but loses materially on MAE. Then deploy the small model as a *band source* and keep LightGBM's median — which is exactly EXP-025's arm A, with a cheaper spread source.

**Method (pre-committed 2026-08-29).** Two parts, both required.

*(a) Skill ladder.* `chronos-bolt-tiny`, `-mini`, `-small`, `-base` on the **identical matched-information contexts** already built at `ml/shadow/exp021_foundation_aligned/` — no regeneration, so the only variable is the checkpoint. Same scoring, same gates, DM against `lean` and against `base`.

*(b) Latency benchmark on sadalsuud, not on a GPU box.* For each checkpoint: 10 runs of a single 1343-point / 72h forecast, CPU only, report median and max wall-clock, plus resident memory and venv size delta. Latency measured on the machine that would actually run it, per the Stage 2 gate.

**Gates.** Skill: retention ≥80% of base's advantage with DM p<0.10 vs `lean`. Feasibility: median CPU latency ≤10s, max ≤30s. A checkpoint passing both is the Stage 2 candidate and should be named in EXP-021a before its Stage 2 runs.

---

## EXP-027 — Fine-tuning will improve point skill and *destroy* the calibration prior

**Priority: 5.** The most interesting prediction here because it is a **dissociation**, not a direction — and it is falsifiable in a way "fine-tuning helps" is not.

**Question.** EXP-021's Alternative 4 said a zero-shot result within ~10% would make fine-tuning worth trying. The result was better than that, so fine-tuning is the natural next move. But EXP-022 established that the calibration advantage is a **broad pretrained prior**, context-independent and worth ~0.20 of band coverage — which is exactly the kind of thing that fine-tuning on a single narrow series destroys.

**Position (provisional).** Fine-tuning `chronos-bolt-base` on NL day-ahead history improves MAE by **≥5%** over zero-shot **and simultaneously degrades raw band coverage by ≥0.05** (0.811 → ≤0.76). Point skill up, calibration down.

**Mechanism.** Fine-tuning on one series for many steps overwrites a spread prior learned across a large heterogeneous corpus with one estimated from ~7900 NL points. That is the same sample-starvation that gives the incumbent 0.611 coverage — so a heavily fine-tuned FM should drift *toward the incumbent's failure mode*, not away from it. If true, this is the sharpest available evidence for what the pretrained corpus is actually buying.

**Alternatives (falsification signals).**

1. **Both improve.** **Signal:** MAE better and coverage holds ≥0.79. Then the prior is robust to fine-tuning, and a fine-tuned candidate should go to EXP-021a's shadow stage instead of the zero-shot one.
2. **Both degrade.** **Signal:** MAE worse too. Then ~7900 points is simply too little to fine-tune 205M parameters and zero-shot is the right deployment mode — the cheapest possible answer, and the one the single-asset caveat predicts.
3. **Fine-tuning re-introduces window sensitivity.** **Signal:** gains concentrated in months resembling the fine-tuning window and losses in the level-shift months (Jul/Aug 2026). Then fine-tuning has turned the FM into the incumbent — it would have *acquired* the very regime-fragility that EXP-018 spent three experiments diagnosing. This is the most informative outcome available and should be checked explicitly via the monthly panel even if the headline gates pass.

**Method (pre-committed 2026-08-29).** The leakage discipline here is stricter than anywhere else in this backlog, because fine-tuning makes contamination trivially easy to create by accident.

- **Temporal split, no exceptions.** Fine-tune only on data with `timestamp ≤ 2026-02-28`. Evaluate **only** on vintages with `t0 ≥ 2026-03-01`. The 260-vintage set used by EXP-021/022 **must not** be reused, since it spans the fine-tuning period; the zero-shot comparator must be re-scored on the same restricted vintage subset so both arms see an identical evaluation set.
- **Report the training curve, not just the endpoint.** Evaluate at several checkpoints (e.g. 0/250/1000/4000 steps). The Position predicts MAE and coverage move in *opposite* directions as steps increase; a single endpoint cannot show that, and the trajectory is the actual evidence.
- Same scoring functions, HAC 71, matched-information contexts, no CQR.

**Gates.** The dissociation is the claim, so it is gated as a conjunction: MAE improvement ≥5% **and** coverage degradation ≥0.05 confirms the Position. Either one alone refutes it and selects among the alternatives above.

**Blocked by.** Should follow EXP-021a Stage 1 — do not spend GPU hours on fine-tuning before the zero-shot advantage has been confirmed on fresh vintages. Not technically blocked, but sequencing it earlier would be investing in a refinement of an unconfirmed result.

---

## EXP-028 — A covariate-capable foundation model can use the exogenous data that LightGBM demonstrably cannot

**Priority: inserted at 4** (before EXP-026). Added 2026-08-29 in response to a direct question: none of EXP-023..027 feeds exogenous data to the foundation model, and that was a real gap in the backlog.

**Why this is not re-opening a refuted bet.** EXP-020 tested exogenous features and refuted them — residual load inert (p=0.648 main, p=0.899 control), plain load inert (p=0.851), TTF gas *degrading* (+3.2% QS). But it refuted them **for one model class**, and the mechanism it landed on is explicitly LightGBM-specific: *"redundant smoothed-level columns diluting the split search"*, generalised to *"this model class rejects added level columns."* A cross-attention transformer has no split search to dilute. So the mechanism that killed exogenous for LightGBM does not transfer, and the question genuinely re-opens with model class. This is the same "narrows rather than loosens" move EXP-020 itself made after the [2026-08-20] refutation, and it carries the same gates.

**The sharper motivation.** EXP-021's foundation model wins by 20.3% **while being strictly information-poorer than the model it beats.** The incumbent receives wind speed, solar GHI and load forecast; Chronos-Bolt receives nothing but the price series. There is an entire information channel that the winning model currently cannot see, and EXP-022 localised its advantage to a *distributional prior* — spread and shape — which is precisely the part of the problem that exogenous data does *not* address. The two could be additive.

**Position (provisional).** `amazon/chronos-2` with the exogenous columns supplied as covariates improves quantile score by **≥5%** over the same model run univariate, on the same vintages — and the gain sits in the **median** (pinball@p50 ≥5% better) rather than in the tails, because covariates carry conditional-mean information while the pretrained prior already supplies the spread.

**Do we need to retrain? No — and for Bolt it is not a training question at all.**

- **Chronos-Bolt (EXP-021's model) cannot accept features under any amount of training.** Its `predict` signature is `(inputs, prediction_length, limit_prediction_length)` — a 1-D series in, quantiles out. There is no covariate slot; adding one means changing architecture, not weights.
- **Chronos-2 accepts covariates at inference time, zero retraining.** Its `predict` takes a list of dicts with `target` (required), `past_covariates` (past-only, or past values of known-future covariates) and `future_covariates` (known ahead, length = `prediction_length`; keys must be a subset of `past_covariates`).
- **Augur's exogenous are the favourable case:** `wind_speed_80m`, `solar_ghi`, `temperature`, `load_forecast`, `wind_gen_forecast_mw`, `solar_gen_forecast_mw` and `is_holiday_nl` are all *forecasts or calendar*, i.e. genuinely **known-future** over the 72h horizon — they go in both dicts. `gas_ttf_eur_mwh` is a daily realised scalar with no forward curve, so it is **past-only**.
- **The columns already exist.** All nine are in `ml/data/training_history_fundamentals.parquet` from EXP-020's Step-0 plumbing, which was kept precisely because it was additive and free. This entry is that decision paying off.

**Alternatives (falsification signals).**

1. **Exogenous is inert here too.** **Signal:** covariate arm lands within ±1% QS of the univariate arm, matching EXP-020's result for LightGBM. Then "exogenous does not help NL day-ahead at this horizon" is established across *two* model classes with different mechanisms, which is a far stronger claim than EXP-020 alone supports, and the feature lever closes permanently rather than provisionally.
2. **Gas degrades here too.** **Signal:** dropping the past-only gas covariate recovers the loss. Then the level-column harm is not a split-search artifact after all but something more general about slow-moving level regressors — which would *contradict* EXP-019/020's stated mechanism and is worth knowing.
3. **Chronos-2 univariate is already worse than Bolt.** The comparison assumes Chronos-2 is a fair vehicle. **Signal:** Chronos-2 run univariate underperforms Bolt on the same vintages. Then a covariate gain may only be recovering Chronos-2's own deficit; the honest baseline becomes Chronos-2-univariate, and any claim against Bolt must be made separately.
4. **The gain is in the tails, not the median.** **Signal:** pinball@p50 improves <2% while p10/p90 improve. That refutes the stated mechanism even if the headline number passes, and suggests covariates are acting as a volatility proxy rather than a mean signal. Record as such rather than as a win.

**Method (pre-committed 2026-08-29, before any Chronos-2 weight is downloaded).**

**Contamination control, and it is stricter than EXP-021's.** Chronos-Bolt's weights were frozen **2025-11-21**, before the evaluation window opens, which is why EXP-021 could call contamination impossible. **`amazon/chronos-2` was last modified 2026-06-05 — inside the window.** So the Bolt guarantee does not transfer. Every Chronos-2 arm is therefore evaluated **only on vintages with `t0 > 2026-06-05`** (82 days available, 2026-06-05..2026-08-25), and the Bolt and LightGBM comparators are **re-scored on that same restricted subset** so all arms share an evaluation period. Results on the full 260-vintage window may be computed for curiosity but must not be reported as evidence, and must be labelled contaminated in the registry.

Arms, all on the restricted subset, same 56-day context, same h+1..h+72, same scoring functions, HAC 71, no CQR:

```
chronos2_univariate            target only                          (base)
chronos2_known_future          target + the 7 known-future covariates
chronos2_all                   + gas as past_covariates only
chronos2_gasdrop               = chronos2_all minus gas   (Alternative 2)
bolt_base_univariate           EXP-021's model, re-scored here      (reference)
lean_lgbm / full_lgbm          re-scored here                       (reference)
```

Covariates are supplied at their **parquet values**, which for the forecast columns are the vintage-overwritten values the EXP-018 harness already uses — carrying the same documented backtest optimism (`consolidate.py` overwrites with later vintages, ratio 1.84). That bias favours *this* entry, so a null result is strong and a positive result must be read as an upper bound. State this in the resolution regardless of outcome.

**Gates.** Primary `chronos2_known_future` vs `chronos2_univariate`: (1) paired DM on QS, one-sided p<0.10; (2) QS ≥5% better; (3) per-side coverage not >0.02 worse; (4) Winkler ≤1.05×. **Mechanism requirement:** pinball@p50 must improve ≥5%, or the Position's mechanism is refuted even if the gates pass (Alternative 4).

**Cost.** GPU minutes on `b650-gpu`; `chronos-forecasting` 2.3.1 is already installed and exposes `Chronos2Pipeline`. No training, no new dependency. The restricted subset (~82 vintages) is the binding constraint on power, not compute — note that a 5% effect on 82 vintages is a weaker test than EXP-021's 260, and do not over-read a marginal p-value.

---

## EXP-029 — Cheap pre-screen: are the foundation model's residuals correlated with the exogenous at all?

**Priority: run immediately before EXP-028.** Minutes of CPU, and it can save the GPU work entirely.

**Question.** EXP-028 is worth running only if the exogenous carry information the FM's residuals do not already contain. That is directly measurable on prediction files that already exist, with no new model of any kind.

**Position (provisional).** The FM's residuals `(y − p50_FM)` carry **little exploitable exogenous signal**: a gradient-boosted regression of residual on the nine exogenous columns plus horizon achieves out-of-sample R² **< 0.05**, and correcting the median by its prediction improves MAE by **<2%**.

**Mechanism.** EXP-020 found exogenous inert for a model that *had* price lags and calendar; EXP-022 found the FM's advantage is a distributional prior rather than a conditional-mean gain. If price history plus calendar already spans what wind/solar/load contribute at this horizon — which is EXP-020's standing conclusion — then the FM's residuals should be close to exogenous-orthogonal, and EXP-028 should be expected to return Alternative 1.

Stating it this way makes the pre-screen honest: **this entry expects EXP-028 to fail**, and a surprise here is the thing that would justify the GPU work.

**Alternatives (falsification signals).**

1. **Real exploitable signal.** **Signal:** R² ≥0.05, or a residual correction that improves MAE ≥2%. Then EXP-028 is well motivated and should run at higher priority — and a residual-regression hybrid is itself a candidate needing no covariate-capable model at all.
2. **Signal exists but only linearly / only in one column.** **Signal:** most of the R² traces to a single covariate. Then the finding is about that column, not about "exogenous", and should be tested as such.
3. **Screen is too weak.** A tree on residuals could miss interactions the covariate model would find. **Signal:** near-zero R² *and* EXP-028 later shows a gain. Recorded here in advance so a negative screen is treated as *evidence against* rather than as *proof of absence* — a null here lowers EXP-028's priority, it does not cancel it.

**Method (pre-committed 2026-08-29).** No new models, no GPU. Take `ml/shadow/exp021_foundation_aligned/fm_predictions.parquet`, join the nine parquet columns on `timestamp_utc`, and:

1. Report Pearson and Spearman correlation of the signed residual against each covariate, pooled and by horizon group.
2. Fit LightGBM on `(y − p50_FM)` from the nine covariates plus `horizon_h`, using a **temporal** split (fit on the first 70% of vintages, score the last 30% — never random, per the project's hard constraint), and report out-of-sample R².
3. Apply the fitted correction to the FM median on the held-out vintages and report ΔMAE and ΔQS against the uncorrected FM.

**Gates.** Advisory rather than decisive: R² ≥0.05 **or** ΔMAE ≥2% promotes EXP-028 ahead of EXP-026; below both, EXP-028 drops to lowest priority but stays open on Alternative 3.

## EXP-034 — A *leading* fragility indicator breaks the ceiling that a lagging one cannot

**Written 2026-08-31. Not part of the 2026-08-29 batch.** Descends from EXP-015/016, not from EXP-021/022.

**Sequencing — read before running.** Queue **after EXP-018a Stage 1**. The replay consumes `calibration_history` raws produced by the *production* model, so if Stage 1 changes `FEATURE_COLUMNS` the historical raws come from a superseded model. A result obtained before Stage 1 is a mechanism test, not a deployable one, and would need re-confirming on whichever base Stage 1 leaves standing. Runs offline on the existing window and consumes **no fresh vintages**.

**Question.** EXP-016 tested per-side ACI and parked it: it repairs post-shift days but hits a **γ-independent ~0.85 ceiling caused by first-shift-day misses**, and trips the Winkler guardrail. Is that ceiling a property of *adaptive conformal* specifically, or of *lagging* signals in general?

**Mechanism, which is the whole reason this entry exists.** ACI adapts using past coverage errors. It is therefore structurally incapable of reacting on the day a shift begins — no value of γ changes that, which is exactly what "γ-independent" reports. Every calibration attempt so far (EXP-015 static per-side, EXP-016 ACI) reads only the model's own realised misses. If a signal available **at t0, before the price moves** carries information about conditional *variance*, it can widen on day zero rather than day one, and that is the only part of the ceiling that has never been tested.

Residual load — `load_forecast − wind_gen_forecast_mw − solar_gen_forecast_mw` — is the standard scarcity proxy in power markets, all three columns are *forecasts* already in the parquet, and its price response is famously **convex**: it barely moves the mean until it moves it enormously.

**This is not a re-run of EXP-020, and the distinction is the load-bearing claim.** EXP-020 refuted these columns **as level features for the conditional mean**, four times over with EXP-019/024/029. It says nothing about them **as conditioning variables for the conditional variance**. A variable that is inert in the first moment and informative in the tail is precisely the shape the standing "levels hurt" conclusion does not cover — and if that turns out to be wishful, this experiment is how we find out cheaply.

**Position (provisional).** Conditioning the CQR quantile on a residual-load scarcity z-score lifts **upper-side coverage on shift-onset days from ~0.77 to ≥0.85**, with pooled Winkler **not more than 5% worse** than production, **and** the gain is not reproducible by a uniform widening of the same average band width.

**Definitions, fixed here before any data is seen** (this is the part a post-hoc version would tune):

- **Scarcity score** at each t0 and horizon: z-score of residual load against the trailing **56-day** distribution *at the same hour-of-day*, computed from forecast columns only.
- **Shift-onset day**: a day whose realised daily-mean price differs from the trailing 7-day mean by more than **1.5σ** of the trailing 28-day daily-mean distribution. First qualifying day of a run only — subsequent days are "post-shift", which EXP-016 already handles.
- **Conditioning rule**: a single scalar multiplier on the per-side CQR quantile, monotone in the scarcity z, with **one** free parameter fitted on the first 70% of vintages and evaluated on the last 30% — temporal split, never random.

**Alternatives (falsification signals).**

1. **Inert in the variance too.** EXP-020's conclusion extends to the second moment. **Signal:** onset-day upper coverage improves <0.03, or improves but is matched by the uniform-width control. Then the exogenous columns are closed for calibration as well as for the mean, which is a genuinely useful negative — it would make the fifth independent confirmation and should be recorded as such.
2. **It works, but only as a price proxy.** Residual load may be standing in for price level or recent volatility, adding nothing over a signal derived from price alone. **Signal:** an EWMA-of-price-volatility baseline captures the same onset-day gain. Then the finding is *"conditional variance modelling helps"*, not *"exogenous helps"* — still worth having, but a different and weaker claim, and it should be re-titled rather than reported as an exogenous win.
3. **Underpowered.** **Signal:** fewer than **20** shift-onset days in the window. Then report as underpowered and say so; do not read a null from it. Pre-committed because onset days are rare by construction and the temptation to relax the 1.5σ definition after counting them is exactly what this section exists to prevent.

**Method (pre-committed 2026-08-31).** Offline replay, no new model, no GPU. Extend the harness in `scripts/exp015_replay_cqr.py` / `exp016_replay_aci.py`, which already read `p10_raw/p50_raw/p90_raw` from `shadow_state.json:calibration_history`.

1. Build the scarcity z-series from the parquet forecast columns; join to `calibration_history` on `timestamp_utc`.
2. Label shift-onset days by the definition above; report the count **before** looking at any coverage number.
3. Score **three** arms on the held-out 30%:
   - **A — production CQR** (baseline, as shipped).
   - **B — uniform widening**, scaled so its *mean band width equals arm C's*. This is the control, and it is not optional: without it the experiment measures "wider bands cover more", which is the EXP-024 matched-count lesson applied to width instead of feature count.
   - **C — fragility-conditioned CQR** per the conditioning rule.
4. Report for each arm: upper / lower / band coverage, pooled and restricted to onset days; Winkler; mean width; and the per-side breakdown, since augur#19's deficit has moved sides once already.

**Gates.** PROMOTE to a live shadow trial only if **all three** hold:
- onset-day upper-side coverage ≥ **0.85** in arm C;
- pooled Winkler in arm C not more than **5%** worse than arm A;
- arm B does **not** reach the first bar — i.e. the gain comes from *conditioning*, not from width.

Any one failing parks it with the reason recorded. Arm B reaching the bar is a `rejected`, not a `parked`.

**Cost.** Minutes of CPU on the existing window. No GPU, no fresh vintages, no production path touched.

**Standing caution.** EXP-029 is the cautionary twin: a cheap, well-motivated pre-screen that was rejected as a gate because it would have vetoed a true positive. Fragility indicators are the same shape — trivial to construct, hard to validate. The matched-width control in arm B is the specific defence against believing this one too early.
