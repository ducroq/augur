#!/bin/bash
# Is the EDH gate consuming the CURRENT publish, or an older one?
#
# augur#34. `wait_for_edh.sh` releases when the EDH report is strictly newer
# than the last consumed one. That is monotonicity, not freshness: the unit
# fires ~2h before EDH publishes, so any multi-publish EDH day leaves one
# publish unconsumed, and every later run then releases on it within seconds.
# The pipeline runs a full day behind from then on, indefinitely, and nothing
# alarms -- `classify_t0_advance` checks the DELTA, which a uniformly-lagged
# pipeline satisfies exactly. Seeded twice in seven days in 2026-09; cleared
# both times only by accident, the second time at the cost of a vintage.
#
# The check is a comparison, not a heuristic: the timestamp in
# logs/.edh_gate_state is the report this pipeline last consumed, and the
# timestamp in EDH's newest committed report is what was available. Equal means
# current. Different means we are behind by at least one publish.
#
# Read-only. Never writes, never fixes, exits non-zero only when genuinely
# lagged so it can back a `<!-- verify: ... -->` annotation.
set -u

AUGUR_DIR="${AUGUR_DIR:-$HOME/local_dev/augur}"
DATAHUB_DIR="${DATAHUB_DIR:-$HOME/local_dev/energydatahub}"
STATE="$AUGUR_DIR/logs/.edh_gate_state"

[ -r "$STATE" ] || { echo "CANNOT VERIFY: no gate state at $STATE"; exit 0; }
[ -d "$DATAHUB_DIR" ] || { echo "CANNOT VERIFY: no EDH checkout at $DATAHUB_DIR"; exit 0; }

consumed=$(cat "$STATE" 2>/dev/null)
newest=$(git -C "$DATAHUB_DIR" show origin/main:data/data_quality_report.json 2>/dev/null \
         | python3 -c 'import json,sys; print(json.load(sys.stdin).get("timestamp",""))' 2>/dev/null)

[ -n "$consumed" ] || { echo "CANNOT VERIFY: gate state is empty"; exit 0; }
[ -n "$newest" ]   || { echo "CANNOT VERIFY: could not read EDH's newest report"; exit 0; }

if [ "$consumed" = "$newest" ]; then
    echo "gate is CURRENT — last consumed $consumed is EDH's newest"
    exit 0
fi

# Behind. Say by how much in days, because one publish behind is the augur#34
# fixed point and several behind is an ordinary outage still resolving.
days=$(python3 -c '
import sys, datetime as dt
try:
    a = dt.datetime.fromisoformat(sys.argv[1]); b = dt.datetime.fromisoformat(sys.argv[2])
except Exception:
    print("?"); raise SystemExit
print(round((b - a).total_seconds() / 86400, 1))
' "$consumed" "$newest" 2>/dev/null)

echo "gate is LAGGED by ${days}d — consumed $consumed, EDH newest $newest"
echo "  augur#34: this does not self-correct. See docs/hypothesis-log.md [2026-09-14]."
exit 1
