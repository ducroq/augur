# Memory

Last audit: 2026-11-06 (defects)

<!-- Read at session start. POINTERS ONLY: one line per fact, depth lives in topic files.
     Rewritten lean 2026-10-16 (was 46.6k chars); the previous text is verbatim in
     memory/archive/memory-index-2026-10-16.md. Do not grow narrative back here. -->

## ON "CONTINUE" — the queue (rewritten 2026-11-15)

Direction: judge forecasters on cheap-hour regret per horizon block (`docs/hypothesis-log.md` [2026-10-28]). The profile rule (ADR-009) drives the dashboard, so it is the bar; the FM's gate against it is EXP-041. LightGBM tuning is parked. **Data-gated reads come first on the day they're due; then the read surface (item 2) every session.** Counts: `.venv/bin/python scripts/vintage_counts.py`, never by hand.

**Never touch `/mnt/sadalmelik`** (the NAS holds PII; auto-memory `situla-nas-codex-sandbox`). Codex worked by day on 2026-11-15, but if it fails, reviews run on Claude subagents (`.claude/review-profile.md`, "Reviewer model").

0. **Engineer only:** (a) at night, confirm that `ls /mnt/sadalmelik/Documents` as jeroen says Permission denied and that `sudo -u nas ls …` lists the files. (b) The **sadalsuud power visit (augur#40)**, outside the job window: BIOS AC-loss setting, a different outlet or UPS, a spare brick; no BIOS update yet. That reboot is also the **augur#39 boot-trigger check** (the command is in #40's plan; close #39 when it passes).
1. **EXP-021a Stage 1, formal: TRIGGERED.** 14 of 14 fully realised clean vintages as of the 2026-11-14 run. Gate vs `lean` per its own Method in `docs/hypothesis-log.md` [2026-08-29]. Read it first. Nominated to infra for the 2026-11-16 Fable 5.2 day (the engineer decides; if Fable runs it, check its work against the pinned Method rather than redoing it). The 2026-11-13 reset cost a forecast vintage but no eval date (RUNBOOK, t0-jumped row).
2. **PRUNE FIRST (engineer, 2026-11-15: "start pruning, thinning, mechanizing, retiring")**. Every session until the live docs are under ~100k chars total. Chars on 2026-11-15: hypothesis-log 32.0k, backlog 27.0k, RUNBOOK 15.8k, gotcha log 15.7k, `experiment-results.md` 12.1k, `model-class-findings` 9.1k; auto-loaded set 24.7k (`CLAUDE.md` 11.6k + this index 10.8k). Measure: `wc -m` on each. Order: (a) **backlog 27k**: measure what is live; pre-commits that aren't next (EXP-028a, EXP-040) can't go to `docs/archive/experiment-backlog-run.md` (executed only), so check how check 5 hashes a third file first. (b) **hypothesis-log 32k**: the EXP-021a entry moves to `docs/archive/hypothesis-log-resolved.md` the day item 1 resolves it (check 6 pins both files); EXP-028a (Review 11-30) is next. (c) **gotcha log**: top five Promoted rows thinned 2026-11-15 (17.0k → 15.7k); thin the rest the same way. (d) **retire**: ARF + `memory/ml-decisions.md` (augur#32), which takes a step out of the daily job and a topic file out. (e) **mechanize**: a `scripts/read_surface.sh` that prints these numbers and fails over the ceiling, so this line stops carrying them. Dependency rule (augur#41): never bump NumPy in `requirements.lock` without a pandas 3.x upgrade; the timedelta warnings come from pandas internals, not our code.
3. **FM shadow → EXP-041**: 2 of 14 on 2026-11-14 (room 27). `scripts/exp041_fm_vs_profile.py` refuses below 14; read it with the [2026-10-28] product criterion on the same window. augur#36 (duplicate rows) open. Watch h49–72.
4. **CQR live check** (augur#19): 7 of 28 on 2026-11-14, room 22, so **one vintage of slack**. A lost night now costs the read; read it the run the counter's room hits 0.
5. **Later**: EXP-028a (deferred; Review by 11-30), then EXP-040 (TabPFN; license check first). Retire ARF (augur#32; nominated for the 2026-11-16 Fable day, skipped by the engineer) and `memory/ml-decisions.md` with it. augur#33 (staleness indicator).

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

- **Production**: as `CLAUDE.md` Stack. Revert = `dashboard.js:loadAugurForecast`. <!-- verify: grep -q "ml.shadow.update_profile" scripts/daily_update.sh && grep -q "augur_forecast_profile.json" static/js/dashboard.js && echo PASS || { echo FAIL; exit 1; } -->
- **Daily job** on sadalsuud: as `CLAUDE.md` Architecture. A reboot re-runs a killed job since 2026-11-15 (`OnBootSec` + `scripts/daily_slot_done.sh`, augur#39; boot path unproven until the next boot). The box resets unclean every ~10–14 days (augur#40). <!-- verify: ssh sadalsuud "systemctl is-enabled augur-daily.timer && systemctl is-active augur-daily.timer" 2>/dev/null | grep -q "enabled" && echo PASS || { echo FAIL; exit 1; } -->
- **Gate lag** (augur#34): <!-- verify: if ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud true 2>/dev/null; then ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud 'bash -s' < scripts/check_gate_lag.sh; else echo "CANNOT VERIFY: sadalsuud unreachable"; fi -->
- **Guards**: t0-advance alarm, content-contract gate, no clock floor. <!-- verify: grep -q "classify_t0_advance" ml/shadow/update_shadow.py && grep -q "T0_MARKER" scripts/daily_update.sh && grep -q "expected_points" scripts/wait_for_edh.sh && ! grep -qE 'MIN_PUBLISH_HOUR_UTC[=}]|[$]MIN_PUBLISH_HOUR_UTC' scripts/wait_for_edh.sh && echo "guard, marker and content-contract gate present; clock floor gone" || exit 1 -->
  Plus post-run output guards. <!-- verify: grep -q "ARF_FC_HOURS" scripts/daily_update.sh && grep -q "EVAL_LAG_DAYS" scripts/daily_update.sh && echo PASS || { echo FAIL; exit 1; } -->
- **Alerting**: as `CLAUDE.md` Architecture; RUNBOOK "Monitoring". <!-- verify: [ -f scripts/notify_email.py ] && [ -f scripts/alert_failure.sh ] && [ -f scripts/heartbeat_check.sh ] && grep -q "OnFailure=augur-alert" scripts/systemd/augur-daily.service.d/alert.conf && echo PASS || { echo FAIL; exit 1; } -->
- **Cheap-hour regret** (nightly since 2026-10-28): live since 09-14 the profile floor ranks cheap hours about 2× better than production in every block. <!-- verify: grep -q "ml.shadow.regret" scripts/daily_update.sh && [ -s ml/shadow/regret_log.jsonl ] && echo "regret step wired, log present" || exit 1 -->
- **Skill floor (augur#29)**: verdict confirmed 2026-11-06 (`scripts/augur29_verdict.py`): mean skill vs the carry −0.152, 78% of it one row (2026-10-24). The eval log scores both floors daily. <!-- verify: grep -q "lightgbm_skill_vs_naive" ml/shadow/evaluate_shadow.py && grep -q "NAIVE_MARKER" scripts/daily_update.sh && grep -q "t0_utc" ml/shadow/update_shadow.py && echo "floor, reader and anchor all present" || exit 1 -->
- **Model-class record**: EXP-001..039 in the registry (gaps at 017 and 034). The FM wins (EXP-021), but quote EXP-036's halving beside it. Fresh-vintage early read EXP-038: −21.5% QS vs `lean`; feasible on sadalsuud (EXP-039). <!-- verify: [ -f scripts/exp021_foundation_zeroshot.py ] && .venv/bin/python -c "import json;g=json.load(open('ml/shadow/exp021_foundation_aligned/summary.json'))['gates']['primary'];print('primary verdict',g['verdict']);raise SystemExit(0 if g['verdict'].startswith('SUPERIORITY') else 1)" -->
  <!-- verify: n=$(wc -l < experiments/registry.jsonl); last=$(tail -1 experiments/registry.jsonl | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['id'])"); echo "$n lines, last $last"; [ "$n" = 37 ] && [ "$last" = EXP-039 ] || exit 1 -->
- **Experiment data** (gitignored dumps) lives in `/home/jeroen/lab/augur/shadow/`, linked back to its old paths; `scripts/link_lab.sh` recreates the links (2026-10-16). It isn't byte-reproducible, so treat it as data. <!-- verify: [ -L lab ] && [ -L ml/shadow/exp021_foundation_aligned/contexts.parquet ] && [ -f ml/shadow/exp028_chronos2/c2_predictions.parquet ] && echo "lab link + data links resolve" || { echo "links missing: run scripts/link_lab.sh"; exit 1; } -->
- **Tests**: 477 collected on 2026-11-15. The probe is a floor: a drop means tests were lost. <!-- verify: n=$(.venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | grep -oE "[0-9]+ tests" | grep -oE "[0-9]+"); echo "collected ${n:-none} (floor 477)"; [ "${n:-0}" -ge 477 ] || exit 1 -->
- **Calibration (augur#19)**: the P80 band under-covers (130 days to 11-05, pooled: 0.703 band, 0.852 lower, 0.851 upper). The earlier "upper side" reading (Aug: 0.887 / 0.774) no longer reproduces: full August is 0.855 / 0.819. Likely driven at least partly by the CQR feedback loop; the fix's live check is queue item 4. EXP-015/016's premise is stale.
- **Branches**: `wip/drop-epex-target` (REVIEW-class, stale number) and two April feature branches stay parked, unmerged and undeleted on purpose. Reasons in `memory/archive/memory-index-2026-10-16.md`.
- **Framework**: pinned by the `CLAUDE.md` stamp (drift-checked 2026-11-06 at v1.52.2). <!-- verify: F=~/repos/agent-ready-projects; if [ -f "$F/scripts/stampcheck.sh" ]; then FRAMEWORK=$F bash "$F/scripts/stampcheck.sh"; else echo "CANNOT VERIFY: no stampcheck.sh in $F"; fi --> On DRIFT, `/update-drift`. History: `memory/archive/session-archive.md`.
- **Open issues**: `gh issue list` (22 open on 2026-11-15; #39, #40 and #41 opened that day).
- **Index size**: ceiling 20k chars. Past it, move a topic out; don't compress. <!-- verify: n=$(wc -m < memory/MEMORY.md); echo "index chars: $n (ceiling 20000)"; [ "$n" -lt 20000 ] || { echo "OVER 20k: move a topic out"; exit 1; } -->

## Active decisions

- ADR-009: the dashboard shows the day-type profile rule (product decision on live regret, not an ADR-007 promotion). ADR-006: LightGBM-Quantile + CQR, now a shadow. ADR-007: promotion method (pre-commit, then existing-data test, then review batteries). ADR-008: UTC in data, browser-local at one render boundary. ADR-003: Netlify `--force`.
- Lag-0 anchor ratified 2026-09-14: `t0` = end of tomorrow local.
