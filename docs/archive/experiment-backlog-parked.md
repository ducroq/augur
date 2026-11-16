# Experiment Backlog: parked entries

Pre-commitments that have not been run and are not next, moved here from `docs/experiment-backlog.md` on 2026-11-16 to keep the backlog short. They are still open. Rules and the list of open entries are in `docs/experiment-backlog.md`.

Every section below is byte-identical to its pre-commit revision, and `scripts/audit_registry.py` check 5 proves it: the baseline comes from the backlog at the pinned revision and the current text from here. **Nothing in a section may change.** To pick an entry up, move its section back to the backlog unedited; an addendum moves with its entry and stays below it. Where a section says "this file", it means the backlog, where it was written; the promotion rule it cites is in the backlog's preamble.

Moved with them, from the backlog preamble as it stood on 2026-11-16:

| Entry | Cost | Runs on | Status |
|---|---|---|---|
| EXP-034 fragility-conditioned bands | minutes | CPU | **Added 2026-08-31, not run.** Parked 2026-10-28 with the LightGBM tuning |
| EXP-040 TabPFN-2/3, a tabular foundation model with covariates | GPU min–h (unverified) | b650-gpu | **Added 2026-10-29, not run.** License and feasibility checks first; see its own sequencing note |
| EXP-043 finer calendar / k / shape-level split; EXP-044 weather analogs | minutes; 044 unverified | CPU, situla | **Added 2026-11-16, not run.** Parked the same day, after review and pinning; augur#44 |

**EXP-040 was added 2026-10-29** from Lipiecki & Weron (2026, arXiv:2609.00089), the first outside evidence that a *tabular* foundation model beats Chronos-2 on electricity prices. Its Method was fixed before any TabPFN number existed for Augur.

**EXP-034 was added 2026-08-31** and descends from the EXP-015/016 calibration arc. Its Method was fixed before any data was seen. It's parked with the rest of the LightGBM tuning.

---

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

---

## EXP-040 — A tabular foundation model keeps the diurnal amplitude LightGBM loses, and uses the covariates

**Priority: after the EXP-028a review (due 2026-10-31), so the two covariate results aren't read together.** It runs on stored data and uses no fresh vintages. Provisional id; take the next free one from the registry at run time.

**Source.** Lipiecki & Weron (2026, arXiv:2609.00089); deep-dive in `docs/foundation-models-epf-literature-review.md`. On DE/PL/ES day-ahead over 2021–2025, zero-shot TabPFN beats Chronos-2 by 10–22% CRPS and DDNN-JSU by 12–15%, significant at 1% in every market. TabPFN-2 is within 1.7–4.4% of TabPFN-3. Both are pretrained on **synthetic data only**, so test-window contamination is ruled out by construction. In battery arbitrage TabPFN wins the riskier strategies and DDNN-JSU the risk-averse ones. **Their horizon is day-ahead only**, so nothing there speaks to 25–72h, which is where Augur's product question sits.

**Question.** EXP-037 traced LightGBM's regret loss to amplitude collapse: within-block forecast spread of 14.9 EUR/MWh at 49–72h against a realised 42.7. TabPFN is a tabular regressor like LightGBM, but it is a pretrained in-context learner: its predictive distribution comes from a synthetic prior over generative processes rather than from minimising pinball loss on a short window. Does it keep the diurnal shape beyond 24h, and do the covariates help it rank the cheap hours?

**Position (provisional).** TabPFN with covariates holds a within-block spread **≥ 30 EUR/MWh at 49–72h**, and its mean k6 regret is at or below the EXP-036 profile floor's **in all three horizon blocks**. That is the bar the 2026-10-28 product criterion in `docs/hypothesis-log.md` sets for any live candidate.

**Alternatives (falsification signals).**

1. **Tabular means flat.** Fitting rows of (lags, covariates) → price shrinks toward the conditional median, as LightGBM does. **Signal:** spread at 49–72h below 20 EUR/MWh and k6 regret above the floor at 25–48h and 49–72h. Then the amplitude problem belongs to the tabular framing, not to LightGBM, and the sequence models (Chronos) keep first claim.
2. **The paper's lead is a day-ahead lead.** **Signal:** TabPFN beats bolt-base on regret at 1–24h and loses at 25–48h and 49–72h. Then the paper is consistent with Augur, but the result doesn't transfer to the horizons the dashboard depends on.
3. **The covariate gain is backtest freshness.** Same failure mode as EXP-028a Alternative 4: the harness feeds vintage-overwritten covariates. **Signal:** the lagged-covariate arm loses more than half of the covariate arm's k6 regret advantage over the univariate arm. Then stop; the result can't survive deployment.
4. **Accuracy without regret.** The paper's own split, replayed on NL. **Signal:** the covariate arm beats bolt-base on quantile score but not on k6 regret in at least two blocks. Then it counts against TabPFN under the product criterion, whatever its QS.
5. **Short history erases the advantage.** The paper gave TabPFN 1,449 days of context; Augur's consolidated history starts 2025-09-28, so the earliest vintages see about 10 weeks. **Signal:** TabPFN's regret relative to bolt-base improves monotonically with available history (first vs last third of the vintages, by block). Then the verdict on the early vintages understates it, and a re-run belongs after history has grown, not a rejection.

**Pre-run checks (not gates; any failure stops the entry before data is scored).**

- **License.** The paper marks TabPFN-3 and TabPFN-TS-3 as not free for commercial use and does not mark TabPFN-2. Read the actual licenses. If TabPFN-2's doesn't permit use in Augur's pipeline either, the whole entry is research-only and says so in its registry row.
- **Contamination: confirm, don't assume.** Confirm from the model cards that the checkpoints used are synthetic-only, as the paper states. If one isn't, restrict that arm to vintages after its release date and record the reduced n.
- **Feasibility.** Time one vintage per arm on b650-gpu and on sadalsuud's CPU. Record both; a CPU time above 10 minutes per vintage is reported as a deployment blocker, not a reason to skip the run.

**Method (pre-committed 2026-10-29, before any TabPFN number has been computed on Augur data).** Same **260 paired vintages** (2025-12-05..2026-08-21) and context tape as EXP-035/037.

*Rows.* One fit per vintage per horizon block, pooled over the block's 24 target hours, one row per (day, hour) with hour of day as a feature. This deviates from the paper, which fits one model per hour of day; pooling is chosen because our history gives a per-hour model only 70–330 rows. Features follow the paper's Eq. 5, shifted so every input is known at t0: price at the target hour on the three most recent days available for that block and 7 days before the target; the known-future covariates (the `KNOWN_FUTURE` columns of `scripts/exp028_chronos2_covariates.py`) for the target hour, and their values 1 and 7 days earlier; day of week as a categorical. **Context: every row available at t0 (expanding window)**, which is the paper's choice of using all the context the model takes. Zero-shot, default settings, no tuning.

*Arms.*

```
tabpfn2_covariates        Eq. 5 features with covariates          — PRIMARY (the arm that could ship)
tabpfn3_covariates        same, TabPFN-3                          — research arm, same gates
tabpfn2_univariate        price lags + calendar only
tabpfn2_cov_lagged        covariates as known at t0 (Alternative 3)
references                profile floor (naive_profile, 5 day types), carry, LightGBM full, chronos-bolt-base
```

*Scoring.* Per 24-slot block with `score_block` from `scripts/exp037_rank_metric.py` (k = 3 and 6, stable-sort ties, partial blocks dropped, never padded, identical surviving block set for every arm). Quantile score from the p10/p50/p90 of each arm's predictive distribution. Within-block forecast spread (max − min of p50) per block.

**Gates** (applied to the primary arm; the TabPFN-3 arm is gated identically and reported beside it).

- **G1 — product.** Mean k6 regret ≤ the profile floor's in **each** of the three blocks. Paired DM per block (HAC lags 3, one-sided) is reported as strength of evidence and does not gate.
- **G2 — amplitude.** Spread at 49–72h ≥ 30 EUR/MWh. Reported beside LightGBM's 14.9 and bolt-base's 35.7.
- **G3 — covariates.** `tabpfn2_covariates` beats `tabpfn2_univariate` on k6 regret pooled over blocks. If `tabpfn2_cov_lagged` loses more than half of that gain, Alternative 3 is confirmed and the entry stops there.
- **Reported, never gated:** QS against every reference, k3 regret, Spearman, bolt-base on the identical blocks, and the Alternative 5 history split.

**Pre-commitment boundary.** Stored-data corroboration only. Passing G1 earns a live-shadow entry of its own on fresh vintages under the 2026-10-28 criterion; it doesn't move the EXP-021a queue or touch production.

**What it would change.** G1 and G2 pass on the primary arm → TabPFN-2 joins Chronos as a live-shadow candidate, and the first one that uses Augur's exogenous data. Only the TabPFN-3 arm passes → the result stands as research until its license is settled. Alternative 1 fires → the amplitude problem is the tabular framing, and the covariate route runs through Chronos-2 (EXP-028a) only. Alternative 2 fires → the paper is filed as day-ahead evidence that doesn't extend to 72h.

**Cost.** Unverified until the feasibility check: 260 vintages × 3 blocks × 4 arms of in-context fits on up to ~8k rows each, which should be GPU minutes to low hours on b650-gpu. No fresh vintages, no production path touched.

---

## Addendum 2026-10-29 to EXP-040 — feasibility and definition defects, found by pre-commit review before any TabPFN number existed

The EXP-040 section above stays byte-identical. `scripts/audit_registry.py` check 5 pins it at `d53af7a`, and per this file's promotion rule a Method needing change before its run gets a new dated record, never an edit. A `/review-changes` round on 2026-10-29, the same day, found the defects below before anything was run or scored. This addendum **supersedes the section above where they conflict.** Gate thresholds and Alternative signals are unchanged; no gate is removed. What changes is the data source, the source of the lagged arm, and definitions that couldn't be executed as written.

1. **Data source (blocker).** The section says both "same … context tape as EXP-035/037" and "every row available at t0 (expanding window)". Both can't hold: `ml/shadow/exp021_foundation/contexts.parquet` stores price only, at most 56 days per vintage and 73 hours for the earliest. **Corrected:** the 260 stored vintages supply only the list of `t0` anchors and the realised prices for scoring, as in EXP-037. Features come from the fundamentals parquet EXP-028 reads (`ml/data/training_history_fundamentals.parquet`; copy at `~/lab/augur/data/`), loaded with `load_frame_ext` from `scripts/exp020_fundamentals_ablation.py`. Covariates take their stored values, with EXP-028's vintage-overwrite optimism.
2. **Rows.** For a target at slot *h* of block *b* = ⌈h/24⌉: price at target − 24·k elapsed hours (UTC, not clock hour, so DST days don't shift it) for k ∈ {b, b+1, b+2}, and at target − 168 h; each known-future covariate at the target, target − 24 h and target − 168 h; hour of day and day of week (Europe/Amsterdam) as categoricals. Every price lag is ≥ 24·b h back, so it's known at t0 for every slot in the block. Training rows use the same offsets, and their target is ≤ t0. **Rows with any missing feature are dropped, never imputed.** The univariate arm trains on the *same* rows as the covariate arm, so G3 isolates the covariates.
3. **Vintage set.** The covariates start 2025-11-30..2025-12-02, not on the price parquet's 2025-09-28. A vintage is scored only if, for every block, t0 minus the first complete training target is ≥ 28 × 24 h (a span, not a row count). With wind from 2025-12-02 23:00 and a 168 h lag, the first complete row falls around 2025-12-09, so the first scorable t0 is around 2026-01-07: roughly 33 of the 260 vintages drop. **Alternative 5's premise changes accordingly:** the earliest scored vintages see about 4 weeks of complete rows, not 10, so the history-split signal is read across that range. All arms are scored on the identical surviving vintages and blocks, and n is reported. EXP-037 itself scored 253 vintages and 755 blocks after its intersection; this one will be smaller.
4. **Spread (G2 and Alternative 1).** "Max − min of p50" is wrong. The comparators the section quotes (LightGBM 14.9, bolt-base 35.7, realised 42.7) are the **mean over vintages of the within-block standard deviation of p50**, from `amplitude()` in `scripts/exp037_diagnostics.py`. Under max − min the incumbent itself would pass G2 (44.9). **Corrected:** spread is `amplitude()`'s measure. The thresholds stay as written (G2 ≥ 30, Alternative 1 < 20).
5. **Profile floor.** It's not "5 day types". `naive_profile_prediction` (`ml/shadow/evaluate_shadow.py`) is the mean of the same hour over the last 5 days of the matching day type, out of the 3 that `_day_type` distinguishes.
6. **Source for the lagged-covariate arm.** Nothing in augur builds it, but the energydatahub repo archives every EDH publish (`data/YYMMDD_HHMMSS_<feed>.json`, encrypted with the same keys, from 2025-12-01; about 365 each for load, wind and solar). `tabpfn2_cov_lagged` takes, for each covariate, the last publish at or before t0, with HMAC verified before decryption. The run records the column → feed mapping for every `KNOWN_FUTURE` column. A column with no archived feed is dropped from **all** covariate arms, so they stay comparable, and is named in the report. The arm and G3's stop rule stay as written.
7. **G3 with no gain.** If `tabpfn2_covariates` doesn't beat `tabpfn2_univariate` on pooled k6 regret, G3 fails and the half-the-gain rule doesn't apply.
8. **Id.** EXP-040 is fixed, not provisional. The audit keys check 5 on it.
9. **Source paragraph.** The 10–22% and 12–15% CRPS gains are TabPFN-3's. The primary arm, TabPFN-2, is 8–19% better than Chronos-2 and 10–11% better than DDNN-JSU (Tables 3–5).
10. **Declared deviations from the paper's Eq. 5:** target-hour values instead of full 24-hour vectors, pooled per block instead of one model per hour, and no EUA/TTF/Brent/API2 columns.

---

## EXP-043 — A finer calendar, more days, or a shape/level split ranks cheap hours better than the shipped day-type rule

**Added 2026-11-16 on the engineer's request to register the similar-day route for later, before any challenger arm below was computed.** Offline, price-only, no fresh vintages consumed, no production path touched. The id is fixed; check 5 keys on it.

**Sequencing.** Runs any time. Whatever it finds, the shipped rule does not change before EXP-041 is read: EXP-041's population pairs the FM with the *shipped* profile forecast, and a rule change inside that population would mix two estimators.

**Source.** The similar-day family in electricity price forecasting (`docs/literature.md`, "Similar-day and analog methods"). Its calendar-only form treats Monday, Saturday and Sunday apart from the mid-week days; the shipped rule (ADR-009) has three types: weekday, weekend, NL holiday. EXP-036 chose that rule (`N5_dt`) among seven arms **on MAE**, before the product criterion existed, and never crossed day-type matching with any `k` other than 5.

**What is known before writing, so this is part-blind.** EXP-036 (t0 2025-12-08..2026-08-21, MAE): N5 26.10, N7 25.20, N5_decay 25.92, N5_dt 24.35, so more days helped without matching and matching helped at k = 5. The incumbent's own regret is known on later vintages (EXP-038: k6 7.81 at h49–72 on 60 vintages; `ml/shadow/regret_log.jsonl` nightly since 2026-09-14). No challenger below has been computed on any window, on any metric.

**Question.** Cheap-hour regret depends on the *shape* of a 24-slot block and is blind to its level. Does a rule that matches shape more closely (finer day types) or averages it over more days rank the cheap hours better, and can it do so without the stale level that reaching five Mondays back brings?

**Position (provisional).** At least one challenger has lower pooled k6 regret than the shipped rule on the discovery window, and the selected one keeps that on the confirmation window in every block. Expected order: `SL5` best, `N5_dt5` better on regret and worse on MAE, `N7_dt` a small gain.

**Definitions, fixed here.**

- **Incumbent `R`.** `ml.shadow.update_profile.predict_hour` as shipped on 2026-11-16: `naive_profile_prediction` (5 matching days of three types, local calendar, whole UTC days back from `naive_source_timestamp`, at most 56 days) with its weekend-pool fallback for a holiday it cannot fill. The holiday set is built as `update_profile` builds it.
- **Five-type calendar `dt5`**, on the Europe/Amsterdam date: Monday; Tuesday–Thursday; Friday; Saturday; Sunday or NL holiday. A holiday is the last type whatever its weekday.
- **Walk.** Every challenger walks back exactly as `naive_profile_prediction` does (same start, whole days, at most 56) and keeps a candidate iff its type matches the target hour's and its price is present. It stops at `k`. Fewer than `k` means undefined: dropped, never filled.
- **`N7_dt`**: `R` with k = 7 (the fallback pool unchanged).
- **`N5_dt5`**: k = 5 under `dt5`.
- **`SL5`**: let `F` be `N5_dt5`'s five sources and `G` the five sources `R` uses for the same hour. With `c(x)` the mean price over the 24 hours `x−23h..x` (all 24 required), `SL5 = mean over F of [p(x) − c(x)] + mean over G of c(x)`: shape from the finer calendar, level from the shipped rule's days. Where `F = G` it equals `R`.

**Alternatives (falsification signals).**

1. **Recency beats resemblance.** Five same-type days reach five weeks back for four of the five types, and the price shape drifts with the season faster than the weekday pattern repays. **Signal:** `N5_dt5` and `SL5` both have higher pooled k6 regret than `R` on the discovery window. Then the three-type calendar is as fine as this window supports, and the calendar axis is closed.
2. **It is only averaging.** **Signal:** `N7_dt` is selected. Then the finding is `k`, not the calendar, and it says nothing for the similar-day literature's day classes.
3. **Selection noise.** One arm of three chosen on about 257 vintages can win by chance. **Signal:** the selected arm fails G1 or G2 on the confirmation window. Then the rule stands and the discovery ranking is recorded as noise.
4. **Shape improves, level worsens.** **Signal:** G1 and G2 pass and G3 blocks. Then the result is a ranking-only finding; a dashboard that also shows prices cannot take it as it is.

**Method (pre-committed 2026-11-16).**

- **Data.** `price_eur_mwh` from the newest parquet snapshot in `~/lab/augur/data/` at run time (name and sha256 recorded). `t0` = every day at 23:00 UTC. `y` is the same column at the target hour. Every source is at or before `t0` by the walk's construction. Scored with `score_block` and the block rules of `scripts/exp037_rank_metric.py` (24 slots, k = 3 and 6, stable-sort ties, partial blocks dropped), on the blocks where all four arms are defined in all 24 slots.
- **Harness check, before any challenger is read.** The strict `N5_dt` of EXP-036, built by this runner on EXP-036's tape and row set with EXP-036's own holiday set (`scripts/exp036_profile_floor.py:holiday_dates`), reproduces `baselines.N5_dt.mae` 24.3465 (`ml/shadow/exp036_profile_floor/summary.json`; `N5_dt_mae` in the registry) to four decimals. If not, stop and fix the harness.
- **Stage A, discovery: t0 2025-12-08..2026-08-21.** Pooled mean k6 regret (all complete blocks, the three block types together) for `R` and the three challengers. If no challenger is below `R`: stop, the rule stands, no Stage B read. Otherwise, among the challengers below `R` only, select the simplest (order `N7_dt`, `N5_dt5`, `SL5`) whose pooled k6 regret is within 1% of the best challenger's.
- **Stage B, confirmation: t0 from 2026-08-25 to the last t0 whose 72 hours are all in the snapshot.** The selected challenger `C` against `R`, read once:
  - **G1, product form.** In each of the three blocks, mean k6 regret of `C` is at or below `R`'s.
  - **G2, evidence.** Paired `ml/shadow/metrics.py:diebold_mariano` with `loss_a` = `C`'s per-block k6 regret and `loss_b` = `R`'s, blocks pooled and ordered by `t0` then block, `hac_lags = 5` (h49–72 of one vintage scores the same 24 hours as h1–24 two vintages later, 4 positions on). Passes iff the mean difference is negative and one-sided p < 0.10.
  - **G3, level guardrail.** MAE of `C` on the common rows is not more than 2% above `R`'s.
- **Reported, not gated.** Every arm on both windows (k3, k6, Spearman, MAE, per block); the per-block DM; the pooled k6 advantage against EXP-037's 1.0 EUR/MWh materiality bar, a pass below it being recorded as real but small; the count of rows each arm leaves undefined.
- **Outcome.** All three gates pass: `C` is a candidate to replace the shipped rule, which is an ADR-009 amendment and the engineer's call, with bands regenerated by the shipped own-error procedure and their coverage read live. Anything else: the rule stands.

**Caveat fixed in advance.** Snapshot prices are final; the live rule can read a provisional price that a later EDH file corrects. The nightly regret log is the check on that, not this experiment.

**Cost.** Minutes, CPU, situla. The runner (`scripts/exp043_*.py`) is written before the read, and its docstring states this pre-commitment.

---

## EXP-044 — Choosing the five neighbour days by forecast weather ranks cheap hours better than choosing the five most recent

**Added 2026-11-16 on the engineer's request to register the similar-day route for later, before any analog number existed for Augur.** Offline, no fresh vintages consumed, no production path touched. The id is fixed; check 5 keys on it.

**Sequencing and prerequisites.** Independent of EXP-041 and EXP-043. Needs, on situla: an `energydatahub` clone current to the run date (the local one stood at 2026-10-28 when this was written) and the decryption keys in the environment (absent from the shell this was written in). Step 0 decides whether the experiment can run at all.

**Source.** The similar-day literature's second level picks neighbours by a distance on features instead of by recency (`docs/literature.md`, "Similar-day and analog methods"; read from search snippets only, 2026-11-16).

**What is known before writing.** (1) The shipped rule sees no weather: it cannot anticipate a wind front or a clear day inside its 72 hours. (2) EXP-019/020/024/029 refuted added level columns, exogenous ones included, **as features for LightGBM's conditional mean**. Nothing has tested them **as similarity keys** for an estimator that predicts only prices that occurred; that is a different use, and EXP-028 (Chronos-2 with covariates, 8.3% better quantile score than the same model univariate, offline on vintage-overwritten covariates, and failing its coverage gate; it says nothing against the profile floor) already showed the refutation is model-specific. (3) The harness's covariates are vintage-overwritten, fresher than the live job sees (`ml/data/consolidate.py`: later files overwrite earlier ones; EXP-028a Alternative 4, ratio 1.84). (4) In the parquet snapshot of 2026-11-14 20:22 UTC every forecast column ends by 2026-11-15 22:00 UTC, about 26 hours ahead, and `solar_gen_forecast_mw` ends before the snapshot time. So residual load as known at `t0` does not reach the blocks where the product question sits (25–72h, augur#30), and the parquet cannot say how far the raw wind and solar forecast files reach. That is unmeasured: Step 0.

**Question.** Within the same day type and the same 56 days, do the five days whose weather most resembles the *forecast* for the target block rank its cheap hours better than the five most recent days?

**Position (provisional).** Yes where the weather forecast reaches: the analog arm has lower k6 regret than the shipped rule in every testable block, the gain sits in blocks whose forecast weather differs most from the recent days', and it survives using only what was known at `t0`.

**Definitions, fixed here.**

- **Incumbent `R`**: as in EXP-043, the rule shipped on 2026-11-16.
- **Weather vector.** For a 24-slot block, the 48 values of `wind_speed_80m` and `solar_ghi` (the two weather columns production's feature builder requires; load is carried by the day type). Each variable is z-scored with the mean and standard deviation of its hourly values over the 56 days ending at `t0`, taken from the same values the arm's vectors use (known-at-`t0` for `A_known`, final snapshot for `A_overwritten`).
- **Known at `t0`.** A value built from EDH files whose filename timestamp is at or before `t0` (a stamp without a zone is read as UTC, the conservative reading: a local stamp is one or two hours earlier in UTC), parsed by `consolidate`'s own parsers, later files overwriting earlier ones and stopping at `t0`. The target block's vector is therefore a forecast; a past block's vector is whatever those files last said of it.
- **Candidates.** For a target hour, exactly the rule's: the walk of `naive_profile_prediction` (matching three-type day type, price present, at most 56 days), without stopping at five. Candidate `j` lies a whole number of days `Δj` before the target hour; its block is the target's 24 slots shifted back by `Δj`. A candidate whose shifted block lacks any of the 48 values is not eligible.
- **`A_known` (PRIMARY).** The mean price over the 5 eligible candidates with the smallest Euclidean distance between the target block's vector and the candidate block's, both as known at `t0`; ties go to the more recent. Fewer than 5 eligible: undefined, dropped. A holiday the rule fills by its weekend-pool fallback uses the same pool here.
- **`A_overwritten`.** The same with vectors from the final snapshot. It measures the backtest optimism and is never a candidate.
- **`P_all`.** The mean price over all eligible candidates (at least 5): the control for averaging more days.
- **`A_price`.** The same selection with a price-only distance: Euclidean between the 24 prices `t0−23h..t0` and the same window shifted back by `Δj`. The control for selection without weather.

**Alternatives (falsification signals).**

1. **Inert as a key too.** EXP-020's conclusion extends from features to similarity. **Signal:** G2 fails for `A_known` and `A_overwritten` alike. Then weather is closed for this estimator at this window, a fifth independent negative, and it should be recorded as one.
2. **A freshness artifact.** **Signal:** `A_overwritten` passes G1 and G2 and `A_known` does not. Then the gain is a backtest artifact that cannot survive deployment.
3. **It is only averaging.** **Signal:** `P_all`'s pooled k6 regret is at or below `A_known`'s. Then the finding belongs with EXP-043's `k`, not with weather.
4. **Recent prices already carry it.** **Signal:** `A_price` is at or below `A_known`. Then selection helps and weather is not shown to; re-title the finding instead of reporting an exogenous win.
5. **Shape improves, level worsens.** Neighbours up to 56 days old carry an old price level. **Signal:** G1 and G2 pass and G4 blocks. Then it is a ranking-only result, and a level correction (EXP-043's `SL5` construction) is a new entry.

**Method (pre-committed 2026-11-16).**

- **Step 0, feasibility, before any price is scored.** Build the known-at-`t0` values for every `t0` (23:00 UTC daily) from 2026-02-01 (the EDH archive starts 2025-12-01; the first `t0` with 56 days of candidates behind it falls in late January) to the last `t0` whose 72 hours are realised in the newest parquet snapshot at run time. Report, per block, the share of vintages whose 24 slots all have both variables. A block is **testable** iff that share is at least 0.90. An untestable block is reported as such and never filled from later files. If neither h25_48 nor h49_72 is testable: stop, record the horizons the files do reach, and score nothing. A similarity on other columns is then a new entry.
- **Population.** The vintages of Step 0, testable blocks only, blocks where `R` and all four arms are defined in all 24 slots. `y` and all prices are `price_eur_mwh` from that snapshot (name and sha256 recorded). Scoring as in EXP-043: `score_block`, 24 slots, k = 3 and 6, partial blocks dropped. No parameter is fitted, so there is no split; the window is read once.
- **G1, product form.** In each testable block, mean k6 regret of `A_known` is at or below `R`'s.
- **G2, evidence.** Paired `diebold_mariano` with `loss_a` = `A_known`'s per-block k6 regret and `loss_b` = `R`'s, testable blocks pooled, ordered by `t0` then block, `hac_lags = 5` (as EXP-043: the same realised hours recur up to 4 positions on). Passes iff the mean difference is negative and one-sided p < 0.10.
- **Minimum data, applied before G1–G4 and taking precedence over them.** A testable block with fewer than 28 scored vintages is reported as insufficient and leaves the pool; "testable block" in G1–G4 means a block that survives this filter. If no h25_48 or h49_72 block survives, the verdict is **insufficient data**: nothing passes or fails, no shadow follows, and a longer window is a new entry.
- **G3, attribution.** `A_known`'s pooled mean k6 regret is below both `P_all`'s and `A_price`'s.
- **G4, level guardrail.** MAE of `A_known` on the common rows is not more than 2% above `R`'s.
- **Reported, not gated.** Every arm per block (k3, k6, Spearman, MAE); the share of `A_overwritten`'s pooled advantage over `R` that `A_known` keeps; the same comparison on **weather-change blocks**, the top third of blocks by distance between the target vector and the mean vector of `R`'s five neighbours, against the rest; the pooled advantage against EXP-037's 1.0 EUR/MWh bar.
- **Outcome.** G1–G4 pass: `A_known` is a candidate for a live shadow arm, which needs its own entry and the engineer's call (a new step in the daily job is REVIEW-class). G1 and G2 pass and G3 fails: record what Alternative 3 or 4 says; no shadow on the weather claim. Anything else: parked or rejected by the signal that fired.

**Cost.** Unverified. Step 0 parses about a year of EDH files once per file and snapshots at each `t0`; the scoring is minutes. CPU, situla. The runner (`scripts/exp044_*.py`) is written before the read, and its docstring states this pre-commitment.
