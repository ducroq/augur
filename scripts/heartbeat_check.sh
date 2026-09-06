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
# Notification policy (2026-09-01): findings are deduplicated by SHAPE, not by
# text. An unchanged shape is logged but not re-emailed; it is re-sent every
# REMIND_DAYS with a day counter, any shape not seen in the episode breaks
# through at once, and clearing sends one recovery notice. Before this, check 4
# re-read the same immutable commit subject every morning and mailed every time
# -- the 2026-08-31 ENTSO-E outage produced a daily identical alert about a
# condition already known. Tests: tests/test_heartbeat_check.py.
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

# Notification state (2026-09-01). Check 4 reads an IMMUTABLE commit subject, so
# a soft failure re-alarms EVERY morning until a clean run lands. During the
# 2026-08-31 ENTSO-E outage that meant an identical email each day about a
# condition already known and already being worked. A burst guard like
# alert_failure.sh's is the wrong instrument here -- a 3h window means nothing
# against a daily timer. What was missing is memory.
#
# Policy: suppress an unchanged finding SHAPE, but never let a persisting
# problem decay into silence. Re-send every REMIND_DAYS with a day counter,
# break through immediately on any shape not seen in this episode, and send one
# line when it clears so silence is never ambiguous.
STATE="${HEARTBEAT_STATE:-$AUGUR_DIR/logs/.heartbeat_state}"
REMIND_DAYS="${REMIND_DAYS:-3}"
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

# Canonical marker TYPE, with the varying parts (day counts, dates, hour deltas,
# feed lists) stripped: `[ALARM: t0 jumped 2d]` and `[ALARM: t0 jumped 3d]` are
# the same shape and must not re-alert, while a marker type not seen in this
# episode must. Unrecognised markers pass through verbatim -- an unknown alarm
# should break through, not be folded silently into an existing episode.
marker_kinds() {
    printf '%s' "$1" | tr ';' '\n' | sed -E '
        s/.*t0 +held +back.*/t0-held-back/
        s/.*t0 +jumped.*/t0-jumped/
        s/.*t0 +went +BACKWARDS.*/t0-backwards/
        s/.*t0 +stale.*/t0-stale/
        s/.*eval +stale.*/eval-stale/
        s/.*naive +unscored.*/naive-unscored/
        s/.*ARF +forecast.*/arf-forecast-short/
        s/.*ARF FAIL.*/arf-fail/
        s/^ *rc=skip *$/rc-skip/
        s/^ *rc=[0-9]+ *$/rc-nonzero/
    ' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | grep -v '^$' | sort -u | paste -sd',' -
}

FINDINGS=""
KINDS=""
add_kind() { KINDS="${KINDS}${KINDS:+,}$1"; }

if [ "$AGE_H" -gt "$MAX_AGE_HOURS" ]; then
    add_kind stale
    FINDINGS="${FINDINGS}
  * STALE: newest 'Daily update' commit is ${AGE_H}h old (threshold ${MAX_AGE_HOURS}h).
    At least one vintage has been lost, and nothing alarmed — the unit either
    did not run, or ran and committed nothing."
fi
if [ "$TIMER_ENABLED" != "enabled" ]; then
    add_kind timer-not-enabled
    FINDINGS="${FINDINGS}
  * TIMER NOT ENABLED: systemctl is-enabled augur-daily.timer => ${TIMER_ENABLED}"
fi
if [ "$TIMER_ACTIVE" != "active" ]; then
    add_kind timer-not-active
    FINDINGS="${FINDINGS}
  * TIMER NOT ACTIVE: systemctl is-active augur-daily.timer => ${TIMER_ACTIVE}"
fi
if [ "$UNPUSHED" != "0" ] && [ "$UNPUSHED" != "?" ]; then
    add_kind unpushed
    FINDINGS="${FINDINGS}
  * UNPUSHED: ${UNPUSHED} commit(s) on HEAD are not on origin/main — Netlify
    never rebuilt, so the live dashboard is behind the local forecast."
fi
if [ -n "$ALARM_HIT" ]; then
    add_kind "soft:$(marker_kinds "$ALARM_HIT")"
    FINDINGS="${FINDINGS}
  * SOFT FAILURE in the newest daily commit: ${ALARM_HIT}
    The run completed and committed, so it is invisible to the staleness and
    timer checks above — but a non-zero step rc means that step produced
    nothing. \`shadow rc=N\` specifically means the PRODUCTION LightGBM model
    did not update and the dashboard forecast is stale."
fi

NOW=$(date +%s)

if [ -z "$FINDINGS" ]; then
    # Recovery notice: only when an episode was actually open. Without this,
    # "no mail" is ambiguous between fixed and watchman-broken.
    if [ -f "$STATE" ]; then
        PREV_FP=""
        IFS=$(printf '\t') read -r PREV_FP _ _ < "$STATE" 2>/dev/null || true
        if [ -n "$PREV_FP" ]; then
            RBODY="$TS — Augur daily pipeline heartbeat RECOVERED on sadalsuud.

The episode that was alarming as '${PREV_FP}' has cleared. Newest daily commit
is ${AGE_H}h old, timer ${TIMER_ENABLED}/${TIMER_ACTIVE}, and its subject carries
no alarm markers.

Newest daily commit: ${LAST_SUBJECT:-(none)}

No action needed. This is the close of the episode, sent once."
            RRESULT=$(printf '%s' "$RBODY" | python3 "$AUGUR_DIR/scripts/notify_email.py" \
                "[Augur] heartbeat recovered — pipeline clean again" 2>&1) \
                || RRESULT="ERROR: notify_email.py did not run"
            echo "$TS: heartbeat RECOVERED (was '${PREV_FP}') — $RRESULT" >> "$LOG" 2>/dev/null || true
        fi
        rm -f "$STATE" 2>/dev/null || true
    fi
    echo "$TS: heartbeat OK — last daily commit ${AGE_H}h ago, timer ${TIMER_ENABLED}/${TIMER_ACTIVE}, subject clean" >> "$LOG" 2>/dev/null || true
    exit 0
fi

# Episode bookkeeping. FP is the shape; FIRST_SEEN dates the episode; LAST_EMAIL
# is armed only on a CONFIRMED send, so a degraded channel (missing secrets ->
# log-only) retries tomorrow instead of suppressing itself into silence.
FP="$KINDS"
PREV_FP=""; FIRST_SEEN=""; LAST_EMAIL=""
if [ -f "$STATE" ]; then
    IFS=$(printf '\t') read -r PREV_FP FIRST_SEEN LAST_EMAIL < "$STATE" 2>/dev/null || true
fi
case "${FIRST_SEEN:-}" in ''|*[!0-9]*) FIRST_SEEN="" ;; esac
case "${LAST_EMAIL:-}" in ''|*[!0-9]*) LAST_EMAIL="" ;; esac

if [ "$FP" != "$PREV_FP" ] || [ -z "$FIRST_SEEN" ]; then
    FIRST_SEEN=$NOW
    EPISODE_DAY=1
    SEND=1
    REASON="new"
else
    EPISODE_DAY=$(( (NOW - FIRST_SEEN) / 86400 + 1 ))
    if [ -z "$LAST_EMAIL" ] || [ $(( (NOW - LAST_EMAIL) / 86400 )) -ge "$REMIND_DAYS" ]; then
        SEND=1
        REASON="reminder"
    else
        SEND=0
        REASON="suppressed"
    fi
fi

if [ "$REASON" = "reminder" ]; then
    SUBJECT="[Augur] heartbeat STILL FAILING — day ${EPISODE_DAY} (last commit ${AGE_H}h ago)"
else
    SUBJECT="[Augur] daily pipeline heartbeat FAILED (last commit ${AGE_H}h ago)"
fi

BODY="$TS — Augur daily pipeline heartbeat FAILED on sadalsuud.
${FINDINGS}

Newest daily commit: ${LAST_SUBJECT:-(none)}
Timer: ${TIMER_ENABLED} / ${TIMER_ACTIVE}   next elapse: ${NEXT_RUN:-unknown}
Finding shape: ${FP}   (episode day ${EPISODE_DAY})

This check exists because these shapes produce no unit failure, so
OnFailure=augur-alert@ cannot fire for them: a run that commits nothing still
exits 0, and a disabled timer never runs at all.

Cost: EXP-018a / EXP-021a / EXP-028a are gated on consecutive vintages from
t0 >= 2026-08-25. Each missed day slips the September schedule by a day and is
permanently unevaluable (no backfill — augur#14).

Diagnose:  ssh sadalsuud 'systemctl list-timers augur-daily.timer; journalctl -u augur-daily.service -n 50 --no-pager'
Run log:   $AUGUR_DIR/logs/daily_update.log"

if [ "$SEND" = "1" ]; then
    RESULT=$(printf '%s' "$BODY" | python3 "$AUGUR_DIR/scripts/notify_email.py" \
        "$SUBJECT" 2>&1) \
        || RESULT="ERROR: notify_email.py did not run"
    # Arm the reminder clock only on a confirmed send, mirroring
    # alert_failure.sh: a log-only degrade must not buy three days of silence.
    case "$RESULT" in
        SENT*) LAST_EMAIL=$NOW ;;
    esac
    echo "$TS: heartbeat ALERT (${REASON}, day ${EPISODE_DAY}, shape '${FP}', age ${AGE_H}h, timer ${TIMER_ENABLED}/${TIMER_ACTIVE}, unpushed ${UNPUSHED}, markers '${ALARM_HIT}') — $RESULT" >> "$LOG" 2>/dev/null || true
else
    NEXT_IN=$(( REMIND_DAYS - (NOW - LAST_EMAIL) / 86400 ))
    echo "$TS: heartbeat ALERT suppressed (unchanged shape '${FP}', day ${EPISODE_DAY}, reminder in ${NEXT_IN}d, age ${AGE_H}h, markers '${ALARM_HIT}')" >> "$LOG" 2>/dev/null || true
fi

printf '%s\t%s\t%s\n' "$FP" "$FIRST_SEEN" "${LAST_EMAIL:-}" > "$STATE" 2>/dev/null || true

# A sent alert means the check worked. Do not fail the unit, or the heartbeat's
# own OnFailure= would send a second, less informative email for the same event.
exit 0
