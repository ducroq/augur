# Experiment Backlog

Designed-but-not-run experiments, each written as a **pre-commitment under ADR-007**: Position, Alternatives with falsification signals, Method with gates fixed *before* the data is seen, and cost.

Different from its neighbours:

- **`docs/hypothesis-log.md`** — positions actively awaiting evidence, with a `Review by:` date. An entry here is *promoted into* that file when work starts.
- **`experiments/registry.jsonl`** — experiments already run and decided.
- **GitHub issues** — tasks with an owner, ready to execute.

**The promotion rule, which is what makes these pre-commits rather than notes:** when one of these is picked up, copy the entry into `hypothesis-log.md` `## Open` **verbatim**, adding only the run date. If the Method needs changing before running, that is a *new* entry with a new date — never an edit to this one. A Method fixed on 2026-08-29 and executed in October is still fixed-before-data; a Method edited in October after a peek at the data is not. Provisional `EXP-0NN` numbers below are indicative only; take the next free id from the registry at run time.

**Amendment 2026-08-30 (workflow only — no Method is touched).** The copy-into-`## Open` step assumed a slow one-at-a-time cadence. Seven entries were run in one night on 2026-08-29/30, and the rule was simply skipped — a real process failure, recorded rather than papered over. The rule is therefore widened: pre-commitment may be evidenced **either** by copying the entry into `hypothesis-log.md` `## Open` before the run, **or** — for batch runs — by leaving the Method here untouched and citing the git revision, with a dated entry in `hypothesis-log.md` `## Resolved` once the arc closes. The second route is the stronger evidence, because `scripts/audit_registry.py` check 5 verifies by sha256 that every Method body is byte-identical to its pre-commit revision and exits non-zero otherwise. What remains absolutely fixed is unchanged: **a Method is never edited after its data is seen.**

**Executed entries (EXP-023..029, 036, 037) live in `docs/archive/experiment-backlog-run.md`**, bytes unchanged, with the preamble of the batch they were written under. Check 5 covers both files. To retire an entry, move its section there unedited once it has a registry row; never keep a copy in both.

**Open entries:**

| Entry | Cost | Runs on | Status |
|---|---|---|---|
| EXP-034 fragility-conditioned bands | minutes | CPU | **Added 2026-08-31, not run.** Parked 2026-10-28 with the LightGBM tuning |
| EXP-040 TabPFN-2/3, a tabular foundation model with covariates | GPU min–h (unverified) | b650-gpu | **Added 2026-10-29, not run.** License and feasibility checks first; see its own sequencing note |

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
