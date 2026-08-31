#!/bin/bash
# Augur daily model update — runs on sadalsuud via the system-level systemd
# timer at /etc/systemd/system/augur-daily.timer (16:30 UTC + wait_for_edh.sh
# ExecStartPre gate). Canonical unit files: scripts/systemd/. Cron was retired
# 2026-06-09 and the crontab deleted 2026-06-10 (augur#12).
#
# Order of operations:
#   1. Pull energyDataHub + Augur
#   2. Run ARF model update (kept as backup signal — see EXP-014 promotion)
#   3. Re-consolidate parquet from energyDataHub                — non-blocking
#   4. Run shadow update (LightGBM-Quantile, EXP-014 production model)
#   5. Run shadow evaluation (writes eval_log.jsonl)
#   6. Commit + push everything
#
# EXP-014 promotion (2026-05-29): LightGBM is now the production model
# driving the dashboard via static/data/augur_forecast_shadow.json. ARF
# (step 2) is kept running as a backup signal for one rolling-window
# cycle. The Model tab still reads ARF metrics (model-viz.js).
#
# Steps 4-5 still run with `set +e` so a shadow failure does NOT abort the
# ARF backup commit. A persistent shadow failure now degrades the dashboard
# forecast — the in-script pre-flight ALARM (SHADOW_PRE_AGE_H >36h) surfaces
# it in the next day's commit message; watching for missing daily commits on
# origin/main is the external alive signal.
#
# Alarms in the commit subject (all non-blocking):
#   pre-flight:  SHADOW_PRE_AGE_H >36h (stale shadow state), DEP_PROBE_OK=0
#                (broken venv imports)
#   post-run:    ARF forecast <24h (empty output despite rc=0), no new eval
#                row for >2 days (skipped vintages despite rc=0) — augur#14;
#                t0 not advancing exactly one calendar day (stale parquet
#                overwriting a vintage, or a jump that loses one for good)

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
# Re-enabled 2026-05-29 with EXP-014 promotion — shadow now drives the
# dashboard so silent failures degrade production. Reads `last_run_utc`
# from shadow_state.json and yells if it's >36h old. Never blocks ARF.
# SHADOW_WAS_STALE feeds the commit message below so a recovery shows up
# in the GitHub commit list, not just the log file.
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

# Pre-flight dependency probe: catch silently corrupted venv before shadow steps run.
# Why this exists: 2026-06-10 the venv's lightgbm install became an empty husk
# (only lib/ + __pycache__/, no __init__.py) between yesterday's clean cron and
# the same-day manual smoketest; root cause unexplained. The shadow step
# import-fails at runtime, which only surfaces in the log file, not the
# commit subject. This probe alarms in the commit message so the failure is
# visible on origin/main without log inspection. Doesn't block ARF.
# NOTE (2026-07-03): river is deliberately NOT probed here. It is a
# backup-only dependency (ARF); the production LightGBM shadow imports only
# lightgbm/pandas. This probe gates the shadow, so a broken `import river`
# must NOT skip the production forecast — that would be the exact
# "backup dep freezes the dashboard" class the same-day decoupling removed
# from ARF's runtime. A broken river surfaces via ARF_STATUS in the commit
# subject instead (ARF now runs non-fatal). Previously this line also had
# `import river`; a multi-model review caught the leftover coupling.
DEP_PROBE_OK=1
python3 -c "from lightgbm import LGBMRegressor; import pandas; import lightgbm" 2>/dev/null || {
    echo "ALARM: dep probe failed — lightgbm/pandas import broken in venv. Shadow steps will be skipped."
    DEP_PROBE_OK=0
}

# Pre-flight pytest smoke gate (NON-BLOCKING). The import dep-probe above
# catches an empty/husk install, but a subtly wrong environment (major
# version bump, unpicklable model) can import cleanly and still misbehave.
# A fast unit subset catches that class before it ships. Non-blocking on
# purpose: a flaky test must never freeze the dashboard — the failure
# surfaces as an ALARM in the commit subject, same as the other pre-flight
# alarms. Needs pytest (requirements-dev.txt); skipped with a WARN if absent.
SMOKE_OK=1
if python -c "import pytest" 2>/dev/null; then
    echo "Running pytest smoke gate..."
    python -m pytest -q -x --no-header -p no:cacheprovider \
        "$AUGUR_DIR/tests/test_secure_pickle.py" \
        "$AUGUR_DIR/tests/test_conformal.py" \
        "$AUGUR_DIR/tests/test_metrics.py" \
        "$AUGUR_DIR/tests/test_lightgbm_quantile.py" \
        > "$AUGUR_DIR/logs/smoke.log" 2>&1 || SMOKE_OK=0
    [ "$SMOKE_OK" = "0" ] && echo "ALARM: pytest smoke gate failed — see logs/smoke.log; env may be broken."
else
    echo "WARN: pytest not installed in venv — smoke gate skipped (run scripts/bootstrap_venv.sh --dev)."
fi

# Run ARF model update (backup signal — NON-FATAL since the 2026-05-29
# EXP-014 demotion; LightGBM-Quantile is production). A failure here must
# NOT abort the LightGBM production shadow steps or the git push — so run
# it under set +e and surface any failure as an ALARM in the commit
# subject. (Before 2026-07-03 this ran under set -e as "must succeed",
# which let a stale ARF pickle freeze the whole dashboard for 5 days after
# the situla/sadalsuud migration — see memory/gotcha-log.md.)
echo "Running ARF model update..."
set +e
python -m ml.update --data-dir $DATAHUB_DIR/data --augur-dir $AUGUR_DIR
ARF_UPDATE_RC=$?
if [ $ARF_UPDATE_RC -ne 0 ]; then
    echo "ALARM: ARF model update failed (rc=$ARF_UPDATE_RC) — backup signal down; continuing to LightGBM production steps."
fi

# --- EXP-009 shadow pipeline: non-blocking -------------------------------
# Shadow failures must not block the LightGBM production commit. Already
# under set +e from the ARF block above; kept explicit for clarity. The
# trap restores set -e regardless of how we exit it.
set +e

# Parquet consolidate runs even with shadow parked — parquet has other uses
# (ad-hoc analysis, next-bet experiments) and the cost is small.
echo "Re-consolidating training_history.parquet..."
python -m ml.data.consolidate --data-dir $DATAHUB_DIR/data
SHADOW_CONSOLIDATE_RC=$?

# LGBM shadow steps RE-ENABLED 2026-05-29 with EXP-014 promotion. The
# shadow now produces consumer_forecast fields too (via read_arf_surcharge
# in update_shadow.py), so its output drives the dashboard's price charts.
# Dep probe (above) gates this — a broken venv would import-fail the same
# way every minute, no value in running it just to fail.
if [ $SHADOW_CONSOLIDATE_RC -eq 0 ] && [ $DEP_PROBE_OK -eq 1 ]; then
    echo "Running shadow update (LightGBM-Quantile, EXP-014 production)..."
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
        echo "WARN: shadow update failed (rc=$SHADOW_UPDATE_RC) — dashboard forecast will be stale"
    fi
elif [ $DEP_PROBE_OK -eq 0 ]; then
    echo "WARN: skipping shadow steps because dep probe failed (see ALARM above)"
else
    echo "WARN: parquet re-consolidation failed (rc=$SHADOW_CONSOLIDATE_RC) — skipping shadow"
fi

set -e
# --- end shadow block ----------------------------------------------------

# Post-run output-quality guards: rc=0 does not mean good output.
# Why these exist: during the EDH v2.2 schema break (2026-06-08..10) three
# daily commits said "ARF OK | shadow rc=0/eval rc=0" while ARF published
# EMPTY forecasts and evaluate_shadow logged no rows — eval vintages
# 2026-06-08 and 2026-06-10 are permanently unevaluable. See augur#14
# (comment 2026-06-12) and memory/gotcha-log.md. Both checks are
# non-blocking and surface in the commit subject like the pre-flight alarms.
ARF_FC_HOURS=$(python3 -c "
import json
try:
    with open('$AUGUR_DIR/static/data/augur_forecast.json') as f:
        print(len(json.load(f).get('forecast', {})))
except Exception:
    print(-1)
" 2>/dev/null || echo -1)
ARF_EMPTY_MARKER=""
if [ "${ARF_FC_HOURS:--1}" -lt 24 ]; then
    echo "ALARM: ARF forecast spans only ${ARF_FC_HOURS}h (<24h) — empty/broken output despite rc=0."
    ARF_EMPTY_MARKER=" [ALARM: ARF forecast ${ARF_FC_HOURS}h]"
else
    # 72h nominal; 48h expected while the EDH v2.2 window truncation is open (augur#26)
    echo "ARF forecast spans ${ARF_FC_HOURS}h."
fi

EVAL_LAG_DAYS=$(python3 -c "
import json
from datetime import date
try:
    dates = []
    with open('$AUGUR_DIR/ml/shadow/eval_log.jsonl') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line).get('date')
            except Exception:
                continue
            if d:
                dates.append(d)
    print((date.today() - date.fromisoformat(max(dates))).days)
except Exception:
    print(999)
" 2>/dev/null || echo 999)
EVAL_STALE_MARKER=""
if [ "${EVAL_LAG_DAYS:-999}" -gt 2 ]; then
    echo "ALARM: no new eval row for ${EVAL_LAG_DAYS} day(s) — eval vintages are being skipped despite eval rc=0."
    EVAL_STALE_MARKER=" [ALARM: eval stale ${EVAL_LAG_DAYS}d]"
fi

# t0-advance guard (2026-08-28). update_shadow.py records how many calendar
# days t0 moved since the previous run; anything but 1 means the vintage
# stream broke. This is the UPSTREAM signal for the eval-stale alarm above:
# on 2026-08-23/27 a late EDH publish left the parquet stale, t0 repeated,
# the prediction set was overwritten, and the only symptom three days later
# pointed at evaluate_shadow.py rather than at the stale data. Only read it
# when the shadow update actually succeeded — otherwise shadow_state.json
# still holds the previous run's values and would re-fire a stale alarm.
T0_MARKER=""
if [ "${SHADOW_UPDATE_RC:-1}" -eq 0 ]; then
    T0_ADVANCE_INFO=$(python3 -c "
import json
try:
    with open('$AUGUR_DIR/ml/models/shadow/shadow_state.json') as f:
        st = json.load(f)
    adv = st.get('t0_advance_days')
    held = st.get('t0_held_back_hours') or 0
    feeds = ','.join(st.get('t0_short_feeds') or []) or '-'
    print('none' if adv is None else adv, (st.get('last_t0') or '')[:10], held, feeds)
except Exception:
    print('none', '', 0, '-')
" 2>/dev/null || echo "none  0 -")
    T0_ADVANCE=$(echo "$T0_ADVANCE_INFO" | cut -d' ' -f1)
    T0_DATE=$(echo "$T0_ADVANCE_INFO" | cut -d' ' -f2)
    T0_HELD_BACK=$(echo "$T0_ADVANCE_INFO" | cut -d' ' -f3)
    T0_SHORT_FEEDS=$(echo "$T0_ADVANCE_INFO" | cut -d' ' -f4)
    case "$T0_ADVANCE" in
        none|1) : ;;  # first run after a state reset, or a healthy one-day step
        0)
            echo "ALARM: t0 did not advance (still ${T0_DATE}) — stale parquet; this run overwrote yesterday's vintage and produced nothing evaluable."
            T0_MARKER=" [ALARM: t0 stale ${T0_DATE}]"
            ;;
        -*)
            echo "ALARM: t0 moved backwards to ${T0_DATE} — parquet lost realised prices; check consolidate.py."
            T0_MARKER=" [ALARM: t0 backwards ${T0_DATE}]"
            ;;
        *)
            echo "ALARM: t0 jumped ${T0_ADVANCE}d to ${T0_DATE} — $((T0_ADVANCE - 1)) vintage(s) skipped and permanently unevaluable."
            T0_MARKER=" [ALARM: t0 jumped ${T0_ADVANCE}d]"
            ;;
    esac

    # Hold-back is a SEPARATE condition from advance, and can coexist with a
    # healthy +1 step. t0 is held back when a feature column's coverage ends
    # before the price column's (2026-08-31: EDH's load feed halved 48h->24h
    # while price stayed 48h). The run then succeeds with `shadow rc=0` while
    # producing a SHORTER, degraded forecast anchored in the past. Without a
    # marker that is invisible — the same soft-failure-with-no-reader shape
    # that hid the 2026-08-30 outage for a day, repeated inside its own fix.
    # Self-clears the moment upstream restores the horizon.
    if [ -n "$T0_HELD_BACK" ] && [ "$T0_HELD_BACK" != "0" ] && [ "$T0_HELD_BACK" != "0.0" ]; then
        echo "ALARM: t0 held back ${T0_HELD_BACK}h — short upstream feeds: ${T0_SHORT_FEEDS}. Forecast horizon is reduced by that much."
        T0_MARKER="${T0_MARKER} [ALARM: t0 held back ${T0_HELD_BACK}h — ${T0_SHORT_FEEDS} short]"
    fi
fi

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
DEP_MARKER=""
[ "$DEP_PROBE_OK" = "0" ] && DEP_MARKER=" [ALARM: dep probe failed — shadow skipped]"
# ARF is now a non-fatal backup signal — report its real rc, don't hardcode "OK".
ARF_STATUS="ARF OK"
[ "${ARF_UPDATE_RC:-0}" -ne 0 ] && ARF_STATUS="ARF FAIL rc=${ARF_UPDATE_RC}"
SMOKE_MARKER=""
[ "${SMOKE_OK:-1}" = "0" ] && SMOKE_MARKER=" [ALARM: smoke tests failed]"

git diff --cached --quiet && echo "No changes to commit" || {
    git commit -m "Daily update $(date -u '+%Y-%m-%d') — ${ARF_STATUS} | ${SHADOW_STATUS}${STALE_MARKER}${DEP_MARKER}${SMOKE_MARKER}${ARF_EMPTY_MARKER}${EVAL_STALE_MARKER}${T0_MARKER}"
    git push
}

echo "Done!"
