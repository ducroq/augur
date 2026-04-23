"""
Phase-1 warmup harness — TTF gas + NL generation mix A/B experiment.

Functionally identical to ml/training/warmup.py but:
  - Writes to ml/models/river_p1/ by default (prod model untouched).
  - Passes the 5 Phase-1 feature kwargs (TTF, NL gas/wind/solar MW,
    renewable share) through OnlineFeatureBuilder.build().
  - --baseline skips the new kwargs, so a baseline run over the same parquet
    produces a comparable model trained only on the pre-Phase-1 feature set.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
from collections import deque
from pathlib import Path

import numpy as np
import pandas as pd
from river import compose, forest, preprocessing

from ml.features.online_features import OnlineFeatureBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_MODEL_DIR = Path(__file__).parent.parent / "models" / "river_p1"

PHASE1_FEATURE_COLS = (
    "gas_ttf_eur_mwh",
    "gen_nl_fossil_gas_mw",
    "gen_nl_wind_total_mw",
    "gen_nl_solar_mw",
    "gen_nl_renewable_share",
)


def create_model():
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        forest.ARFRegressor(n_models=10, seed=42),
    )


def warmup(data_path: Path, model_dir: Path, baseline: bool = False):
    df = pd.read_parquet(data_path)
    assert df.index.is_monotonic_increasing, "Training data must be sorted"
    logger.info(f"Loaded {len(df)} rows from {data_path}")
    logger.info(f"Range: {df.index.min()} to {df.index.max()}")
    mode = "BASELINE (pre-Phase-1 features only)" if baseline else "PHASE 1 (+TTF, NL genmix)"
    logger.info(f"Mode: {mode}")

    model = create_model()
    fb = OnlineFeatureBuilder()
    errors = deque(maxlen=168)  # ~1 week 15-min ≈ 672; keep 168 for comparability with prod
    all_errors = []
    all_actuals = []
    n_learned = 0
    n_skipped = 0
    daily_log_interval = max(len(df) // 20, 500)

    for ts, row in df.iterrows():
        ts_iso = ts.isoformat()
        price = row["price_eur_mwh"]
        if np.isnan(price):
            n_skipped += 1
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
            n_skipped += 1
            continue

        y_pred = model.predict_one(features)
        model.learn_one(features, price)
        fb.push_price(ts_iso, price)

        signed = price - y_pred
        errors.append(abs(signed))
        all_errors.append(signed)
        all_actuals.append(price)
        n_learned += 1

        if n_learned % daily_log_interval == 0:
            logger.info(
                f"  [{ts_iso[:10]}] learned={n_learned}, "
                f"rolling MAE(168)={np.mean(errors):.2f}"
            )

    overall_mae = np.mean([abs(e) for e in all_errors]) if all_errors else float("nan")
    last_window_mae = np.mean(list(errors)) if errors else float("nan")
    mape_vals = [abs(e / p) * 100 for e, p in zip(all_errors, all_actuals) if abs(p) > 1.0]
    overall_mape = np.mean(mape_vals) if mape_vals else float("nan")

    logger.info("=" * 60)
    logger.info(f"Warmup complete ({mode}):")
    logger.info(f"  learned={n_learned}, skipped={n_skipped}")
    logger.info(f"  overall MAE:        {overall_mae:.2f} EUR/MWh")
    logger.info(f"  last-168 MAE:       {last_window_mae:.2f} EUR/MWh")
    logger.info(f"  overall MAPE:       {overall_mape:.1f}%")
    logger.info("=" * 60)

    model_dir.mkdir(parents=True, exist_ok=True)
    mp = model_dir / "river_model.pkl"
    tmp = mp.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(model, f)
    os.replace(tmp, mp)
    logger.info(f"Model saved to {mp}")

    state = {
        "last_timestamp": df.index.max().isoformat() if len(df) else None,
        "n_samples": n_learned,
        "metrics": {
            "mae": round(overall_mae, 2) if not np.isnan(overall_mae) else None,
            "mape": round(overall_mape, 1) if not np.isnan(overall_mape) else None,
            "last_week_mae": round(last_window_mae, 2) if not np.isnan(last_window_mae) else None,
        },
        "price_buffer": fb.get_price_buffer(),
        "error_history": [round(e, 2) for e in all_errors[-500:]],
    }
    sp = model_dir / "state.json"
    with open(sp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    logger.info(f"State saved to {sp}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True)
    p.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    p.add_argument(
        "--baseline", action="store_true",
        help="Train without the Phase-1 feature kwargs (for A/B baseline).",
    )
    args = p.parse_args()
    warmup(Path(args.data), Path(args.model_dir), baseline=args.baseline)


if __name__ == "__main__":
    main()
