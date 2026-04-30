"""Walk-forward backtest harness for the EXP-009 LightGBM-Quantile shadow.

For each evaluation day D:
  1. train on a rolling 28-day window ending at D 00:00 UTC,
  2. predict every hour of D using realized lag inputs (next-hour, perfect-lag),
  3. record [P10, P50, P90, realized] per hour.

Single-horizon by design: this measures *model quality given perfect inputs*,
apples-to-apples with River ARF's `update_mae`. Iterated 72-hour-ahead
behaviour is a later milestone and a different question.

CLI:
    python -m ml.shadow.backtest \
        --parquet ml/data/training_history.parquet \
        --start 2026-04-01 --end 2026-04-29 \
        --out ml/shadow/backtest_results
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.features_pandas import build_features
from ml.shadow.lightgbm_quantile import LightGBMQuantileForecaster

DEFAULT_WINDOW_DAYS = 28


@dataclass
class BacktestConfig:
    parquet_path: Path
    eval_start: pd.Timestamp  # inclusive, UTC
    eval_end: pd.Timestamp    # exclusive, UTC
    window_days: int = DEFAULT_WINDOW_DAYS


def _load_parquet(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"Parquet index is not DatetimeIndex: {df.index.dtype}")
    if df.index.tz is None:
        raise ValueError("Parquet index must be tz-aware")
    if str(df.index.tz) != "UTC":
        df = df.tz_convert("UTC")
    return df.sort_index()


def walk_forward_backtest(cfg: BacktestConfig) -> pd.DataFrame:
    """Run the walk-forward backtest. Returns one row per predicted hour."""
    df = _load_parquet(cfg.parquet_path)
    features_all = build_features(df)
    target = df["price_eur_mwh"]

    eval_days = pd.date_range(cfg.eval_start, cfg.eval_end, freq="D", tz="UTC", inclusive="left")

    records: list[dict] = []
    for day_start in eval_days:
        train_end = day_start  # exclusive
        train_start = train_end - pd.Timedelta(days=cfg.window_days)

        train_mask = (features_all.index >= train_start) & (features_all.index < train_end)
        eval_mask = (features_all.index >= day_start) & (features_all.index < day_start + pd.Timedelta(days=1))

        X_train = features_all.loc[train_mask].dropna()
        y_train = target.loc[X_train.index]

        if len(X_train) < 100:
            continue

        X_eval = features_all.loc[eval_mask].dropna()
        if len(X_eval) == 0:
            continue
        y_eval = target.loc[X_eval.index]

        model = LightGBMQuantileForecaster().fit(X_train, y_train)
        preds = model.predict(X_eval)

        for ts, (p10, p50, p90), y in zip(X_eval.index, preds, y_eval.to_numpy()):
            records.append(
                {
                    "timestamp_utc": ts,
                    "eval_day": day_start.date().isoformat(),
                    "realized": float(y),
                    "p10": float(p10),
                    "p50": float(p50),
                    "p90": float(p90),
                    "n_train": int(len(X_train)),
                }
            )

    return pd.DataFrame.from_records(records)


def compute_metrics(
    preds: pd.DataFrame,
    p10_col: str = "p10",
    p50_col: str = "p50",
    p90_col: str = "p90",
) -> dict:
    """Compute the promotion-criteria metrics from the per-hour predictions.

    Column-name args let callers re-evaluate against post-processed bands
    (e.g. p10_cqr / p90_cqr from conformal correction) without copying.
    """
    if len(preds) == 0:
        return {"n_hours": 0}

    realized = preds["realized"].to_numpy()
    p50 = preds[p50_col].to_numpy()
    p10 = preds[p10_col].to_numpy()
    p90 = preds[p90_col].to_numpy()
    abs_err = np.abs(p50 - realized)

    low_mask = realized < 30.0

    ts = pd.to_datetime(preds["timestamp_utc"])
    hour = ts.dt.hour.to_numpy()
    dow = ts.dt.dayofweek.to_numpy()
    peak_mask = (dow < 5) & (hour >= 16) & (hour <= 19)

    in_band = (realized >= p10) & (realized <= p90)

    return {
        "n_hours": int(len(preds)),
        "n_eval_days": int(preds["eval_day"].nunique()),
        "mae_overall": float(abs_err.mean()),
        "mae_low_price_lt30": float(abs_err[low_mask].mean()) if low_mask.any() else None,
        "n_low_price_hours": int(low_mask.sum()),
        "mae_evening_peak": float(abs_err[peak_mask].mean()) if peak_mask.any() else None,
        "n_evening_peak_hours": int(peak_mask.sum()),
        "p80_band_coverage": float(in_band.mean()),
        "p80_band_width_mean": float((p90 - p10).mean()),
    }


def per_day_metrics(preds: pd.DataFrame) -> pd.DataFrame:
    """Per-day MAE for plotting against ARF metrics_history.csv."""
    df = preds.copy()
    df["abs_err"] = np.abs(df["p50"] - df["realized"])
    return (
        df.groupby("eval_day")
        .agg(
            mae=("abs_err", "mean"),
            n_hours=("abs_err", "size"),
            min_realized=("realized", "min"),
            max_realized=("realized", "max"),
        )
        .reset_index()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", default="ml/data/training_history.parquet")
    parser.add_argument("--start", default="2026-04-01", help="UTC eval start (inclusive)")
    parser.add_argument("--end", default="2026-04-29", help="UTC eval end (exclusive)")
    parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    parser.add_argument("--out", default="ml/shadow/backtest_results")
    args = parser.parse_args()

    cfg = BacktestConfig(
        parquet_path=Path(args.parquet),
        eval_start=pd.Timestamp(args.start, tz="UTC"),
        eval_end=pd.Timestamp(args.end, tz="UTC"),
        window_days=args.window_days,
    )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[backtest] {cfg.eval_start.date()} -> {cfg.eval_end.date()}, window={cfg.window_days}d")
    preds = walk_forward_backtest(cfg)
    print(f"[backtest] produced {len(preds)} predictions across {preds['eval_day'].nunique()} days")

    preds.to_parquet(out_dir / "predictions.parquet", index=False)
    per_day_metrics(preds).to_csv(out_dir / "per_day_metrics.csv", index=False)

    summary = compute_metrics(preds)
    summary["config"] = {
        "parquet": str(cfg.parquet_path),
        "eval_start": cfg.eval_start.isoformat(),
        "eval_end": cfg.eval_end.isoformat(),
        "window_days": cfg.window_days,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
