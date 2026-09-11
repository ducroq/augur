# Session archive — closed work

<!-- Load when: you need to know whether something was already done and when,
     or you are about to re-open a question that was settled.
     Moved out of memory/MEMORY.md 2026-09-06 — it is history, not current state,
     and the index is read at every session start. Nothing here was edited. -->

## Closed 2026-09-11

- ✅ **augur#31 CLOSED** — EDH gate expectation had decayed median 192→96, so pre-auction publishes were accepted. Fixed two ways in `bad615b`: expectation moved to the **75th percentile** (`expected_points`, 192 against live history at the deployed `SAMPLE_N=10`), and a short primary is now **held up to 4h then accepted with an alarm** rather than refused to the deadline. Six of the last nine shorts were off-schedule catch-ups later superseded by a full publish (2026-09-04 went short×3 then 192), while 2026-09-08's scheduled short never was — neither pure position fits both. **Alternative 3 (assert span) closed as NOT IMPLEMENTABLE**: EDH's quality report carries `data_points` and no time range, payloads are encrypted, and upstream confirms *"span has no accidental detector"*. Deployed and verified live.

## Closed 2026-09-10

- ✅ **Heartbeat could silence itself after a dropped send** (`7fecd79`) — `LAST_EMAIL` was never cleared on an episode boundary, so a new episode inherited the previous one's send clock and a failed first send read as already delivered. Reproduced, fixed, 5 tests. **Not fixed: `notify_email.py` still makes one SMTP attempt with no retry** — that is what actually lost the 2026-09-10 alert.
- ✅ **`paste -sd'; '` was dropping marker types from the heartbeat fingerprint** (`7fecd79`) — `paste -d` takes a *cycling delimiter list*, so every second marker merged onto its neighbour's line and the first matching `marker_kinds` rule discarded it. On the real 09-10 commit that lost `eval-stale`. A marker absent from the shape cannot break through an open episode.
- ✅ **EDH gate can now tell "late" from "failed"** (`ad10432`, `a07a77b`) — reads EDH's `publish-failure` label and gives up early, referenced to *this run's start* so a previous night's still-open issue cannot abandon the wait before EDH has run. **First cut used `gh`, which is not installed on sadalsuud**; rewritten on python3 stdlib and verified from sadalsuud. 10 tests.
- ✅ **`audit_registry.py` check 5 false positive** (`1bcb191`) — `method_sections` let the last backlog section run to EOF, so appending EXP-036 reported EXP-034 as EDITED (the whole diff was the `---` separator). Second occurrence of the promoted rule *an integrity check that makes the correct action fail is a defect*. New `tests/test_audit_registry.py`.
- ✅ **EXP-036 pre-committed** (`2113e1f`, pinned in `PRECOMMIT_REV_BY_ID`) — an averaged daily profile as a stronger skill floor than the single-day carry. Bounded so it cannot move augur#29 retroactively.
- ✅ **Moved out of the index 2026-09-10 (ceiling pressure), preserved here:** Weather tab: two-dropdown UI parity. Both "Temperature & Wind (10-day)" and "Cloud Cover & Humidity" each show a `<select>` (synced — changing one mirrors the other before re-render). Distinct aria-labels per chart. Commits `656e917` + `fa28450`.
- 📌 **Filed, not fixed:** augur#31 (gate expectation decayed 192→96 — **live**), augur#32 (ARF wall-clock anchored), augur#33 (no dashboard staleness indicator).

## Closed 2026-08-28

- ✅ **Silent vintage loss** — t0 stall/jump now alarms at the step that owns t0 (`4a2afc4`), and `wait_for_edh.sh` no longer releases the run on an overnight catch-up publish (`05b4d43`). Deployed to sadalsuud the same day; first observation is the 2026-08-28 18:30 CEST run. Position + 14-run review in `docs/hypothesis-log.md` [2026-08-28].
- ✅ **2026-08-27 `[ALARM: eval stale 3d]` diagnosed** — not an evaluator fault. `eval_log.jsonl` ended 08-24 because 08-25's vintage was never created (t0 jumped 08-24T21 → 08-26T21) and 08-26 sat at 23 of the 24 realised hours it needs. The 08-24 trigger was ours: EDH's 06:28 catch-up satisfied the date-only gate and the real publish landed 16:32:17, 90 seconds after Augur finished.
- ✅ **energydatahub#50 filed** — EDH's scheduled publish silently skips whole days; quantified over 35 days.

## Closed 2026-06-03

- ✅ augur#16 — dashboard timezone-mutation bug (ADR-001 superseded by ADR-008; convertUTCToAmsterdam removed). Commit `5ae82b4`.
- ✅ augur#17 — dashboard wholesale lower-band clamp at 0 (hid LGBM's negative-price predictions; same pattern as deprecated ARF clamp). Commit `07fb9a4`.
- ✅ augur#5 — backtesting framework substantially completed in a different shape during EXP-009..014.
- ✅ augur#6 — peak/off-peak model variants speculative + obsolete (LGBM already does horizon stacking).
- ✅ augur#7 — ARF ensemble / Prophet baseline stale (ARF retired; Prophet overlaps with #15).
- ✅ augur#11 — cron→systemd standalone superseded by broader augur#12.

## Closed 2026-06-12

- ✅ **Missing eval-row forensics** — vintages 06-08/06-10 explained (EDH v2.2 → stale parquet → t0 froze/jumped; permanent, unrecoverable); 06-09 `arf_mae: null` explained (empty ARF archive, no lookup fallback). Incident on augur#14.
- ✅ **Post-run output guards in `daily_update.sh`** (`1c33daa`) — ARF forecast <24h + eval row stale >2d alarm in commit subject. Pattern promoted: "rc=0 is not output quality".
- ✅ **EXP-015 (per-side CQR replay)** — parked; pre-commit `bcc3e78`, resolution `b40db95`. Fixes side asymmetry; can't reach regime days. Baseline redirect: horizon-conditioning refuted (deficit flat across groups).
- ✅ **EXP-016 (per-side ACI replay)** — parked; pre-commit `440b0b6`, resolution `d21b179`. Fixes post-shift days; γ-independent ~0.85 ceiling from first-shift days; Winkler guardrail tripped. Arc conclusion: gap is in the raw quantiles → EXP-017 next.
- ✅ **augur#26 filed** — ARF 48h truncation (EDH v2.2 file-window narrowing), live degradation, EDH-side fix preferred.

## Closed 2026-06-10

- ✅ **EDH v2.2 envelope wrap Python parser fix** — `e11487b` adds `_unwrap_v22_envelope` shim to `ml/data/consolidate.py`. Parquet recovered from being pinned at 2026-06-07 21:00Z; full 72h dashboard forecast restored. Eval log backfilled for 2026-06-07 (LGBM MAE 30.6 vs ARF 39.5) and 2026-06-09 (LGBM 19.9, ARF empty). 2026-06-08 has a permanent eval-log gap (no LGBM prediction set was made for that target date during the outage). Code-review battery returned REVIEW with 4 non-blocking findings (parser test gap is biggest); filed for separate follow-up.
- ✅ **augur#12 cron-comment cleanup** — sadalsuud crontab now empty; systemd timer is the sole trigger. Backup at `/tmp/crontab.backup`.
- ✅ **sadalsuud `.venv/` untracked** — `d20992a` adds `.venv/`+`venv/` to `.gitignore`; `967b653` runs `git rm -r --cached .venv/` (7921 files untracked). Next daily commit (`576a65c`) was clean — only 6 data/state files instead of swept-up venv noise.
- ✅ **sadalsuud lightgbm reinstall** — install was silently corrupted at 15:50 UTC today (root cause unknown — directory existed but contained no `__init__.py`); `pip install --force-reinstall lightgbm` recovered. Gotcha logged for potential pre-flight hardening.

## Closed 2026-06-09

- ✅ Healthchecks.io shadow endpoint removed from `scripts/daily_update.sh` (curl ping block deleted) and sadalsuud `.env` (`HEALTHCHECKS_SHADOW_URL` line removed). Comments in `scripts/wait_for_edh.sh` + `scripts/systemd/README.md` reworded — the alarm path is now: pre-flight `SHADOW_PRE_AGE_H >36h` ALARM in `daily_update.sh` surfaces stale state in the next commit message, and absence of a daily commit on origin/main is the external alive signal. Orphaned hc-ping UUID `e7771ae1-…1cc58bab0992` left dangling on healthchecks.io (owning account unknown; check will go silent/down on its own since no pings are sent).

## Resolved 2026-05-29

- ✅ EXP-011: M4 verdict (PROMOTE=False initially, Path B park).
- ✅ EXP-012: metric-redesign validation on existing data — surprise findings.
- ✅ EXP-013: corrections following code-review battery (vintage-join bug; pinball-at-p10 reversed).
- ✅ EXP-014: redesigned-criterion pass + LightGBM promoted to production (Path A swap).
- ✅ Article draft: `docs/articles/m4-metric-redesign-story.md` (five-iteration arc).
- ✅ Literature bibliography: `docs/literature.md`, `docs/metric-redesign-literature-review.md`.
- ✅ ADR-006 and ADR-007 written.
- ✅ `tests/test_metrics.py` (19 tests) added.
