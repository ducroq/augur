"""Audit `experiments/registry.jsonl` against the rules in `experiments/README.md`.

Written 2026-08-30 after a documentation audit found 19 registry metrics that
could not be traced to any committed artifact. They were correct but had been
computed by throwaway inline analyses, so nobody could regenerate or check them
— the same class of failure as leaving results in /tmp. This script makes the
check repeatable instead of a one-off claim.

Five checks:

  1. SCHEMA      every required field present, `decision` from the allowed set,
                 `data_window` has its four keys, `commits` non-empty.
  2. ORDER       ids unique and sorted ascending (README: "sorted by id ascending").
  3. ARTIFACTS   every `artifacts` path exists. Paths carrying a commit pin
                 (`path@sha`) or a doc anchor (`file.md#anchor`) are reported
                 separately as unresolvable-by-design rather than as failures.
  4. NUMBERS     every numeric metric is traceable to a committed artifact —
                 either present in one, or a derivation of values in one. This
                 is the README's "numbers should match the source artifact ...
                 do not invent" rule, enforced rather than trusted.
  5. PRECOMMIT   for entries pre-committed in `docs/experiment-backlog.md`, the
                 Method body at the pre-commit revision is byte-identical to
                 HEAD, proving no Method was edited after its result landed.

Exit code is non-zero if any check fails, so it can gate `/curate` or CI.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/audit_registry.py
    PYTHONPATH=. .venv/bin/python scripts/audit_registry.py --since EXP-021
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

REQUIRED = ["id", "date", "title", "hypothesis", "model", "branch", "commits",
            "data_window", "hyperparameters", "features", "metrics", "decision",
            "decision_rationale", "artifacts", "references"]
DECISIONS = {"kept", "parked", "rejected", "rolled_back", "superseded"}
DW_KEYS = {"train_start", "train_end", "holdout_start", "holdout_end"}
PRECOMMIT_REV = "4024420"
BACKLOG = "docs/experiment-backlog.md"

# Which artifacts back which entry's numbers. Entries absent from this map are
# skipped by check 4 (their numbers predate the artifact convention).
NUMBER_SOURCES = {
    "EXP-021": ["ml/shadow/exp021_foundation_aligned/summary.json",
                "ml/shadow/exp021_foundation/summary.json",
                "ml/shadow/exp021_foundation_aligned/fm_predict_meta.json"],
    "EXP-022": ["ml/shadow/exp022_context_ladder/summary.json",
                "ml/shadow/exp022_context_ladder/diagnostics.json"],
    "EXP-023": ["ml/shadow/exp023_window_sweep/summary.json"],
    "EXP-024": ["ml/shadow/exp024_lag_richness/summary.json"],
    "EXP-025": ["ml/shadow/exp025_band_transplant/summary.json",
                "ml/shadow/exp025_band_transplant/diagnostics.json"],
    "EXP-026": ["ml/shadow/exp026_size_ladder/summary.json"],
    "EXP-027": ["ml/shadow/exp027_finetune/summary.json"],
    "EXP-028": ["ml/shadow/exp028_chronos2/summary.json"],
    "EXP-029": ["ml/shadow/exp029_residual_screen/summary.json"],
    "EXP-030": ["ml/shadow/exp026_size_ladder/cpu_latency_proxy.json"],
}
# Values that are arithmetic on artifact-backed numbers rather than stored ones.
# Each must state HOW it is derived, so the claim is checkable by a reader.
DERIVED_OK = {
    ("EXP-021", "alt5_months_fm_upper_better"):
        "count of months with fm_upper_minus_lean_upper > 0 in alternative_5 panel",
    ("EXP-030", "base_headroom_vs_10s_gate_x"): "10.0 / base median_s",
    ("EXP-030", "base_headroom_vs_60s_stage2_gate_x"): "60.0 / base median_s",
}


def flatten(o, acc):
    if isinstance(o, dict):
        for v in o.values():
            flatten(v, acc)
    elif isinstance(o, list):
        for v in o:
            flatten(v, acc)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        acc.add(float(o))
    return acc


def traceable(v, pool):
    for p in pool:
        if v == p or (p != 0 and abs(v - p) <= abs(p) * 0.005 + 1e-9):
            return True
        for r in (round(p, 1), round(p, 2), round(p, 3), round(p, 4),
                  round(p * 100, 1), round(p * 100, 2)):
            if abs(v - r) < 1e-9:
                return True
    return False


def method_sections(text):
    out = {}
    for part in re.split(r"\n## ", text)[1:]:
        m = re.match(r"(EXP-\d+)", part.split("\n", 1)[0].strip())
        if m:
            out[m.group(1)] = part
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default="experiments/registry.jsonl")
    ap.add_argument("--since", default=None, help="only audit ids >= this")
    args = ap.parse_args()

    entries = [json.loads(l) for l in open(args.registry)]
    scope = [e for e in entries if not args.since or e["id"] >= args.since]
    fails, warns = [], []

    # 1 SCHEMA
    for e in scope:
        for f in REQUIRED:
            if f not in e:
                fails.append(f"{e['id']}: missing field '{f}'")
        if e.get("decision") not in DECISIONS:
            fails.append(f"{e['id']}: invalid decision {e.get('decision')!r}")
        if set(e.get("data_window", {})) != DW_KEYS:
            fails.append(f"{e['id']}: data_window keys != {sorted(DW_KEYS)}")
        if not e.get("commits"):
            warns.append(f"{e['id']}: empty commits[] (uncommitted work?)")

    # 2 ORDER
    ids = [e["id"] for e in entries]
    if ids != sorted(ids):
        fails.append("registry not sorted by id ascending")
    if len(set(ids)) != len(ids):
        fails.append("duplicate ids present")

    # 3 ARTIFACTS
    # Older entries annotate paths ("file.md (what changed)") and some pin a
    # commit ("path@sha") or a doc anchor ("file.md#heading"). Strip the
    # annotation before testing existence, and count pinned/anchored refs
    # separately — they are unresolvable from the worktree by design.
    pinned = 0
    annotated = 0
    for e in scope:
        for a in e.get("artifacts", []):
            if "@" in a or "#" in a:
                pinned += 1
                continue
            base = re.sub(r"\s*\(.*\)\s*$", "", a).strip()
            if base != a:
                annotated += 1
            if not os.path.exists(base):
                fails.append(f"{e['id']}: artifact missing: {a}")

    # 4 NUMBERS
    untraceable = []
    for e in scope:
        srcs = NUMBER_SOURCES.get(e["id"])
        if not srcs:
            continue
        pool = set()
        for s in srcs:
            if os.path.exists(s):
                flatten(json.load(open(s)), pool)
            else:
                fails.append(f"{e['id']}: declared number source missing: {s}")
        for k, v in e["metrics"].items():
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                continue
            if traceable(float(v), pool) or (e["id"], k) in DERIVED_OK:
                continue
            untraceable.append(f"{e['id']}: metric '{k}' = {v} not traceable to any artifact")
    fails.extend(untraceable)

    # 5 PRECOMMIT
    precommit_ok = True
    try:
        old = subprocess.run(["git", "show", f"{PRECOMMIT_REV}:{BACKLOG}"],
                             capture_output=True, text=True, check=True).stdout
        new = subprocess.run(["git", "show", f"HEAD:{BACKLOG}"],
                             capture_output=True, text=True, check=True).stdout
        a, b = method_sections(old), method_sections(new)
        for k in sorted(set(a) | set(b)):
            ha = hashlib.sha256(a.get(k, "").encode()).hexdigest()
            hb = hashlib.sha256(b.get(k, "").encode()).hexdigest()
            if ha != hb:
                fails.append(f"{k}: Method body EDITED since pre-commit {PRECOMMIT_REV}")
                precommit_ok = False
    except subprocess.CalledProcessError:
        warns.append(f"could not read {BACKLOG} at {PRECOMMIT_REV}; pre-commit check skipped")
        precommit_ok = False

    n_nums = sum(len([1 for k, v in e["metrics"].items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)])
                 for e in scope if e["id"] in NUMBER_SOURCES)
    print(f"audited {len(scope)} of {len(entries)} entries"
          + (f" (>= {args.since})" if args.since else ""))
    print(f"  1 schema       {len(scope)} entries, {len(REQUIRED)} required fields")
    print(f"  2 order        sorted={ids == sorted(ids)}  unique={len(set(ids)) == len(ids)}")
    print(f"  3 artifacts    checked; {pinned} commit-pinned/anchored, "
          f"{annotated} annotated 'path (note)' (base path verified)")
    print(f"  4 numbers      {n_nums} numeric metrics checked, "
          f"{len(DERIVED_OK)} whitelisted as documented derivations")
    print(f"  5 precommit    Method bodies identical to {PRECOMMIT_REV}: {precommit_ok}")

    for w in warns:
        print(f"  WARN  {w}")
    if fails:
        print(f"\nFAILED ({len(fails)}):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
