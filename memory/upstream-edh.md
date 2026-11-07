# Upstream: energyDataHub

<!-- Load when: an EDH publish is late/short/missing, a feed changes shape or span,
     or you are about to cite an energydatahub issue number.
     The one-line state lives in memory/MEMORY.md; this file is the depth. -->

The lessons from these incidents are in `memory/gotcha-log.md` (2026-08-31 and
2026-09-04 entries). This file is the *upstream relationship* record: what the
feeds do, who detects what, and which issue numbers are real.

## Division of labour — read this before trusting either side's alarm

**Augur's `t0` hold-back and heartbeat detect the ABSENCE of a fresh vintage;
EDH's issue explains a run that fired and FAILED.** Ours covers the worse case.

⚠️ EDH's publish-failure alerting is **DIAGNOSIS, NOT DETECTION. Do not make it
the primary alarm.** (An earlier note had this hierarchy backwards.) Its `alert:`
job lives *inside* `energydatahub/.github/workflows/collect-data.yml` with
`needs: [collect-and-publish, deploy]`, and that workflow's only triggers are
`schedule` and `workflow_dispatch` — verified on main. It is therefore
structurally blind to a run that never starts: a dropped cron (GitHub
deprioritises schedules on quiet repos), a queue outage, or a disabled workflow
all produce no run, no alert, and a clean issue tracker while nothing publishes.

⚠️ **Our alarm firing with NO issue on `ducroq/energydatahub` is a WORSE signal
than an issue existing** — it means the pipeline is not running at all, rather
than running and failing. For the 08-31..09-03 outage theirs would have fired on
all five days; had the cron simply stopped, theirs would have been silent on all
five and only ours would have caught it. A true liveness check must fire when a
publish has *not* happened for N hours and cannot live inside the workflow it
watches — unbuilt on both sides, and the same shape as Augur's own accepted blind
spot (the heartbeat runs *on* sadalsuud, so it cannot report sadalsuud down).

## Issue-number map — verified against the API 2026-09-04

| Number | What it actually is |
|---|---|
| `energydatahub#47` | member-drift duration guard |
| `energydatahub#50` | skipped publishes ("silently skips whole days") — **live and correct, do not strike** |
| `energydatahub#51` | load-forecast horizon — verdict **resolved-upstream**, not transient; closed 2026-11-06 |
| *(none)* | the abandoned time-boxed drift block — **it has no number, because it does not exist** |
| `energydatahub#69` | publish-failure issue for the 09-07 outage — opened 09-07 19:51Z, auto-closed 09-08 19:16Z |
| `energydatahub#70` | publish-failure issue for the 09-09 outage — opened 09-09 19:13Z, auto-closed 09-10 ~07:4xZ |
| `energydatahub#71` | Luchtmeetnet `air_quality_buurt` missing (HTTP 429) — **Augur does not consume it** |
| `energydatahub#73` | whether `data/data_quality_report.json` should be a *published* artifact — **read this before adding gating** |

⚠️ The time-box was cited as `#47`, then as `#50`, and neither is its number.
Citing any number for it is how a phantom dependency gets recorded.

## Publish reliability

EDH published on **31 of 35 days** over 2026-07-25..08-28 (missed 08-03, 08-06,
08-23, 08-27; catch-up double-publishes 08-09, 08-24) — roughly an 11% miss rate.
Augur's gate is fail-open by design, so each miss costs a vintage and now
announces itself. Filed as **energydatahub#50**.
<!-- verify: n=$(gh api "repos/ducroq/energyDataHub/commits?path=data/data_quality_report.json&per_page=100&since=2026-07-25T00:00:00Z&until=2026-08-29T00:00:00Z" --jq ".[].commit.committer.date" 2>/dev/null | cut -c1-10 | sort -u | wc -l); if [ -z "$n" ] || [ "$n" = 0 ]; then echo "CANNOT VERIFY: gh api unreachable or empty"; else echo "EDH published on $n of 35 days in 2026-07-25..08-28 (claim says 31)"; [ "$n" = 31 ] || exit 1; fi -->

## Incidents — archived

Narratives moved verbatim to `memory/archive/upstream-edh-incidents-2026-11-07.md` (2026-11-07). Grep it by date or feed.

- Publish outage 2026-08-31..09-04 — five vintages lost, upstream, resolved.
- `load_forecast` horizon halved 2026-08-28, recovered 2026-09-04 — NOT structural. <!-- verify: grep -q "t0_short_feeds" ml/shadow/update_shadow.py && grep -q "t0 held back" scripts/daily_update.sh && echo "hold-back alarm still the only span detector on this side" || exit 1 -->
- Publish outage 2026-09-07 and 2026-09-09 — two more vintages lost, TWO UNRELATED CAUSES.

## Augur now reads the `publish-failure` label — and this does NOT contradict "diagnosis, not detection"

`scripts/wait_for_edh.sh` polls EDH's open `publish-failure` issues (unauthenticated `api.github.com`, python3 stdlib — **not `gh`, which is not installed on sadalsuud**) and gives up its wait early when one was opened *after this run started*. The hierarchy recorded above is unchanged and still correct: **Augur's `t0` hold-back and heartbeat detect the ABSENCE of a fresh vintage; EDH's issue explains a run that fired and FAILED.** The probe cannot start or extend a wait and is never a primary alarm — it only shortens a wait we were going to abandon anyway, and every way of not knowing falls through to the existing deadline. The structural blindness noted above (a run that never starts opens no issue) is exactly why it stays secondary.

**Known limitation:** EDH opens **one** issue per failure *streak* and closes it on recovery. #70 sat open from 09-09 with `updatedAt == createdAt` and zero comments, so on the second and later nights of a streak nothing is newer than our start time and the gate waits to the deadline as before. The probe helps on the **first** night — when a still-evaluable vintage is at risk — and not after. Making it work every night requires EDH to touch the issue per repeat failure; asked, not yet answered.

⚠️ **Dependency worth knowing before building more gating on it (their #73):** `data_quality_report.json` is committed to `data/` only and is **not** copied into `docs/`, so it is not part of the Pages artifact and carries **no published-schema contract**. Augur reads it from the git checkout (`git show origin/main:data/data_quality_report.json` in `wait_for_edh.sh`), which works, but it is a file upstream has never treated as published and may reshape without notice. Two existing cautions still apply: **do not gate on `_span_shortfalls.json`** (their #53 — reporting-only, no expectations yet; the last two runs reported "0 of 56/64 members have >=10 prior observations", so it cannot return a meaningful clean result), and **never judge feed freshness by file mtime** — a graced feed is *absent* from a publish, so `docs/` keeps yesterday's file unchanged and it looks fresh while being a day stale.
