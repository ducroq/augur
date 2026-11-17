# RUNBOOK text retired 2026-11-17

Moved verbatim from `docs/RUNBOOK.md` to keep the live read surface under its ceiling. The gate-lag row's clean-marker symptom should be unreachable since clause (c), 2026-09-14, which turns stale acceptance into an `[ALARM: EDH publish Nh stale …]` (`scripts/check_gate_lag.sh` is still the detector); the schema-bump row is a one-off from 2026-06-10; the boot catch-up guard is documented in `scripts/daily_slot_done.sh`'s header.

**From "Monitoring the daily job":**

**A reboot re-runs a killed job** (augur#39). `Persistent=true` replays only a *missed* trigger, so on 2026-11-13 a reset mid-gate lost the day. The timer also fires ~5 min after boot; `scripts/daily_slot_done.sh` (ExecCondition) skips unless the latest 16:30 UTC slot lacks a `Daily update` commit on `origin/main`. A skip is "condition failed", not a failure; each check logs one `slot guard:` line. Limits, fail-open rule and `AUGUR_FORCE_RUN`: the script header. No multi-day backfill (#14); resets: #40.

**From "Common Problems" (EDH gate and data freshness):**

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Every marker clean, run ends ~16:35, but the forecast is anchored a day back | Gate lag (augur#34): consuming yesterday's unconsumed publish. Every guard reads green. Should be unreachable since clause (c), 2026-09-14. | `scripts/check_gate_lag.sh` prints CURRENT or LAGGED. If LAGGED, clause (c) is off or broken: check `EDH_STALE_GRACE_HOURS`, and that the gate on the box is the committed one (`ExecStartPre` runs before the pull). |
| 72h forecast shows only a short stub; `WARNING ENTSO-E data missing` while EDH is healthy | An EDH schema bump; parsers read the old shape. | Audit `ml/data/consolidate.py`, `data-processor.js`, `tab-charts.js` for top-level `data['<source>']` access; add a `data.get('data', data)` shim. `memory/data-formats.md`. |
