# Experiment Backlog

Designed-but-not-run experiments, each written as a **pre-commitment under ADR-007**: Position, Alternatives with falsification signals, Method with gates fixed *before* the data is seen, and cost.

Different from its neighbours:

- **`docs/hypothesis-log.md`** — positions actively awaiting evidence, with a `Review by:` date. An entry here is *promoted into* that file when work starts.
- **`experiments/registry.jsonl`** — experiments already run and decided.
- **GitHub issues** — tasks with an owner, ready to execute.

**The promotion rule, which is what makes these pre-commits rather than notes:** when one of these is picked up, copy the entry into `hypothesis-log.md` `## Open` **verbatim**, adding only the run date. If the Method needs changing before running, that is a *new* entry with a new date — never an edit to this one. A Method fixed on 2026-08-29 and executed in October is still fixed-before-data; a Method edited in October after a peek at the data is not. Provisional `EXP-0NN` numbers below are indicative only; take the next free id from the registry at run time.

**Amendment 2026-08-30 (workflow only — no Method is touched).** The copy-into-`## Open` step assumed a slow one-at-a-time cadence. Seven entries were run in one night on 2026-08-29/30, and the rule was simply skipped — a real process failure, recorded rather than papered over. The rule is therefore widened: pre-commitment may be evidenced **either** by copying the entry into `hypothesis-log.md` `## Open` before the run, **or** — for batch runs — by leaving the Method here untouched and citing the git revision, with a dated entry in `hypothesis-log.md` `## Resolved` once the arc closes. The second route is the stronger evidence, because `scripts/audit_registry.py` check 5 verifies by sha256 that every Method body is byte-identical to its pre-commit revision and exits non-zero otherwise. What remains absolutely fixed is unchanged: **a Method is never edited after its data is seen.**

**An entry lives in exactly one of three files**, and check 5 covers all three:

- here, while it is next or running;
- `docs/archive/experiment-backlog-parked.md`, while it is pre-committed but not next. Parking is a move, not a decision: the Method stays fixed and pinned. To pick one up, move its section back here unedited (with any addendum, in the same order);
- `docs/archive/experiment-backlog-run.md`, once it has a registry row.

Every move is the whole section, bytes unchanged; never keep a copy in two files.

**Open entries:**

| Entry | Cost | Runs on | Status |
|---|---|---|---|
| EXP-041 FM vs the profile rule on live vintages (replaces the [2026-11-07] skill gate) | minutes | CPU, situla | **Added 2026-11-08, not run.** Waits on 14 qualifying FM vintages |
| EXP-034 fragility-conditioned bands | minutes | CPU | Parked file. Not run; parked 2026-10-28 with the LightGBM tuning |
| EXP-040 TabPFN-2/3 (with its 2026-10-29 addendum) | GPU min–h (unverified) | b650-gpu | Parked file. Not run; license and feasibility checks first |
| Candidates: gas-parity threshold; fixed clock-window regret floor | minutes | CPU, situla | **Not pre-committed.** Ideas only, in augur#43 |

---

## EXP-041 — Chronos-Bolt beats the profile rule, the dashboard's incumbent, on point error without worse band coverage, on live vintages

**Added 2026-11-08 on the engineer's decision of that day, before any FM vintage counted under it was read.** It replaces the skill gate and the calibration guardrail of `docs/hypothesis-log.md` [2026-11-07], whose comparator, production LightGBM, has been a shadow since ADR-009. That entry's Method text is unchanged; it stays the record of the old gate. EXP-021a Stage 3 said its criterion would be re-derived against "the incumbent of the day", and since 2026-11-07 that is the profile rule. Without this entry the FM met the incumbent only on k6 regret, which is not a proper scoring rule ([2026-10-28], related evidence) and should sit beside a proper-score gate, never replace it. The id is fixed; check 5 keys on it.

**What is known before writing, so this is part-blind.** Offline, EXP-038 (60 vintages): bolt-base MAE 37.5 vs `lean` 45.6, and at h49–72 its k6 regret only ties the profile floor (7.87 vs 7.81). EXP-036: production `p50` sits 12.4% behind the floor offline. FM MAE against the floor was not computed in either. No live FM vintage with `cqr_n_calib_days ≥ 3` existed when this was written (`scripts/vintage_counts.py`: 0 of 14).

**Position (provisional).** On live vintages, Chronos-Bolt's `p50` has lower absolute error than the profile rule's shipped forecast, and its shipped bands are not worse covered on either side.

**Alternatives (falsification signals).**

1. **The FM wins on error and loses on ranking.** It improves MAE by flattening, as LightGBM did (EXP-037). **Signal:** the skill gate passes and the [2026-10-28] product criterion fails in at least one block. Then no swap: both are required.
2. **The rule's own-error bands are the stronger bands.** They are fitted on the rule's last 28 days of errors per block, while the FM's CQR window is shorter. **Signal:** the guardrail blocks with the skill gate passing. Then the band choice is a separate question (an FM `p50` with the rule's bands is a new entry, not a reading of this one).
3. **The offline win was a LightGBM-relative win.** **Signal:** the FM beats LightGBM (reported below) and fails the skill gate against the rule. Then EXP-021's result does not transfer to the incumbent that matters.

**Method (pre-committed 2026-11-08).**

- **Population.** The first 14 FM vintages in date order that meet all of: (a) the [2026-11-07] FM conditions: every row has `cqr_n_calib_days ≥ 3`, and after keeping the last row per (`eval_day`, `timestamp_utc`) in `fm_state.json:calibration_history`, 72 unique timestamps all have `realized`; (b) a shipped profile forecast for the same vintage: the `static/data/augur_forecast_profile.json` in the daily commit for that `eval_day`, whose `metadata.t0` equals the FM vintage's `t0_utc`, with `forecast`, `forecast_lower` and `forecast_upper` present on the same 72 timestamps. A vintage failing (b), such as one where the profile step was skipped, is excluded and listed in the verdict, never for its result. `y` is the FM row's `realized`. Observations are ordered by `t0`, then horizon. No interim read, and the window isn't extended.
- **Skill gate.** `ml/shadow/metrics.py:diebold_mariano` with `loss_a = |y − FM p50|`, `loss_b = |y − profile forecast|`, per observation, `hac_lags = 71`, one-sided α = 0.10. Passes iff the mean difference is negative and p < 0.10.
- **Calibration guardrail.** Lower-side coverage (share of `y ≥ lower`) and upper-side coverage (share of `y ≤ upper`), FM `p10`/`p90` after CQR against the profile's `forecast_lower`/`forecast_upper`, on the same population. Blocks if FM coverage is more than 0.02 below the rule's on either side. Winkler score and median width are reported, never gated (ADR-007).
- **Reported, not gated.** The same DM and coverage against production LightGBM on the vintages of this population that also meet the [2026-11-07] pairing, and the profile JSON's `n_holiday_fallback_hours` per vintage.
- **Swap.** Requires EXP-021a Stage 1 passed as written, this skill gate passed, no guardrail block here, and the [2026-10-28] product criterion passed. The judgement on operational surface stays the engineer's.

**Revisit trigger.** 14 such vintages exist. Read before the first leaves the FM's 30-day `calibration_history`; the profile side lives in git history and doesn't expire.

**Cost.** Minutes, CPU, situla, from committed state and git history. The runner (`scripts/exp041_*.py`) is written before the read, and its docstring states this pre-commitment.

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
