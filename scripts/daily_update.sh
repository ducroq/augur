#!/bin/bash
# Augur daily model update — runs via cron on sadalsuud
# Cron: 45 16 * * * /home/jeroen/local_dev/augur/scripts/daily_update.sh >> /home/jeroen/local_dev/augur/logs/daily_update.log 2>&1
#
# Order of operations:
#   1. Pull energyDataHub + Augur
#   2. Run ARF model update (production — must succeed)
#   3. Re-consolidate parquet from energyDataHub
#   4. Run shadow update (LightGBM-Quantile, EXP-009)        — non-blocking
#   5. Run shadow evaluation (writes eval_log.jsonl)         — non-blocking
#   6. Commit + push everything
#
# Steps 4-5 run with `set +e` so a shadow failure does NOT block the ARF
# commit. The shadow forecast file is not consumed by the dashboard during
# shadow phase (plan §5), so a stale shadow file is acceptable.

set -e

# Defense-in-depth: any files this script creates inherit mode 640 (rw for owner,
# r for group, none for others). The cron log itself is created by cron's
# redirection (not this script), so we also chmod it explicitly below.
umask 027

AUGUR_DIR=$HOME/local_dev/augur
DATAHUB_DIR=$HOME/local_dev/energydatahub

# Self-correct the cron log file mode every run, in case cron's umask
# created it world-readable. Silent + non-blocking — this should never fail.
chmod 640 "$AUGUR_DIR/logs/daily_update.log" 2>/dev/null || true

echo "========================================"
echo "Augur daily update: $(date -u '+%Y-%m-%d %H:%M UTC')"
echo "========================================"

# Pull latest data
echo "Pulling energyDataHub..."
cd $DATAHUB_DIR && git pull --quiet

# Pull latest code
echo "Pulling Augur..."
cd $AUGUR_DIR && git pull --quiet

# Load environment
source $AUGUR_DIR/.venv/bin/activate
# Conventional safe pattern — handles quoted values with spaces, unlike
# `export $(cat .env | xargs)` which word-splits on whitespace. Guarded
# so a missing .env doesn't abort under `set -e` and kill the ARF cron
# (deployment-troubleshooter BLOCKER from EXP-009 M3 round-2 review).
if [ -f "$AUGUR_DIR/.env" ]; then
    set -a
    source $AUGUR_DIR/.env
    set +a
else
    echo "WARN: $AUGUR_DIR/.env not found — relying on cron-supplied env vars."
fi

# Pre-flight heartbeat: surface yesterday's silent shadow failure (if any).
# Reads `last_run_utc` from shadow_state.json and yells if it's >36h old.
# Never blocks ARF. SHADOW_WAS_STALE feeds the commit message below so a
# recovery shows up in the GitHub commit list, not just the log file.
# Why this exists: see memory/gotcha-log.md "Shadow cron failed silently
# for 7 nights" (2026-05-08).
SHADOW_WAS_STALE=0
SHADOW_PRE_AGE_H=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    with open('$AUGUR_DIR/ml/models/shadow/shadow_state.json') as f:
        last = json.load(f).get('last_run_utc')
    ts = datetime.fromisoformat(last)
    print(int((datetime.now(timezone.utc) - ts).total_seconds() / 3600))
except Exception:
    # File missing or last_run_utc malformed/null — treat as 'should-have-state-but-doesn't',
    # i.e. always alarm. Cost: one false alarm on the first cron after a fresh M3-style
    # deployment (before shadow_state.json exists). Gain: silent state-file deletion
    # or null'd timestamp can't go undetected.
    print(999)
" 2>/dev/null || echo 999)
if [ "${SHADOW_PRE_AGE_H:-0}" -gt 36 ]; then
    echo "ALARM: shadow_state.json is ${SHADOW_PRE_AGE_H}h stale at start of run (>36h). Likely silent failure on prior run(s)."
    SHADOW_WAS_STALE=1
fi

# Run ARF model update (production — must succeed)
echo "Running ARF model update..."
python -m ml.update --data-dir $DATAHUB_DIR/data --augur-dir $AUGUR_DIR

# --- EXP-009 shadow pipeline: non-blocking -------------------------------
# Shadow failures must not block the ARF commit. set +e for this block;
# the trap restores set -e regardless of how we exit it.
set +e

echo "Re-consolidating training_history.parquet..."
python -m ml.data.consolidate --data-dir $DATAHUB_DIR/data
SHADOW_CONSOLIDATE_RC=$?

if [ $SHADOW_CONSOLIDATE_RC -eq 0 ]; then
    echo "Running shadow update (LightGBM-Quantile)..."
    # update_shadow.py derives all paths from _REPO_ROOT; no flags needed.
    # NB: evaluate_shadow.py below still takes explicit --shadow-dir / --arf-forecasts-dir / --eval-log.
    # See augur follow-up: harmonize the two CLIs.
    python -m ml.shadow.update_shadow
    SHADOW_UPDATE_RC=$?

    if [ $SHADOW_UPDATE_RC -eq 0 ]; then
        echo "Running shadow evaluation..."
        python -m ml.shadow.evaluate_shadow --shadow-dir $AUGUR_DIR/ml/models/shadow \
            --arf-forecasts-dir $AUGUR_DIR/ml/forecasts \
            --eval-log $AUGUR_DIR/ml/shadow/eval_log.jsonl
        SHADOW_EVAL_RC=$?
        if [ $SHADOW_EVAL_RC -ne 0 ]; then
            echo "WARN: shadow evaluation failed (rc=$SHADOW_EVAL_RC) — continuing"
        fi
    else
        echo "WARN: shadow update failed (rc=$SHADOW_UPDATE_RC) — skipping eval"
    fi
else
    echo "WARN: parquet re-consolidation failed (rc=$SHADOW_CONSOLIDATE_RC) — skipping shadow"
fi

set -e
# --- end shadow block ----------------------------------------------------

# Commit and push
echo "Committing and pushing..."
cd $AUGUR_DIR

# ARF artifacts (always)
git add ml/models/river_model.pkl ml/models/state.json static/data/augur_forecast.json

# Shadow artifacts (best-effort: only add if they exist)
[ -f ml/models/shadow/shadow_state.json ] && git add ml/models/shadow/shadow_state.json
[ -f static/data/augur_forecast_shadow.json ] && git add static/data/augur_forecast_shadow.json
[ -f ml/shadow/eval_log.jsonl ] && git add ml/shadow/eval_log.jsonl

# Compose status string from per-step return codes — replaces the
# hardcoded "ARF + LGBM-shadow" message that hid the May 1-7 silent
# failures. "skip" indicates the step was gated off by an earlier failure.
SHADOW_STATUS="shadow rc=${SHADOW_UPDATE_RC:-skip}/eval rc=${SHADOW_EVAL_RC:-skip}"
STALE_MARKER=""
[ "$SHADOW_WAS_STALE" = "1" ] && STALE_MARKER=" [recovered after stale state ${SHADOW_PRE_AGE_H}h]"

git diff --cached --quiet && echo "No changes to commit" || {
    git commit -m "Daily update $(date -u '+%Y-%m-%d') — ARF OK | ${SHADOW_STATUS}${STALE_MARKER}"
    git push
}

# Healthchecks.io heartbeat — ping ONLY on shadow success, so the HC
# endpoint's natural absence-detection alerts on shadow failure (not just
# script execution). Set HEALTHCHECKS_SHADOW_URL in .env to enable;
# unset = silently skip (no-op).
if [ -n "${HEALTHCHECKS_SHADOW_URL:-}" ] && [ "${SHADOW_UPDATE_RC:-1}" -eq 0 ]; then
    curl -fsS --retry 3 --max-time 10 "$HEALTHCHECKS_SHADOW_URL" > /dev/null \
        && echo "Healthchecks ping sent." \
        || echo "WARN: Healthchecks ping failed (non-fatal)."
fi

echo "Done!"
