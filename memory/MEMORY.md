# Memory

Last audit: 2026-11-06 (defects)

<!-- Read at session start. POINTERS ONLY: one line per fact, depth lives in topic files.
     Rewritten lean 2026-10-16 (was 46.6k chars); the previous text is verbatim in
     memory/archive/memory-index-2026-10-16.md. Do not grow narrative back here. -->

## ON "CONTINUE" — the queue (rewritten 2026-11-07)

Direction: judge forecasters on cheap-hour regret per horizon block (`docs/hypothesis-log.md` [2026-10-28]). Since ADR-009 (2026-11-07) the profile floor itself drives the dashboard, so that criterion is the bar to replace it. LightGBM tuning (EXP-018a, EXP-023a Stage B, EXP-034) is parked. **The read surface is a first-class task: prune, thin, mechanize, retire.**

0. **FIRST: check the ADR-009 deploy (augur#37).** Pushed 2026-11-07, so the first nightly run with `update_profile` is that evening's. Check: the daily commit subject has no `[ALARM: profile forecast`; `static/data/augur_forecast_profile.json` `metadata.t0` advanced and `n_hours` = 72; https://energy.jeroenveen.nl shows "Forecast: average of the last 5 similar days" plus the caption. Then close augur#37. Revert = the path in `dashboard.js:loadAugurForecast`. Open by design: the forecast needs `update_shadow`'s `t0` (ADR-009 Consequences).
1. **Read surface: mechanize, then thin, `docs/hypothesis-log.md`** (34.7k, the largest live file). (a) Generate the `## Open` trigger table's vintage counts from `eval_log.jsonl`, `calibration_history` and `fm_state.json` with a script plus a `render --check`, like `render_results.py`, instead of hand-counting. (b) Archive resolved entries verbatim to `docs/archive/hypothesis-log-resolved.md`. Other live sizes 2026-11-07: RUNBOOK 22k, backlog 22k, gotcha log 14k <!-- verify: n=$(wc -m < memory/gotcha-log.md); echo "gotcha-log chars: $n (ceiling 20000)"; [ "$n" -lt 20000 ] || exit 1 -->, progress log 7k (archived to 09-14 today).
2. **Engineer decision, before the FM's 14 vintages are read:** the [2026-11-07] FM criterion's skill gate is still against LightGBM, which is now a shadow (see that entry's 2026-11-07 note). Keep it, or write a new entry against the profile rule.
3. **EXP-021a Stage 1, formal**: on clean vintages (`t0` ≥ 2026-10-30; 14 realised ≈ 2026-11-16).
4. **EXP-021a Stage 3 FM shadow** (deployed 2026-11-07): criterion in `docs/hypothesis-log.md` [2026-11-07], ≈17 nights; read it before day 30 of `fm_state.json`. After a week of clean runs (≈11-14), delete `~/local_dev/augur-venv-pre-fm-20261107` on sadalsuud. augur#36 (duplicate rows) is open on production. Watch h49–72: offline, Chronos only ties the profile floor there (EXP-038 regret 7.87 vs 7.81).
5. **CQR live check**: 28 post-deploy vintages from 2026-11-06 (`docs/hypothesis-log.md` [2026-11-06]). Since ADR-009 this affects only LightGBM's shadow band.
6. **Later**: EXP-028a (deferred; Review by 11-30), then EXP-040 (TabPFN; license check first). Retire ARF (augur#32) and `memory/ml-decisions.md` along with it.

## Topic files

| File | Load when |
|---|---|
| `memory/model-class-findings.md` | Any model work: standing conclusions, opens with the EXP-036 correction |
| `memory/upstream-edh.md` | An EDH publish is late, short or missing; you're citing an energydatahub issue number |
| `memory/gotcha-log.md` | Stuck: Promoted patterns + open entries. Resolved ones are in `memory/archive/gotcha-log-resolved.md`; grep it by mechanism |
| `memory/archive/session-archive.md` | Before re-opening a settled question: dated closed-work sections |
| `memory/data-formats.md` | Parsing or changing EDH data: schema v2.2 envelope, units, timezones |
| `memory/ml-decisions.md` | ARF-era architecture (archival, frozen 2026-05-29) |
| `memory/archive/` | Retired text, unedited: the 2026-10-16 index, resolved gotchas, the Promoted rows before thinning (`gotcha-promoted-rows-2026-11-06.md`) |
| `docs/archive/hypothesis-log-resolved.md` | A citation like `hypothesis-log.md [2026-09-14]` for a resolved entry |

## Current state

- **Production**: the day-type profile rule (ADR-009) drives the dashboard via `augur_forecast_profile.json`; LightGBM-Quantile + CQR (ADR-006) runs as a shadow and sets `t0`; ARF runs as a modelling fallback, not an availability backup (`augur_forecast.json`, Model tab; also the surcharge). One-line revert: `dashboard.js:loadAugurForecast`. <!-- verify: grep -q "ml.shadow.update_profile" scripts/daily_update.sh && grep -q "augur_forecast_profile.json" static/js/dashboard.js && echo PASS || echo FAIL -->
- **Daily job** on sadalsuud: `augur-daily.timer` 16:30 UTC, gated by `wait_for_edh.sh` (content contract + clause (c) freshness, augur#34). Last daily commit seen 2026-11-06, clean. <!-- verify: ssh sadalsuud "systemctl is-enabled augur-daily.timer && systemctl is-active augur-daily.timer" 2>/dev/null | grep -q "enabled" && echo PASS || { echo FAIL; exit 1; } -->
- **Gate lag** (augur#34) is invisible to every other guard. `scripts/check_gate_lag.sh` is the only probe. <!-- verify: if ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud true 2>/dev/null; then ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud 'bash -s' < scripts/check_gate_lag.sh; else echo "CANNOT VERIFY: sadalsuud unreachable"; fi -->
- **Guards**: t0-advance alarm, content-contract gate, no clock floor. <!-- verify: grep -q "classify_t0_advance" ml/shadow/update_shadow.py && grep -q "T0_MARKER" scripts/daily_update.sh && grep -q "expected_points" scripts/wait_for_edh.sh && ! grep -qE 'MIN_PUBLISH_HOUR_UTC[=}]|[$]MIN_PUBLISH_HOUR_UTC' scripts/wait_for_edh.sh && echo "guard, marker and content-contract gate present; clock floor gone" || exit 1 -->
  Plus post-run output guards. <!-- verify: grep -q "ARF_FC_HOURS" scripts/daily_update.sh && grep -q "EVAL_LAG_DAYS" scripts/daily_update.sh && echo PASS || echo FAIL -->
- **Alerting**: OnFailure + 06:00 heartbeat, which reads the commit subject. `[ALARM:]` is a fault; `[NOTE:]` is invisible by design. The heartbeat can't see sadalsuud itself being down (accepted). <!-- verify: [ -f scripts/notify_email.py ] && [ -f scripts/alert_failure.sh ] && [ -f scripts/heartbeat_check.sh ] && grep -q "OnFailure=augur-alert" scripts/systemd/augur-daily.service.d/alert.conf && echo PASS || { echo FAIL; exit 1; } -->
- **Cheap-hour regret** (nightly since 2026-10-28): `ml/shadow/regret_log.jsonl`, all 72h per block. `eval_log` rows cover h1–24 only. Live since 09-14 the profile floor ranks cheap hours about 2× better than production in every block. <!-- verify: grep -q "ml.shadow.regret" scripts/daily_update.sh && [ -s ml/shadow/regret_log.jsonl ] && echo "regret step wired, log present" || exit 1 -->
- **Skill floor (augur#29)**: verdict confirmed 2026-11-06: mean skill vs the carry −0.152, of which 78% is one row, 2026-10-24 (−0.034 without it; median +0.021, pooled −0.009; `scripts/augur29_verdict.py`). Against EXP-036's profile floor it sits at −12.4% offline. The eval log scores both floors daily. <!-- verify: grep -q "lightgbm_skill_vs_naive" ml/shadow/evaluate_shadow.py && grep -q "NAIVE_MARKER" scripts/daily_update.sh && grep -q "t0_utc" ml/shadow/update_shadow.py && echo "floor, reader and anchor all present" || exit 1 -->
- **Model-class record**: EXP-001..039 in the registry (gaps at 017 and 034). The FM wins (EXP-021), but quote EXP-036's halving beside it. Fresh-vintage early read EXP-038: −21.5% QS vs `lean`; feasible on sadalsuud (EXP-039). <!-- verify: [ -f scripts/exp021_foundation_zeroshot.py ] && .venv/bin/python -c "import json;g=json.load(open('ml/shadow/exp021_foundation_aligned/summary.json'))['gates']['primary'];print('primary verdict',g['verdict']);raise SystemExit(0 if g['verdict'].startswith('SUPERIORITY') else 1)" -->
  <!-- verify: n=$(wc -l < experiments/registry.jsonl); last=$(tail -1 experiments/registry.jsonl | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['id'])"); echo "$n lines, last $last"; [ "$n" = 37 ] && [ "$last" = EXP-039 ] || exit 1 -->
- **Experiment data** (gitignored dumps) lives in `/home/jeroen/lab/augur/shadow/`, linked back to its old paths; `scripts/link_lab.sh` recreates the links (2026-10-16). It isn't byte-reproducible, so treat it as data. Since 2026-10-16 it also holds the EXP-024/026/027/028 dumps pulled from b650-gpu. <!-- verify: [ -L lab ] && [ -L ml/shadow/exp021_foundation_aligned/contexts.parquet ] && [ -f ml/shadow/exp028_chronos2/c2_predictions.parquet ] && echo "lab link + data links resolve" || { echo "links missing: run scripts/link_lab.sh"; exit 1; } -->
- **Tests**: 432 collected. <!-- verify: n=$(.venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | grep -oE "[0-9]+ tests" | grep -oE "[0-9]+"); echo "collected ${n:-none}"; [ "$n" = 432 ] || exit 1 -->
- **Calibration (augur#19)**: the P80 band under-covers (130 days to 11-05, pooled: 0.703 band, 0.852 lower, 0.851 upper). The earlier "upper side" reading (Aug: 0.887 / 0.774) no longer reproduces: full August is 0.855 / 0.819. Likely driven at least partly by the CQR feedback loop (queue item 0). EXP-015/016's premise is stale. Confound: CQR window depth changed with the 2026-09-13 anchor shift.
- **Upstream**: EDH misses ~11% of days, and their alerting is diagnosis, not detection. See `upstream-edh.md`.
- **Branches**: `wip/drop-epex-target` (REVIEW-class, stale number) and two April feature branches stay parked, unmerged and undeleted on purpose. Reasons in `memory/archive/memory-index-2026-10-16.md`.
- **Framework**: agent-ready-projects, pinned by the `CLAUDE.md` stamp (drift-checked 2026-11-06 at v1.52.2). The four global skills match that tag byte for byte. <!-- verify: F=~/repos/agent-ready-projects; if [ -f "$F/scripts/stampcheck.sh" ]; then FRAMEWORK=$F bash "$F/scripts/stampcheck.sh"; else echo "CANNOT VERIFY: no stampcheck.sh in $F"; fi --> On DRIFT, run `/update-drift`, or reinstall at the tag if a `master` install caused it. Adoption and decline history, with reopen conditions: `memory/archive/session-archive.md`.
- **Open issues**: `gh issue list`. #28 says it supersedes #2/#4/#22, yet they are open.
- **Index size**: ceiling 20k chars. Past it, move a topic out; don't compress. <!-- verify: n=$(wc -m < memory/MEMORY.md); echo "index chars: $n (ceiling 20000)"; [ "$n" -lt 20000 ] || { echo "OVER 20k: move a topic out"; exit 1; } -->

## Active decisions

- ADR-009: the dashboard shows the day-type profile rule (product decision on live regret, not an ADR-007 promotion). ADR-006: LightGBM-Quantile + CQR, now a shadow. ADR-007: promotion method (pre-commit, then existing-data test, then review batteries). ADR-008: UTC in data, browser-local at one render boundary. ADR-003: Netlify `--force`.
- Lag-0 anchor ratified 2026-09-14: `t0` = end of tomorrow local.
