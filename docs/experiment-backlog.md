# Experiment Backlog

Designed-but-not-run experiments, each written as a **pre-commitment under ADR-007**: Position, Alternatives with falsification signals, Method with gates fixed *before* the data is seen, and cost.

Different from its neighbours:

- **`docs/hypothesis-log.md`** — positions actively awaiting evidence, with a `Review by:` date. An entry here is *promoted into* that file when work starts.
- **`experiments/registry.jsonl`** — experiments already run and decided.
- **GitHub issues** — tasks with an owner, ready to execute.

**The promotion rule, which is what makes these pre-commits rather than notes:** when one of these is picked up, copy the entry into `hypothesis-log.md` `## Open` **verbatim**, adding only the run date. If the Method needs changing before running, that is a *new* entry with a new date — never an edit to this one. A Method fixed on 2026-08-29 and executed in October is still fixed-before-data; a Method edited in October after a peek at the data is not. Provisional `EXP-0NN` numbers below are indicative only; take the next free id from the registry at run time.

**Written 2026-08-29**, immediately after EXP-021 (foundation model beats the incumbent by 20.3% QS) and EXP-022 (~12 of those points are pretrained prior, ~8 are context volume; the calibration half is *entirely* prior). Every entry below descends from those two results.

**Standing calendar these must not collide with:** EXP-018a Stage 1 fires ≈2026-09-09 and has priority on the fresh-vintage window (`t0 ≥ 2026-08-25`); EXP-021a Stage 1 runs after it; the t0-guard review is ≈2026-09-11. **Everything in this backlog runs on the existing 260-vintage historical window and consumes none of those fresh vintages.**

**Suggested order** — by decision value per unit cost, and by what blocks what:

| # | Entry | Cost | Runs on | Blocked by |
|---|---|---|---|---|
| 1 | EXP-025 transplanted calibration prior | minutes | CPU, situla | nothing |
| 2 | EXP-023 window-length sweep | ~3h | CPU, situla | nothing |
| 3 | EXP-024 lag richness | ~1h | CPU, situla | nothing |
| 4 | EXP-026 model-size ladder | GPU min + bench | b650-gpu + sadalsuud | nothing |
| 5 | EXP-027 fine-tuning dissociation | GPU hours | b650-gpu | should follow EXP-021a Stage 1 |

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
