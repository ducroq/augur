"""Render `experiments/registry.jsonl` into a readable results digest.

`registry.jsonl` is the source of truth and is machine-readable by design — one
JSON object per line, diffable and greppable. That makes it a poor thing to
*read*. This renders it into `docs/experiment-results.md`: a summary table plus
a per-experiment section with the headline numbers pulled straight out of the
committed `summary.json` artifacts.

**The output is generated, never hand-edited.** Every value comes from the
registry or from an artifact the registry points at, so the digest cannot drift
from the record it summarises. `--check` re-renders and diffs without writing,
exiting non-zero if the committed digest is stale — suitable for `/curate` or
CI alongside `scripts/audit_registry.py`.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/render_results.py
    PYTHONPATH=. .venv/bin/python scripts/render_results.py --check
    PYTHONPATH=. .venv/bin/python scripts/render_results.py --since EXP-021
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

OUT = Path("docs/experiment-results.md")

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


def fmt(v):
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def render(entries, since=None) -> str:
    scope = [e for e in entries if not since or e["id"] >= since]
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True).stdout.strip()

    L = []
    L.append("# Experiment Results\n")
    L.append("**Generated file — do not edit.** Rendered from `experiments/registry.jsonl` "
             "and the `summary.json` artifacts it references, by "
             "`scripts/render_results.py`. Regenerate after appending to the registry; "
             "`--check` fails if this file is stale.\n")
    L.append(f"Registry state: **{len(entries)} entries**, rendered at `{head}`. "
             "Integrity of the underlying record is verified separately by "
             "`scripts/audit_registry.py` (schema, id order, artifact existence, "
             "number traceability, and sha256 proof that no pre-committed Method was "
             "edited after its result landed).\n")
    L.append("Decision values: `kept` (evidence stands / in production) · `parked` "
             "(works, not adopted, revisit) · `rejected` (does not work) · "
             "`rolled_back` · `superseded`.\n")

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
        arts = " · ".join(f"`{a}`" for a in e["artifacts"])
        L.append(f"**Artifacts.** {arts}\n")
        if e.get("commits"):
            L.append(f"**Commits.** {' '.join('`'+c+'`' for c in e['commits'])}\n")
        L.append("---\n")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--registry", default="experiments/registry.jsonl")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--since", default=None)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed digest is current; write nothing")
    args = ap.parse_args()

    entries = [json.loads(l) for l in open(args.registry)]
    text = render(entries, args.since)
    out = Path(args.out)

    if args.check:
        if not out.exists():
            print(f"STALE: {out} does not exist")
            return 1
        cur = out.read_text()
        # The rendered-at commit line legitimately changes every commit; compare
        # everything else so the check tracks content, not the hash.
        strip = lambda s: "\n".join(l for l in s.splitlines()
                                    if not l.startswith("Registry state:"))
        if strip(cur) != strip(text):
            print(f"STALE: {out} does not match the registry — rerun render_results.py")
            return 1
        print(f"{out} is current ({len(entries)} entries)")
        return 0

    out.write_text(text)
    print(f"wrote {out}  ({len(entries)} entries, {len(text.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
