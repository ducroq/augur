#!/usr/bin/env python3
"""EXP-035: re-score every stored model arm against a seasonal-naive floor.

Why this exists
---------------
Every comparison in this project is *relative*. `eval_log.jsonl` scores LightGBM
against ARF; the registry scores variants against production; the DM test in
`ml/shadow/metrics.py` compares two candidates. None of them can see the case
where every arm is worse than a trivial baseline — that reads as a healthy log
with a clear winner. `docs/hypothesis-log.md` [2026-09-06] opened that question
on the live record; this script answers it on the 260 offline vintages already
stored by EXP-018 and EXP-021, so it needs no fresh vintages and no GPU.

ADR-007 layer 2 ("apply the criterion to existing data before running a new
shadow window") is exactly this move.

The baseline
------------
Seasonal-naive: for an hour at horizon h from anchor t0, the prediction is the
price at the same clock hour `24 * ceil(h / 24)` hours earlier — the last
same-hour observation available when the forecast was made. For a 72h vintage
that is always the single window `[t0-23h, t0]`.

Prices come from `exp021_foundation/contexts.parquet`, which is the context tape
the foundation model was actually fed at each t0. That makes the baseline's
information set a strict subset of the candidate's by construction, rather than
by an argument about a separate price series: it cannot read anything the model
did not already have.

Usage
-----
    python scripts/exp035_naive_floor.py
    python scripts/exp035_naive_floor.py --out ml/shadow/exp035_naive_floor
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from ml.shadow.metrics import diebold_mariano  # noqa: E402
CONTEXTS = REPO / "ml" / "shadow" / "exp021_foundation" / "contexts.parquet"
FM_PREDS = REPO / "ml" / "shadow" / "exp021_foundation" / "fm_predictions.parquet"
LGBM_PREDS = REPO / "ml" / "shadow" / "exp018_stage0" / "predictions.parquet"

# HAC truncation lag = max_horizon - 1, per ADR-007's skill gate.
HAC_LAGS = 71


def add_naive(df: pd.DataFrame, price: pd.Series) -> pd.DataFrame:
    """Attach the seasonal-naive prediction for every row."""
    out = df.copy()
    days_back = np.ceil(out["horizon_h"] / 24.0).astype(int).clip(lower=1)
    source = out["timestamp_utc"] - pd.to_timedelta(days_back * 24, unit="h")
    idx = pd.MultiIndex.from_arrays([out["t0"], source])
    out["naive"] = price.reindex(idx).to_numpy()
    return out


def skill(pred: pd.Series, naive: pd.Series, realized: pd.Series) -> dict:
    e_model = (realized - pred).abs()
    e_naive = (realized - naive).abs()
    dm = diebold_mariano(e_model.to_numpy(), e_naive.to_numpy(), hac_lags=HAC_LAGS)
    return {
        "n": int(len(e_model)),
        "mae": round(float(e_model.mean()), 4),
        "naive_mae": round(float(e_naive.mean()), 4),
        "skill_vs_naive": round(float(1 - e_model.mean() / e_naive.mean()), 4),
        "dm_statistic": round(float(dm.statistic), 4),
        "dm_p_one_sided": round(float(dm.p_value_one_sided), 6),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="EXP-035 seasonal-naive floor")
    ap.add_argument("--out", default=str(REPO / "ml" / "shadow" / "exp035_naive_floor"))
    args = ap.parse_args()

    price = pd.read_parquet(CONTEXTS).set_index(["t0", "timestamp_utc"])["price"]
    fm = add_naive(pd.read_parquet(FM_PREDS), price)
    lgbm = add_naive(pd.read_parquet(LGBM_PREDS), price)

    arms = {f"lgbm_{v}": d for v, d in lgbm.groupby("variant")}
    arms.update({f"fm_{v}": d for v, d in fm.groupby("variant")})

    summary: dict = {
        "baseline": "seasonal-naive, 24*ceil(h/24) lookback, sourced from the FM context tape",
        "hac_lags": HAC_LAGS,
        "arms": {},
        "monthly": {},
    }

    for name, d in sorted(arms.items()):
        d = d.dropna(subset=["naive", "p50", "realized"]).sort_values(["t0", "horizon_h"])
        row = skill(d["p50"], d["naive"], d["realized"])
        row["vintages"] = int(d["t0"].nunique())
        # Per horizon group, because naive MAE is strongly horizon-dependent.
        for lab, lo, hi in (("h1_24", 1, 24), ("h25_48", 25, 48), ("h49_72", 49, 72)):
            s = d[(d["horizon_h"] >= lo) & (d["horizon_h"] <= hi)]
            e_m = (s["realized"] - s["p50"]).abs().mean()
            e_n = (s["realized"] - s["naive"]).abs().mean()
            row[f"skill_{lab}"] = round(float(1 - e_m / e_n), 4)
        summary["arms"][name] = row

        months = d.assign(month=d["t0"].dt.tz_convert("UTC").dt.strftime("%Y-%m"))
        per_month = {}
        for mo, g in months.groupby("month"):
            e_m = (g["realized"] - g["p50"]).abs().mean()
            e_n = (g["realized"] - g["naive"]).abs().mean()
            per_month[mo] = {
                "mean_price": round(float(g["realized"].mean()), 2),
                "mae": round(float(e_m), 3),
                "naive_mae": round(float(e_n), 3),
                "skill": round(float(1 - e_m / e_n), 4),
            }
        summary["monthly"][name] = per_month

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"{'arm':<26} {'n':>6} {'MAE':>8} {'naive':>8} {'skill':>8} {'DM p':>10}")
    for name, r in sorted(summary["arms"].items(), key=lambda kv: -kv[1]["skill_vs_naive"]):
        print(f"{name:<26} {r['n']:>6} {r['mae']:>8.2f} {r['naive_mae']:>8.2f} "
              f"{r['skill_vs_naive']:>8.4f} {r['dm_p_one_sided']:>10.6f}")
    print(f"\nWritten to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
