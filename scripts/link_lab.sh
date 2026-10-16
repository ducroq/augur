#!/usr/bin/env bash
# Recreate the links from this checkout into the lab tree, where gitignored
# experiment data lives (prediction dumps, FM contexts, input snapshots).
#
# Why: those files used to sit in the working tree, where `git clean -xfd`
# deletes them and a fresh worktree never has them. They now live under
# $AUGUR_LAB (default /home/jeroen/lab/augur, inside the restic backup), and
# the repo keeps only links, so every script keeps reading and writing its
# usual path (e.g. ml/shadow/exp021_foundation_aligned/contexts.parquet).
#
#   <repo>/lab                      -> $AUGUR_LAB              (absolute)
#   <repo>/ml/shadow/<x>/<item>     -> ../../../lab/shadow/<x>/<item>
#   <repo>/ml/shadow/<file>         -> ../../lab/shadow/<file>
#   <repo>/ml/data/<file>           -> ../../lab/data/<file>
#
# Idempotent: existing correct links are left alone; a real file or dir in the
# way is reported and skipped, never overwritten. Run after a clean or in a new
# worktree:  scripts/link_lab.sh
#
# A NEW experiment's output still lands as real files in the tree. To adopt it:
# move the gitignored files to the same relative path under $AUGUR_LAB/shadow/
# and rerun this script.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LAB="${AUGUR_LAB:-/home/jeroen/lab/augur}"

[ -d "$LAB" ] || { echo "lab root $LAB does not exist" >&2; exit 1; }

made=0; skipped=0

link() {  # link <path in repo> <relative target>
    local at="$1" to="$2"
    if [ -L "$at" ]; then
        [ "$(readlink "$at")" = "$to" ] && return 0
        echo "SKIP $at: is a link to $(readlink "$at"), expected $to" >&2
        skipped=$((skipped + 1)); return 0
    fi
    if [ -e "$at" ]; then
        echo "SKIP $at: a real file/dir is in the way (move it into the lab first)" >&2
        skipped=$((skipped + 1)); return 0
    fi
    mkdir -p "$(dirname "$at")"
    ln -s "$to" "$at"
    made=$((made + 1))
}

link "$REPO/lab" "$LAB"

if [ -d "$LAB/shadow" ]; then
    for e in "$LAB"/shadow/*; do
        [ -e "$e" ] || continue
        x="$(basename "$e")"
        if [ -f "$e" ]; then
            link "$REPO/ml/shadow/$x" "../../lab/shadow/$x"
        else
            # The repo dir holds the committed record (summary.json); link items into it.
            for item in "$e"/*; do
                [ -e "$item" ] || continue
                i="$(basename "$item")"
                link "$REPO/ml/shadow/$x/$i" "../../../lab/shadow/$x/$i"
            done
        fi
    done
fi

if [ -d "$LAB/data" ]; then
    for f in "$LAB"/data/*; do
        [ -e "$f" ] || continue
        link "$REPO/ml/data/$(basename "$f")" "../../lab/data/$(basename "$f")"
    done
fi

echo "link_lab: $made link(s) created, $skipped skipped (lab: $LAB)"
[ "$skipped" -eq 0 ]
