"""
Replay a held-out period through a trained River model as predict+learn,
recording per-sample errors for comparison against the production baseline.

Usage:
    python -m ml.evaluation.backtest \
        --model ml/models/river_v2/river_model.pkl \
        --state ml/models/river_v2/state.json \
        --data ml/data/historical_holdout.parquet \
        --out ml/models/river_v2/backtest_report.json
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from ml.features.online_features import OnlineFeatureBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def backtest(model_path: Path, state_path: Path, data_path: Path) -> dict:
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    state = json.load(open(state_path))
    fb = OnlineFeatureBuilder(state.get("price_buffer"))

    df = pd.read_parquet(data_path).sort_index()
    logger.info(f"Backtest {len(df)} samples: {df.index.min()} to {df.index.max()}")

    preds, actuals = [], []
    for ts, row in df.iterrows():
        ts_iso = ts.isoformat()
        price = row["price_eur_mwh"]
        if np.isnan(price):
            continue
        features = fb.build(
            ts_iso,
            wind_speed_80m=row.get("wind_speed_80m"),
            solar_ghi=row.get("solar_ghi"),
            load_forecast=row.get("load_forecast"),
        )
        if features is None:
            fb.push_price(ts_iso, price)
            continue
        y_pred = model.predict_one(features)
        model.learn_one(features, price)
        fb.push_price(ts_iso, price)
        preds.append(y_pred)
        actuals.append(price)

    preds = np.array(preds)
    actuals = np.array(actuals)
    signed = actuals - preds
    mae = np.mean(np.abs(signed))
    mape = np.mean(np.abs(signed) / np.where(np.abs(actuals) > 1, np.abs(actuals), 1)) * 100
    rmse = np.sqrt(np.mean(signed ** 2))
    spike_mask = actuals > 150
    if spike_mask.sum() > 0:
        spike_rel_err = np.abs(signed[spike_mask]) / actuals[spike_mask]
        spike_recall = float(np.mean(spike_rel_err < 0.30))
    else:
        spike_recall = None

    report = {
        "n_samples": int(len(preds)),
        "span": [str(df.index.min()), str(df.index.max())],
        "mae": round(float(mae), 2),
        "mape": round(float(mape), 1),
        "rmse": round(float(rmse), 2),
        "spike_n": int(spike_mask.sum()),
        "spike_recall_30pct": round(spike_recall, 3) if spike_recall is not None else None,
    }
    logger.info("=" * 60)
    logger.info(f"Backtest summary:")
    for k, v in report.items():
        logger.info(f"  {k}: {v}")
    logger.info("=" * 60)
    return report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", required=True)
    p.add_argument("--state", required=True)
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    r = backtest(Path(args.model), Path(args.state), Path(args.data))
    Path(args.out).write_text(json.dumps(r, indent=2))
    logger.info(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
