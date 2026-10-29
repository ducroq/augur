# Memory

<!-- Read at session start. POINTERS ONLY: one line per fact, depth lives in topic files.
     Rewritten lean 2026-10-16 (was 46.6k chars); the previous text is verbatim in
     memory/archive/memory-index-2026-10-16.md. Do not grow narrative back here. -->

## ON "CONTINUE" — the queue (set 2026-10-29)

Direction since 2026-10-28: judge forecasters on cheap-hour regret per horizon block against the EXP-036 profile floor (`docs/hypothesis-log.md` [2026-10-28] product criterion), and take the Chronos ladder first. LightGBM tuning (EXP-018a, EXP-023a Stage B, EXP-034) is parked. **Since 2026-10-29 the read surface is a first-class task: prune, thin, mechanize, retire.**

1. **Read-surface pass, continued** (started 2026-10-29). Live chars that day: `hypothesis-log.md` 76k, `experiment-backlog.md` 70k, `model-progress-log.md` 64k (split at 2026-08-28; was 118k), `memory/` 80k (92k before `session-archive.md` moved). In order:
   a. **Backlog: mechanize, then retire.** Move the executed entries (EXP-023..029, 036, 037) to `docs/archive/experiment-backlog-run.md`. Blocked on `scripts/audit_registry.py` check 5, which reads only `docs/experiment-backlog.md`: a moved Method would read as EDITED. Teach it the archive path first, seed a positive, then move.
   b. **Hypothesis log `## Open`** (10 entries): resolve the two DUE entries ([2026-08-31] feed divergence, [2026-09-10] ARF not a backup, augur#32) and move the two parked LightGBM entries to the archive as parked.
   c. **`memory/gotcha-log.md`** (33k): thin the long Promoted rows to the rule plus a pointer.
   d. Then `/audit-context`.
2. **EXP-028a review, due 2026-10-31.** Decide it on its own frozen Method. The notes beside it name two new candidate entries (a Chronos-2-synth re-run on all 260 vintages, which is contamination-free; TabPFN = EXP-040). They also name the source for its mandatory lagged arm, the EDH publish archive in the energydatahub repo (`data/YYMMDD_HHMMSS_<feed>.json`, encrypted, from 2025-12-01).
3. **EXP-021a Stage 3** (live shadow): Stage 2 **FEASIBLE** (EXP-039: 1.2s per forecast on sadalsuud CPU). Build `ml/shadow/update_fm.py` writing `static/data/augur_forecast_fm.json` (same schema, CQR via `conformal.py`), a NON-FATAL step after `update_shadow` in `daily_update.sh`, torch pinned in `requirements.lock`. Score it in `regret.py` too. After 14 vintages: the ADR-007 gate plus the product criterion.
4. **augur#29 verdict**: overdue (Review by 10-20). Uses no new vintages. `eval_log` rows cover h1–24 only.
5. **EXP-021a Stage 1, formal**: on clean vintages (t0 ≥ 2026-10-30; 14 realised ≈ 2026-11-16).
6. **EXP-040** (TabPFN-2/3, backlog + addendum): after the EXP-028a review. Pre-run checks first: license (TabPFN-3 isn't free for commercial use), feasibility.
7. Watch `ml/shadow/regret_log.jsonl`. At h49–72 Chronos only ties the profile floor (EXP-038: 7.87 vs 7.81).
8. Once upstream v1.50.1 is tagged: `/update-drift`, `install-global-skills.sh`, re-check byte identity.

Pre-commit review is `/review-changes` (profile `.claude/review-profile.md`). Never rebase or amend a commit pinned in `PRECOMMIT_REV_BY_ID` (five today, incl. `d53af7a`, `47b2f16`): check 5 fails on an unreachable pin.

Before any model work, read `docs/experiment-results.md` Decision state and `memory/model-class-findings.md` (EXP-036 rescales every effect size).

## Topic files

| File | Load when |
|---|---|
| `memory/model-class-findings.md` | Any model work: standing conclusions, opens with the EXP-036 correction |
| `memory/upstream-edh.md` | An EDH publish is late, short or missing; you're citing an energydatahub issue number |
| `memory/gotcha-log.md` | Stuck: Promoted patterns + open entries. Resolved ones are in `memory/archive/gotcha-log-resolved.md`; grep it by mechanism |
| `memory/archive/session-archive.md` | Before re-opening a settled question: dated closed-work sections |
| `memory/data-formats.md` | EDH schema v2.2 envelope, units, timezones |
| `memory/ml-decisions.md` | ARF-era architecture (archival, frozen 2026-05-29) |
| `memory/archive/` | Retired text, unedited: the 2026-10-16 index, resolved gotchas |
| `docs/archive/hypothesis-log-resolved.md` | A citation like `hypothesis-log.md [2026-09-14]` for a resolved entry |

## Current state

- **Production**: LightGBM-Quantile + CQR (ADR-006) drives the dashboard via `augur_forecast_shadow.json`; ARF runs as backup signal (`augur_forecast.json`, Model tab). One-line revert: `dashboard.js:loadAugurForecast`. <!-- verify: grep -q "ml.shadow.update_shadow" scripts/daily_update.sh && grep -q "augur_forecast_shadow.json" static/js/dashboard.js && echo PASS || echo FAIL -->
- **Daily job** on sadalsuud: `augur-daily.timer` 16:30 UTC, gated by `wait_for_edh.sh` (content contract + clause (c) freshness, augur#34). Last daily commit seen 2026-10-15, clean. <!-- verify: ssh sadalsuud "systemctl is-enabled augur-daily.timer && systemctl is-active augur-daily.timer" 2>/dev/null | grep -q "enabled" && echo PASS || { echo FAIL; exit 1; } -->
- **Gate lag** (augur#34) is invisible to every other guard. `scripts/check_gate_lag.sh` is the only probe. <!-- verify: if ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud true 2>/dev/null; then ssh -o BatchMode=yes -o ConnectTimeout=6 sadalsuud 'bash -s' < scripts/check_gate_lag.sh; else echo "CANNOT VERIFY: sadalsuud unreachable"; fi -->
- **Guards**: t0-advance alarm, content-contract gate, no clock floor. <!-- verify: grep -q "classify_t0_advance" ml/shadow/update_shadow.py && grep -q "T0_MARKER" scripts/daily_update.sh && grep -q "expected_points" scripts/wait_for_edh.sh && ! grep -qE 'MIN_PUBLISH_HOUR_UTC[=}]|[$]MIN_PUBLISH_HOUR_UTC' scripts/wait_for_edh.sh && echo "guard, marker and content-contract gate present; clock floor gone" || exit 1 -->
  Plus post-run output guards. <!-- verify: grep -q "ARF_FC_HOURS" scripts/daily_update.sh && grep -q "EVAL_LAG_DAYS" scripts/daily_update.sh && echo PASS || echo FAIL -->
- **Alerting**: OnFailure + 06:00 heartbeat, which reads the commit subject. `[ALARM:]` is a fault; `[NOTE:]` is invisible by design. The heartbeat can't see sadalsuud itself being down (accepted). <!-- verify: [ -f scripts/notify_email.py ] && [ -f scripts/alert_failure.sh ] && [ -f scripts/heartbeat_check.sh ] && grep -q "OnFailure=augur-alert" scripts/systemd/augur-daily.service.d/alert.conf && echo PASS || { echo FAIL; exit 1; } -->
- **Cheap-hour regret** (nightly since 2026-10-28): `ml/shadow/regret_log.jsonl`, all 72h per block. `eval_log` rows cover h1–24 only. Live since 09-14 the profile floor ranks cheap hours about 2× better than production in every block. <!-- verify: grep -q "ml.shadow.regret" scripts/daily_update.sh && [ -s ml/shadow/regret_log.jsonl ] && echo "regret step wired, log present" || exit 1 -->
- **Skill floor (augur#29)**: production doesn't reliably beat seasonal-naive; against EXP-036's profile floor it sits at −12.4%. The eval log scores both floors daily. <!-- verify: grep -q "lightgbm_skill_vs_naive" ml/shadow/evaluate_shadow.py && grep -q "NAIVE_MARKER" scripts/daily_update.sh && grep -q "t0_utc" ml/shadow/update_shadow.py && echo "floor, reader and anchor all present" || exit 1 -->
- **Model-class record**: EXP-001..039 in the registry (gaps at 017 and 034). The FM wins (EXP-021), but quote EXP-036's halving beside it. Fresh-vintage early read EXP-038: −21.5% QS vs `lean`; feasible on sadalsuud (EXP-039). <!-- verify: [ -f scripts/exp021_foundation_zeroshot.py ] && .venv/bin/python -c "import json;g=json.load(open('ml/shadow/exp021_foundation_aligned/summary.json'))['gates']['primary'];print('primary verdict',g['verdict']);raise SystemExit(0 if g['verdict'].startswith('SUPERIORITY') else 1)" -->
  <!-- verify: n=$(wc -l < experiments/registry.jsonl); last=$(tail -1 experiments/registry.jsonl | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['id'])"); echo "$n lines, last $last"; [ "$n" = 37 ] && [ "$last" = EXP-039 ] || exit 1 -->
- **Experiment data** (gitignored dumps) lives in `/home/jeroen/lab/augur/shadow/`, linked back to its old paths; `scripts/link_lab.sh` recreates the links (2026-10-16). It isn't byte-reproducible, so treat it as data. Since 2026-10-16 it also holds the EXP-024/026/027/028 dumps pulled from b650-gpu. <!-- verify: [ -L lab ] && [ -L ml/shadow/exp021_foundation_aligned/contexts.parquet ] && [ -f ml/shadow/exp028_chronos2/c2_predictions.parquet ] && echo "lab link + data links resolve" || { echo "links missing: run scripts/link_lab.sh"; exit 1; } -->
- **Tests**: 389 collected. <!-- verify: n=$(.venv/bin/python -m pytest tests/ --collect-only -q 2>&1 | grep -oE "[0-9]+ tests" | grep -oE "[0-9]+"); echo "collected ${n:-none}"; [ "$n" = 389 ] || exit 1 -->
- **Calibration (augur#19)**: the P80 band under-covers on the upper side (Aug: 0.887 lower / 0.774 upper). EXP-015/016's premise is stale. Confound: CQR window depth changed with the 2026-09-13 anchor shift.
- **Upstream**: EDH misses ~11% of days, and their alerting is diagnosis, not detection. See `upstream-edh.md`.
- **Branches**: `wip/drop-epex-target` (REVIEW-class, stale number) and two April feature branches stay parked, unmerged and undeleted on purpose. Reasons in `memory/archive/memory-index-2026-10-16.md`.
- **Framework**: agent-ready-projects v1.50.0 (drift-checked 2026-10-28, re-triaged 2026-10-29; the four global skills are byte-identical to v1.50.0). **Adopted v1.40.0 on 2026-10-29**, reversing the 2026-10-28 decline: `.claude/review-profile.md` (tracked through a `.gitignore` negation) carries the tiers, guarantees and a `pre-commitment` lens, and `/review-changes` is the pre-commit review. v1.42.0's #172 row, v1.43.0's #166 sections and v1.50.0's `Reviewer model` were adopted with it. **Declined v1.45.1's one-lens HIGH**: HIGH here is production run overnight unattended plus the pre-registration record, and the framework's own evidence doesn't support switching. Reopen only if review cost becomes the binding constraint.
- **Index size**: ceiling 20k chars. Past it, move a topic out; don't compress. <!-- verify: n=$(wc -m < memory/MEMORY.md); echo "index chars: $n (ceiling 20000)"; [ "$n" -lt 20000 ] || { echo "OVER 20k: move a topic out"; exit 1; } -->

## Active decisions

- ADR-006: LightGBM-Quantile + CQR in production. ADR-007: promotion method (pre-commit, then existing-data test, then review batteries). ADR-008: UTC in data, browser-local at one render boundary. ADR-003: Netlify `--force`.
- Lag-0 anchor ratified 2026-09-14: `t0` = end of tomorrow local.
- b650-gpu is third-party (Arian's): working copies only. Pull results to `~/lab/augur`, then delete once a snapshot holds them (owner rule 2026-10-16).

## Open issues (GitHub, 2026-10-16)

#29 skill floor (verdict due) · #28 EXP-018a · #15 foundation models · #19 calibration · #30 first-24h dashboard · #32 ARF backup value · #33 staleness indicator · #25 event-driven EDH trigger · #14 backfill (detection shipped) · #24 #23 #18 dashboard · #22 #4 #2 feature ideas (demoted; #28 says it supersedes #2/#4/#22, yet they are open) · #20 #21 #9 #10 #8 backlog.
