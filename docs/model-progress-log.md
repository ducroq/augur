# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-11-08 (latest) — The first ADR-009 night skipped the profile step; the FM gate moves to the profile rule (EXP-041)

**What happened.** The 2026-11-07 run pulled the ADR-009 commit at `daily_update.sh:62`, resumed misaligned in the changed script (bash reads by byte offset) and never ran `update_profile`. The unset `PROFILE_RC` read as OK, so there was no alarm. The dashboard kept the manual-deploy forecast (`t0` 11-07 22:00). Fix: the job re-execs once on its pulled script, and `[ALARM: profile forecast t0 behind shadow]` asserts on the artifact. Deployed to sadalsuud by hand pull before the 2026-11-08 run started (gotcha-log 2026-11-08, RUNBOOK "Monitoring").

**Decision (engineer, 2026-11-08).** The FM's skill gate and band guardrail compare against the profile rule, the incumbent since ADR-009, not the LightGBM shadow: EXP-041 in the backlog, runner `scripts/exp041_fm_vs_profile.py`. LightGBM is reported, not gated. No model or forecast changed.

**Instruments.** `scripts/vintage_counts.py` replaces the hand-counted trigger table (the 11-06 count read eval days, 7, where 6 vintages were fully realised). Audit check 6 pins all 17 pre-committed hypothesis-log Methods.

## 2026-11-07 — The dashboard shows the day-type profile rule (ADR-009)

**What changed.** A new step, `python -m ml.shadow.update_profile`, runs right after `update_shadow` on its `t0`. It writes `static/data/augur_forecast_profile.json` (shadow schema, consumer fields), and `dashboard.js:loadAugurForecast` now reads it. LightGBM keeps running unchanged as a shadow. Failure is `[ALARM: profile forecast failed rc=N]`. Why: live k6 regret 11.6/11.0/10.0 (LightGBM) vs 5.8/5.6/5.9 (rule) per block since 2026-09-14 (ADR-009, augur#37).

**Choices worth keeping.** The rule is `naive_profile_prediction` itself, so the dashboard shows the scored arm. Bands are P10/P90 of the rule's own errors over the last 28 days per block. A built-in NL calendar covers the forecast window, because the parquet's holiday flag stops at `t0`; it's pinned to the parquet's flagged dates. Holidays with fewer than 5 earlier holidays in reach (Christmas, New Year) pool with weekends instead of leaving a 24h hole.

**Rehearsal (situla, sadalsuud's parquet and state, `t0` 2026-11-07T22:00Z).** 72 of 72 hours, 1.2s, 672 residuals per block. Band P10/P90 about −85/+120 EUR/MWh, mean width 207 vs LightGBM's 106. Rendered in headless Chromium with the legend and caption line. The seed file committed with the change is this run's output.

## 2026-11-07 — Chronos-Bolt live shadow built (EXP-021a Stage 3)

**The dashboard reads nothing new.** A new last step in the shadow block, `python -m ml.shadow.update_fm`, forecasts on production's `t0` and writes `static/data/augur_forecast_fm.json`, `ml/models/shadow/fm_state.json` and, through `regret.py --model-arm fm`, `ml/shadow/fm_regret_log.jsonl`. The forecast JSON is committed, so Hugo serves it publicly like its siblings. The step is non-fatal, runs under `timeout -k 30 900`, and reports `[ALARM: FM shadow failed exit N]`.

**Choices worth keeping.** The context ends at t0 − 1h because production's features are shifted one row, the offset EXP-038/039 measured. Weights are pinned to revision `5d9f166` and loaded offline. FM regret has its own log because a block is logged once, so a shared row would hold a null for good after one failed night. `augur_forecast_fm.json` needed a `.gitignore` negation: `git add` on an ignored path fails, and under `set -e` that would have lost the production commit.

**Rehearsal (situla, 2026-11-07, Python 3.12, clean bootstrap from `requirements.lock`, sadalsuud's parquet and state).** One real forecast took 6.4s including imports and model load, peak 1.4 GB, offline, with lightgbm and torch in one process. Same schema, `t0` and 72 timestamps as production; context 1319 present, 24 missing. No existing pin changed (33 added, venv 1.7G, no CUDA packages). torch stays out of `requirements.txt` because Netlify may install that file (augur#35). This doesn't yet cover sadalsuud's own venv.

**Reading it.** The first vintages run at q = 0, so FM band width isn't comparable with production's until CQR warms up. See the 2026-11-07 addendum in `docs/hypothesis-log.md` [2026-08-29] and the promotion criterion at [2026-11-07].

## 2026-11-06 — CQR stops scoring its own widening

`compute_cqr_q` scored the stored bands, which already included each day's `q`. EXP-015 recorded this on 2026-06-12, but it dropped out of the index on 2026-10-16 and its cost was never measured. After a wide spell the scores went negative, `q` clipped to 0 and the band collapsed: `last_cqr_q` went from 72 on 10-29 to 0 from 11-03.

The fix scores the sorted, unwidened quantiles (`unwidened_bands`). `p50`, the forecast and the widening step don't change. On a 130-day replay, pooled band coverage goes from 0.703 to 0.788, lower side 0.852 to 0.887, upper side 0.851 to 0.901. Median width rises 17% (113 to 132 EUR/MWh) and Winkler is level (216.2 to 214.6). Since the 2026-09-13 anchor shift width rises 24% (144 to 178) with Winkler level; on November's 288 rows it rises 84% and Winkler worsens (185.7 to 198.2). This removes a defect; it doesn't improve the score. The pre-committed guardrail passes by construction, so it isn't evidence: `docs/hypothesis-log.md` [2026-11-06]. Live check after 28 post-deploy vintages.

**Reading across a deploy:** coverage in `eval_log.jsonl` and band width in `calibration_history` change at the deploy date for this reason, not because the model changed. The confound also touches augur#19 and any before/after coverage comparison. On the first run `q` steps from 0 to about 27. A rollback would probably collapse `q` for up to 7 days, because the old code would score the newly wider stored bands (reasoned, not measured).

## 2026-10-28 — Live cheap-hour regret: hours 25–72 were never scored, and the profile floor ranks twice as well everywhere

**No model or forecast logic changed.** A new nightly step, `python -m ml.shadow.regret`, appends k3/k6 cost regret per 24-slot horizon block (h1_24, h25_48, h49_72) for the shipped `p50`, the carry and the EXP-036 profile to `ml/shadow/regret_log.jsonl`. It is its own step in `daily_update.sh`, and a failure rides the subject as `[ALARM: regret pass failed rc=N]`. It serves the product criterion pre-committed in `docs/hypothesis-log.md` [2026-10-28].

**Why it could not live in `eval_log.jsonl`.** A day is logged once, as soon as 24 hours are realised, so every eval row covers horizons 1–24 (`naive_min/max_horizon_h` = 1/24 on every recent row). Hours 25–72, where EXP-037 found the amplitude collapse, have never been scored live. Every live MAE or skill number quoted from `eval_log` is an h1_24 number.

**First reading** (backfilled from the committed states of 2026-10-14 and 2026-10-28; vintages with t0 ≥ 2026-09-14 where all three arms are complete; 36–38 per block; mean k6 regret, EUR/MWh):

| block | LightGBM | carry | profile | LightGBM amplitude | realised amplitude |
|---|---|---|---|---|---|
| h1_24 | 12.32 | 10.68 | 6.37 | 31.6 | 51.8 |
| h25_48 | 11.03 | 11.09 | 6.25 | 23.8 | 54.1 |
| h49_72 | 9.65 | 11.63 | 6.40 | 20.5 | 54.4 |

Descriptive, not a gate (the criterion gates a future shadow, not the incumbent). It reproduces EXP-037's mechanism live: the shipped forecast carries 40–60% of the real daily swing, and the seven-line profile floor picks cheap hours about twice as well as production in every block. Re-derive from the log: rows with `date >= 2026-09-14`, not `incomplete`, and non-null `naive_regret_k6` and `profile_regret_k6`.

**Blocks that can never complete** (a withheld or non-ENTSO-E hour) are logged once as `incomplete: true` with their slot count, 48h after the block's last hour, rather than dropped silently. 9 of 126 rows at backfill.

---

Entries 2026-08-29..2026-09-14: `docs/archive/model-progress-log-2026-08-29-to-09-14.md` (verbatim). Earlier: `docs/archive/model-progress-log-2026-03-to-08-28.md`.
