"""EXP-022 — how much of Chronos-Bolt's 20% win is pretrained prior, and how much is just seeing more context?

**Exploratory diagnostic, NOT a pre-committed arm.** EXP-021 measured the gap;
this asks what produces it. It has no gates, decides nothing, and ships nothing
— per ADR-007 the pre-commit discipline governs *promotion* decisions, and this
is descriptive in the same sense EXP-018 Stage 0 was. Read it as mechanism
evidence, not as a criterion anything passed.

The question. EXP-021's incumbent (`lean` LightGBM) trains on a 56-day window
and then predicts all 72 horizons from a *single feature row* at t0 — 8 price
lags plus 6 rolling stats, ~14 numbers. Chronos-Bolt reads the raw 1343-point
series. Two very different things could be producing the gap:

  1. **Pretrained prior** — the model knows what hourly-price shape and h-step
     uncertainty look like, from ~10^11 pretraining points.
  2. **Context volume** — it simply sees 1343 numbers where the incumbent's
     feature vector sees 14, and the gap is a critique of our feature design
     rather than of gradient boosting.

These separate cleanly by *starving the FM of context* while leaving the
incumbent untouched. If Chronos on 7 days still beats LightGBM trained on 56,
the surviving margin is prior, not information.

Method. Truncate each EXP-021 context to its last N hours (the same vintages,
the same targets, the same t0 grid — only the context start moves), re-run the
identical `exp021_foundation_zeroshot.py predict` on the GPU box, and score
every rung against the same `lean`/`full` arms with the same functions and the
same HAC bandwidth 71. Truncation is applied to the **matched-information**
contexts (`--context-end-offset-h 1`), so every rung inherits EXP-021's
correction for the incumbent's `shift(1)` feature row.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp022_context_ladder.py truncate \
        --source ml/shadow/exp021_foundation_aligned \
        --hours 168,336,672 --out ml/shadow/exp022_context_ladder

    # per rung, on b650-gpu:
    ~/augur-fm/.venv/bin/python exp021_foundation_zeroshot.py predict \
        --out ~/augur-fm/ctx168 --device cuda:0

    PYTHONPATH=. .venv/bin/python scripts/exp022_context_ladder.py score \
        --out ml/shadow/exp022_context_ladder \
        --full-context ml/shadow/exp021_foundation_aligned/fm_predictions.parquet \
        --incumbents ml/shadow/exp020_fundamentals_ctl/predictions.parquet
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

QUANTILE_LEVELS = (0.1, 0.5, 0.9)
HAC_LAGS = 71


def mode_truncate(args: argparse.Namespace) -> None:
    src = Path(args.source)
    ctx = pd.read_parquet(src / "contexts.parquet")
    meta = json.loads((src / "contexts_meta.json").read_text())
    out_root = Path(args.out)

    for hours in [int(h) for h in args.hours.split(",")]:
        out = out_root / f"ctx{hours}"
        out.mkdir(parents=True, exist_ok=True)
        g = ctx.sort_values(["t0", "pos"]).groupby("t0", group_keys=False).tail(hours).copy()
        # Positions must restart at 0 or `predict` reassembles the series wrong.
        g["pos"] = g.groupby("t0").cumcount()
        g.to_parquet(out / "contexts.parquet")
        shutil.copy(src / "targets.parquet", out / "targets.parquet")
        m = dict(meta)
        m["truncated_context_hours"] = hours
        m["truncated_from"] = str(src)
        (out / "contexts_meta.json").write_text(json.dumps(m, indent=2))
        print(f"  ctx{hours}: median context {g.groupby('t0').size().median():.0f} points -> {out}")


def mode_score(args: argparse.Namespace) -> None:
    from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

    out_dir = Path(args.out)
    key = ["t0", "timestamp_utc"]
    inc = pd.read_parquet(args.incumbents)

    arms: dict[str, pd.DataFrame] = {
        "lean_lgbm_56d": inc[inc["variant"] == "lean"],
        "full_lgbm_56d": inc[inc["variant"] == "full"],
        "chronos_ctx_full": pd.read_parquet(args.full_context),
    }
    rungs = sorted(
        (int(p.name.removeprefix("ctx")) for p in out_dir.glob("ctx*") if p.is_dir()),
        reverse=True,
    )
    for h in rungs:
        f = out_dir / f"ctx{h}" / "fm_predictions.parquet"
        if f.exists():
            arms[f"chronos_ctx_{h}h"] = pd.read_parquet(f)

    # Every rung is scored on the incumbent's exact cell set, so the ladder is
    # internally paired as well as paired against the baseline.
    ref = arms["lean_lgbm_56d"].set_index(key)
    scored: dict[str, dict] = {}
    losses: dict[str, np.ndarray] = {}
    for label, d in arms.items():
        m = d.set_index(key).loc[ref.index]
        y = m["realized"].to_numpy()
        qs = per_observation_quantile_score(
            y, m[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(), list(QUANTILE_LEVELS)
        )
        losses[label] = qs
        lo, hi = m["p10"].to_numpy(), m["p90"].to_numpy()
        scored[label] = {
            "n_obs": int(len(m)),
            "mae": float(np.abs(m["p50"].to_numpy() - y).mean()),
            "quantile_score": float(qs.mean()),
            "coverage_lower": float((y >= lo).mean()),
            "coverage_upper": float((y <= hi).mean()),
            "coverage_band": float(((y >= lo) & (y <= hi)).mean()),
            "band_width_median": float(np.median(hi - lo)),
        }

    base = losses["lean_lgbm_56d"]
    base_qs = scored["lean_lgbm_56d"]["quantile_score"]
    for label, e in scored.items():
        e["qs_delta_pct_vs_lean"] = 100.0 * (e["quantile_score"] / base_qs - 1.0)
        if label != "lean_lgbm_56d":
            dm = diebold_mariano(losses[label], base, hac_lags=HAC_LAGS)
            e["dm_beats_lean"] = {
                "statistic": float(dm.statistic),
                "p_one_sided": float(dm.p_value_one_sided),
                "hac_lags": int(dm.hac_lags),
            }

    summary = {
        "config": {
            "purpose": "exploratory mechanism diagnostic for EXP-021 — NOT pre-committed, no gates",
            "incumbents": str(args.incumbents),
            "full_context_arm": str(args.full_context),
            "hac_lags": HAC_LAGS,
            "quantiles": list(QUANTILE_LEVELS),
            "cqr_applied": False,
            "context_end_offset_h": 1,
            "n_paired_observations": scored["lean_lgbm_56d"]["n_obs"],
        },
        "arms": scored,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'arm':<22}{'MAE':>8}{'QS':>8}{'dQS% vs lean':>14}{'cov_band':>10}{'DM p':>9}")
    for label, e in scored.items():
        dm = e.get("dm_beats_lean")
        p = "—" if dm is None else format(dm["p_one_sided"], ".4f")
        print(
            f"{label:<22}{e['mae']:>8.2f}{e['quantile_score']:>8.2f}"
            f"{e['qs_delta_pct_vs_lean']:>14.1f}{e['coverage_band']:>10.3f}{p:>9}"
        )
    print(f"\nwrote {out_dir/'summary.json'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    t = sub.add_parser("truncate", help="build truncated-context rungs from an EXP-021 context set")
    t.add_argument("--source", default="ml/shadow/exp021_foundation_aligned")
    t.add_argument("--hours", default="168,336,672")
    t.add_argument("--out", default="ml/shadow/exp022_context_ladder")
    t.set_defaults(func=mode_truncate)

    s = sub.add_parser("score", help="score every rung against lean/full")
    s.add_argument("--out", default="ml/shadow/exp022_context_ladder")
    s.add_argument("--full-context", default="ml/shadow/exp021_foundation_aligned/fm_predictions.parquet")
    s.add_argument("--incumbents", default="ml/shadow/exp020_fundamentals_ctl/predictions.parquet")
    s.set_defaults(func=mode_score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
