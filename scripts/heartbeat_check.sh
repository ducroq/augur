#!/usr/bin/env bash
# Daily liveness check for the Augur pipeline (augur-heartbeat.timer).
#
# Why this exists alongside OnFailure= (both built 2026-08-30): OnFailure=
# structurally cannot fire for the failure shapes that produce no unit failure.
# daily_update.sh ends with
#     git diff --cached --quiet && echo "No changes to commit" || { commit; push; }
# so a run that produces nothing exits 0 and the unit *succeeds*. Same for a
# timer that got disabled, and for a box that was down at 16:30 UTC. In all
# three the vintage is lost and nothing is emitted. This turns "someone notices
# missing `Daily update` commits on origin/main" into an actual signal.
#
# Known limitation, stated rather than papered over: this runs on sadalsuud, so
# it cannot report that sadalsuud is down. Only an off-host dead-man's switch
# covers that, which would mean a new service (declined 2026-07-17).
#
# Checks (all local, no network):
#   1. age of the newest `Daily update` commit  -- the primary signal
#   2. augur-daily.timer is enabled and active  -- catches a disabled timer
#   3. commits on HEAD not on origin/main       -- advisory; a commit that
#      never reached Netlify leaves the dashboard stale
#   4. alarm markers in the newest commit SUBJECT -- added 2026-08-31 after the
#      2026-08-30 incident: the shadow update crashed (`shadow rc=1/eval rc=skip`),
#      a commit still landed, so checks 1-3 all read healthy while the PRODUCTION
#      model was down and the dashboard forecast was stale. Every soft-failure
#      alarm this pipeline raises rides in the commit subject by design, and
#      until now nothing read them.
#
# Exit contract: 0 when healthy AND when a staleness alert was sent (that is a
# successful check, not a failed unit). Non-zero only on internal error, so
# augur-heartbeat.service's own OnFailure= catches a broken watchman.
set -u

AUGUR_DIR="${AUGUR_DIR:-/home/jeroen/local_dev/augur}"
LOG="$AUGUR_DIR/logs/alerts.log"
# 30h at a 06:00 UTC check: a healthy run (commits ~18:30-21:00 UTC) is ~10h
# old, and a single missed day is ~34h -- so one silent miss alarms the next
# morning, while a legitimately late run never does.
MAX_AGE_HOURS="${MAX_AGE_HOURS:-30}"
TS=$(date -Iseconds)

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true

cd "$AUGUR_DIR" || { echo "$TS: heartbeat ERROR — cannot cd to $AUGUR_DIR" >> "$LOG"; exit 1; }

LAST_EPOCH=$(git log -1 --grep='^Daily update' --format=%ct 2>/dev/null)
if [ -z "$LAST_EPOCH" ]; then
    echo "$TS: heartbeat ERROR — no 'Daily update' commit found in $AUGUR_DIR" >> "$LOG"
    exit 1
fi

NOW_EPOCH=$(date +%s)
AGE_H=$(( (NOW_EPOCH - LAST_EPOCH) / 3600 ))
LAST_SUBJECT=$(git log -1 --grep='^Daily update' --format='%h %ad %s' --date=iso 2>/dev/null)

TIMER_ENABLED=$(systemctl is-enabled augur-daily.timer 2>&1 || true)
TIMER_ACTIVE=$(systemctl is-active augur-daily.timer 2>&1 || true)
NEXT_RUN=$(systemctl show augur-daily.timer -p NextElapseUSecRealtime --value 2>/dev/null || true)
UNPUSHED=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
LAST_BODY=$(git log -1 --grep='^Daily update' --format='%s' 2>/dev/null)
# Soft-failure markers daily_update.sh composes into the subject: any [ALARM: ...],
# `ARF FAIL rc=N`, a non-zero step rc, or a step gated off as `rc=skip`.
ALARM_HIT=$(printf '%s' "$LAST_BODY" | grep -oE 'ALARM: [^]]*|ARF FAIL rc=[0-9]+|rc=[1-9][0-9]*|rc=skip' | paste -sd'; ' - 2>/dev/null || true)

FINDINGS=""
[ "$AGE_H" -gt "$MAX_AGE_HOURS" ] && FINDINGS="${FINDINGS}
  * STALE: newest 'Daily update' commit is ${AGE_H}h old (threshold ${MAX_AGE_HOURS}h).
    At least one vintage has been lost, and nothing alarmed — the unit either
    did not run, or ran and committed nothing."
[ "$TIMER_ENABLED" != "enabled" ] && FINDINGS="${FINDINGS}
  * TIMER NOT ENABLED: systemctl is-enabled augur-daily.timer => ${TIMER_ENABLED}"
[ "$TIMER_ACTIVE" != "active" ] && FINDINGS="${FINDINGS}
  * TIMER NOT ACTIVE: systemctl is-active augur-daily.timer => ${TIMER_ACTIVE}"
[ "$UNPUSHED" != "0" ] && [ "$UNPUSHED" != "?" ] && FINDINGS="${FINDINGS}
  * UNPUSHED: ${UNPUSHED} commit(s) on HEAD are not on origin/main — Netlify
    never rebuilt, so the live dashboard is behind the local forecast."
[ -n "$ALARM_HIT" ] && FINDINGS="${FINDINGS}
  * SOFT FAILURE in the newest daily commit: ${ALARM_HIT}
    The run completed and committed, so it is invisible to the staleness and
    timer checks above — but a non-zero step rc means that step produced
    nothing. \`shadow rc=N\` specifically means the PRODUCTION LightGBM model
    did not update and the dashboard forecast is stale."

if [ -z "$FINDINGS" ]; then
    echo "$TS: heartbeat OK — last daily commit ${AGE_H}h ago, timer ${TIMER_ENABLED}/${TIMER_ACTIVE}, subject clean" >> "$LOG" 2>/dev/null || true
    exit 0
fi

BODY="$TS — Augur daily pipeline heartbeat FAILED on sadalsuud.
${FINDINGS}

Newest daily commit: ${LAST_SUBJECT:-(none)}
Timer: ${TIMER_ENABLED} / ${TIMER_ACTIVE}   next elapse: ${NEXT_RUN:-unknown}

This check exists because these shapes produce no unit failure, so
OnFailure=augur-alert@ cannot fire for them: a run that commits nothing still
exits 0, and a disabled timer never runs at all.

Cost: EXP-018a / EXP-021a / EXP-028a are gated on consecutive vintages from
t0 >= 2026-08-25. Each missed day slips the September schedule by a day and is
permanently unevaluable (no backfill — augur#14).

Diagnose:  ssh sadalsuud 'systemctl list-timers augur-daily.timer; journalctl -u augur-daily.service -n 50 --no-pager'
Run log:   $AUGUR_DIR/logs/daily_update.log"

RESULT=$(printf '%s' "$BODY" | python3 "$AUGUR_DIR/scripts/notify_email.py" \
    "[Augur] daily pipeline heartbeat FAILED (last commit ${AGE_H}h ago)" 2>&1) \
    || RESULT="ERROR: notify_email.py did not run"
echo "$TS: heartbeat ALERT (age ${AGE_H}h, timer ${TIMER_ENABLED}/${TIMER_ACTIVE}, unpushed ${UNPUSHED}, markers '${ALARM_HIT}') — $RESULT" >> "$LOG" 2>/dev/null || true

# A sent alert means the check worked. Do not fail the unit, or the heartbeat's
# own OnFailure= would send a second, less informative email for the same event.
exit 0
