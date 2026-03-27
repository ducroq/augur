#!/bin/bash
# Augur daily model update — runs via cron on sadalsuud
# Cron: 45 16 * * * /home/jeroen/local_dev/augur/scripts/daily_update.sh >> /home/jeroen/local_dev/augur/logs/daily_update.log 2>&1

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

# Run model update
echo "Running model update..."
python -m ml.update --data-dir $DATAHUB_DIR/data --augur-dir $AUGUR_DIR

# Commit and push
echo "Committing and pushing..."
cd $AUGUR_DIR
git add ml/models/river_model.pkl ml/models/state.json static/data/augur_forecast.json
git diff --cached --quiet && echo "No changes to commit" || {
    git commit -m "Daily model update $(date -u '+%Y-%m-%d')"
    git push
}

echo "Done!"
