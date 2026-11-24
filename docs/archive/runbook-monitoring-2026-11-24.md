# RUNBOOK "Monitoring the daily job": text removed 2026-11-24, verbatim

Removed while thinning the live read surface. The layer table, channel, checks and alert reading stay in `docs/RUNBOOK.md`.

**Why three.** `daily_update.sh` ends with `git diff --cached --quiet && echo "No changes to commit" || {commit; push;}`, so a run producing nothing exits 0 and the unit *succeeds* — `OnFailure=` cannot fire for it. And on 2026-08-30 the production model crashed while the run completed and committed: `shadow rc=1` in the subject, unit green, heartbeat green. Every soft-failure alarm this pipeline raises rides in the commit subject by design, so the third layer is what gives them a reader.

**Accepted blind spot.** The heartbeat runs *on* sadalsuud, so it cannot report that sadalsuud is down. Closing that needs an off-host dead-man's switch, i.e. a new service — declined 2026-07-17. The residual case is also the one where daily commits visibly stop.

**Channel (removed clauses):** — the same sender `nexusmind-alert@.service` uses. Deliberately no new notification service. On missing creds: an alerter that throws inside systemd's failure handling only adds noise.
