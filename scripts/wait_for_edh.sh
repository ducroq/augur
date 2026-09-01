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
#      Every catch-up is exactly half size, so content separates them without
#      any clock rule. And the two anomalies were both real incidents the hour
#      rule waved through: 08-26 is the day 2 hours of the training target came
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
# proceed and name it, and latest_feasible_t0 handles the rest.
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

median_points() {
    # $1 = dataset name. Median primary-dataset size over the last SAMPLE_N
    # publishes. Deriving the expectation instead of hardcoding 192 means a
    # resolution change upstream (15-min -> hourly) is absorbed within a few
    # days instead of making every publish read as short forever. The median
    # also shrugs off the catch-ups mixed into that history.
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
    done | sort -n | awk '{a[NR]=$1} END {if (NR) print a[int((NR+1)/2)]}'
}

git -C "$DATAHUB_DIR" fetch --quiet origin main 2>/dev/null || true

EXPECTED_PTS=$(median_points "$PRIMARY_DATASET")
EXPECTED_SECONDARY=$(median_points "$SECONDARY_DATASET")
if ! printf '%s' "${EXPECTED_PTS:-}" | grep -qE '^[0-9]+$'; then
    EXPECTED_PTS="$FALLBACK_PRIMARY_PTS"
    echo "[wait_for_edh] WARN: could not sample ${PRIMARY_DATASET} history; using fallback expectation ${EXPECTED_PTS}"
fi

echo "[wait_for_edh] Started $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "[wait_for_edh] Ready when report is newer than '${LAST_CONSUMED:-<none, bootstrapping>}' and ${PRIMARY_DATASET} >= ${EXPECTED_PTS} points (median of last ${SAMPLE_N})"
echo "[wait_for_edh] Deadline $(date -u -d "@$DEADLINE_TS" '+%Y-%m-%d %H:%M UTC'); proceeding anyway at that point"

record_and_go() {
    # $1 = upstream timestamp, $2 = marker to ride the commit subject
    printf '%s\n' "$1" > "$STATE" 2>/dev/null || true
    printf '%s' "$2" > "$VERDICT" 2>/dev/null || true
    exit 0
}

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

    if [ "$IS_NEW" = "1" ] && [ "$IS_FULL" = "1" ]; then
        MARKER=""
        if printf '%s' "$SECONDARY_PTS" | grep -qE '^[0-9]+$' \
           && printf '%s' "${EXPECTED_SECONDARY:-}" | grep -qE '^[0-9]+$' \
           && [ "$SECONDARY_PTS" -lt "$EXPECTED_SECONDARY" ]; then
            echo "[wait_for_edh] ALARM: ${SECONDARY_DATASET} short at publish (${SECONDARY_PTS} < ${EXPECTED_SECONDARY}) — t0 will be held back; proceeding anyway."
            MARKER=" [ALARM: EDH ${SECONDARY_DATASET} short at publish ${SECONDARY_PTS}/${EXPECTED_SECONDARY}]"
        fi
        [ -z "$LAST_CONSUMED" ] && echo "[wait_for_edh] NOTE: no prior state — bootstrapping from this publish. Subsequent runs require a strictly newer one."
        echo "[wait_for_edh] READY: ${UPSTREAM_TS}, ${PRIMARY_DATASET}=${PRIMARY_PTS} (>= ${EXPECTED_PTS}), ${SECONDARY_DATASET}=${SECONDARY_PTS:-?}. Proceeding."
        record_and_go "$UPSTREAM_TS" "$MARKER"
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
