#!/bin/bash
# Block until energyDataHub publishes a usable dataset, or hit a deadline.
#
# augur#12 / augur#25. The daily LGBM update must not start before EDH has
# committed a data_quality_report.json that actually contains what Augur needs.
#
# WHY THIS WAS REWRITTEN (2026-09-01). The previous gate read one field of the
# report -- `timestamp` -- and decided readiness from the CLOCK: date must be
# today, publish hour must be >= 12 UTC. Two things were wrong with that.
#
#   1. The window was fixed (16:30 UTC + 4h). GitHub Actions defers this cron
#      unpredictably: over 56 days the scheduled run STARTED anywhere from 00:18
#      to 21:14 UTC, median 16:51. A real publish landing at 21:20 is invisible
#      to a window that shut at 20:30. No such miss has been recorded yet only
#      because the late-starting runs also happened to fail for other reasons.
#
#   2. The clock was a proxy for a question the report already answers. Compare
#      what the sentinel actually said on the days that hurt:
#
#        2026-08-22 16:17   entsoe=192  load=384   normal
#        2026-08-24 06:28   entsoe= 96  load=192   catch-up (correctly rejected)
#        2026-08-24 16:32   entsoe=192  load=384   the real one, 90s later
#        2026-08-26 16:44   entsoe= 96  load=384   short ENTSO-E at a NORMAL hour
#        2026-08-28 00:44   entsoe= 96  load=192   catch-up
#        2026-08-30 19:02   entsoe=192  load=192   halved load feed
#
#      Every catch-up is exactly half size. ⚠️ CORRECTED 2026-09-10 (augur#31):
#      the converse does NOT hold, and this comment asserted it for nine days.
#      Half-size does not imply catch-up -- the 08-26 row four lines above is a
#      SCHEDULED 16:44 run that is short anyway, and 2026-09-08T19:15 is another.
#      8 of the last 14 publishes are half-size and at least two are scheduled
#      evening runs, so point count cannot separate "pre-auction" from
#      "genuinely degraded" and EXPECTED_PTS keeps absorbing the latter. The
#      table below refuted the sentence it was used to justify. Upstream is
#      investigating the two scheduled shorts as energydatahub#74; the fix on
#      this side is to assert the day-ahead SPAN, which is decidable without
#      classifying the cause. And the two anomalies were both real incidents
#      the hour rule waved through: 08-26 is the day 2 hours of the training target came
#      from a fallback source, and 08-30 is the run whose halved load feed
#      crashed update_shadow and forced latest_feasible_t0. Both were described
#      in the report at publish time. Nothing was reading them.
#
# READINESS CONTRACT. Proceed when BOTH hold:
#   (a) the report timestamp is strictly newer than the one we last consumed --
#       monotonic, so a publish is never used twice. This is also what stops the
#       "t0 did not advance, vintage overwritten" shape at its source: if EDH
#       has published nothing new, we do not treat yesterday's data as ready.
#   (b) the primary dataset carries a full publish, measured against the median
#       of recent publishes rather than a hardcoded constant -- see EXPECTED_PTS.
#
# A short SECONDARY feed (load_forecast) does NOT block. 08-26 proves blocking
# would be wrong: that day's only publish was short, so refusing it would have
# cost the vintage outright rather than costing two hours of provenance. We
# proceed and name it, and latest_feasible_t0 handles the rest. Because it does
# not block, it is emitted as `[NOTE: ...]` and not `[ALARM: ...]` -- see the
# comment at the emission site.
#
# GIVING UP EARLY (2026-09-10). The contract above answers "has a good publish
# landed?" but cannot distinguish "EDH is running late" from "EDH has FAILED and
# nothing is coming tonight" -- so both spend the whole window polling to the
# 03:00 deadline. EDH's alert job opens exactly one issue labelled
# `publish-failure` on ducroq/energydatahub when a publish fails and closes it on
# recovery (#69 opened 09-07 19:51 and closed 09-08 19:16, 27s after the
# recovery publish). Reading that label turns an 8-hour blind wait into a
# definite answer: on 2026-09-09 the issue opened at 19:13 UTC while this gate
# sat polling until 03:00, then let the run retrain on an unchanged parquet and
# republish a byte-identical vintage over a still-evaluable one.
#
# The reference point is this run's START, not the last consumed report, and the
# difference matters: an issue from a PREVIOUS night can still be open when we
# start (EDH only closes it on the next successful publish), and comparing
# against the last consumed report would then make the gate give up at 16:30
# before EDH's run -- deferred to 17:50-19:30 -- had even begun. Only a failure
# reported WHILE we were waiting says anything about tonight.
#
# This never blocks and never adds a wait: it can only end one early, and every
# way of not knowing (offline, rate limit, non-200, schema change) falls
# through to the existing deadline path. Read with python3 stdlib, not `gh`,
# which is not installed on sadalsuud.
#
# FAIL OPEN, ALWAYS. Unreadable report, missing dataset, schema change, deadline
# reached -- every path exits 0 and lets the run proceed. A gate that fails
# closed freezes the dashboard with no signal. Everything it notices is written
# to the verdict file and ridden into the commit subject by daily_update.sh,
# which is where every other alarm in this pipeline already lives.

set -u

DATAHUB_DIR="${DATAHUB_DIR:-$HOME/local_dev/energydatahub}"
AUGUR_DIR="${AUGUR_DIR:-$HOME/local_dev/augur}"
STATE="${EDH_GATE_STATE:-$AUGUR_DIR/logs/.edh_gate_state}"
VERDICT="${EDH_GATE_VERDICT:-$AUGUR_DIR/logs/.edh_gate_verdict}"

# 03:00 UTC covers the entire observed publish distribution (latest real start
# 21:14, latest catch-up 06:28) with margin before the next 16:30 fire.
DEADLINE_HOUR_UTC="${EDH_DEADLINE_HOUR_UTC:-3}"
POLL_SEC="${EDH_POLL_SEC:-120}"
SAMPLE_N="${EDH_SAMPLE_N:-10}"
PRIMARY_DATASET="${EDH_PRIMARY_DATASET:-entsoe}"
SECONDARY_DATASET="${EDH_SECONDARY_DATASET:-load_forecast}"
# Only used when git history cannot be sampled at all.
FALLBACK_PRIMARY_PTS="${EDH_FALLBACK_PRIMARY_PTS:-192}"
# How long a SHORT primary publish is held before it is accepted anyway
# (augur#31, 2026-09-11). Not a refusal and not an instant accept -- see the
# block above record_and_go for why the two pure positions are both wrong.
# 0 disables the hold entirely (accept-and-alarm on the first short).
SHORT_HOLD_HOURS="${EDH_SHORT_HOLD_HOURS:-4}"

# Upstream publish-failure signal. Polled every Nth iteration rather than every
# one: at the default 120s poll that is a GitHub API read every 10 minutes,
# which stays well inside even the unauthenticated hourly budget. 0 disables.
FAILURE_REPO="${EDH_FAILURE_REPO:-ducroq/energydatahub}"
FAILURE_LABEL="${EDH_FAILURE_LABEL:-publish-failure}"
ISSUE_POLL_EVERY="${EDH_ISSUE_POLL_EVERY:-5}"
API_TIMEOUT_SEC="${EDH_API_TIMEOUT_SEC:-20}"
# Read GitHub's public REST API directly with python3 stdlib rather than via
# `gh`: gh is NOT installed on sadalsuud, so a gh-based probe silently no-ops
# in the one place it needs to work. This needs no binary, no auth and no
# secret -- energydatahub is public, and an unauthenticated read is 60/hr per
# IP against our ~6/hr. Overridable as a whole so tests can point at file://.
FAILURE_API_URL="${EDH_FAILURE_API_URL:-https://api.github.com/repos/${FAILURE_REPO}/issues?labels=${FAILURE_LABEL}&state=open&per_page=5}"

case "$SHORT_HOLD_HOURS" in
    ''|*[!0-9]*)
        echo "[wait_for_edh] WARN: EDH_SHORT_HOLD_HOURS='${SHORT_HOLD_HOURS}' is not a number — using 4."
        SHORT_HOLD_HOURS=4 ;;
esac
# Seconds override: finer granularity than the hours knob, for tests and for
# an operator who wants a hold shorter than an hour. Hours remains the
# documented dial; this is the same value in the unit the code compares in.
SHORT_HOLD_SEC="${EDH_SHORT_HOLD_SEC:-$(( SHORT_HOLD_HOURS * 3600 ))}"
case "$SHORT_HOLD_SEC" in
    ''|*[!0-9]*) SHORT_HOLD_SEC=$(( SHORT_HOLD_HOURS * 3600 )) ;;
esac
FIRST_SHORT_TS=""

START_TS=$(date -u +%s)
mkdir -p "$(dirname "$VERDICT")" 2>/dev/null || true
: > "$VERDICT"

# EDH_MAX_WAIT_SEC overrides the wall-clock deadline with a relative one. Used
# by the tests, and available as an operator escape hatch for a one-off run that
# should not sit until 03:00.
if [ -n "${EDH_MAX_WAIT_SEC:-}" ]; then
    DEADLINE_TS=$(( START_TS + EDH_MAX_WAIT_SEC ))
else
    DEADLINE_TS=$(date -u -d "today ${DEADLINE_HOUR_UTC}:00" +%s 2>/dev/null || echo 0)
    if [ "$DEADLINE_TS" -le "$START_TS" ]; then
        DEADLINE_TS=$(date -u -d "tomorrow ${DEADLINE_HOUR_UTC}:00" +%s 2>/dev/null || echo $(( START_TS + 37800 )))
    fi
fi

# Never let the wait outlive the unit's own TimeoutStartSec. If this script is
# still polling when systemd's start timeout expires, the unit is KILLED and the
# run is skipped entirely — fail-CLOSED, the one outcome this gate exists to
# avoid. That happens the moment the script is deployed ahead of the updated
# augur-daily.service, which is an easy ordering mistake to make. So cap the
# deadline against whatever the running unit actually allows, minus room for the
# run itself. Unparseable or absent (standalone runs, tests): no cap.
RUN_RESERVE_SEC="${EDH_RUN_RESERVE_SEC:-5400}"
UNIT_TIMEOUT_RAW=$(systemctl show augur-daily.service -p TimeoutStartUSec --value 2>/dev/null || true)
UNIT_TIMEOUT_SEC=$(printf '%s' "${UNIT_TIMEOUT_RAW:-}" | awk '
    /infinity/ { exit }
    {
        total = 0
        n = split($0, part, /[[:space:]]+/)
        for (i = 1; i <= n; i++) {
            p = part[i]
            if      (p ~ /^[0-9]+d$/)   { sub("d","",p);   total += p * 86400 }
            else if (p ~ /^[0-9]+h$/)   { sub("h","",p);   total += p * 3600 }
            else if (p ~ /^[0-9]+min$/) { sub("min","",p); total += p * 60 }
            else if (p ~ /^[0-9]+s$/)   { sub("s","",p);   total += p }
        }
        if (total > 0) print total
    }')
if printf '%s' "${UNIT_TIMEOUT_SEC:-}" | grep -qE '^[0-9]+$'; then
    UNIT_CAP_TS=$(( START_TS + UNIT_TIMEOUT_SEC - RUN_RESERVE_SEC ))
    if [ "$UNIT_CAP_TS" -lt "$DEADLINE_TS" ]; then
        echo "[wait_for_edh] WARN: capping deadline at $(date -u -d "@$UNIT_CAP_TS" '+%H:%M UTC') — augur-daily.service TimeoutStartSec is ${UNIT_TIMEOUT_RAW}, too short for the intended window. Deploy scripts/systemd/augur-daily.service and daemon-reload to get the full wait."
        DEADLINE_TS="$UNIT_CAP_TS"
    fi
fi

LAST_CONSUMED=""
[ -f "$STATE" ] && LAST_CONSUMED=$(head -n1 "$STATE" 2>/dev/null || true)

# Parse one report into "timestamp|primary_points|secondary_points".
#
# The delimiter is "|" and NOT a tab on purpose. Tab is IFS *whitespace*, so
# bash collapses runs of it: "ts<TAB><TAB>384" reads back as two fields,
# silently shifting load_forecast's count into the entsoe slot and making a
# report with no ENTSO-E data at all look like a full publish. A non-whitespace
# delimiter preserves empty fields. Caught by
# tests/test_wait_for_edh.py::test_missing_primary_dataset_still_exits_zero.
# Blank fields on any failure -- the caller treats blanks as "not ready yet",
# and the deadline guarantees we still run.
parse_report() {
    python3 -c '
import sys, json
try:
    r = json.load(sys.stdin)
except Exception:
    print("||"); sys.exit(0)
d = {x.get("dataset_name"): x for x in r.get("dataset_reports", []) if isinstance(x, dict)}
def pts(name):
    v = d.get(name, {}).get("data_points")
    return str(v) if isinstance(v, int) else ""
print("|".join([str(r.get("timestamp", "")), pts(sys.argv[1]), pts(sys.argv[2])]))
' "$PRIMARY_DATASET" "$SECONDARY_DATASET" 2>/dev/null || printf '||'
}

expected_points() {
    # $1 = dataset name. The 75th PERCENTILE of primary-dataset size over the
    # last SAMPLE_N publishes. Deriving the expectation instead of hardcoding
    # 192 means a resolution change upstream (15-min -> hourly) is absorbed in
    # a few days instead of making every publish read as short forever.
    #
    # It was the MEDIAN until 2026-09-11 (augur#31), and the median broke: a
    # run of degraded and catch-up publishes took it from 192 to 96, so the
    # gate stopped recognising a short publish as short at all. Over the last
    # 20 publishes 11 were 192 and 9 were 96 -- a median that close to the
    # boundary is one bad week away from flipping, in either direction.
    #
    # The catch-ups are the reason it is so close: EDH republishes several
    # times on a recovery day (three on 2026-09-04 alone), so short publishes
    # are over-represented per DAY, not just per day-with-a-problem. Per-day
    # dedup was measured and refuted as the fix. The 75th percentile is the
    # blunter and more honest one: the expectation should sit where a HEALTHY
    # publish sits, and healthy publishes are the majority of a normal week.
    local name="$1" rev
    for rev in $(git -C "$DATAHUB_DIR" log --format=%H --grep='^Update energy data' \
                     -n "$SAMPLE_N" origin/main 2>/dev/null); do
        git -C "$DATAHUB_DIR" show "$rev:data/data_quality_report.json" 2>/dev/null \
          | python3 -c '
import sys, json
try:
    r = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for x in r.get("dataset_reports", []):
    if isinstance(x, dict) and x.get("dataset_name") == sys.argv[1]:
        v = x.get("data_points")
        if isinstance(v, int):
            print(v)
        break
' "$name" 2>/dev/null
    done | sort -n | awk '{a[NR]=$1} END {if (NR) print a[int((NR*3+3)/4)]}'
}

# Print the number of an OPEN publish-failure issue reported since this run
# started, or nothing at all. Every failure mode -- offline, DNS, rate-limited,
# non-200, changed schema, unparseable date -- prints nothing, which the caller
# reads as "no information" and keeps waiting. It must never be able to
# manufacture a give-up.
upstream_publish_failed() {
    python3 -c '
import sys, json, datetime as dt, urllib.request
url, since_epoch, timeout = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    since = dt.datetime.fromtimestamp(int(since_epoch), dt.timezone.utc)
    req = urllib.request.Request(url, headers={
        "User-Agent": "augur-wait-for-edh",
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=float(timeout)) as r:
        rows = json.load(r)
except Exception:
    sys.exit(0)
if not isinstance(rows, list):
    sys.exit(0)
newest = None
for r in rows:
    if not isinstance(r, dict):
        continue
    # REST spells it created_at; gh --json spells it createdAt. Accept either.
    raw = r.get("created_at") or r.get("createdAt")
    num = r.get("number")
    if not isinstance(raw, str) or not isinstance(num, int):
        continue
    try:
        created = dt.datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except Exception:
        continue
    if created.tzinfo is None:
        continue
    # Strictly after this run began -- see the header note on why START_TS and
    # not the last consumed report.
    if created > since and (newest is None or created > newest[0]):
        newest = (created, num)
if newest:
    print(newest[1])
' "$FAILURE_API_URL" "$START_TS" "$API_TIMEOUT_SEC" 2>/dev/null || true
}

git -C "$DATAHUB_DIR" fetch --quiet origin main 2>/dev/null || true

EXPECTED_PTS=$(expected_points "$PRIMARY_DATASET")
EXPECTED_SECONDARY=$(expected_points "$SECONDARY_DATASET")
if ! printf '%s' "${EXPECTED_PTS:-}" | grep -qE '^[0-9]+$'; then
    EXPECTED_PTS="$FALLBACK_PRIMARY_PTS"
    echo "[wait_for_edh] WARN: could not sample ${PRIMARY_DATASET} history; using fallback expectation ${EXPECTED_PTS}"
fi

echo "[wait_for_edh] Started $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "[wait_for_edh] Ready when report is newer than '${LAST_CONSUMED:-<none, bootstrapping>}' and ${PRIMARY_DATASET} >= ${EXPECTED_PTS} points (median of last ${SAMPLE_N})"
echo "[wait_for_edh] Deadline $(date -u -d "@$DEADLINE_TS" '+%Y-%m-%d %H:%M UTC'); proceeding anyway at that point"

# Sets SECONDARY_MARKER (possibly empty) and logs. A function rather than an
# inline block because BOTH accept paths need it -- the full-publish path and
# the short-publish-accepted-after-hold path -- and duplicating it is how the
# two would drift.
#
# NOTE, not ALARM (demoted 2026-09-11). heartbeat_check.sh treats every
# `ALARM:` in the commit subject as a SOFT FAILURE and mails "pipeline FAILED",
# so this marker mailed a failure for a run that is explicitly allowed to
# proceed -- 2026-09-10 published load_forecast=288/384 and the run finished
# `shadow rc=0/eval rc=0` with t0_held_back_hours=0.0. Same split the
# seasonal-naive floor got on 2026-09-06: a condition worth recording is not a
# fault.
#
# And the gate cannot say t0 WILL be held back -- it sees a point count, not a
# feature row. Whether the short feed actually costs anything is
# `latest_feasible_t0`'s call, and when it does the answer arrives as
# `[ALARM: t0 held back Nh — <feeds> short]` from a place that measured it.
# That alarm is the fault detector; this is the early warning beside it.
#
# A short SECONDARY never holds, in either accept path: 2026-08-26's only
# publish was short and refusing it would have cost the vintage outright.
SECONDARY_MARKER=""
check_secondary() {
    SECONDARY_MARKER=""
    if printf '%s' "$SECONDARY_PTS" | grep -qE '^[0-9]+$' \
       && printf '%s' "${EXPECTED_SECONDARY:-}" | grep -qE '^[0-9]+$' \
       && [ "$SECONDARY_PTS" -lt "$EXPECTED_SECONDARY" ]; then
        echo "[wait_for_edh] NOTE: ${SECONDARY_DATASET} short at publish (${SECONDARY_PTS} < ${EXPECTED_SECONDARY}) — may cost horizon; the t0 guard decides. Proceeding."
        SECONDARY_MARKER=" [NOTE: EDH ${SECONDARY_DATASET} short at publish ${SECONDARY_PTS}/${EXPECTED_SECONDARY}]"
    fi
}

record_and_go() {
    # $1 = upstream timestamp, $2 = marker to ride the commit subject
    printf '%s\n' "$1" > "$STATE" 2>/dev/null || true
    printf '%s' "$2" > "$VERDICT" 2>/dev/null || true
    exit 0
}

POLL_I=0
while : ; do
    git -C "$DATAHUB_DIR" fetch --quiet origin main 2>/dev/null || true
    REPORT=$(git -C "$DATAHUB_DIR" show "origin/main:data/data_quality_report.json" 2>/dev/null || true)
    PARSED=$(printf '%s' "$REPORT" | parse_report)
    IFS='|' read -r UPSTREAM_TS PRIMARY_PTS SECONDARY_PTS <<< "$PARSED"
    UPSTREAM_TS="${UPSTREAM_TS:-}"; PRIMARY_PTS="${PRIMARY_PTS:-}"; SECONDARY_PTS="${SECONDARY_PTS:-}"

    IS_NEW=0
    if [ -n "$UPSTREAM_TS" ]; then
        if [ -z "$LAST_CONSUMED" ]; then
            IS_NEW=1   # bootstrap: no state yet, any readable report counts as new
        elif [[ "$UPSTREAM_TS" > "$LAST_CONSUMED" ]]; then
            IS_NEW=1
        fi
    fi

    IS_FULL=0
    if printf '%s' "$PRIMARY_PTS" | grep -qE '^[0-9]+$' && [ "$PRIMARY_PTS" -ge "$EXPECTED_PTS" ]; then
        IS_FULL=1
    fi

    # Bounded hold on a SHORT primary (augur#31, 2026-09-11). Neither pure
    # position is right, and the publish record says so plainly:
    #
    #   2026-09-04  06:53 / 08:13 / 10:16 short, then 18:46 FULL (192)
    #   2026-09-08  19:15 short, and nothing better ever came
    #
    # Refusing outright wins the first case -- the gate held ~2h from its 16:30
    # start and got the good publish. Accepting instantly wins the second --
    # EDH's root-cause (their d3e540f) is that upstream answered a four-day
    # query with one day, silently, so nothing better is coming and the next
    # publish is 24h away. Six of the nine shorts in the last twenty publishes
    # are off-schedule catch-ups of the first kind, so a design that always
    # accepts throws away the commoner save.
    #
    # So: hold, but bound it. A superseding publish gets its chance; a genuine
    # short-delivery costs SHORT_HOLD_HOURS instead of burning to the 03:00
    # deadline (~5h saved on the 09-08 shape). The bound runs from the first
    # short seen IN THIS RUN and is never reset by a later one -- upstream
    # republishing shorts hourly must not extend the hold indefinitely.
    if [ "$IS_NEW" = "1" ] && [ "$IS_FULL" = "0" ] \
       && printf '%s' "$PRIMARY_PTS" | grep -qE '^[0-9]+$'; then
        if [ -z "$FIRST_SHORT_TS" ]; then
            FIRST_SHORT_TS=$(date -u +%s)
            echo "[wait_for_edh] SHORT primary: ${PRIMARY_DATASET}=${PRIMARY_PTS} < ${EXPECTED_PTS}. Holding up to ${SHORT_HOLD_HOURS}h for a fuller publish, then accepting anyway."
        fi
        HELD_SEC=$(( $(date -u +%s) - FIRST_SHORT_TS ))
        if [ "$HELD_SEC" -ge "$SHORT_HOLD_SEC" ]; then
            check_secondary
            echo "[wait_for_edh] ACCEPTING short publish after $(( HELD_SEC / 60 ))min: no fuller one arrived. The vintage is degraded, not lost — t0 guards mark the consequence."
            echo "[wait_for_edh] READY: ${UPSTREAM_TS}, ${PRIMARY_DATASET}=${PRIMARY_PTS} (< ${EXPECTED_PTS}, accepted after hold), ${SECONDARY_DATASET}=${SECONDARY_PTS:-?}."
            record_and_go "$UPSTREAM_TS" \
                " [ALARM: EDH ${PRIMARY_DATASET} short ${PRIMARY_PTS}/${EXPECTED_PTS} accepted after ${SHORT_HOLD_HOURS}h]${SECONDARY_MARKER}"
        fi
    fi

    if [ "$IS_NEW" = "1" ] && [ "$IS_FULL" = "1" ]; then
        check_secondary
        MARKER="$SECONDARY_MARKER"
        [ -z "$LAST_CONSUMED" ] && echo "[wait_for_edh] NOTE: no prior state — bootstrapping from this publish. Subsequent runs require a strictly newer one."
        echo "[wait_for_edh] READY: ${UPSTREAM_TS}, ${PRIMARY_DATASET}=${PRIMARY_PTS} (>= ${EXPECTED_PTS}), ${SECONDARY_DATASET}=${SECONDARY_PTS:-?}. Proceeding."
        record_and_go "$UPSTREAM_TS" "$MARKER"
    fi

    POLL_I=$(( POLL_I + 1 ))
    if [ "$ISSUE_POLL_EVERY" -gt 0 ] \
       && [ $(( (POLL_I - 1) % ISSUE_POLL_EVERY )) -eq 0 ]; then
        FAILED_ISSUE=$(upstream_publish_failed)
        if printf '%s' "${FAILED_ISSUE:-}" | grep -qE '^[0-9]+$'; then
            echo "[wait_for_edh] UPSTREAM FAILED: ${FAILURE_REPO}#${FAILED_ISSUE} (${FAILURE_LABEL}) was opened while we were waiting — nothing is coming tonight. Giving up after $(( ($(date -u +%s) - START_TS) / 60 ))min instead of holding to the deadline."
            # Same as the deadline path: do NOT record this as consumed, so the
            # recovery publish is still accepted by the next run.
            printf '%s' " [ALARM: EDH publish FAILED upstream — ${FAILURE_REPO}#${FAILED_ISSUE}]" > "$VERDICT" 2>/dev/null || true
            exit 0
        fi
    fi

    NOW_TS=$(date -u +%s)
    if [ "$NOW_TS" -ge "$DEADLINE_TS" ]; then
        if [ -z "$UPSTREAM_TS" ]; then
            REASON="report unreadable"
        elif [ "$IS_NEW" != "1" ]; then
            REASON="no new publish since ${LAST_CONSUMED}"
        else
            REASON="${PRIMARY_DATASET} only ${PRIMARY_PTS:-?} points (want >= ${EXPECTED_PTS})"
        fi
        echo "[wait_for_edh] DEADLINE reached after $(( (NOW_TS - START_TS) / 60 ))min — ${REASON}. Proceeding on possibly stale data; t0 guards will mark the result."
        # Deliberately NOT recording this timestamp as consumed: we never got an
        # adequate publish, so the next run must still be allowed to accept it.
        printf '%s' " [ALARM: EDH gate timeout — ${REASON}]" > "$VERDICT" 2>/dev/null || true
        exit 0
    fi

    echo "[wait_for_edh] not ready (ts=${UPSTREAM_TS:-<empty>} new=${IS_NEW} ${PRIMARY_DATASET}=${PRIMARY_PTS:-?}/${EXPECTED_PTS}); $(( (DEADLINE_TS - NOW_TS) / 60 ))min to deadline; sleeping ${POLL_SEC}s"
    sleep "$POLL_SEC"
done
