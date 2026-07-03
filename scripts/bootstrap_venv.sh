#!/bin/bash
# Reproducible venv bootstrap for the Augur ML pipeline.
#
# Builds an IDENTICAL .venv on any machine (sadalsuud deploy, situla dev)
# from the pinned lockfile, then verifies the key imports load. This exists
# because the situla/sadalsuud migration (2026-07-03) rebuilt the venv from
# the loose `>=` ranges in requirements.txt and silently pulled bleeding-edge
# majors (river 0.25, pandas 3.0, numpy 2.5) — river 0.25 then couldn't
# unpickle the ARF model and the daily job failed for 5 days. Pinning +
# this script make "recreate the environment" a one-liner that reproduces
# the exact known-good set.
#
# Usage:
#   scripts/bootstrap_venv.sh            # runtime deps only (deploy)
#   scripts/bootstrap_venv.sh --dev      # runtime + pytest (dev / test gate)
#   VENV_DIR=/path/to/.venv scripts/bootstrap_venv.sh
#
# Reproducibility contract: installs from requirements.lock (exact pins).
# Falls back to requirements.txt (loose) only if the lock is missing, and
# LOUDLY warns — a loose install is not reproducible and is what broke us.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_DIR/.venv}"
LOCK="$REPO_DIR/requirements.lock"
RUNTIME_REQ="$REPO_DIR/requirements.txt"
DEV_REQ="$REPO_DIR/requirements-dev.txt"

WITH_DEV=0
[ "${1:-}" = "--dev" ] && WITH_DEV=1

PYTHON="${PYTHON:-python3}"
echo "==> Bootstrapping venv at $VENV_DIR using $($PYTHON --version 2>&1)"

if [ ! -d "$VENV_DIR" ]; then
    "$PYTHON" -m venv "$VENV_DIR"
fi
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

python -m pip install --quiet --upgrade pip

if [ -f "$LOCK" ]; then
    echo "==> Installing pinned runtime deps from requirements.lock"
    pip install --quiet -r "$LOCK"
else
    echo "!!  WARNING: requirements.lock not found — falling back to the loose"
    echo "!!  ranges in requirements.txt. This install is NOT reproducible."
    echo "!!  Regenerate the lock:  pip freeze > requirements.lock"
    pip install --quiet -r "$RUNTIME_REQ"
fi

if [ "$WITH_DEV" = "1" ] && [ -f "$DEV_REQ" ]; then
    echo "==> Installing dev deps from requirements-dev.txt"
    pip install --quiet -r "$DEV_REQ"
fi

echo "==> Verifying key imports"
python - <<'PY'
import importlib
mods = ["cryptography", "river", "pandas", "numpy", "sklearn", "pyarrow", "lightgbm"]
for m in mods:
    mod = importlib.import_module(m)
    print(f"    {m:12s} {getattr(mod, '__version__', '?')}")
# Loadability of the committed ML artifacts is the real contract — a venv
# that imports but can't unpickle the models is the failure we are guarding
# against. The daily job / test suite exercise that; here we just confirm
# the stack is importable.
print("OK: all key imports succeeded")
PY

echo "==> Done. Activate with:  source $VENV_DIR/bin/activate"
