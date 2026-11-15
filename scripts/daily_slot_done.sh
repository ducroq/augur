#!/usr/bin/env bash
# ExecCondition for augur-daily.service: skip the run when this slot already has
# a `Daily update` commit (augur#39).
#
# Why: augur-daily.timer also fires at boot (OnBootSec), so a reboot that kills
# a run in flight gets picked up again. Persistent=true can't do this. It only
# replays a trigger that was *missed*, and a run that was killed mid-way had
# already been triggered. 2026-11-13: sadalsuud reset at 17:42 CET while the
# gate was waiting, nothing re-ran the job, and the day was lost
# ([ALARM: t0 jumped 2d] the next night). Most boots happen when the slot is
# already done, so this guard turns those boot triggers into a quiet skip.
#
# Slot: the most recent 16:30 UTC at or before now (the OnCalendar time). The
# slot is done when the newest commit whose SUBJECT starts `Daily update ` is at
# or after it AND has reached origin/main (the local tracking ref, so no
# network). Subject only: `git log --grep` also matches body lines, so a doc
# commit quoting a daily subject would have counted. Pushed only: the job
# commits and pushes as two steps, and a reboot between them must not count as
# delivered. In that case the job runs again; if that rerun has nothing new
# to commit it skips the push too, and the heartbeat's unpushed check is the
# backstop. Commit time is used, not the date in the subject: the gate polls to
# 03:00 UTC, so a run can commit after midnight UTC under the next day's date.
#
# Exit contract (systemd ExecCondition): 0 = run, 1 = skip cleanly (no failure,
# no OnFailure=). The decision fails OPEN: if git or date can't answer, run.
# Same rule as wait_for_edh.sh, which never fails closed. This covers the
# script's own decision only. If systemd can't exec the script at all (missing,
# not executable), the unit fails and OnFailure= alerts.
#
# Manual re-run of a slot that is already done: this guard will skip
# `systemctl start augur-daily.service`. Use `scripts/daily_update.sh` directly,
# or `sudo systemctl set-environment AUGUR_FORCE_RUN=1`, start, then
# `sudo systemctl unset-environment AUGUR_FORCE_RUN`. It stays in the manager
# environment, and so reaches every unit the manager starts, until unset or
# reboot.
#
# Test hooks: AUGUR_DIR, NOW_EPOCH. Tests: tests/test_daily_slot_done.py.
set -u

AUGUR_DIR="${AUGUR_DIR:-/home/jeroen/local_dev/augur}"
NOW="${NOW_EPOCH:-$(date -u +%s)}"
# TS is display only: a failed format leaves "?" and doesn't touch the decision.
TS=$(date -u -d "@$NOW" '+%Y-%m-%d %H:%M:%S UTC' 2>/dev/null) || TS="?"

if [ "${AUGUR_FORCE_RUN:-0}" = "1" ]; then
    echo "$TS: slot guard: AUGUR_FORCE_RUN=1, running"
    exit 0
fi

run_open() { echo "$TS: slot guard: $1, running (fail open)"; exit 0; }

[[ "$NOW" =~ ^[0-9]+$ ]] || run_open "NOW_EPOCH '$NOW' is not an epoch"
DAY=$(date -u -d "@$NOW" +%Y-%m-%d) || run_open "date failed"
SLOT=$(date -u -d "$DAY 16:30:00 UTC" +%s) || run_open "date failed"
[ "$NOW" -lt "$SLOT" ] && SLOT=$((SLOT - 86400))
SLOT_H=$(date -u -d "@$SLOT" '+%Y-%m-%d %H:%M UTC') || run_open "date failed"

# Newest commit on HEAD whose subject (not body) starts with the literal
# "Daily update " (the prefix daily_update.sh writes).
read -r LAST SHA < <(git -C "$AUGUR_DIR" log --format='%ct %H %s' 2>/dev/null |
    awk '{ ts = $1; sha = $2; sub(/^[^ ]+ [^ ]+ /, "") }
         index($0, "Daily update ") == 1 { print ts, sha; exit }')
[[ "${LAST:-}" =~ ^[0-9]+$ ]] || run_open "no readable 'Daily update' commit"

if [ "$LAST" -lt "$SLOT" ]; then
    echo "$TS: slot guard: slot $SLOT_H has no commit yet, running"
    exit 0
fi
if ! git -C "$AUGUR_DIR" merge-base --is-ancestor "$SHA" origin/main 2>/dev/null; then
    echo "$TS: slot guard: slot $SLOT_H committed (${SHA:0:7}) but not on origin/main, running"
    exit 0
fi
echo "$TS: slot guard: slot $SLOT_H already committed and pushed (${SHA:0:7}), skipping"
exit 1
