# Hypothesis Log

Provisional design decisions under observation. Each entry is a position we took where the evidence to confirm or revise it lives in the future. Different from:

- **`docs/TODO`** / GitHub issues — tasks with an owner, ready to execute
- **`docs/experiment-backlog.md`** — experiments *designed but not started*, each already pre-committed under ADR-007. Promoted into this file verbatim (adding only the run date) when work begins; if the Method needs changing first, that is a new entry with a new date, never an edit.
- **ADRs** — decisions accepted, with rationale frozen
- **`memory/gotcha-log.md`** — problems encountered & solved

Lifecycle: **open** → dormant → revisit (with evidence) → resolved (close or promote to ADR).

**How to use this file:**

- Add an entry when you take a provisional position you want to revisit later.
- Each entry has a `Review by:` date and a `Revisit trigger:` so Claude can surface due items at session start and in `/curate`.
- The **Method** field pins the falsification criterion *before* the data lands — that's the whole point. Don't loosen Method when the answer arrives; if you want to redefine the bet, open a new entry.
- When an entry is resolved (ratified, revised, or no longer relevant), move it to the `## Resolved` section at the bottom with a one-line outcome.
- Keep entries tight. If an entry grows a plan, it becomes a TODO; if it grows a rationale, it becomes an ADR.

---

## Open

> **Counted 2026-10-16 — use this, not the "≈date" in any entry below; those dates are all stale.**
> Source: the committed `ml/models/shadow/shadow_state.json` / `ml/shadow/eval_log.jsonl` at `18581cd` (daily run 2026-10-15).
> 30 vintages with `t0 ≥ 2026-08-26` (last `eval_day` 2026-10-15); 34 eval rows carry `lightgbm_skill_vs_naive`,
> ~33 of them with ≥12 naive-paired hours. **Every gate below is met except EXP-023a Stage B (30 of 45)**, and nothing
> has been run against them since 2026-09-14. Run order, unchanged from the pre-commitments:
>
> | Entry | Trigger | Status 2026-10-16 |
> |---|---|---|
> | [2026-08-25] EXP-018a Stage 1 | ≥14 vintages | **PARKED 2026-10-28**, see [2026-10-28] park entry |
> | [2026-08-29] EXP-021a Stage 1 | ≥14 vintages | **TRIGGERED**, first claim since 2026-10-28 (gate vs `lean`, per its own Method) |
> | [2026-09-06] augur#29 verdict | ≥21 qualifying rows | **TRIGGERED** (~33) — consumes no vintages; Review by 10-20 |
> | [2026-08-30] EXP-028a | ≥28 vintages | **TRIGGERED** (30) — Review by 10-31. Lagged-arm source found 10-29: the EDH publish archive (see the entry's notes) |
> | [2026-08-30] EXP-023a Stage B | ≥45 vintages | **PARKED 2026-10-28**, see [2026-10-28] park entry |
> | [2026-10-28] EXP-038 FM early read | runs 2026-10-28 | **RESOLVED** (kept; opened Stage 2 → EXP-039 FEASIBLE), moved to the archive |
> | [2026-10-28] product criterion | FM Stage 3 shadow reaches 14 vintages | pre-committed; gates the swap beside ADR-007 |
> | [2026-08-31] feed divergence | two normal-hour publishes | **DUE** — Review by 09-30 passed |
> | [2026-09-10] ARF not a backup | ARF failure / date | **DUE** — Review by 10-01 passed |
> | [2026-05-29] publishable | engineer's call | not due (12-31) |
>
> Vintage holes: count them from `calibration_history` at run time; do not trust a list here. Holes since 2026-09-14 have not been enumerated.

### [2026-10-28] Product criterion: a forecaster earns the dashboard only by ranking cheap hours at least as well as the profile floor, in every horizon group

**Position (provisional):** the dashboard's job is choosing *when* to run a heat pump or charge a car, so the metric that decides what it serves is cheap-hour cost regret, not MAE. EXP-037 showed the two disagree: production LightGBM improves MAE by flattening (forecast amplitude 14–15 vs realised 42 EUR/MWh beyond 24h) and so ranks cheap hours *worse* than the carry (k6 regret 9.2 / 10.7 at h25_48 / h49_72 vs the carry's 5.3 / 4.8). EXP-036 pre-committed that a scalar floor is the wrong shape, so the bar is per horizon group.

**Why now, and why this is a new entry, not an edit:** no fresh-vintage regret has been computed for any arm at the time of writing (the daily eval log carries MAE only). ADR-007's skill gate and EXP-021a's four Stage 1 gates are untouched; this adds a second, product-level condition to the *swap*, written before its data exists.

**Method (pre-committed 2026-10-28):** at the end of any live shadow (first use: the EXP-021a Stage 3 Chronos shadow, 14 evaluable vintages), score each 24-slot block (h1_24, h25_48, h49_72) per vintage with `score_block` from `scripts/exp037_rank_metric.py` (k = 3 and 6, stable-sort ties, partial blocks dropped, never padded). The candidate passes iff, **in each of the three blocks**, its mean **k6** regret is at or below the EXP-036 profile floor's (`naive_profile_prediction`, 5 matching day types) on the same blocks. k3 and Spearman are reported, never gated. A paired DM (HAC lags 3, one-sided) is reported per block as the strength of evidence; it does not gate, because 14 blocks per group cannot carry a p < 0.10 test reliably, and a gate that cannot pass at the available n is an abstention, not a criterion.

**Alternatives (failure-mode signals):**
1. **Regret is too noisy at n = 14 to rank anything.** **Signal:** the per-block regret standard error exceeds the candidate-floor difference in two or more groups. Then extend the shadow to 28 vintages before deciding; do not loosen the bar.
2. **The floor wins at h1_24 only, where both are already good.** **Signal:** the candidate fails h1_24 by under 0.5 EUR/MWh and wins the other two by more than 2. That is a real failure under this Method; a hybrid (floor for h1_24) is a new entry, not a reading of this one.

**Review by:** when the first Stage 3 shadow reaches 14 vintages.

**Related evidence (added 2026-10-29, outside the Method, which is unchanged):** Lipiecki & Weron (2026, arXiv:2609.00089) reach the same split on battery arbitrage. TabPFN has the best CRPS in every market, yet DDNN-JSU earns the most under the risk-averse strategies. Their caveat applies here too: trading profit, like k6 regret, is **not a proper scoring rule**. That supports this entry's shape, regret as an *added* swap condition beside ADR-007's proper-score gate, never a replacement for it. Their gaps between top models are mostly ~1%, and they warn against reading the order of close models, which matches Alternative 1's noise concern.

### [2026-10-28] Park EXP-018a Stage 1 and EXP-023a Stage B: LightGBM tuning cannot move the decision that is open

**Position:** both entries tune the incumbent (feature set, window length) while every standing finding says the bottleneck is the model class (`memory/model-class-findings.md`: feature engineering closed at 56 days; the FM's context advantage is not recoverable inside LightGBM). Their Methods stand as written and are not edited; they are parked, not refuted. EXP-018a's only downstream role was choosing EXP-021a's incumbent arm, and EXP-021a's own Method already says that, with 018a unconcluded, *"the primary gate stays against `lean`, the harder bar"*.

**Revisit trigger:** EXP-021a fails Stage 1 or Stage 2 (then LightGBM stays in production and tuning it matters again), or the engineer asks.

### [2026-09-10] ARF is not a backup: it and production die through the same door, and it dies harder

**Position (provisional):** keeping ARF running as a "backup signal" (ADR-006, 2026-05-29) buys less resilience than the label implies, because the two models share their single most likely failure cause — stale upstream data — and ARF degrades *worse* than the thing it is backing up.

**Evidence (2026-09-10, the EDH stall):** LightGBM is **data-anchored**. `predict_72h` builds features for one row at `t0` and gets all 72 horizons from horizon-as-feature stacking, so it never needs forward exogenous; when the parquet is stale it re-emits from the old anchor. Verified byte-identical against the previous run — `forecast`, `forecast_upper`, `forecast_lower` all `identical=True`, only `last_updated` moved. ARF is **wall-clock anchored**: `generate_forecast` loops from `datetime.now()`, and `OnlineFeatureBuilder.build` returns `None` unless it has both a 1h and 24h price lag (`online_features.py:112`). With prices ending 09-09T20:00 and the run at 09-10T03:01 the 1h lag is missing at the very first hour; nothing is pushed back into the buffer, so every subsequent hour fails the same way. Result: `forecast: {}`, 0 of 72 hours.

So on the failure mode that has cost this pipeline the most vintages, production degrades to *stale* and the backup degrades to *nothing*. This was flagged independently by the energyDataHub session on the same day, which is weak corroboration but from a different vantage point.

**Alternatives (falsification signals):**

1. **The backup was never for this failure mode.** ARF is kept as a *modelling* fallback — a second opinion if LightGBM's quality regresses — not an availability fallback, and it is doing that job (it still feeds the Model-tab metrics). **Signal:** ADR-006 or the retrospective states an availability rationale nowhere. Then the label "backup signal" is imprecise but nothing is broken, and the fix is wording plus the wall-clock anchor being an ordinary bug.
2. **The wall-clock anchor is trivially fixable.** **Signal:** anchoring ARF on `parquet.index.max()` like the shadow path costs less than an hour and makes it degrade to stale rather than empty. Then this is a small bug fix, not an architecture question, and it should just be done.
3. **The right answer is to stop running it.** ARF was retired as a model 2026-04-28 and kept running for one rolling-window cycle; that cycle is long over. **Signal:** the Model-tab widgets are its only consumer and can be sourced from `eval_log.jsonl` instead. Then the honest move is retirement, not repair — and the daily job loses a step.

**Method / revisit trigger:** decide between Alternative 2 and 3 before any work — they point opposite ways and the cost difference is an hour versus a deletion. Read `docs/river-arf-retrospective.md` and ADR-006 for the stated rationale first (Alternative 1 is checkable from documents alone and may close this outright).

**Review by:** 2026-10-01, or whenever the ARF step next fails in a way that costs attention. Not urgent: it is non-fatal in `daily_update.sh` (`set +e` since 2026-07-03) and cannot abort the production path.

---

### [2026-09-06] The production model has no demonstrated skill over a seasonal-naive baseline, and the eval harness could not have told us

**Position (provisional):** LightGBM-Quantile's point forecast does not beat "same clock hour, last day available at t0" — not at any horizon, and not on average over the record. The 20-odd experiments since EXP-018 have been optimising deltas against a reference that itself loses to one line of pandas. Until a skill-vs-naive floor is in the log, no model comparison here is interpretable.

**Why this went unseen for four months:** `eval_log.jsonl` scores LightGBM against ARF, `docs/experiment-results.md` scores variants against production, and `metrics.py`'s Diebold-Mariano compares two candidates. Every instrument in the project is *relative*. Both models being worse than naive is invisible to all of them — it reads as a healthy log with a clear winner. ADR-007 pre-commits how we decide *what to change*; it never pinned what "good" is measured against.

**Evidence (measured 2026-09-06, before this entry was written):**

- Horizon-matched, model `p50` vs naive on identical timestamps from `calibration_history` (24 eval days, `t0 ∈ [2026-07-30, 2026-08-24]` — the full extent of the paired data):

  | horizon | n | LGBM p50 MAE | naive MAE | winner |
  |---|---|---|---|---|
  | 1–24h | 576 | 26.92 | **23.34** | naive |
  | 25–48h | 576 | 33.87 | **28.94** | naive |
  | 49–72h | 552 | 36.92 | **32.71** | naive |
  | all | 1704 | 32.51 | **28.27** | naive |

- Longer but mixed-horizon (96 eval days, 2026-05-08..08-24, `eval_log` MAE vs daily naive-24h): LGBM 27.11 vs naive 26.66, **model ahead on 42 of 96 days (44%)**.
- Band coverage over the last 30 eval days averages **0.653** (14d: 0.627) against an 0.80 target — chronic, and predating the 2026-08-30..09-04 outage that produced 09-04's 0.083.

**Alternatives (failure-mode signals):**

1. **The comparison window is the August level shift, not the model.** Jul–Aug 2026 was the highest-price, highest-variance stretch in the parquet, and a trailing-56-day learner is worst exactly there while a naive carry is at its best. **Signal:** skill turns positive over a calmer stretch once `n_naive_hours` accumulates across a regime change. Then the finding is regime-conditional and the fix is an adaptive window (which is EXP-023a's territory), not a model-class change.

   **→ ANSWERED, partly, same day (EXP-035).** Re-scoring the 260 stored offline vintages (2025-12-05..2026-08-21) against the same floor: LightGBM `full` is **+5.1% over naive across the full window** (DM p=0.033) — so the alternative is half-right, the flat "no skill ever" reading was too strong. But the skill is **regime-dependent exactly as the alternative predicts, and that is the damaging half**: `lgbm_full` is *below* naive in 2 of 9 months, and in **August 2026 all eight LightGBM ablation variants are below naive** (best `drop_rolling` −0.104, `full` −0.157). Chronos-bolt-base is above naive in **9 of 9 months** (+0.196 in August) and +25.0% overall, DM p<1e-6. So the regime confound is real *and* it is a property of this model class, not of the measurement. This narrows the entry rather than resolving it — the live-record verdict is still Step 2's job.
2. **The baseline is accidentally cheating.** **Signal:** the baseline sources an hour later than `24 * ceil(h/24)` back, or the parquet carries revised rather than as-published prices. Two failure surfaces, and only one is pinned:
   - *Arithmetic* — `TestNaiveSourceTimestamp::test_source_is_never_after_t0` covers it, but only by handing the true `t0` in as an argument, so it validates the formula and nothing else.
   - *Anchor resolution* — the realistic way this cheats, and **the way it actually did**. Code review on 2026-09-06 (before any `naive_*` row was written) found the first implementation inferring `t0` as `min(timestamp) - 1h` over `calibration_history`, which holds **realised rows only**: a vintage whose leading hours were withheld by `backfill_realized` would infer an anchor too late and source prices from after the true `t0` — a leak biasing skill *downward*, toward this entry's own conclusion. Fixed by recording `t0_utc` at prediction time (`update_shadow.py` step 7) and refusing to score rather than infer when it is absent and the leading hours are gone. Pinned by `TestT0Resolution` (6 tests).
   - *Still unpinned:* ENTSO-E price revisions. If the parquet carries revised rather than as-published values, the baseline is scored on numbers nobody had at `t0`, and it would be flattered. Not currently checkable — `consolidate.py` keeps last-write-wins per timestamp with no revision trail.
3. **MAE is the wrong lens for the product.** Augur exists for load shifting, where what matters is ranking the cheap hours within a day, not the level. **Signal:** a rank-correlation or cheapest-k-hours-hit-rate metric shows the model ahead of naive even where MAE is behind. That would make this entry's verdict narrow rather than wrong — and it would mean the dashboard should be scored on that instead.

   **→ SIGNAL DID NOT FIRE; REFUTED, AND IN THE OPPOSITE DIRECTION (EXP-037, 2026-09-11).** Scored as **cost regret in EUR/MWh** — what you actually pay if you run a load for the k hours the forecaster calls cheapest, against perfect foresight — on the same 260 stored vintages, method pre-committed before any number existed. LightGBM `full` regret **7.99** vs the carry's **5.01**: **worse by 2.98 EUR/MWh**, worse in 2 of 3 horizon groups (+0.84 at 1–24h, −3.85 at 25–48h, −5.94 at 49–72h), worse in **6 of 9 months**, mean Spearman 0.718 vs 0.787. The materiality bar was never reached because the sign was wrong. **The product lens is the harsher one, not the kinder one**, which makes this entry simpler and stronger rather than narrower: the incumbent is not vindicated by any lens tried so far. Alternative 1 above is refuted by the same run's *sign* — it predicted the carry winning short and the model winning long; the pattern is exactly reversed.

   **Mechanism (post-hoc):** amplitude collapse. LightGBM's within-block forecast spread falls from 26.6 EUR/MWh at 1–24h to **14.9** at 49–72h, against a realised spread of **42.7** and a carry holding **41.1**. Beyond a day it forecasts about a third of the true diurnal amplitude. A flattened forecast has a *better* MAE — hedging toward the conditional median is precisely what minimising absolute error buys — and a nearly arbitrary ranking. **The training objective is buying MAE by destroying the product value.** Chronos-bolt-base holds 35.7 and beats the carry by **+2.55 EUR/MWh** (DM p<1e-6) in all three groups and all nine months, Spearman 0.883.

   Not an artefact of the shipped column: the raw tau=0.50 output scores 7.95, materially identical. Does **not** discharge Step 2 — same stored-vintage status as EXP-035.
4. **It is real and it is the model class.** **Signal:** EXP-021's Chronos-Bolt arm, re-scored against the same naive floor, clears it while LightGBM does not. EXP-021 measured −20.3% QS *against the incumbent*; that number means something entirely different if the incumbent is sub-naive.

   **→ SIGNAL FIRED (EXP-035, 2026-09-06).** Chronos-bolt-base 22.72 MAE vs naive 30.31 (+25.0%, DM p<1e-6), clearing the floor at every horizon group (+0.259 / +0.245 / +0.249) and in every month. LightGBM `full` 28.76 (+5.1%). The gap between model classes is therefore **larger** than EXP-021 stated, not smaller: the incumbent it beat by 20.3% is itself only marginally above a free baseline. Note the direction of this correction — it does not rescue the incumbent, it demotes it.

**Method (pre-committed 2026-09-06, before any of the above is re-run):**

*Step 1 — instrument, shipped with this entry.* `evaluate_shadow.py` gains six fields per row: `n_naive_hours`, `naive_mae`, `lightgbm_mae_on_naive_hours`, `lightgbm_skill_vs_naive` (`1 - lgbm/naive` on the paired hours, positive = model better), and `naive_min_horizon_h` / `naive_max_horizon_h`. The baseline may only read `24 * ceil(h/24)` hours back — which, for a 72h vintage, is always the single window `[t0-23h, t0]`. LGBM is restricted to the same hours so a gappy baseline cannot manufacture skill. Any unusable input leaves the fields **null, never 0.0** — "not computed" must not read as "no edge". `update_shadow.py` additionally records `t0_utc` per prediction so the anchor is never re-derived. 25 tests in `tests/test_evaluate_shadow.py`.

The horizon-span fields exist because a vintage becomes eligible at 24 of 72 realised hours and *which* 24 varies, while naive MAE is strongly horizon-dependent (23.3 / 28.9 / 32.7 by the table above). **Step 2's mean is therefore taken over rows sharing a comparable span; rows whose span differs materially are reported separately rather than averaged in.**

*Step 2 — the verdict, on fresh vintages only.* Do not re-litigate this on the 24 days above; they are how the hypothesis was formed. **EXP-035 does not discharge this step either** — it re-scores the same offline vintages EXP-018/021 already used, so it is corroboration from independent data but not the pre-committed live test, and its LightGBM arms are the walk-forward harness's rebuilds rather than the deployed model. After **≥21 vintages carrying non-null `lightgbm_skill_vs_naive`**, read the mean skill:

- mean skill **< 0** → confirmed. The model class is the problem, EXP-021a inherits first claim, and `docs/experiment-results.md` gets a Decision-state line saying every pre-2026-09-06 effect size is measured against a sub-naive reference.
- mean skill **∈ [0, 0.05]** → the model is a rounding error above a free baseline. Same practical conclusion, but keep the incumbent while EXP-021a runs.
- mean skill **> 0.05** → the August window was the confound (Alternative 1). Re-read this entry against the regime, and treat the 24-day evidence as regime-conditional.

~~Whichever bucket lands, **run Alternative 3's rank metric before acting**~~ — **discharged 2026-09-11 by EXP-037, before the verdict, as instructed.** The model does *not* rank hours well while missing levels: it ranks them worse than the carry does. So the dashboard's problem is not presentation, and this instruction no longer gates acting on whichever bucket Step 2 lands in. What EXP-037 adds instead is a *mechanism* the verdict should be read against — the amplitude collapse above — and a second product-denominated metric on which the model-class gap is large.

*Step 3 — what is NOT pre-committed here.* Dropping the 1–24h horizon. That is a product change (the day-ahead auction publishes those hours ~4h before the run starts, and `api-client.js:226` already fetches them from Energy Zero), not a model finding, and it needs its own entry once it is known whether EDH's file already carries tomorrow's prices — unverifiable on the dev box, which has no keys. Filed as an open question, not a decision.

**Clarified 2026-09-11 (author's intent, previously unrecorded).** The 1–24h block is forecast **deliberately**, and not because nobody noticed the auction had cleared. It is a **known-answer self-test**: at run time the day-ahead prices for those hours are already published, so the pipeline can be scored against ground truth *immediately*, without waiting a day for realisation. That is the only zero-latency check this system has. Recording it because both this entry and `CLAUDE.md` previously filed it as an open product question, and it was argued the wrong way in session on 2026-09-11 — "stop forecasting hours you already know" is a reasonable-sounding move that would remove the instrument.

⚠️ **But the test region is not representative, and EXP-037 measured how badly.** The 1–24h block is the one place the incumbent still holds diurnal shape: within-block forecast spread **26.6** EUR/MWh there against **14.3 / 14.9** at 25–48h and 49–72h, versus a realised spread of ~42.5 throughout. On cost regret it *beats* the carry at 1–24h (+0.84 EUR/MWh) and loses heavily beyond it (−3.85, −5.94). So a self-test on this block **passes while the hours the product depends on degrade** — it is flattering by roughly a factor of two in amplitude and by a sign flip in regret. Use it as an integrity check ("did the pipeline produce sane output tonight?"), never as a health proxy for the 25–72h forecast. If it is to serve as the health check, it should be **stratified per horizon group**; the EXP-037 summary carries the per-block baselines to calibrate that against.

The separate product question — whether the *dashboard* should display published prices for those hours rather than the forecast — is untouched by this and remains open. Displaying published prices and forecasting them internally are independent choices.

**Revisit trigger:** ≥21 eval rows with non-null `lightgbm_skill_vs_naive` — the field starts populating on the next sadalsuud run, so ≈2026-09-27 at one row/day. **Does not consume fresh vintages** and does not block EXP-018a Stage 1 or EXP-021a; it re-frames how both are read. Surface in `/curate`.

**Update [2026-09-06, same day]:** EXP-035 re-scored every stored arm against this floor with no GPU and no fresh vintages (ADR-007 layer 2). Headline: **the floor separates the model classes cleanly** — Chronos +25.0% and never below naive in any month; every LightGBM variant below naive in August 2026. Secondary, and useful to EXP-018a: `drop_rolling` is the strongest LightGBM arm against the floor (+0.107, double `full`'s +0.051), which points the same way EXP-018a's pre-committed direction does, while `drop_calendar` is the only arm below naive over the whole window (−0.017) — the calendar block is the one feature group clearly carrying its weight. None of this changes what is deployed, and none of it discharges EXP-018a or EXP-021a, both of which remain gated on 14 fresh vintages (6 counted 2026-09-06).

**Amendment [2026-09-11] — the floor itself was weak, and a scalar floor is the wrong shape (EXP-036).**

EXP-036 ran its pre-committed arms. **Every** multi-day profile beats the single-day carry this entry's floor is built on, monotonically in K, and the best arm — `N5_dt`, the mean of the same clock hour over the last 5 *matching day types* — beats it by **15.8%** (MAE 24.35 vs 28.92, DM p<1e-5). Its Alternative 1 (averaging destroys more than it denoises) is refuted; its Alternative 2 (day-type is the whole effect) did not fire, because plain `N5` already beats the carry by 9.8% and day-type matching adds ~6pp on top of that.

What that does to this entry's subject: LightGBM `full`'s **+5.1% over the carry becomes −12.4% below the honest floor**, and its months below go from **2 of 9 to 7 of 9**. `drop_rolling`, the best LightGBM arm, is also below (−5.5%). Chronos-bolt-base survives every arm (+10.7% vs `N5_dt`, never below in any month).

**Alternative 3 of EXP-036 fired, and it lands on this entry's Method.** The profile's gain over the carry is strongly horizon-dependent — `N5_dt` gains **+7.1%** at 1–24h and **+19.8%** at 49–72h, a 12.6pp spread against a 5pp signal. EXP-036 pre-committed that this means *"a single scalar floor is the wrong shape and augur#29's threshold must be restated per horizon group rather than as one mean."*

**That instruction and this entry's own boundary are in tension, and the tension resolves against changing anything now.** Step 2 pre-commits buckets on a mean skill against the carry, on ≥21 fresh vintages. Re-specifying the threshold *while the data is arriving*, on evidence from stored vintages, is precisely the post-hoc criterion swap ADR-007 forbids and the 2026-09-04 lesson in `docs/model-progress-log.md` is about. So:

- The **≥21 verdict fires as written** — mean skill, against the single-day carry, in the three buckets above. Unchanged.
- It is **reported alongside** the per-horizon-group split and the profile-floor skill, both of which `evaluate_shadow.py` now logs (`naive_profile_mae`, EXP-036 gate G2 — additive, never replacing `naive_mae`, so pre-2026-09-11 rows stay comparable).
- Any **successor** criterion is per-group. A scalar one is now known to be the wrong shape, and that knowledge applies forward.

**And a correction that is not about this entry.** EXP-036's Alternative 4 also fired: the profile floor closes **57%** of Chronos-bolt-base's margin (+24.8% over the carry → +10.7% over `N5_dt`), against a >1/3 signal. A material part of what EXP-021/022 attributed to a pretrained distributional prior is ordinary profile smoothing that a seven-line baseline also has. The foundation model still clears every arm in every month — the model-class conclusion is unchanged in *direction* — but its headline margin over an honest floor is roughly **half** what it is over the carry. Anyone quoting −20.3% or +25.0% should quote this beside it. That is the third correction to the EXP-021 mechanism story, as EXP-022 warned there might be.

**Amendment [2026-09-11] — the trigger counts rows; the verdict reads spans; a row can be counted in and read out.**

Step 1 says the baseline may only read `24 * ceil(h/24)` hours back, and restricts LGBM to the same hours so a gappy baseline cannot manufacture skill. What it does not say is what happens when the pairing is *thin*. It can be a single hour: the 2026-09-09 row paired **one** hour, at horizon 25, and scored **+0.762** — the most flattering number in the log, from one draw of a variable whose daily MAE ranges over tens of EUR/MWh, and at that moment one of only **three** scored rows in existence. Cause was upstream, not the evaluator: the 09-08 `t0 jumped 2d` and the 09-10 stale-parquet run left almost no source day to pair against.

The reading rule above already handles this at verdict time — rows of materially different span are reported separately, not averaged in, and a 25–25h row is a different span from a 1–24h one. But the **trigger** is a bare count of non-null rows, and a bare count admits rows the reading rule will then discard. The two numbers must describe the same population or the verdict fires on a sample it cannot read.

So, with no change to the thresholds, the buckets, or what counts as evidence:

- **≥21 rows** now means ≥21 rows carrying non-null `lightgbm_skill_vs_naive` **and** `n_naive_hours ≥ 12` (`MIN_NAIVE_HOURS`, `scripts/daily_update.sh`). Half a day, on a metric whose unit of observation was always meant to be a day.
- Thin rows are still **written and still readable** — excluded from the count, not from the record. One is logged; **three or more of the last ten reach the commit subject** as `[NOTE: naive thin N]`, the same threshold the unscored alarm uses. A log line alone would not have been enough: nothing reads `logs/daily_update.log` unless the unit dies, so the case that matters — every row thin from here on, `eligible` pinned, the verdict quietly never becoming admissible — would have surfaced nowhere.
- The same floor applies to the nightly 7-row sub-naive window, and fixing it exposed a latent bug in that window worth recording: it scanned a fixed `rows[-10:]`, so excluded rows consumed slots. With four thin rows among the last ten, `[NOTE: sub-naive L/N]` could never fire again — going quiet in exactly the vintage damage that produces thin rows. The window now walks back until it has 7 qualifying rows, which is what `docs/RUNBOOK.md` always claimed it did ("after an EDH outage it can span weeks"). The unscored **fault** detector stays recency-bound at the last 10, because "rows are landing now carrying no score" is a claim about now.
- The count is now **mechanical**: every run prints `Seasonal-naive verdict trigger: N/21 qualifying rows`. It was previously counted by eye from a log in which a 1-hour row is indistinguishable from a 24-hour one.

This is a tightening, so it can only delay the verdict, never bring it forward — which is the right direction for a rule changed while the data is arriving. Count at amendment: **2 qualifying rows of 21** (09-06, 09-07; 09-09 excluded), so the ≈2026-09-27 date now assumes an unbroken run of full vintages from here and is optimistic. 22 tests in `tests/test_naive_floor_guard.py`.

**Review by:** 2026-10-20.

---

### [2026-08-30] EXP-023a: the 112-day window's 3.0% gain is real and survives on vintages the sweep never scored

**Position (provisional):** EXP-023 found a 112-day training window beats production's 56 by 3.0% quantile score (DM p<0.0001), with better coverage on both sides and better Winkler — all four pre-committed gates passing. Position: this is a real generalisation gain, and it reproduces both on historical vintages the discovery sweep never touched and on vintages that did not exist when it was measured.

**Why this needs its own pre-commit:** EXP-023's 112d rung is the **best of five** compared on one window, so its effect size is upward-biased by selection — the same objection that produced EXP-018a. Worse, the confound control (fix the vintage set so the 168d rung is available throughout) left only **95 vintages, all 2026-03-15..2026-08-21** — the high-price half of the year. A 3.0% effect measured on a best-of-five over one regime is exactly the kind of result that evaporates. Per ADR-007 the confirming test is fixed here, before the confirming data is looked at, and before `WINDOW_DAYS` changes anywhere.

**The power problem, stated up front because it drives the design.** EXP-018a could demand 14 fresh vintages because its in-sample effect was 8.1%. Here it is 3.0%. Power scales roughly with the square of the effect, so matching EXP-018a's power at this effect size needs on the order of **7× the vintages** — ~98, i.e. late November. Demanding "≥3% on 14 fresh vintages" would be demanding *zero shrinkage* on an underpowered sample, which is not a test, it is a coin flip dressed as one. The design below therefore splits into a cheap quasi-holdout available now and a properly-powered fresh-vintage stage later, with the bar lowered honestly rather than the sample pretended larger.

**Alternatives (failure-mode signals):**

1. **Regime artifact.** 112d wins only because Mar–Aug 2026 was a rising, high-price regime where a longer window damps over-reaction. **Signal:** Stage A (Dec 2025–Mar 2026, a calmer stretch) shows no gain or a loss. Then the finding is regime-conditional, not a window-length law, and the right answer is an adaptive window rather than a new constant.
2. **Selection mirage.** **Signal:** Stage A or B lands under 1.0% against 3.0% in-sample. Do not ship on a shrunken effect; the curve's *shape* (inverted U peaking interior) may still be worth keeping as evidence while the point estimate is not.
3. **The optimum moves with the feature set.** EXP-023 ran on `lean`, but production is `full` and EXP-018a has not concluded. **Signal:** re-running the two rungs on `full` gives a different winner. Then window and feature set are not separable and both must be settled together.
4. **Longer is simply better and 168 was a fluke of the confound control.** **Signal:** Stage B shows 168d ≥ 112d. Then re-open the sweep at 140/168/196 on the then-available history rather than shipping 112.

**Method (pre-committed 2026-08-30, before either stage is run):**

*Stage A — quasi-holdout on unscored history, runnable immediately.* EXP-023's sweep scored only `t0 ∈ [2026-03-15, 2026-08-21]`, because the 168d rung needed 168 days of pre-history. A **56-vs-112 comparison needs only 112 days**, so vintages from `2026-01-20` to `2026-03-14` are available *and were never scored by the discovery run*. Run exactly two rungs — **56 and 112, treatment fixed here so it cannot be chosen on the holdout** — on `t0 ∈ [2026-01-20, 2026-03-14]`, feature set `lean`, everything else identical to EXP-023:

```
PYTHONPATH=.:scripts .venv/bin/python scripts/exp023_window_sweep.py \
    --start 2026-01-20 --end 2026-03-15 --windows 56,112 \
    --jobs 14 --out ml/shadow/exp023a_stage_a
```

This is a **quasi**-holdout, not a true one: the data existed when 112 was chosen, even though these rows were not scored. It is therefore evidence about Alternative 1 (regime) and Alternative 2 (shrinkage), and **cannot on its own justify shipping**.

*Stage B — fresh-vintage confirmation.* When **≥45 vintages with `t0 ≥ 2026-08-26`** exist (≈2026-10-09; 45 rather than 14 for the power reason above, and ≥ the EXP-023 discovery end so there is no overlap), run the same two rungs on that range. Incumbent = 56d. Treatment = 112d.

*Gates.* IMPLEMENT iff **all four** hold **on Stage B** (Stage A informs but does not gate):

1. **Skill:** paired DM on per-observation quantile score, H1 112d better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size:** 112d QS at least **1.5%** better than 56d. Deliberately below the in-sample 3.0% — half the discovery effect is the most that can be honestly demanded of a properly-powered replication of a small effect, and pretending otherwise would make the gate unpassable by design.
3. **Calibration:** 112d lower- and upper-side coverage each **not more than 0.02 worse** than 56d (raw quantiles, no CQR).
4. **Sharpness:** 112d mean Winkler (α=0.20) **≤ 1.05 ×** 56d.

*If it passes.* The change is one constant (`WINDOW_DAYS` in `ml/shadow/update_shadow.py` and its siblings), and the revert is the same one constant. Deploy behind the same live-shadow discipline ADR-006 was earned with: 14 evaluable post-deploy vintages in `shadow_state.json:calibration_history`, `lightgbm_mae` not worse than the pre-deploy trailing-14 mean, no new alarm classes. **Note the interaction with EXP-018a**: if that ships the lean feature set, re-derive the optimum before changing the window, per Alternative 3.

**Addendum 2026-08-30 (feasibility defect found before Stage A was run; gates unchanged).** The Stage A range above is **wrong and unrunnable**, and finding out why also corrects a factual error in EXP-023's own record. `load_frame_ext` drops rows on the EXP-020 fundamentals columns, which begin 2025-12-01, so the *feature frame* starts **2025-12-02** — not the parquet's 2025-09-28. Consequences:

- The earliest usable `t0` for a 112-day window is **2026-03-24**, not 2026-01-18, so the pre-committed Stage A range (2026-01-20..2026-03-14) yields **zero** vintages.
- **EXP-023's discovery window was `2026-05-19..2026-08-21`, not "2026-03-15..2026-08-21" / "Mar–Aug 2026"** as recorded in `experiments/registry.jsonl` EXP-023 notes, `docs/model-progress-log.md`, CLAUDE.md and `memory/MEMORY.md`. The real window is **three months, May–August**, narrower and later than recorded — which makes Alternative 1 (regime artifact) *more* live, not less, since May–Aug 2026 is squarely the rising-price stretch.

**Corrected Stage A range: `t0 ∈ [2026-03-24, 2026-05-18]`** — the vintages that a 112d window can reach and that the discovery sweep never scored, ~56 of them. Everything else about Stage A is unchanged: two rungs only (56 and 112, treatment still fixed in advance), `lean`, quasi-holdout status, informs but does not gate. **Stage B and all four gates are untouched.** Recorded here rather than edited into the text above, per ADR-007: this is a defect in the data the Method reads, found *before* any Stage A number was seen, not a Method loosened after a peek.

**Revisit trigger:** Stage A immediately (corrected range). Stage B at ≥45 vintages with `t0 ≥ 2026-08-26`, ≈2026-10-09, and **after** EXP-018a Stage 1 has claimed the fresh window. Surface in `/curate`.

**Review by:** 2026-11-15.

**Domain:** EXP-023a, window length, ADR-006, augur#19, `scripts/exp023_window_sweep.py`.

**Status:** open — pre-committed 2026-08-30, before either stage was run.

### [2026-08-30] EXP-028a: Chronos-2's covariate gain survives on uncontaminated fresh vintages, and the coverage cost is a real trade rather than a fixable artifact

**Position (provisional):** EXP-028 found `amazon/chronos-2` gains **8.3% quantile score** (DM p=0.0051) from exogenous covariates supplied at inference time with no retraining — Augur's first positive exogenous result, and a genuine qualification of EXP-020's "exogenous is inert" conclusion, which held for LightGBM and for a LightGBM-specific mechanism. Position: the gain reproduces on fresh vintages, and the coverage cost that failed gate 3 (lower 0.923→0.886, upper 0.880→0.856) persists rather than vanishing — i.e. it is a real skill-for-calibration trade that a conformal layer must be asked to absorb, not a small-sample wobble.

**Why this needs its own pre-commit, and why it is more urgent than EXP-023a's:** EXP-028 carries a contamination exposure that none of the Bolt experiments do. `chronos-bolt-base`'s weights were frozen **2025-11-21**, before the evaluation window, so EXP-021 could call contamination *impossible*. **`amazon/chronos-2` was last modified 2026-06-05 — inside the window.** Restricting to `t0 > 2026-06-05` removes overlap with the freeze date but does **not** prove the pretraining corpus excludes NL day-ahead prices. Fresh vintages from September onward are the only thing that resolves this by construction, and they are the reason this entry exists. Additionally the discovery ran on only **77 vintages**, and its covariates carry the harness's vintage-overwrite optimism (ratio 1.84), which biases *toward* the result.

**Alternatives (failure-mode signals):**

1. **It was contamination.** **Signal:** the gain collapses to under 2% on vintages strictly after the weight-modification date by a wide margin. Then the exogenous question is *not* re-opened, EXP-020's conclusion stands unqualified across model classes, and this is the most important negative available — it would also cast doubt on the c2-vs-bolt comparison generally.
2. **It was the model, not the covariates.** chronos-2 univariate already beat bolt-base by 5.5% on the discovery subset. **Signal:** the covariate-vs-univariate delta shrinks while chronos-2 univariate keeps beating bolt. Then the headline belongs to the newer checkpoint and the covariate story is separate and smaller. *(The covariate-vs-univariate comparison is the internally valid one precisely because both arms share weights; this alternative is why the two must never be conflated.)*
3. **The coverage cost is fixable, not intrinsic.** **Signal:** applying CQR to the covariate arm restores coverage to ≥0.80 without giving back the skill. Then gate 3's failure was an artifact of comparing raw bands, and the arm becomes shippable on a conformal layer we already run.
4. **Exogenous freshness is doing the work.** The harness feeds vintage-overwritten covariates, fresher than the live cron sees. **Signal:** re-running with covariates lagged to what was genuinely known at t0 erases the gain. Then the result is a backtest artifact and cannot survive deployment — **this arm is mandatory, not optional**, because it is the failure mode most likely to produce a real-looking gain that dies in production.

**Method (pre-committed 2026-08-30, before any fresh vintage is scored):**

*Stage 1 — fresh, uncontaminated confirmation.* When **≥28 vintages with `t0 ≥ 2026-08-26`** exist (≈2026-09-23; 28 rather than 14 because the discovery subset was small and the effect must clear a raised bar), re-run four arms on that range with `scripts/exp028_chronos2_covariates.py`:

```
c2_univariate            base
c2_known_future          treatment  — PRIMARY
c2_known_future_lagged   Alternative 4: covariates as known at t0, not overwritten
bolt_base                reference  (frozen weights, contamination-free anchor)
```

*Gates.* IMPLEMENT-as-candidate iff **all four** hold for `c2_known_future` vs `c2_univariate`:

1. **Skill:** paired DM on per-observation quantile score, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size:** QS at least **5%** better — the same bar the discovery cleared (8.3%), not lowered, because unlike EXP-023a this effect is large enough that a properly-powered replication can be held to it.
3. **Calibration:** lower- and upper-side coverage each not more than **0.02** worse than the univariate base. **This gate FAILED in discovery and is expected to fail again**; the Position predicts it. Failing it again is *not* a reason to loosen it — it routes to Stage 2 rather than to shipping.
4. **Sharpness:** mean Winkler (α=0.20) ≤ 1.05 × base.

*Mandatory regardless of gate outcome:* report `c2_known_future_lagged`. If the lagged arm loses more than half the gain, record Alternative 4 as confirmed and **stop** — no Stage 2, whatever the primary arm did.

*Stage 2 — only if skill passes and calibration fails, which is what the Position predicts.* Apply the production CQR layer to both arms and re-score. Ship-worthy iff the covariate arm's CQR-corrected band coverage is within 0.02 of the univariate arm's **and** it keeps ≥5% QS advantage. That tests Alternative 3 directly. If CQR cannot absorb the cost, the honest conclusion is that covariates buy point skill at a calibration price Augur should not pay while augur#19 is open, and the entry parks.

**What does not happen in this entry, whatever the numbers.** No production path is touched. Chronos-2 is not in the nightly job, and EXP-021a — the confirmation ladder for the foundation model as *forecaster* — is a separate and earlier question than whether that forecaster gets covariates. If EXP-021a fails, this entry is moot regardless of its own result.

**Revisit trigger:** ≥28 vintages with `t0 ≥ 2026-08-26`, ≈2026-09-23, after EXP-018a Stage 1. Surface in `/curate`.

**Review by:** 2026-10-31.

**Domain:** EXP-028a, foundation models (augur#15), exogenous features (augur#3, augur#22), augur#19, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-30, before any fresh vintage was scored.

**Related evidence (added 2026-10-29, outside the Method, which is unchanged):** Lipiecki & Weron (2026, arXiv:2609.00089; deep-dive `docs/foundation-models-epf-literature-review.md`), DE/PL/ES day-ahead 2021–2025. Two points for this review. **(a) Alternative 1 has a cheap, direct test that this Method doesn't contain:** `Chronos-2-synth`, pretrained on synthetic data only, matches Chronos-2 there (CRPS better in DE and PL, 2% worse in ES). Re-running EXP-028's covariate-vs-univariate pair with it would be contamination-free by construction and could use all 260 stored vintages instead of the 77 after 2026-06-05. **(b) Chronos-2 is not the strongest covariate model:** TabPFN-3 (10–22% better CRPS) and TabPFN-2 (8–19%), tabular and also synthetic-only, beat it in every market (backlog EXP-040). Both are new entries. Day-ahead only, so neither speaks to 25–72h. **(c) Alternative 4's mandatory lagged arm has a source:** `scripts/exp028_chronos2_covariates.py` has no `c2_known_future_lagged` arm yet, but the energydatahub repo archives every EDH publish (`data/YYMMDD_HHMMSS_<feed>.json`, encrypted, from 2025-12-01), so covariates as published at t0 can be rebuilt (found 2026-10-29).

### [2026-08-29] EXP-021a: Chronos-Bolt's 20% zero-shot win survives on fresh vintages, and survives contact with production constraints

**Position (provisional):** EXP-021 (resolved same day) measured `chronos-bolt-base` zero-shot at **-20.3% quantile score and -16% MAE against the lean LightGBM incumbent**, with raw band coverage 0.811 against a 0.80 target where the incumbent sits at 0.611, on 260 paired vintages. Position: this reproduces on vintages that did not exist when it was measured, and the operational objections to running it in production (latency, dependency weight, the loss of a nightly-refit story, no CPU path on sadalsuud) are surmountable rather than disqualifying.

**Why this needs its own pre-commit:** EXP-021's window is the same one EXP-018/019/020 already explored. The usual selection-bias objection is *weaker* here than it was for EXP-018a — a zero-shot arm tunes nothing, so there was no search to overfit with, and the model's weights were frozen 2025-11-21, before the window opens. But "weaker" is not "absent": the window was chosen because it is the one already instrumented, the FM was chosen after a literature scan, and a 20% claim against a production system should clear a fresh-vintage bar at least as high as the 8% one did. Per ADR-007 the confirming test is fixed here, before the confirming data exists and before any production path is touched.

**Alternatives (failure-mode signals):**

1. **The gap is a backtest artifact of exogenous freshness.** The EXP-018 harness reads a parquet whose exogenous rows are overwritten by later vintages (refuted-hypothesis 2026-05-29, ratio 1.84), so the *incumbent* is scored with fresher inputs than the live cron sees — but the incumbent is also the arm that gets hurt if that advantage is removed, and the FM uses no exogenous at all. **Signal:** the gap *widens* on live vintages rather than narrowing. That is a confirmation, not a failure — recorded here so the direction is fixed in advance and cannot be read either way after the fact.
2. **Latency or footprint makes it undeployable.** 205M params, a torch install, and a GPU-less production host. **Signal:** CPU inference for 1 vintage x 72h exceeds ~60s on sadalsuud's hardware, or the dependency set cannot be installed alongside the existing venv. Then the arm is offline-only — an ensemble member or a band source scored on the GPU box, not the nightly production path.
3. **Zero-shot skill is unstable vintage-to-vintage.** Pooled means can hide a model that is excellent on 8 days and catastrophic on the 9th, which matters far more for a live dashboard than for a pooled score. **Signal:** the FM's per-vintage MAE distribution has a materially heavier right tail than the incumbent's (95th percentile more than 1.5x the incumbent's 95th). Then the pooled win is not the operationally relevant statistic and a hybrid/guarded design is needed.
4. **The calibration win does not survive CQR.** EXP-021 compared *raw* bands, where the incumbent is at 0.611 and badly under-covering. Production wraps CQR around it. **Signal:** the incumbent's CQR-widened live coverage (`shadow_state.json:calibration_history`) is comparable to the FM's raw coverage. Then the calibration half of EXP-021 is an artifact of comparing a pre-conformal band to a post-conformal one, and only the skill half stands.

**Method (pre-committed 2026-08-29, before any fresh vintage is scored and before any production path is touched):**

*Stage 1 — fresh-vintage confirmation, offline, zero production risk.* When ≥14 vintages with `t0 ≥ 2026-08-25` exist in the parquet (≈2026-09-09 — the same trigger as EXP-018a Stage 1, which has priority on that window and must run first), re-run all three arms on `t0 ≥ 2026-08-25` only:

```
PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py contexts \
    --start 2026-08-25 --end <first-unrealised-day> --context-end-offset-h 1 \
    --out ml/shadow/exp021_stage1
# predict on b650-gpu, then:
PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py score \
    --out ml/shadow/exp021_stage1 --incumbents <fresh full/lean predictions>
```

Incumbent = whichever base EXP-018a Stage 1 leaves standing (`lean` if it passes, `full` if it fails); if EXP-018a has not concluded, the primary gate stays against `lean`, the harder bar, exactly as in EXP-021. **The matched-information arm (`--context-end-offset-h 1`) is the one that counts**; the unmatched arm is not run again. IMPLEMENT-as-candidate iff all four hold:

1. **Skill:** paired DM on per-observation quantile score, H1 FM better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size survives:** FM QS at least **10% better** than the incumbent. Deliberately higher than EXP-018a's 3%: the in-sample effect is 20%, and a bar of 3% would let a 90%-shrunken result pass as confirmation.
3. **Calibration:** FM lower- and upper-side coverage each **not more than 0.02 worse** than the incumbent (raw quantiles, no CQR, both arms).
4. **Sharpness:** FM mean Winkler (α=0.20) **≤ 1.05 ×** incumbent.

*Stage 2 — operational feasibility, gated on Stage 1 and decided on measurement, not preference.* Only if Stage 1 passes. Measure, on sadalsuud's actual hardware: (a) CPU-only wall-clock for one 1344-point context x 72h forecast, 10 runs, report median and max; (b) venv size delta and whether `torch` installs cleanly alongside the existing pins; (c) a 14-day replay of per-vintage MAE distributions for Alternative 3's tail check. Feasible iff median CPU latency ≤60s **and** the p95 per-vintage MAE ratio (FM ÷ incumbent) ≤1.5. Infeasible on latency alone → the FM becomes an offline band source for augur#19 rather than the production forecaster, which is a smaller but still real win.

*Stage 3 — shadow, then swap.* Only if Stages 1 and 2 pass. The FM runs as a **shadow** alongside production LightGBM for **14 evaluable vintages**, written to a separate output file, dashboard untouched — the same shape as the original LightGBM shadow that produced ADR-006, and for the same reason: EXP-014's promotion was earned by a live shadow, not a backtest, and this one will be too. Promotion criterion at that point is ADR-007's, re-derived against whatever the incumbent then is; ADR-006 is amended only after a live swap, never before.

**What is explicitly not decided by this entry:** whether Augur's production forecaster *should* be a 205M-parameter pretrained model rather than a 1344-row nightly refit is a question about operational surface, reproducibility and the project's ability to debug its own forecasts — not only about quantile score. Stage 3 is where that judgement gets made, with a live shadow in hand. Recording it here so a strong Stage 1 does not read as having settled it.

**Revisit trigger:** ≥14 vintages with `t0 ≥ 2026-08-25` in the parquet — ≈2026-09-09, **after** EXP-018a Stage 1 has run on the same window. Surface in `/curate`.

**Review by:** 2026-10-15.

**Domain:** EXP-021a, augur#15 (foundation models), augur#19 (calibration), model class, ADR-006, ADR-007.

**Status:** open — pre-committed 2026-08-29 immediately after EXP-021 resolved, before any production path was touched.

### [2026-08-31] The load/price horizon divergence is transient ENTSO-E outage residue, not a new steady state

**Position (provisional):** The 2026-08-30 publish in which EDH's `load_forecast` spanned 24h while `energy_price_forecast` spanned 48h is **one-off outage residue and will not recur**. Basis: the energyDataHub session decrypted the committed publish (`8e5cc52`) and found EDH's request window unchanged at 48h with the envelope still declaring `end_time 2026-08-31T23:59:59+02:00` — so the collector asked for two days and ENTSO-E returned A44 day-ahead prices for 08-31 but not A65 day-ahead load. 2026-08-29 was a total ENTSO-E 503 at EDH (run `33269881393` published nothing), and the 08-30 18:58 run was the first success after it. Every normal-hour publish sampled before that — 08-20, 08-21, 08-24 16:32, 08-25, 08-26 — carried both feeds at 192 points. Filed as energydatahub#51.

**Alternatives (failure-mode signals):**

1. **It is a new steady state.** ENTSO-E's A65 day-ahead load publication may have moved to a 24h horizon permanently, or EDH's window may drift. **Signal:** three or more consecutive normal-hour publishes with price 192 / load 96. Then the `[ALARM: t0 held back Nh]` marker fires nightly forever, the forecast permanently loses ~24h of reach, and the response is a real decision rather than a wait — either accept the shorter horizon, or reconsider whether `load_forecast` earns its place at all (which is **EXP-018a's** question, so it must not be pre-empted by this).
2. **It is intermittent rather than transient.** Recurs every few weeks tied to ENTSO-E incidents. **Signal:** the marker fires, clears, and fires again within a month with a full-length publish in between. Then the hold-back mechanism is doing exactly its job and nothing more is needed — but the nightly heartbeat email becomes noise on those days, and the marker should probably alarm only after N consecutive days rather than on the first.
3. **A different feed truncates next.** The mechanism is not specific to load — any feed whose delivered span can differ from its requested span has it. **Signal:** `t0_short_feeds` names a column other than `load_forecast`/`wind_gen_forecast_mw`/`solar_gen_forecast_mw`. Then the fix generalised correctly and the finding is upstream-wide, worth telling EDH for their horizon-coverage check.

**Method:** over the **next 7 daily runs** (2026-08-31 → ≈2026-09-07), from the daily commit subjects and `ml/models/shadow/shadow_state.json`:

```
# (1) Count days with t0_held_back_hours > 0.
# (2) For each, record t0_short_feeds and whether EDH published at a normal hour.
# (3) Cross-check against energydatahub#51's status and EDH's own publish record.
```

Position confirmed if the hold-back appears on ≤1 of the 7 days and `#51` is closed as non-reproducing. ≥3 consecutive days confirms Alternative 1. A clear-then-recur pattern confirms Alternative 2.

**Cost of being wrong is asymmetric and worth stating:** if the Position holds, doing nothing is correct and the marker self-clears. If Alternative 1 holds and we assume the Position, we run a permanently degraded forecast while a nightly alarm trains us to ignore it — the classic alert-fatigue path. So the failure mode to watch for is *not noticing the marker stopped being informative*.

**Revisit trigger (corrected 2026-09-04 — was "7 daily runs, ≈2026-09-07", which is the wrong instrument):** **two further NORMAL-HOUR EDH publishes**, regardless of calendar date. Alternative 1's signal is three consecutive normal-hour publishes at price 192 / load 96, and exactly one exists (`260830_190255`, 19:02). Daily *Augur* runs do not advance this test — during 08-31..09-04 there were five of them and zero usable publishes. Early-hour publishes do not count either: they are short in the benign, long-standing way (see the evidence table). Still resolve this **before** EXP-018a Stage 1, for the original reason — its verdict on `load_forecast` is cleaner if we know whether the column is reliably present — and Stage 1 has itself slipped ~5 days from the same outage. Surface in `/curate`.

**Review by:** 2026-09-30.

**Domain:** upstream data reliability, `update_shadow.py:latest_feasible_t0`, `ml/data/consolidate.py`, energydatahub#51, energydatahub#33, EXP-018a.

**Evidence added 2026-09-04 — the Position's basis is confirmed and the Position itself is now the losing side, but the pre-committed signal is formally short.** Every `load_forecast` vintage on EDH `origin/main` was decrypted and counted by **distinct calendar days** as well as points, so a resolution change cannot be confused with a horizon change:

| vintage | publish hour | load NL | days | price entsoe | days |
|---|---|---|---|---|---|
| 260815_161800 | 16:18 | 192 | 2 | 192 | 2 |
| 260820_162737 | 16:27 | 192 | 2 | 192 | 2 |
| 260822_161734 | 16:17 | 192 | 2 | — | — |
| 260824_062847 | 06:28 | 96 | 1 | — | — |
| 260824_163211 | 16:32 | 192 | 2 | 192 | 2 |
| 260826_164411 | 16:44 | 192 | 2 | 96 | 1 |
| 260828_004401 | 00:44 | 96 | 1 | — | — |
| 260829_002024 | 00:20 | 96 | 1 | 96 | 1 |
| **260830_190255** | **19:02** | **96** | **1** | **192** | **2** |
| 260904_065333 | 06:53 | 96 | 1 | 96 | 1 |

**The Position's basis holds** — normal is 192/2 days, for months, so this is not a same-day feed and the 18h hold-back is a real loss of reach rather than a structural cost to design around. **The Position's conclusion does not** — "one-off, will not recur" is now four consecutive short publishes with no return to 192 since 08-26.

**The discriminator neither side had until now is publish hour.** Every 96/1 vintage *before* 08-28 is an early-hour run that recovered to 192 on the same day's normal-hour run (08-09 05:56→96 then 16:27→192; 08-24 06:28→96 then 16:32→192). So short-at-early-hour is the benign, long-standing pattern, and only a **normal-hour** short vintage is evidence. There is exactly one: `260830_190255` at 19:02. `260904_065333` is an early-hour manual dispatch and **does not count**.

**So Alternative 1 is strongly indicated and formally short of its signal** (three or more consecutive normal-hour publishes at price 192 / load 96): the 08-31..09-04 EDH publish outage denied us the normal-hour publishes the test requires. Recorded as indicative, **not** confirmed — resolve on the next two scheduled EDH runs rather than on the calendar trigger. Corroboration from the EDH session's own archive read: `metadata.end_time` declares +2 days on every short vintage, so EDH's request window is unchanged and the envelope over-declares its coverage; DE_LU tracks NL exactly, so it is not zone-specific. Locates the cause in **upstream ENTSO-E A65 availability**. **energydatahub#51 must not be closed as transient on this evidence.**

**Alternative 3 gains a concrete instance, in the other direction.** The mechanism generalises further than "another feed truncates": `load_forecast` is in EDH's `CRITICAL_FEEDS` and delivered half its horizon for four publishes **without their drift tripwire objecting**, because a shape signature captures structure and not span — 96 and 192 records have identical shape. No `CRITICAL_FEEDS` membership fixes that; a horizon/span check is a different instrument and neither repo has one. Augur's `t0` hold-back alarm was the only detector that fired. Told to EDH 2026-09-04; unowned on both sides.

**Narrowed 2026-09-04, and the scope was wider than it needed to be: this is an NL-only question.** `ml/data/consolidate.py:320 parse_load_file` reads `load_data.get("NL", {})` — hard-coded, no fallback, no merge — and `grep -rn "DE_LU" ml/ static/js/ scripts/` returns **zero hits** repo-wide. So `load_forecast` in `FEATURE_COLUMNS` is NL-only, `latest_feasible_t0` holds back on NL coverage alone, and DE_LU's state is structurally invisible to Augur. The evidence table above records both zones because that is what the publishes contain, but only the NL column bears on this entry.

**Pre-registered prediction (from the EDH session, stated 2026-09-04 09:59 CEST before the fact).** A direct ENTSO-E A65 probe found **NL recovered to 192/2 days while DE_LU is still 96/1**, with widening the request to +3d changing nothing and `DE_LU`-tomorrow-alone raising `NoMatchingDataError` — so tomorrow's NL data exists and tomorrow's DE_LU data does not. Their parser check (`_parse_response` in `collectors/entsoe_load.py` builds each zone's index from its own series, no cross-zone intersection) rules out a short DE_LU truncating NL, so the 08-28..08-30 96/96 was both zones genuinely short at once. Revised timeline: **through 08-26 both 192 · 08-28..08-30 both 96 · 09-04 NL 192, DE_LU 96.** Prediction for tonight's ~19:00 UTC scheduled publish: load NL **192/2**, DE_LU **96/1**, price entsoe **192/2**. Augur-side check: `t0_held_back_hours` → 0 and `t0_short_feeds` drops `load_forecast`.

**RESOLVED ON THE LOAD SIDE 2026-09-04, from a published vintage rather than a probe.** EDH's second dispatch of the day, `260904_081356` (08:14 UTC / 10:14 CEST), decrypted and measured:

| feed | pts | days |
|---|---|---|
| load NL | **192** | 2026-09-04, 2026-09-05 |
| load DE_LU | **192** | 2026-09-04, 2026-09-05 |
| price entsoe | 96 | 2026-09-04 |
| price entsoe_de | 96 | 2026-09-04 |

**Alternative 1 ("new steady state") is FALSIFIED, and falsified before its signal could accumulate** — the pre-committed threshold was three consecutive normal-hour publishes at price 192 / **load 96**, and `load` is now back at 192, so that sequence can never complete. It never got past one (`260830_190255`). The price leg at 96 here is *not* the divergence this entry tracks: an 08:14 UTC collection precedes the ~12:00 CET day-ahead auction, so same-day-only price is correct and expected.

**The DE_LU timing confound is confirmed real, and it was the EDH session's own flagged uncertainty.** Their direct A65 probe at 09:59 CEST (07:59 UTC) found DE_LU at 96; this publish 15 minutes later has it at 192. German day-ahead load publishes later in the day than Dutch, so a morning DE_LU short reading is benign. Their pre-registered prediction of *DE_LU 96/1 tonight* is therefore expected to fail while its NL and price legs stand — recorded because it was stated in advance, which is what makes it scoreable.

**Reconciled timeline (supersedes the single-vintage and probe-only readings, both of which were wrong in different directions):**

| period | NL | DE_LU | reading |
|---|---|---|---|
| through 08-26 | 192 | 192 | healthy |
| 08-28..08-30 | 96 | 96 | **genuine both-zone upstream A65 gap** — `260830_190255` at 19:02 was still short, far later than today's ~10:14 recovery, so this was not a timing artifact |
| 09-04 | 192 | 192 by 10:14 | both recovered; DE_LU's morning 96 is publication timing, not a gap |

So: a real multi-day A65 gap that has healed, costing three vintages of forecast reach — **resolved-upstream, not transient-misreading**. energydatahub#51 should close on that basis after tonight's normal-hour publish, not as "transient".

**⚠️ How to score tonight, because the two outcomes are easy to conflate.** If NL returns 192, **Alternative 1 is falsified before its signal could accumulate** — that is *not* "signal met, alternative confirmed", and it is not "nothing happened either": the 08-28..08-30 gap was real, cost reach, and will be invisible once NL is back at 192. Record it as falsified-with-the-gap-on-record. If NL returns 96, the probe caught a transient and the accumulation toward Alternative 1 continues. The DE_LU timing confound the EDH session flagged (German TSOs possibly publishing day-ahead load later) cannot affect this scoring either way, given the NL-only finding above.

**Status:** open — Augur-side fix deployed 2026-08-31; this hypothesis is about the upstream behaviour, not the fix. **Evidence added 2026-09-04 (above): Position's basis confirmed, its "one-off" conclusion superseded, Alternative 1 indicated but formally short. Narrowed the same day to NL-only, and a pre-registered probe predicts NL recovery — so the likely resolution is Alternative 1 FALSIFIED on the zone we use, decided by tonight's normal-hour publish rather than by the ≈2026-09-07 calendar trigger.**

### [2026-08-25] EXP-018a: removing the six rolling-stat features (and the three exogenous) beats the 24-feature production set out of sample

**Position (provisional):** The EXP-018 Stage-0 sweep (entry below) found the production feature set carries features that actively hurt: dropping the six rolling stats buys −6.0% MAE / −7.8% quantile score, and the 15-feature **lean** set (rolling + exogenous removed) buys −6.5% / −8.1% with better lower-side coverage. Position: this is a real generalisation gain, not a selection artifact, and it will reproduce on vintages that did not exist when the finding was made. Mechanism claim: absolute-level features (`price_rolling_mean_168h` above all) make tree splits that are calibrated to the training window's price level, which is exactly what breaks when the level drifts — the same failure that produced August's upper-side coverage breach.

**Why this needs its own pre-commit:** Stage 0 was pre-committed as *descriptive*. The lean variant is the best of eight compared on one 263-vintage window, so its effect size is upward-biased by selection. Per ADR-007 ("don't loosen Method when the answer arrives; open a new entry"), the confirming test is fixed here, before the confirming data is looked at — and before any change to `FEATURE_COLUMNS`.

**Alternatives (failure-mode signals):**

1. **Regime-dependent, not universally harmful.** Rolling stats cost us in the volatile 2026 regime but earned their place in calm months — Stage 0 shows a +5.8% *loss* from dropping them in Dec 2025 and a wash in Jan. **Signal:** the fresh-vintage window is calm and shows no gain. Then the answer is regime-conditional features (or a longer training window), not deletion, and this entry is refuted rather than the feature set vindicated.
2. ~~**The real lever is stationarity, not removal.** Lean wins because absolute-level features drift, not because the information is worthless. **Signal:** a stationary reformulation (`price_lag_1h − price_rolling_mean_168h` spreads, price/rolling-mean ratios) beats *both* lean and incumbent in the same harness. Then park the deletion and open EXP-019 for the reformulation.~~ **Refuted same day (EXP-019, `scripts/exp019_stationary_ablation.py`, same 263 vintages):** anchor-relative spreads *tie* plain deletion (lean vs stat_lean_noanchor: QS p=0.405, |error| p=0.160), and re-adding `price_rolling_mean_168h` as the single explicit level column costs significantly (MAE −5.7% → −2.5% vs incumbent, QS p=0.0001). Since raw price lags are also absolute levels and are harmless, drift is at most half the mechanism — redundant smoothed-level columns diluting the split search fits better. Treatment for Stage 1 stays the plain 15-feature lean set.
3. **Selection-bias mirage.** **Signal:** fresh-vintage QS gain is under 2% (against −8.1% in-sample). Do not ship on a shrunken effect; extend the holdout instead.
4. **Exogenous removal is the wrong half.** Lean drops rolling *and* exogenous; the offline harness is if anything biased *toward* keeping exogenous (`consolidate.py` overwrites parquet rows with later vintages, so backtest exogenous is fresher than live). **Signal:** `drop_rolling` alone ≥ lean on fresh vintages. Then ship the rolling deletion only and keep wind/solar/load.

**Method (pre-committed 2026-08-25):**

*Stage 1 — fresh-vintage confirmation, offline, zero production risk.* When ≥14 vintages with `t0 ≥ 2026-08-25` exist in `ml/data/training_history.parquet` (≈2026-09-09, allowing for the 72h realisation lag), run:

```
PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python scripts/exp018_stage0_ablation.py \
    --start 2026-08-25 --end <first-unrealised-day> --jobs 14 \
    --variants full,drop_rolling,drop_rolling_and_exog \
    --out ml/shadow/exp018_stage1
```

Incumbent = `full`. Treatment = whichever of `drop_rolling` / `drop_rolling_and_exog` has the lower in-sample QS (i.e. `drop_rolling_and_exog`, fixed here so the choice is not made on the holdout). IMPLEMENT iff **all four** hold on the fresh vintages:

1. **Skill:** paired DM on per-observation quantile score, H1 treatment better, one-sided **p < 0.10**, HAC bandwidth 71.
2. **Effect size survives:** treatment QS at least **3% better** than incumbent (guards Alternative 3; in-sample was 8.1%).
3. **Calibration:** treatment lower-side and upper-side coverage each **not more than 0.02 worse** than incumbent (raw quantiles, no CQR — same "not worse than incumbent" framing as EXP-014).
4. **Sharpness:** treatment mean Winkler (α=0.20) **≤ 1.05 ×** incumbent.

*Stage 2 — live confirmation after deploy.* Swap `FEATURE_COLUMNS` in `ml/shadow/features_pandas.py`, deploy, then after **14 evaluable post-deploy vintages** in `shadow_state.json:calibration_history` (NOT `eval_log.jsonl` — it mixes 24/48/72h vintages): (1) mean `lightgbm_mae` from `eval_log.jsonl` ≤ the pre-deploy trailing-14-vintage mean; (2) band coverage not worse than the pre-deploy trailing-14 baseline (0.660 for Aug 2026 — a low bar, deliberately: this entry is about skill, augur#19 is the calibration arc); (3) no new alarm classes in the daily commit subjects. PASS → registry `kept`, update ADR-006's feature list + CLAUDE.md. FAIL → revert (one-line: restore the six/nine columns), registry `rolled_back`.

**Addendum 2026-08-28 (data defect, gates unchanged):** the vintage stream broke 2026-08-23..27 — EDH skipped its publish entirely on 08-23 and 08-27, and its overnight catch-up released Augur's gate early on 08-24, so `t0` repeated on 08-23/08-27 and jumped over 08-25, so **`eval_log.jsonl` has a permanent hole at 2026-08-25** (third, after 06-08/06-10). This does not touch Stage 1, which replays its own t0 grid off `training_history.parquet` rather than off shadow vintages. It does touch **Stage 2 check (1)**, whose trailing-14 mean comes from `eval_log.jsonl`: read 14 *present* rows, do not treat the hole as a zero or let it silently shorten the window, and apply the same rule to the pre-deploy baseline so both sides are measured the same way. Per ADR-007 this records a defect in the data the Method reads; the four Stage-1 gates and the three Stage-2 checks are unchanged. A `t0`-advance guard now alarms on the same failure same-day — see `docs/model-progress-log.md` 2026-08-28.

**Revisit trigger:** ≥14 vintages with `t0 ≥ 2026-08-25` in the parquet — ≈2026-09-09. Surface in `/curate`.

**Review by:** 2026-09-16.

**Domain:** EXP-018a, feature engineering, LightGBM production architecture (ADR-006), augur#19.

**Status:** open — pre-committed 2026-08-25, awaiting fresh vintages; **13 of 14 as of 2026-09-14**, so it takes first claim on the next clean run. ⚠️ Branch `exp018-feature-reduction` is **planned, not created** — verified 2026-09-14, it exists neither locally nor on origin. Stage 1 is offline and touches no production path, so it needs no branch until Stage 2 swaps `FEATURE_COLUMNS`.

### [2026-05-29] The Augur method + the M4 arc are publishable if we invest ~2-3 weeks of empirical follow-up

**Position (provisional):** Augur's production stack (ADR-006: LightGBM-Quantile multi-horizon + CQR + horizon-as-feature stacking + 56-day rolling window on NL day-ahead) is *not* novel as a method — every component is in Lago, Marcjasz, De Schutter & Weron (2021) or Nowotarski & Weron (2018). On its own it's a competent application, not a paper. But combined with the five-iteration M4 → EXP-014 narrative arc (`docs/articles/m4-metric-redesign-story.md`) and the promotion method (ADR-007), plus ~2-3 weeks of standard EPF empirical follow-up, the package becomes publishable as an applied methodology paper at *International Journal of Forecasting* practitioner section, IEEE PES workshops, or similar applied-ML venues.

**Alternatives (failure modes):**

1. **Novelty bar still not met** even after the empirical follow-up. LGBM+CQR on NL is well-trod ground; the arc's contribution might be too case-study-y for a methodology venue. **Signal:** a peer skim says "interesting but not a methodology contribution." Fallback: publish the arc as a long-form blog post (Towards Data Science, Medium) instead. ~4-6 hours of light polish, no empirical follow-up needed.
2. **Interest drift before the work is done.** 2-3 weeks of empirical work is non-trivial; we may not have the bandwidth or motivation when the time comes. **Signal:** the review-by date passes without the work being prioritised. Fallback: same as (1) — blog only.
3. **A better venue exists we haven't surveyed.** EPF has its own conference culture (EEM, ENERGYCON), and an applied-ML practitioner audience might find the arc more useful than a methodology audience. **Signal:** finding a better-fit venue during the polish pass. Adjust target accordingly.

**Method (what gets the package to paper-ready, in order):**

When motivated to publish:

1. **Naive baseline + persistence** (rMAE per Lago 2021 — table-stakes for EPF). Add to `scripts/exp012_evaluate.py` or a sibling script.
2. **PIT histograms + reliability diagram** for LightGBM's 80% interval (table-stakes per Nowotarski & Weron 2018).
3. **Multi-window robustness** — re-run the EXP-014 criterion at 7/14/21/30-day windows from the same eval_log; confirm conclusions stable.
4. **Per-feature ablation** — drop each feature group (lags, calendar, wind, solar, load) and measure MAE/CRPS regression; cheap because LGBM trains fast.
5. **Hyperparameter sensitivity** — small grid around `n_estimators × num_leaves × learning_rate`; cheap.
6. **Optional: epftoolbox comparison** — if an NL dataset exists in `epftoolbox`, run LEAR/DNN as the benchmark. If not, skip.
7. **Canonical CRPS** — retrain at 9-19 quantiles, compute proper CRPS, re-run paired DM. Resolves the "3-point mean quantile score" caveat.
8. **Canonical threshold-weighted CRPS** — implement the Gneiting-Ranjan integral form, re-run on the same data. Resolves the "abstention-rewards" issue in the per-quantile-decomposition variant we have.
9. **Rewrite ADR-006 + arc article + ADR-007 into a single methodology paper** with these as the empirical contribution.

Items 1-5 are ~1 week. Items 6-8 are ~1 week. Item 9 is the polishing pass, ~3-5 days. Total ~2-3 weeks of focused work.

**Cheap shortcut (only the blog post):** items 1-3 sharpen the arc article enough for a TDS / Medium long-form, with no method-paper claims. ~3-4 days total. The current draft is already 80% there.

**Revisit trigger:** when we have a 2-3 week window we want to spend on publishing AND we still find the topic interesting. Surfaced by `/curate` at session-end. Independent of the production system — Augur runs whether or not we publish.

**Review by:** 2026-12-31 (loose — there's no external deadline; this becomes stale, not blocking).

**Domain:** Augur publication strategy, methodology dissemination
**Status:** open — backlog entry, no immediate action

---

## Resolved

**Archived to `docs/archive/hypothesis-log-resolved.md`** (2026-10-16), unedited. A citation like `docs/hypothesis-log.md [2026-09-14]` for a resolved entry resolves there. New resolutions move there too, when they are resolved.
