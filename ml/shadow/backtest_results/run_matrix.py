"""EXP-009 milestone-2.5 — 2x2 matrix: window {28d, 56d} x conformal {off, on}.

For each window size, run the walk-forward backtest once and apply CQR
post-hoc to get the conformal variant for free. Outputs:

- predictions_28d.parquet, predictions_56d.parquet  (raw + cqr columns)
- matrix_summary.csv                                (one row per config)
- matrix_per_day.csv                                (per-day coverage/MAE per config)
"""

from pathlib import Path

import pandas as pd

from ml.shadow.backtest import (
    BacktestConfig,
    compute_metrics,
    walk_forward_backtest,
)
from ml.shadow.conformal import apply_cqr

ROOT = Path(__file__).resolve().parents[3]
PARQUET = ROOT / "ml" / "data" / "training_history.parquet"
OUT = ROOT / "ml" / "shadow" / "backtest_results"
EVAL_START = pd.Timestamp("2026-04-01", tz="UTC")
EVAL_END = pd.Timestamp("2026-04-29", tz="UTC")


def _per_day_coverage(preds: pd.DataFrame, p10_col: str, p90_col: str) -> pd.DataFrame:
    df = preds.copy()
    df["in_band"] = (df["realized"] >= df[p10_col]) & (df["realized"] <= df[p90_col])
    df["abs_err"] = (df["p50"] - df["realized"]).abs()
    return (
        df.groupby("eval_day")
        .agg(coverage=("in_band", "mean"), mae=("abs_err", "mean"))
        .reset_index()
    )


def main():
    summary_rows = []
    per_day_long = []
    OUT.mkdir(parents=True, exist_ok=True)

    for window_days in (28, 56):
        cfg = BacktestConfig(
            parquet_path=PARQUET,
            eval_start=EVAL_START,
            eval_end=EVAL_END,
            window_days=window_days,
        )
        print(f"[matrix] window={window_days}d ...")
        preds = walk_forward_backtest(cfg)
        preds = apply_cqr(preds)
        preds.to_parquet(OUT / f"predictions_{window_days}d.parquet", index=False)

        # Raw bands
        m_raw = compute_metrics(preds, p10_col="p10", p50_col="p50", p90_col="p90")
        m_raw["config"] = f"{window_days}d_raw"
        summary_rows.append(m_raw)
        d_raw = _per_day_coverage(preds, "p10", "p90")
        d_raw["config"] = f"{window_days}d_raw"
        per_day_long.append(d_raw)

        # CQR bands
        m_cqr = compute_metrics(preds, p10_col="p10_cqr", p50_col="p50", p90_col="p90_cqr")
        m_cqr["config"] = f"{window_days}d_cqr"
        # cqr_q stats for visibility
        m_cqr["mean_cqr_q"] = float(preds["cqr_q"].mean())
        m_cqr["nonzero_cqr_days"] = int((preds.groupby("eval_day")["cqr_q"].first() > 0).sum())
        summary_rows.append(m_cqr)
        d_cqr = _per_day_coverage(preds, "p10_cqr", "p90_cqr")
        d_cqr["config"] = f"{window_days}d_cqr"
        per_day_long.append(d_cqr)

    summary = pd.DataFrame(summary_rows)
    cols = [
        "config",
        "n_hours",
        "n_eval_days",
        "mae_overall",
        "mae_low_price_lt30",
        "mae_evening_peak",
        "p80_band_coverage",
        "p80_band_width_mean",
        "n_low_price_hours",
        "n_evening_peak_hours",
        "mean_cqr_q",
        "nonzero_cqr_days",
    ]
    summary = summary.reindex(columns=cols)
    summary.to_csv(OUT / "matrix_summary.csv", index=False, float_format="%.3f")

    per_day = pd.concat(per_day_long, ignore_index=True)
    per_day.to_csv(OUT / "matrix_per_day.csv", index=False, float_format="%.3f")

    print()
    print("=" * 60)
    print("Matrix summary (target P80 coverage in [0.75, 0.85]):")
    print("=" * 60)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
