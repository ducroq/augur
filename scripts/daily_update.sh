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

AUGUR_DIR=$HOME/local_dev/augur
DATAHUB_DIR=$HOME/local_dev/energydatahub

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
export $(cat $AUGUR_DIR/.env | xargs)

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
    python -m ml.shadow.update_shadow --augur-dir $AUGUR_DIR
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

git diff --cached --quiet && echo "No changes to commit" || {
    git commit -m "Daily update $(date -u '+%Y-%m-%d') — ARF + LGBM-shadow"
    git push
}

echo "Done!"
