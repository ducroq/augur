#!/bin/bash
# How many characters does a session have to read to get oriented?
#
# The engineer's rule of 2026-11-15: prune, thin, mechanize and retire until the
# live docs total under ~100k chars. This prints each live doc's size and the
# total, so `memory/MEMORY.md` stops carrying hand-copied numbers.
#
# Read-only. Exits 1 when the total is over the ceiling or a listed file is
# missing (a renamed doc must be renamed here too), and 2 when it could not
# measure, so it can back a `<!-- verify: ... -->` annotation. A total equal to
# the ceiling passes. Ceiling: READ_SURFACE_CEILING (default 100000).
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CEILING="${READ_SURFACE_CEILING:-100000}"
# 1 to 9 digits, no leading zero: bash would read 0100 as octal and overflow past 2^63.
case "$CEILING" in
    ''|0*|*[!0-9]*|??????????*) echo "READ_SURFACE_CEILING must be a whole number from 1 to 999999999, got '$CEILING'" >&2; exit 2 ;;
esac

# Live docs: what a session is told to read. Auto-loaded ones first.
FILES=(
    CLAUDE.md
    memory/MEMORY.md
    docs/hypothesis-log.md
    docs/experiment-backlog.md
    docs/RUNBOOK.md
    memory/gotcha-log.md
    docs/experiment-results.md
    memory/model-class-findings.md
)

total=0; missing=0
for f in "${FILES[@]}"; do
    if [ -f "$REPO/$f" ]; then
        # Characters, whatever the caller's locale. Without a C.UTF-8 locale wc
        # counts bytes, which over-counts and so errs toward failing.
        n=$(LC_ALL=C.UTF-8 wc -m < "$REPO/$f" | tr -d '[:space:]') || n=
        case "$n" in ''|*[!0-9]*) echo "FAIL: could not count $f (wc gave '$n')" >&2; exit 2 ;; esac
        total=$((total + n))
        printf '%8d  %s\n' "$n" "$f"
    else
        printf '%8s  %s\n' MISSING "$f"
        missing=$((missing + 1))
    fi
done
printf '%8d  total (ceiling %d)\n' "$total" "$CEILING"

if [ "$missing" -gt 0 ]; then
    echo "FAIL: $missing listed file(s) missing; update FILES in scripts/read_surface.sh"
    exit 1
fi
if [ "$total" -gt "$CEILING" ]; then
    echo "OVER by $((total - CEILING)) chars: prune, thin, mechanize or retire"
    exit 1
fi
echo "under the ceiling by $((CEILING - total)) chars"
