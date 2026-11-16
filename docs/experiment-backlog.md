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
