"""Render `experiments/registry.jsonl` into a readable results digest.

`registry.jsonl` is the source of truth and is machine-readable by design — one
JSON object per line, diffable and greppable. That makes it a poor thing to
*read*. This renders it into two files (split 2026-11-10 to keep the session
read surface small):

- `docs/experiment-results.md`, the digest a session reads: Decision state
  (closed / live / standing evidence) and the summary table.
- `docs/experiment-results-detail.md`, one section per experiment with every
  recorded metric, caveat, artifact and commit. Grep it by id; don't load it.

**The output is generated, never hand-edited.** Every value comes from the
registry or from an artifact the registry points at, so the digest cannot drift
from the record it summarises. `--check` re-renders and diffs without writing,
exiting non-zero if either committed file is stale — suitable for `/curate` or
CI alongside `scripts/audit_registry.py`.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/render_results.py
    PYTHONPATH=. .venv/bin/python scripts/render_results.py --check
    PYTHONPATH=. .venv/bin/python scripts/render_results.py --since EXP-021
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

OUT = Path("docs/experiment-results.md")
DETAIL_OUT = Path("docs/experiment-results-detail.md")

def _archived_artifacts() -> dict:
    """ARCHIVED_ARTIFACTS from audit_registry.py, the single place it is kept."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_registry", Path(__file__).resolve().with_name("audit_registry.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ARCHIVED_ARTIFACTS


ARCHIVED = _archived_artifacts()


def fmt_artifact(a: str) -> str:
    base = re.sub(r"\s*\(.*\)\s*$", "", a).strip()
    moved = ARCHIVED.get(base)
    return f"`{a}` (archived: `{moved}`)" if moved else f"`{a}`"


DECISION_GLYPH = {
    "kept": "**kept**", "parked": "parked", "rejected": "rejected",
    "rolled_back": "rolled back", "superseded": "superseded",
}

# Headline metrics worth surfacing in the summary table, per entry. Keys are
# looked up in the entry's own `metrics`; missing keys are skipped silently so
# the renderer never fabricates a number it cannot find.
HEADLINE = {
    "EXP-021": ["fm_qs_delta_pct_vs_lean", "fm_mae", "lean_mae", "fm_coverage_band"],
    "EXP-022": ["prior_share_of_gap_pct_points", "context_share_of_gap_pct_points"],
    "EXP-023": ["w112_dqs_pct_vs_56d", "w112_dm_p_beats_56d"],
    "EXP-024": ["lean_lag168_dqs_pct_vs_lean", "lean_lag168_derived_dqs_pct_vs_lean"],
    "EXP-025": ["transplant_band_coverage", "lean_cqr_band_coverage", "fm_band_coverage"],
    "EXP-026": ["bolt_tiny_retention_pct", "bolt_small_retention_pct"],
    "EXP-027": ["final_mae_delta_pct", "final_coverage_delta"],
    "EXP-028": ["known_future_dqs_pct_vs_univariate", "known_future_dm_p"],
    "EXP-029": ["oos_r2_all", "oos_r2_wind_only"],
    "EXP-030": ["chronos-bolt-base_median_s", "chronos-bolt-tiny_median_s"],
    "EXP-031": ["untraceable_before", "untraceable_after", "numeric_metrics_checked"],
}


def first_sentence(s: str, limit: int = 200) -> str:
    """First sentence, without splitting inside a decimal like '-2.0031'."""
    out = re.split(r"(?<=[a-zA-Z)\]])\.\s+(?=[A-Z(])", s.strip(), maxsplit=1)[0].rstrip(".")
    return (out[:limit].rsplit(" ", 1)[0] + "…") if len(out) > limit else out


def fmt(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(entries, since=None, detail_ref=DETAIL_OUT.name,
           digest_ref=OUT.name) -> tuple[str, str]:
    """Return (digest, detail) markdown. Each *_ref is the other file's path
    relative to the file that names it."""
    scope = [e for e in entries if not since or e["id"] >= since]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    L = []
    L.append("# Experiment Results\n")
    L.append("**Generated file — do not edit.** Rendered from `experiments/registry.jsonl` "
             "and the `summary.json` artifacts it references, by "
             "`scripts/render_results.py`. Regenerate after appending to the registry; "
             "`--check` fails if this file is stale. Per-experiment sections (every "
             f"metric, caveat, artifact, commit) are in `{detail_ref}`: "
             "grep it by id rather than reading it whole.\n")
    L.append(f"Registry state: **{len(entries)} entries**, rendered at `{head}`. "
             "Integrity of the underlying record is verified separately by "
             "`scripts/audit_registry.py` (schema, id order, artifact existence, "
             "number traceability, and sha256 proof that no pre-committed Method was "
             "edited after its result landed).\n")
    L.append("Decision values: `kept` (evidence stands / in production) · `parked` "
             "(works, not adopted, revisit) · `rejected` (does not work) · "
             "`rolled_back` · `superseded`.\n")

    # Decision state, derived mechanically from `decision` so it cannot drift
    # into wishful thinking. This is the section a future session reads FIRST:
    # what is settled, what is waiting on a trigger, what must not be re-run.
    by = {}
    for e in scope:
        by.setdefault(e["decision"], []).append(e)

    L.append("## Decision state — read this before proposing new work\n")
    L.append("Derived from each entry's `decision` field, so it cannot drift from the record.\n")
    L.append("> **augur#29 verdict, 2026-11-06:** every effect size from before 2026-09-06 "
             "is measured against a reference that doesn't beat the seasonal-naive floor. "
             "Entry: `docs/archive/hypothesis-log-resolved.md` [2026-09-06].\n")

    L.append("### Closed — refuted, do not re-run as-is\n")
    L.append("Per ADR-007 a refuted position is **not** re-run with a looser Method. "
             "Re-opening one of these needs a *new* entry with a new Position and a "
             "mechanism that says why the earlier test could not have seen the effect "
             "— the way EXP-020 narrowed EXP-018, and EXP-028 narrowed EXP-020.\n")
    L.append("| id | what is closed | why |")
    L.append("|---|---|---|")
    for e in by.get("rejected", []) + by.get("rolled_back", []):
        why = first_sentence(e["decision_rationale"])
        L.append(f"| {e['id']} | {e['title'].split(':')[0].strip()} | {why} |")
    L.append("")

    L.append("### Open — works, not adopted. **These are the live decisions.**\n")
    L.append("The registry records *what was found*; the **revisit trigger and review-by "
             "date live in `docs/hypothesis-log.md`**, which is the file to check for what "
             "each of these is actually waiting on.\n")
    L.append("| id | finding | why it did not ship |")
    L.append("|---|---|---|")
    for e in by.get("parked", []):
        L.append(f"| {e['id']} | {e['title'].split(':')[0].strip()} "
                 f"| {first_sentence(e['decision_rationale'])} |")
    L.append("")

    L.append("### Standing evidence — `kept`\n")
    L.append("| id | finding |")
    L.append("|---|---|")
    for e in by.get("kept", []) + by.get("superseded", []):
        L.append(f"| {e['id']} | {e['title'].split(':')[0].strip()} |")
    L.append("")

    L.append("## Summary\n")
    L.append("| id | date | decision | headline | outcome |")
    L.append("|---|---|---|---|---|")
    for e in scope:
        hl = []
        for k in HEADLINE.get(e["id"], []):
            if k in e["metrics"]:
                hl.append(f"`{k}`={fmt(e['metrics'][k])}")
        title = e["title"].split("—")[0].strip() if "—" in e["title"] else e["title"]
        L.append(f"| {e['id']} | {e['date']} | {DECISION_GLYPH.get(e['decision'], e['decision'])} "
                 f"| {'<br>'.join(hl) if hl else '—'} | {title} |")
    L.append("")
    digest = "\n".join(L)

    L = []
    L.append("# Experiment Results — per-experiment detail\n")
    L.append("**Generated file — do not edit.** Rendered from `experiments/registry.jsonl` "
             "by `scripts/render_results.py`. Decision state and the summary are in "
             f"`{digest_ref}`. Grep this file by id.\n")
    L.append(f"Registry state: **{len(entries)} entries**, rendered at `{head}`.\n")
    for e in scope:
        L.append(f"## {e['id']} — {e['title']}\n")
        L.append(f"**{DECISION_GLYPH.get(e['decision'], e['decision'])}** · {e['date']} · "
                 f"model: {e['model']}\n")
        L.append(f"**Hypothesis.** {e['hypothesis']}\n")
        L.append(f"**Outcome.** {e['decision_rationale']}\n")

        nums = {k: v for k, v in e["metrics"].items()}
        if nums:
            L.append("<details><summary>All recorded metrics "
                     f"({len(nums)})</summary>\n")
            L.append("| metric | value |")
            L.append("|---|---|")
            for k, v in nums.items():
                L.append(f"| `{k}` | {fmt(v)} |")
            L.append("\n</details>\n")

        if e.get("notes"):
            L.append(f"**Caveats.** {e['notes']}\n")
        arts = " · ".join(fmt_artifact(a) for a in e["artifacts"])
        L.append(f"**Artifacts.** {arts}\n")
        if e.get("commits"):
            L.append(f"**Commits.** {' '.join('`'+c+'`' for c in e['commits'])}\n")
        L.append("---\n")
    return digest, "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default="experiments/registry.jsonl")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--detail-out", default=None,
                    help="per-experiment file (default: experiment-results-detail.md beside --out)")
    ap.add_argument("--since", default=None)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed digest is current; write nothing")
    args = ap.parse_args()

    entries = [json.loads(l) for l in open(args.registry)]
    out = Path(args.out)
    detail = Path(args.detail_out) if args.detail_out else out.with_name(DETAIL_OUT.name)
    if out.resolve() == detail.resolve():
        print(f"ERROR: digest and detail both resolve to {out.resolve()}")
        return 2
    texts = dict(zip((out, detail), render(
        entries, args.since,
        detail_ref=os.path.relpath(detail.resolve(), out.resolve().parent),
        digest_ref=os.path.relpath(out.resolve(), detail.resolve().parent))))

    if args.check:
        # The rendered-at hash legitimately changes every commit; mask only the
        # hash, so the rest of the "Registry state:" line (entry count) is checked.
        strip = lambda s: re.sub(r"^(Registry state: .*?rendered at `)[0-9a-f]*(`)",
                                 r"\1HASH\2", s, flags=re.M)
        stale = False
        for path, text in texts.items():
            if not path.exists():
                print(f"STALE: {path} does not exist")
                stale = True
            elif strip(path.read_text()) != strip(text):
                print(f"STALE: {path} does not match the registry — rerun render_results.py")
                stale = True
        if stale:
            return 1
        print(f"{out} and {detail} are current ({len(entries)} entries)")
        return 0

    for path, text in texts.items():
        path.write_text(text)
        print(f"wrote {path}  ({len(entries)} entries, {len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
