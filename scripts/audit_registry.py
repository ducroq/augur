"""Audit `experiments/registry.jsonl` against the rules in `experiments/README.md`.

Written 2026-08-30 after a documentation audit found 19 registry metrics that
could not be traced to any committed artifact. They were correct but had been
computed by throwaway inline analyses, so nobody could regenerate or check them
— the same class of failure as leaving results in /tmp. This script makes the
check repeatable instead of a one-off claim.

Six checks:

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
                 An executed entry may live in the backlog or in
                 `docs/archive/experiment-backlog-run.md`, never both; the
                 baseline is always read from the backlog at the pin.

  6. HYPOTHESIS  every pre-committed Method in `docs/hypothesis-log.md` and its
                 archive is byte-identical to its pin (`HYPOTHESIS_PINS`): the
                 commit where it first appeared, or the version in force where
                 an early edit is recorded beside the pin. An unpinned Method in
                 either file warns. The swap criteria live there.

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
PRECOMMIT_REV = "4024420"          # the 2026-08-29 batch (EXP-023..029)
# Entries pre-committed AFTER that batch, each pinned to the revision where its
# Method first landed. Without this the check compares a later entry against an
# empty string at PRECOMMIT_REV and fails forever — i.e. it would punish adding
# a new pre-commitment, the exact behaviour it exists to encourage. Added
# 2026-08-31 when EXP-034 hit precisely that.
PRECOMMIT_REV_BY_ID = {
    "EXP-034": "eedf7b2",
    "EXP-036": "2113e1f",
    "EXP-037": "2e96bb9",
    "EXP-040": "d53af7a",
    "EXP-040/addendum-2026-10-29": "47b2f16",
    "EXP-041": "db18a39",
}
BACKLOG = "docs/experiment-backlog.md"
# Executed entries retire here, bytes unchanged. It is a location for HEAD and
# the working tree only: baselines stay in BACKLOG at the pin, so nothing written
# to the archive can establish a pre-commitment.
BACKLOG_ARCHIVE = "docs/archive/experiment-backlog-run.md"

# Registry artifact paths whose file was later moved to docs/archive/ (the
# registry is append-only, so the old path stays in it). Check 3 resolves the
# old path through this map and fails if the archived file is missing;
# render_results.py shows the archived location beside the original.
ARCHIVED_ARTIFACTS = {
    "docs/exp-012-results.md": "docs/archive/exp-012-results.md",
    "docs/lightgbm-shadow-postmortem.md": "docs/archive/lightgbm-shadow-postmortem.md",
}

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
    "EXP-036": ["ml/shadow/exp036_profile_floor/summary.json"],
    "EXP-037": ["ml/shadow/exp037_rank_metric/summary.json",
                "ml/shadow/exp037_rank_metric/diagnostics.json"],
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
    """Map EXP id -> its section body, independent of what follows it.

    The split leaves the LAST section running to EOF, so appending a new entry
    used to change the previous last entry's captured body and report it as
    EDITED — a false positive that would fire on every future addition to the
    backlog (observed 2026-09-10 adding EXP-036 after EXP-034: the whole diff
    was the "\n\n---\n" separator between them). Normalising away the trailing
    separator makes a body depend only on itself. Both sides of the comparison
    go through here, so existing pins keep validating unchanged.
    """
    out = {}
    for part in re.split(r"\n## ", text)[1:]:
        head = part.split("\n", 1)[0].strip()
        m = re.match(r"(EXP-\d+)", head)
        # A dated addendum supersedes part of a pinned Method, so it is
        # hashed and pinned like one: `## Addendum YYYY-MM-DD to EXP-NNN …`.
        a = re.match(r"Addendum (\d{4}-\d{2}-\d{2}) to (EXP-\d+)", head)
        key = m.group(1) if m else f"{a.group(2)}/addendum-{a.group(1)}" if a else None
        if key:
            body = part.rstrip()
            if body.endswith("---"):
                body = body[: -len("---")].rstrip()
            out[key] = body
    return out


HYPOTHESIS_LOG = "docs/hypothesis-log.md"
HYPOTHESIS_ARCHIVE = "docs/archive/hypothesis-log-resolved.md"
# Check 6: every pre-committed Method in the hypothesis log, keyed by its entry's
# date plus the first 48 characters of its title (two 2026-08-29 entries exist,
# so a date alone collides) and pinned to the commit where it first appeared. Added 2026-11-08: the
# criteria that gate live swaps lived only here, so "never edited" was a
# convention, not a check. Each pin was verified that day: the block at the pin
# equals HEAD's (see the commit that added this map).
HYPOTHESIS_PINS = {
    "2026-08-29 EXP-021a: Chronos-Bolt's 20% zero-shot win survi": "6cb2633",
    "2026-08-30 EXP-028a: Chronos-2's covariate gain survives on": "0f340bf",
    "2026-10-28 Product criterion: a forecaster earns the dashbo": "a6672d8",
    "2026-11-06 Calibrating CQR on unwidened scores restores P80": "510d60a",
    "2026-11-07 Stage 3 promotion criterion: Chronos-Bolt beats ": "b05d352",
    # Resolved, in the archive. Traced 2026-11-08; unchanged since first commit
    # unless noted.
    "2026-05-29 Iteration-5 redesign of the calibration guardrai": "5fd9fb1",
    "2026-05-29 LightGBM-Quantile passes the redesigned promotio": "5fd9fb1",
    "2026-06-12 EXP-015: two-sided (per-side) CQR fixes the lowe": "bcc3e78",
    "2026-06-12 EXP-016: per-side ACI closes the regime-shift co": "440b0b6",
    "2026-08-20 Feature expansion is the highest-leverage untrie": "f427494",
    "2026-08-25 EXP-018a: removing the six rolling-stat features": "d7581b9",
    "2026-08-29 EXP-020: residual load and gas price carry price": "743476f",
    "2026-08-29 EXP-021: a pretrained time-series foundation mod": "6cb2633",
    "2026-08-30 EXP-023a: the 112-day window's 3.0% gain is real": "0f340bf",
    "2026-10-28 EXP-038: an early, tripwire-exempt read of EXP-0": "91e18ce",
    # Edited after first commit; pinned at the version in force. 62d3ffd ->
    # 0647a1e, 53 minutes later, same day, before any data: the code made
    # evaluable once the eval-log fields it needed existed.
    "2026-04-30 LightGBM-Quantile shadow will pass plan §6 over ": "0647a1e",
    # 89d4ac1 -> 9d356d6 (same day: EXP-035 does not discharge Step 2) ->
    # 44fabcb (09-11: Alternative 3 struck through as discharged by EXP-037).
    # Neither changed the gate; the verdict came 2026-11-06. The second is a
    # status note written inside a Method, which belongs outside it.
    "2026-09-06 The production model has no demonstrated skill o": "44fabcb",
}
# Bold fields that belong to a Method block rather than ending it. [2026-11-06]
# states its 28-vintage live check as its own field.
METHOD_CONTINUATIONS = ("Live check",)


def hypothesis_methods(text):
    """Map "date title-prefix" -> its pre-committed Method block, plus duplicate keys.

    The date is read from the start of the bracket, so a resolution note added
    inside it (`[2026-09-06 → resolved …]`) leaves the key unchanged.

    A block starts at `**Method (pre-committed` and runs to the next bold field
    (`**Label`) not in METHOD_CONTINUATIONS, so italic `*Stage N*` paragraphs
    stay inside it and later notes and addenda stay outside. Only Methods
    marked pre-committed are pinned.
    """
    out, dups = {}, []
    for part in re.split(r"\n### ", text)[1:]:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2})[^\]]*\]\s*(.*)", part)
        if not m:
            continue
        lines = re.split(r"\n## ", part)[0].split("\n")
        start = next((i for i, l in enumerate(lines)
                      if l.startswith("**Method (pre-committed")), None)
        if start is None:
            continue
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("**") and not lines[i][2:].startswith(METHOD_CONTINUATIONS):
                end = i
                break
        key = f"{m.group(1)} {m.group(2).strip()[:48]}"
        if key in out:
            dups.append(key)
        out[key] = "\n".join(lines[start:end]).rstrip()
    return out, dups


def check_hypothesis_methods(fails, warns):
    """Check 6. Pinned hypothesis-log Methods are byte-identical to their pin."""
    def at(rev, path):
        r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else ""

    def both(log_text, arch_text):
        (live, d1), (arch, d2) = hypothesis_methods(log_text), hypothesis_methods(arch_text)
        return {**arch, **live}, sorted(set(d1) | set(d2) | (set(live) & set(arch)))

    read = lambda p: open(p).read() if os.path.exists(p) else ""
    head, dup_h = both(at("HEAD", HYPOTHESIS_LOG), at("HEAD", HYPOTHESIS_ARCHIVE))
    work, dup_w = both(read(HYPOTHESIS_LOG), read(HYPOTHESIS_ARCHIVE))
    for k in sorted(set(dup_h) | set(dup_w)):
        fails.append(f"hypothesis [{k}]: two pre-committed Methods share this key, "
                     f"or the entry is in both the log and its archive")
    # Both files: an entry archived before its pin is added must not escape.
    for k in sorted(set(work) - set(HYPOTHESIS_PINS)):
        warns.append(f"hypothesis [{k}]: pre-committed Method not pinned; add it to "
                     f"HYPOTHESIS_PINS once its commit exists")
    for k, rev in sorted(HYPOTHESIS_PINS.items()):
        if subprocess.run(["git", "merge-base", "--is-ancestor", rev, "HEAD"],
                          capture_output=True).returncode != 0:
            fails.append(f"hypothesis [{k}]: pin {rev} is not an ancestor of HEAD")
            continue
        base = both(at(rev, HYPOTHESIS_LOG), at(rev, HYPOTHESIS_ARCHIVE))[0].get(k, "")
        if not base:
            fails.append(f"hypothesis [{k}]: no pre-committed Method at its pin {rev}")
        elif head.get(k) != base:
            fails.append(f"hypothesis [{k}]: Method EDITED since pin {rev}")
        elif work.get(k) != base:
            fails.append(f"hypothesis [{k}]: Method EDITED in the working tree since pin {rev}")


def merged_sections(backlog_text, archive_text):
    """Sections across both homes, plus the ids found in both.

    A duplicate is reported, not resolved: picking a winner would let the copy
    that was not hashed carry an edit.
    """
    live, run = method_sections(backlog_text), method_sections(archive_text)
    return {**run, **live}, sorted(set(live) & set(run))


def check_precommit(fails, warns):
    """Check 5. Appends to fails/warns; returns True if every Method verified."""
    precommit_ok = True
    try:
        def sections_at(rev):
            return method_sections(subprocess.run(
                ["git", "show", f"{rev}:{BACKLOG}"],
                capture_output=True, text=True, check=True).stdout)

        cache = {PRECOMMIT_REV: sections_at(PRECOMMIT_REV)}
        # No archive at HEAD is legal (it predates the file). Should it vanish
        # later, its entries read as empty below and fail as EDITED.
        arch = subprocess.run(["git", "show", f"HEAD:{BACKLOG_ARCHIVE}"],
                              capture_output=True, text=True)
        b, dup_b = merged_sections(
            subprocess.run(["git", "show", f"HEAD:{BACKLOG}"],
                           capture_output=True, text=True, check=True).stdout,
            arch.stdout if arch.returncode == 0 else "")
        # The working tree too: the audit runs BEFORE committing, when HEAD
        # cannot show an uncommitted edit to a pinned Method.
        with open(BACKLOG) as fh:
            live_text = fh.read()
        arch_text = ""
        if os.path.exists(BACKLOG_ARCHIVE):
            with open(BACKLOG_ARCHIVE) as fh:
                arch_text = fh.read()
        w, dup_w = merged_sections(live_text, arch_text)
        for k in sorted(set(dup_b) | set(dup_w)):
            fails.append(f"{k}: in both {BACKLOG} and {BACKLOG_ARCHIVE}")
            precommit_ok = False
        for k in sorted(set(w) - set(b)):
            if k not in PRECOMMIT_REV_BY_ID:
                warns.append(f"{k}: new in the working tree; pin it in "
                             f"PRECOMMIT_REV_BY_ID once its commit exists")
        # The pins belong in this set: an entry added after PRECOMMIT_REV is in
        # neither of the others once it is lost, and would pass unchecked.
        for k in sorted(set(cache[PRECOMMIT_REV]) | set(b) | set(PRECOMMIT_REV_BY_ID)):
            rev = PRECOMMIT_REV_BY_ID.get(k, PRECOMMIT_REV)
            if rev not in cache:
                # A pin must be in HEAD's history: an amended or rebased commit
                # survives in the reflog, so `git show` alone still succeeds.
                if subprocess.run(["git", "merge-base", "--is-ancestor", rev, "HEAD"],
                                  capture_output=True).returncode != 0:
                    fails.append(f"{k}: pin {rev} is not an ancestor of HEAD "
                                 f"(amended, rebased or unfetched?)")
                    precommit_ok = False
                    continue
                cache[rev] = sections_at(rev)
            baseline = cache[rev].get(k, "")
            if not baseline:
                fails.append(f"{k}: no Method body at its pre-commit {rev} — "
                             f"pin it in PRECOMMIT_REV_BY_ID, or it is not pre-committed")
                precommit_ok = False
                continue
            ha = hashlib.sha256(baseline.encode()).hexdigest()
            hb = hashlib.sha256(b.get(k, "").encode()).hexdigest()
            if ha != hb:
                fails.append(f"{k}: Method body EDITED since pre-commit {rev}")
                precommit_ok = False
            elif hashlib.sha256(w.get(k, "").encode()).hexdigest() != ha:
                fails.append(f"{k}: Method body EDITED in the working tree "
                             f"since pre-commit {rev}")
                precommit_ok = False
    except subprocess.CalledProcessError as e:
        # A FAIL, not a WARN: an unreachable pin (rewritten or unfetched commit,
        # shallow clone) used to skip check 5 for every entry and still exit 0.
        fails.append(f"could not read {e.cmd[2]} (pin unreachable?); "
                     f"pre-commit check 5 did not run for any entry")
        precommit_ok = False
    return precommit_ok


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
    archived = 0
    for e in scope:
        for a in e.get("artifacts", []):
            if "@" in a or "#" in a:
                pinned += 1
                continue
            base = re.sub(r"\s*\(.*\)\s*$", "", a).strip()
            if base != a:
                annotated += 1
            if base in ARCHIVED_ARTIFACTS:
                if os.path.exists(base):
                    fails.append(f"{e['id']}: {base} is mapped as archived but still exists")
                base = ARCHIVED_ARTIFACTS[base]
                archived += 1
            if not os.path.exists(base):
                where = "" if base == re.sub(r"\s*\(.*\)\s*$", "", a).strip() else f" (archived path {base})"
                fails.append(f"{e['id']}: artifact missing: {a}{where}")

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

    precommit_ok = check_precommit(fails, warns)
    n_fails = len(fails)
    check_hypothesis_methods(fails, warns)
    hyp_ok = len(fails) == n_fails

    n_nums = sum(len([1 for k, v in e["metrics"].items()
                      if isinstance(v, (int, float)) and not isinstance(v, bool)])
                 for e in scope if e["id"] in NUMBER_SOURCES)
    print(f"audited {len(scope)} of {len(entries)} entries"
          + (f" (>= {args.since})" if args.since else ""))
    print(f"  1 schema       {len(scope)} entries, {len(REQUIRED)} required fields")
    print(f"  2 order        sorted={ids == sorted(ids)}  unique={len(set(ids)) == len(ids)}")
    print(f"  3 artifacts    checked; {pinned} commit-pinned/anchored, "
          f"{annotated} annotated 'path (note)' (base path verified), "
          f"{archived} resolved via ARCHIVED_ARTIFACTS")
    print(f"  4 numbers      {n_nums} numeric metrics checked, "
          f"{len(DERIVED_OK)} whitelisted as documented derivations")
    print(f"  5 precommit    Method bodies identical to {PRECOMMIT_REV}: {precommit_ok}")
    print(f"  6 hypothesis   {len(HYPOTHESIS_PINS)} pinned hypothesis-log Methods unchanged: {hyp_ok}")

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
