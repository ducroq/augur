#!/bin/bash
# Augur daily model update — runs via cron on sadalsuud
# Cron: 45 16 * * * /home/jeroen/local_dev/augur/scripts/daily_update.sh >> /home/jeroen/local_dev/augur/logs/daily_update.log 2>&1
#
# Order of operations:
#   1. Pull energyDataHub + Augur
#   2. Run ARF model update (production — must succeed)
#   3. Re-consolidate parquet from energyDataHub                — non-blocking
#   4. (PARKED 2026-05-29) Shadow update (LightGBM-Quantile)
#   5. (PARKED 2026-05-29) Shadow evaluation
#   6. Commit + push everything
#
# Shadow steps 4-5 parked per M4 Path B outcome (docs/lightgbm-shadow-postmortem.md).
# Re-enable by uncommenting the block below and the pre-flight stale check.
# Step 3 (parquet consolidate) still runs — parquet has uses beyond the shadow.
#
# Step 3 runs with `set +e` so a consolidate failure does NOT block the ARF
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

# Pre-flight stale-state check DISABLED 2026-05-29 per M4 outcome (Path B park).
# When the shadow block is commented out below, shadow_state.json's last_run_utc
# stops updating and this check would alarm every night. Re-enable alongside
# the shadow block. Why it exists: see memory/gotcha-log.md "Shadow cron failed
# silently for 7 nights" (2026-05-08).
SHADOW_WAS_STALE=0
SHADOW_PRE_AGE_H=parked
# SHADOW_PRE_AGE_H=$(python3 -c "
# import json, sys
# from datetime import datetime, timezone
# try:
#     with open('$AUGUR_DIR/ml/models/shadow/shadow_state.json') as f:
#         last = json.load(f).get('last_run_utc')
#     ts = datetime.fromisoformat(last)
#     print(int((datetime.now(timezone.utc) - ts).total_seconds() / 3600))
# except Exception:
#     print(999)
# " 2>/dev/null || echo 999)
# if [ "${SHADOW_PRE_AGE_H:-0}" -gt 36 ]; then
#     echo "ALARM: shadow_state.json is ${SHADOW_PRE_AGE_H}h stale at start of run (>36h). Likely silent failure on prior run(s)."
#     SHADOW_WAS_STALE=1
# fi

# Run ARF model update (production — must succeed)
echo "Running ARF model update..."
python -m ml.update --data-dir $DATAHUB_DIR/data --augur-dir $AUGUR_DIR

# --- EXP-009 shadow pipeline: non-blocking -------------------------------
# Shadow failures must not block the ARF commit. set +e for this block;
# the trap restores set -e regardless of how we exit it.
set +e

# Parquet consolidate runs even with shadow parked — parquet has other uses
# (ad-hoc analysis, next-bet experiments) and the cost is small.
echo "Re-consolidating training_history.parquet..."
python -m ml.data.consolidate --data-dir $DATAHUB_DIR/data
SHADOW_CONSOLIDATE_RC=$?

# LGBM shadow steps DISABLED 2026-05-29 per M4 outcome (Path B park).
# See docs/lightgbm-shadow-postmortem.md for diagnosis and next-bet plan.
# Code stays in tree; re-enable by uncommenting the block below.
SHADOW_UPDATE_RC=parked
SHADOW_EVAL_RC=parked
# if [ $SHADOW_CONSOLIDATE_RC -eq 0 ]; then
#     echo "Running shadow update (LightGBM-Quantile)..."
#     python -m ml.shadow.update_shadow
#     SHADOW_UPDATE_RC=$?
#
#     if [ $SHADOW_UPDATE_RC -eq 0 ]; then
#         echo "Running shadow evaluation..."
#         python -m ml.shadow.evaluate_shadow --shadow-dir $AUGUR_DIR/ml/models/shadow \
#             --arf-forecasts-dir $AUGUR_DIR/ml/forecasts \
#             --eval-log $AUGUR_DIR/ml/shadow/eval_log.jsonl
#         SHADOW_EVAL_RC=$?
#         if [ $SHADOW_EVAL_RC -ne 0 ]; then
#             echo "WARN: shadow evaluation failed (rc=$SHADOW_EVAL_RC) — continuing"
#         fi
#     else
#         echo "WARN: shadow update failed (rc=$SHADOW_UPDATE_RC) — skipping eval"
#     fi
# else
#     echo "WARN: parquet re-consolidation failed (rc=$SHADOW_CONSOLIDATE_RC) — skipping shadow"
# fi

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
# String equality (not -eq) because SHADOW_UPDATE_RC may be a sentinel like
# "parked" when the shadow block is disabled (post-M4, 2026-05-29).
if [ -n "${HEALTHCHECKS_SHADOW_URL:-}" ] && [ "${SHADOW_UPDATE_RC:-1}" = "0" ]; then
    curl -fsS --retry 3 --max-time 10 "$HEALTHCHECKS_SHADOW_URL" > /dev/null \
        && echo "Healthchecks ping sent." \
        || echo "WARN: Healthchecks ping failed (non-fatal)."
fi

echo "Done!"
