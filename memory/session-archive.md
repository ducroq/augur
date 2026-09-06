# Session archive — closed work

<!-- Load when: you need to know whether something was already done and when,
     or you are about to re-open a question that was settled.
     Moved out of memory/MEMORY.md 2026-09-06 — it is history, not current state,
     and the index is read at every session start. Nothing here was edited. -->

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
