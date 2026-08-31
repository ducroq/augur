#!/usr/bin/env bash
# OnFailure handler for augur-daily.service (wired via augur-alert@.service).
#
# Why this exists (deferred 2026-07-03, built 2026-08-30): the only alive-signal
# for the daily job was "someone notices missing `Daily update` commits on
# origin/main". The 2026-06-29 -> 07-03 outage therefore ran five nights in
# silence. Every in-script ALARM (ARF FAIL, DEP_MARKER, SMOKE_MARKER,
# eval-stale, t0-stale/jumped) surfaces *in the commit subject*, so a unit that
# dies before committing produces no signal at all. That is the case this
# covers. The complementary case -- unit exits 0 but commits nothing, timer
# disabled, box down -- is covered by scripts/heartbeat_check.sh, because
# OnFailure= structurally cannot fire for it.
#
# Stake: three pre-committed experiments (EXP-018a, EXP-021a, EXP-028a) are
# gated on an uninterrupted vintage stream from September onward. A silent
# multi-day freeze now costs a week of that schedule.
#
# Channel: the shared Gmail sender in FluxusSource's gitignored secrets.ini on
# this host, via scripts/notify_email.py -- the same channel NexusMind's
# alert_failure.sh uses. No new notification service (engineer's call,
# 2026-07-17). Creds absent => log-only, still exits 0.
#
# Burst guard: at most one email per 3h. The daily cadence means every failed
# run still emails; a flurry of manual `systemctl start` failures during a
# debugging session sends only one.
#
# This script must NEVER fail or block: it runs inside systemd's failure
# handling, where an alerter that itself errors only adds noise. Hence `set -u`
# (not -e), `|| true` on every side effect, and `exit 0` at the end.
set -u

UNIT="${1:-unknown-unit}"
AUGUR_DIR="${AUGUR_DIR:-/home/jeroen/local_dev/augur}"
LOG="$AUGUR_DIR/logs/alerts.log"
MARKER="$AUGUR_DIR/logs/.alerts_last_email"
BURST_GUARD_MIN="${BURST_GUARD_MIN:-180}"
TS=$(date -Iseconds)

# augur-daily.service sets StandardOutput/StandardError=append:logs/daily_update.log,
# which OVERRIDES systemd's default journal capture — so `journalctl -u` holds only
# systemd's own lifecycle lines and NEVER the script's output. (The comment in
# augur-daily.service claiming output "lands in the journal" is wrong; corrected
# 2026-08-31 after the first test alert shipped an email with seven days of
# "Deactivated successfully" and zero diagnostics.) The journal still carries the
# exit code and timeout, so keep it — but the actual error text is in the run log,
# and that is what the reader needs first.
JOURNAL=$(journalctl -u "$UNIT" -n 12 --no-pager 2>&1 | tail -12) || JOURNAL="(journalctl unavailable)"
RUNLOG="$AUGUR_DIR/logs/daily_update.log"
RUNTAIL=$(tail -40 "$RUNLOG" 2>&1) || RUNTAIL="(run log unreadable at $RUNLOG)"

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
{
    echo "=== $TS $UNIT FAILED ==="
    systemctl status "$UNIT" --no-pager -l 2>&1 | head -20
} >> "$LOG" 2>/dev/null || true

# Burst guard: skips the email, never the log line above.
if [ -f "$MARKER" ] && [ -n "$(find "$MARKER" -mmin "-$BURST_GUARD_MIN" 2>/dev/null)" ]; then
    echo "$TS: email skipped (burst guard, last sent <${BURST_GUARD_MIN}min ago)" >> "$LOG" 2>/dev/null || true
    exit 0
fi

# The journal lines are the evidence. Name causes only as hypotheses -- a
# hardcoded "most likely cause" misdiagnosed the first NexusMind version, and
# this unit has several unrelated fatal paths. Steps that are deliberately
# non-fatal (ARF, consolidate, shadow update/eval, smoke) cannot land here;
# they alarm in the commit subject instead, so do not suggest them.
read -r -d '' HINT <<'HINTEOF' || true
Where daily_update.sh can die hard (it runs under `set -e`, but the ARF,
consolidate, shadow-update, shadow-eval and smoke steps are `set +e` guarded
and alarm in the commit subject instead -- so none of those are the cause here):

  * git pull of energyDataHub or augur -- conflict, auth, or network
  * git commit / git push -- rejected, non-fast-forward, or credential expiry
  * a broken venv on a path outside the DEP_PROBE_OK probe
  * disk full (the parquet rebuild and the model artifact both need room)
  * TimeoutStartSec=19800 exceeded -- ExecStartPre wait_for_edh.sh polls up to
    4h, so a hung poll plus a slow run can trip the 5h30m unit timeout

Cost of this failure: one lost vintage. EXP-018a / EXP-021a / EXP-028a are all
gated on consecutive vintages from t0 >= 2026-08-25, so a multi-day freeze
pushes the whole September schedule.
HINTEOF

BODY="$TS -- systemd unit '$UNIT' FAILED on sadalsuud.

Last 40 lines of the run log -- THIS is where the error text is:
$RUNTAIL

systemd lifecycle lines (exit code / timeout; carries no script output):
$JOURNAL

$HINT

Diagnose:   ssh sadalsuud 'journalctl -u $UNIT -n 50 --no-pager'
Run log:    $AUGUR_DIR/logs/daily_update.log
Alert log:  $LOG"

RESULT=$(printf '%s' "$BODY" | python3 "$AUGUR_DIR/scripts/notify_email.py" \
    "[Augur] $UNIT FAILED on sadalsuud" 2>&1) || RESULT="ERROR: notify_email.py did not run"
echo "$TS: $RESULT" >> "$LOG" 2>/dev/null || true

# Arm the burst guard only after a confirmed send -- a skipped or failed email
# must not silence the next real alert.
case "$RESULT" in
    SENT:*) : > "$MARKER" 2>/dev/null || true ;;
esac

exit 0
