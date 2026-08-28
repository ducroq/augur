#!/bin/bash
# Block until energyDataHub publishes today's data, or hit a 4h timeout.
#
# augur#12: the daily LGBM update must NOT start before
# energydatahub/.github/workflows/collect-data.yml has committed today's
# data_quality_report.json. EDH publish time empirically ranges 16:23-20:13 UTC
# (14-day sample observed 2026-06-08). The previous fixed-time cron at
# 14:45 UTC ran 75 min to 4+ hours BEFORE EDH published, so the parquet
# always trailed 24 hours.
#
# Sentinel: data/data_quality_report.json has a top-level "timestamp" field
# (ISO 8601 UTC). We read it from `origin/main` via `git show` so we never
# pollute the local working tree before daily_update.sh's own `git pull`.
#
# The date alone is NOT enough (2026-08-28). When EDH misses a day it publishes
# a CATCH-UP commit in the early hours of the next one, carrying the previous
# day's collection. On 2026-08-24 that catch-up landed 06:28 UTC; the date-only
# test released the run instantly at 16:30, and EDH's real publish for the day
# arrived 16:32:17 — 90 seconds after Augur had already finished on stale data.
# t0 stalled, the vintage was overwritten, and the day was lost. So we also
# require the report to be published at or after MIN_PUBLISH_HOUR_UTC: the NL
# day-ahead auction clears around 12:00 CET, so anything stamped before noon
# UTC cannot contain today's prices no matter what date it carries.
#
# On timeout: exit 0 anyway. Let the run proceed with possibly-stale data;
# daily_update.sh's pre-flight ALARM (SHADOW_PRE_AGE_H >36h) will surface
# the resulting staleness in the next day's commit message. Failing here
# would skip the run entirely and leave the dashboard frozen with no
# visible signal of the failure.

set -u
DATAHUB_DIR="$HOME/local_dev/energydatahub"
MAX_WAIT_SEC=$(( 4 * 60 * 60 ))   # 4h hard cap
POLL_SEC=120                       # 2-min poll
MIN_PUBLISH_HOUR_UTC=12            # earliest a publish can hold today's auction
START_TS=$(date +%s)
TODAY_UTC=$(date -u '+%Y-%m-%d')

echo "[wait_for_edh] Started $(date -u '+%Y-%m-%d %H:%M:%S UTC'); expecting EDH data dated ${TODAY_UTC}, published >= ${MIN_PUBLISH_HOUR_UTC}:00 UTC"

while : ; do
    cd "$DATAHUB_DIR" && git fetch --quiet origin main 2>/dev/null

    UPSTREAM_TS=$(git show "origin/main:data/data_quality_report.json" 2>/dev/null \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('timestamp',''))" 2>/dev/null || true)
    UPSTREAM_DATE="${UPSTREAM_TS:0:10}"

    # Hour of the upstream publish, blank when the timestamp is unreadable.
    UPSTREAM_HOUR=$(echo "$UPSTREAM_TS" | cut -c12-13 | sed 's/^0//')

    if [ "$UPSTREAM_DATE" = "$TODAY_UTC" ] \
       && [ -n "$UPSTREAM_HOUR" ] \
       && [ "$UPSTREAM_HOUR" -ge "$MIN_PUBLISH_HOUR_UTC" ] 2>/dev/null; then
        echo "[wait_for_edh] EDH ready: data_quality_report.timestamp=${UPSTREAM_TS}. Proceeding."
        exit 0
    fi

    if [ "$UPSTREAM_DATE" = "$TODAY_UTC" ]; then
        # Right date, too early to hold today's auction — an overnight catch-up
        # publish for the day EDH missed. Keep waiting for the real one.
        echo "[wait_for_edh] EDH upstream dated today but published ${UPSTREAM_TS} (before ${MIN_PUBLISH_HOUR_UTC}:00 UTC) — looks like a catch-up for a missed day; still waiting."
    fi

    NOW_TS=$(date +%s)
    ELAPSED=$(( NOW_TS - START_TS ))
    if [ $ELAPSED -ge $MAX_WAIT_SEC ]; then
        echo "[wait_for_edh] TIMEOUT after ${ELAPSED}s waiting for EDH ${TODAY_UTC} (>= ${MIN_PUBLISH_HOUR_UTC}:00 UTC). Latest upstream=${UPSTREAM_TS:-<unreadable>}. Proceeding with possibly stale data — the t0-advance and pre-flight ALARMs will surface it in the commit subject."
        exit 0
    fi
    echo "[wait_for_edh] EDH upstream still ${UPSTREAM_TS:-<empty>} (want ${TODAY_UTC} >= ${MIN_PUBLISH_HOUR_UTC}:00 UTC); elapsed ${ELAPSED}s; sleeping ${POLL_SEC}s"
    sleep "$POLL_SEC"
done
