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
# On timeout: exit 0 anyway. Let the run proceed with possibly-stale data;
# daily_update.sh's pre-flight ALARM (SHADOW_PRE_AGE_H >36h) will surface
# the resulting staleness in the next day's commit message. Failing here
# would skip the run entirely and leave the dashboard frozen with no
# visible signal of the failure.

set -u
DATAHUB_DIR="$HOME/local_dev/energydatahub"
MAX_WAIT_SEC=$(( 4 * 60 * 60 ))   # 4h hard cap
POLL_SEC=120                       # 2-min poll
START_TS=$(date +%s)
TODAY_UTC=$(date -u '+%Y-%m-%d')

echo "[wait_for_edh] Started $(date -u '+%Y-%m-%d %H:%M:%S UTC'); expecting EDH data dated ${TODAY_UTC}"

while : ; do
    cd "$DATAHUB_DIR" && git fetch --quiet origin main 2>/dev/null

    UPSTREAM_TS=$(git show "origin/main:data/data_quality_report.json" 2>/dev/null \
        | python3 -c "import sys,json;print(json.load(sys.stdin).get('timestamp',''))" 2>/dev/null || true)
    UPSTREAM_DATE="${UPSTREAM_TS:0:10}"

    if [ "$UPSTREAM_DATE" = "$TODAY_UTC" ]; then
        echo "[wait_for_edh] EDH ready: data_quality_report.timestamp=${UPSTREAM_TS}. Proceeding."
        exit 0
    fi

    NOW_TS=$(date +%s)
    ELAPSED=$(( NOW_TS - START_TS ))
    if [ $ELAPSED -ge $MAX_WAIT_SEC ]; then
        echo "[wait_for_edh] TIMEOUT after ${ELAPSED}s waiting for EDH ${TODAY_UTC}. Latest upstream=${UPSTREAM_TS:-<unreadable>}. Proceeding with possibly stale data — next-day pre-flight ALARM will surface it."
        exit 0
    fi
    echo "[wait_for_edh] EDH upstream still ${UPSTREAM_DATE:-<empty>} (want ${TODAY_UTC}); elapsed ${ELAPSED}s; sleeping ${POLL_SEC}s"
    sleep "$POLL_SEC"
done
