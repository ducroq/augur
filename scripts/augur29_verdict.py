#!/usr/bin/env python3
"""Compute the augur#29 verdict from ml/shadow/eval_log.jsonl and regret_log.jsonl.

Pre-commitment: docs/archive/hypothesis-log-resolved.md, entry [2026-09-06 -> resolved
2026-11-06], Step 2 and the 2026-09-11 amendment. The verdict reads MEAN skill against
the single-day carry on rows with n_naive_hours >= 12. Rows of a different span are
reported separately, not averaged in. The other reads are context, never the verdict.

Span family choice, made when the verdict was read: min horizon 1, max horizon <= 26.
CUTOFF pins the verdict to the rows it was read on, so later nightly rows do not move
it. The eval log holds h1-24 only, so regret stands in for the per-horizon-group split.
Read-only; runs on any host with the two logs.
"""
import collections
import json
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_NAIVE_HOURS = 12  # scripts/daily_update.sh
CUTOFF = "2026-11-05"


def load(name):
    with open(ROOT / "ml" / "shadow" / name) as f:
        return [json.loads(line) for line in f]


def pooled(rows, mae, base, n):
    return 1 - sum(r[mae] * r[n] for r in rows) / sum(r[base] * r[n] for r in rows)


def main():
    rows = [r for r in load("eval_log.jsonl")
            if r.get("lightgbm_skill_vs_naive") is not None
            and r["n_naive_hours"] >= MIN_NAIVE_HOURS and r["date"] <= CUTOFF]
    main_span = [r for r in rows
                 if r["naive_min_horizon_h"] == 1 and r["naive_max_horizon_h"] <= 26]
    other = [r for r in rows if r not in main_span]
    skill = sorted(r["lightgbm_skill_vs_naive"] for r in main_span)
    mean = st.mean(skill)
    bucket = "confirmed" if mean < 0 else "rounding error" if mean <= 0.05 else "regime"
    print(f"rows {main_span[0]['date']}..{main_span[-1]['date']}: {len(skill)} in span, "
          f"{len(rows)} qualifying")
    print(f"VERDICT mean skill vs carry {mean:.3f} -> {bucket}")
    print(f"context: trimmed (2 each side) {st.mean(skill[2:-2]):.3f}, median "
          f"{st.median(skill):.3f}, pooled "
          f"{pooled(main_span, 'lightgbm_mae_on_naive_hours', 'naive_mae', 'n_naive_hours'):.3f}")
    exact = [r["lightgbm_skill_vs_naive"] for r in main_span if r["naive_max_horizon_h"] == 24]
    print(f"context: exact h1-24 mean {st.mean(exact):.3f} ({len(exact)} rows), "
          f"without the worst row {st.mean(skill[1:]):.3f}")
    for r in other:
        print(f"other span {r['date']} h{r['naive_min_horizon_h']}-{r['naive_max_horizon_h']}: "
              f"skill {r['lightgbm_skill_vs_naive']:.3f} ({r['n_naive_hours']}h)")
    prof = [r for r in main_span if r.get("lightgbm_skill_vs_naive_profile") is not None]
    print(f"profile floor: mean {st.mean(r['lightgbm_skill_vs_naive_profile'] for r in prof):.3f}, "
          f"pooled {pooled(prof, 'lightgbm_mae_on_profile_hours', 'naive_profile_mae', 'n_naive_profile_hours'):.3f}"
          f" ({len(prof)} rows)")
    blocks = collections.defaultdict(list)
    for g in load("regret_log.jsonl"):
        if g["date"] <= CUTOFF and None not in (g.get("lightgbm_regret_k6"), g.get("profile_regret_k6"),
                        g.get("naive_regret_k6")):
            blocks[g["block"]].append(g)
    for name, gs in sorted(blocks.items()):
        means = [st.mean(g[f"{a}_regret_k6"] for g in gs)
                 for a in ("lightgbm", "naive", "profile")]
        print(f"regret k6 {name} ({len(gs)}): lightgbm {means[0]:.2f}, "
              f"carry {means[1]:.2f}, profile {means[2]:.2f}")


if __name__ == "__main__":
    main()
