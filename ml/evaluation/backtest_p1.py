"""
Phase-1 backtest harness.

Replays a held-out period through a trained River model as predict+learn,
computing MAE / MAPE / RMSE / spike-recall. Pair a baseline and a Phase-1
model trained on the same parquet and holdout — the MAE gap decides the
>=2 EUR/MWh gate from ADR-005.

--baseline must match the flag used at warmup time so the feature dict
shape stays consistent between training and backtest.

Usage:
    python -m ml.evaluation.backtest_p1 \
        --model ml/models/river_p1/river_model.pkl \
        --state ml/models/river_p1/state.json \
        --data  ml/data/holdout_p1.parquet \
        --out   ml/models/river_p1/backtest_report.json
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

PHASE1_FEATURE_COLS = (
    "gas_ttf_eur_mwh",
    "gen_nl_fossil_gas_mw",
    "gen_nl_wind_total_mw",
    "gen_nl_solar_mw",
    "gen_nl_renewable_share",
)


def backtest(
    model_path: Path,
    state_path: Path,
    data_path: Path,
    baseline: bool = False,
    from_ts: str | None = None,
) -> dict:
    with open(model_path, "rb") as f:
        model = pickle.load(f)
    state = json.load(open(state_path))
    fb = OnlineFeatureBuilder(state.get("price_buffer"))

    df = pd.read_parquet(data_path).sort_index()
    if from_ts:
        cutoff = pd.Timestamp(from_ts, tz="UTC")
        df = df[df.index >= cutoff]
        logger.info(f"Trimmed to rows from {cutoff}")
    mode = "BASELINE" if baseline else "PHASE 1"
    logger.info(f"Backtest {len(df)} samples: {df.index.min()} to {df.index.max()} ({mode})")

    preds, actuals = [], []
    for ts, row in df.iterrows():
        ts_iso = ts.isoformat()
        price = row["price_eur_mwh"]
        if np.isnan(price):
            continue
        build_kwargs = dict(
            wind_speed_80m=row.get("wind_speed_80m"),
            solar_ghi=row.get("solar_ghi"),
            load_forecast=row.get("load_forecast"),
        )
        if not baseline:
            for col in PHASE1_FEATURE_COLS:
                if col in df.columns:
                    build_kwargs[col] = row[col]
        features = fb.build(ts_iso, **build_kwargs)
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
    p.add_argument(
        "--baseline", action="store_true",
        help="Skip Phase-1 feature kwargs; must match the flag used at warmup.",
    )
    p.add_argument(
        "--from-ts", default=None,
        help="Only backtest rows with timestamp >= this (ISO UTC). Match --until-ts in warmup_p1.",
    )
    args = p.parse_args()
    r = backtest(
        Path(args.model), Path(args.state), Path(args.data),
        baseline=args.baseline, from_ts=args.from_ts,
    )
    Path(args.out).write_text(json.dumps(r, indent=2))
    logger.info(f"Report written to {args.out}")


if __name__ == "__main__":
    main()
