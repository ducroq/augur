"""
Warm up a River online learning model by replaying historical data.

Loads the consolidated parquet, replays all rows through the model
via predict_one/learn_one, and saves the trained model.

Usage:
    python -m ml.training.warmup --data ml/data/training_history.parquet
"""

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

MODEL_DIR = Path(__file__).parent.parent / "models"


def create_model():
    """Create the River online learning pipeline."""
    return compose.Pipeline(
        preprocessing.StandardScaler(),
        forest.ARFRegressor(n_models=10, seed=42),
    )


def warmup(data_path: Path):
    """Replay historical data through River model."""
    df = pd.read_parquet(data_path)
    logger.info(f"Loaded {len(df)} rows from {data_path}")
    logger.info(f"Date range: {df.index.min()} to {df.index.max()}")

    model = create_model()
    fb = OnlineFeatureBuilder()

    errors = deque(maxlen=168)  # Rolling 1-week MAE window
    n_learned = 0
    n_skipped = 0
    all_errors = []

    for ts, row in df.iterrows():
        ts_iso = ts.isoformat()
        price = row["price_eur_mwh"]

        if np.isnan(price):
            n_skipped += 1
            continue

        # Build features
        features = fb.build(
            ts_iso,
            wind_speed_80m=row.get("wind_speed_80m"),
            solar_ghi=row.get("solar_ghi"),
            load_forecast=row.get("load_forecast"),
        )

        if features is None:
            # Not enough price history for lags yet
            fb.push_price(ts_iso, price)
            n_skipped += 1
            continue

        # Predict then learn
        y_pred = model.predict_one(features)
        model.learn_one(features, price)
        fb.push_price(ts_iso, price)

        signed_error = price - y_pred
        error = abs(signed_error)
        errors.append(error)
        all_errors.append(signed_error)
        n_learned += 1

        # Log progress every 500 rows
        if n_learned % 500 == 0:
            rolling_mae = np.mean(errors)
            logger.info(
                f"  [{ts_iso[:10]}] learned={n_learned}, "
                f"rolling MAE={rolling_mae:.2f} EUR/MWh"
            )

    # Final metrics
    if all_errors:
        overall_mae = np.mean([abs(e) for e in all_errors])
        last_week_mae = np.mean(list(errors))
        # MAPE (avoid division by zero)
        prices = df["price_eur_mwh"].dropna().values[-len(all_errors):]
        mape_vals = [abs(e / p) * 100 for e, p in zip([abs(x) for x in all_errors], prices) if abs(p) > 1.0]
        overall_mape = np.mean(mape_vals) if mape_vals else float("nan")

        logger.info(f"\n{'='*60}")
        logger.info(f"Warmup complete:")
        logger.info(f"  Rows learned: {n_learned}")
        logger.info(f"  Rows skipped: {n_skipped}")
        logger.info(f"  Overall MAE:  {overall_mae:.2f} EUR/MWh")
        logger.info(f"  Last-week MAE: {last_week_mae:.2f} EUR/MWh")
        logger.info(f"  Overall MAPE: {overall_mape:.1f}%")
        logger.info(f"{'='*60}")
    else:
        logger.warning("No rows were learned — check data quality")
        overall_mae = float("nan")
        overall_mape = float("nan")
        last_week_mae = float("nan")

    # Save model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / "river_model.pkl"
    tmp_path = model_path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        pickle.dump(model, f)
    os.replace(tmp_path, model_path)
    logger.info(f"Model saved to {model_path}")

    # Save state
    state = {
        "last_timestamp": df.index.max().isoformat() if len(df) > 0 else None,
        "n_samples": n_learned,
        "metrics": {
            "mae": round(overall_mae, 2) if not np.isnan(overall_mae) else None,
            "mape": round(overall_mape, 1) if not np.isnan(overall_mape) else None,
            "last_week_mae": round(last_week_mae, 2) if not np.isnan(last_week_mae) else None,
        },
        "price_buffer": fb.get_price_buffer(),
        "error_history": [round(e, 2) for e in all_errors[-500:]],
    }
    state_path = MODEL_DIR / "state.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)
    logger.info(f"State saved to {state_path}")


def main():
    parser = argparse.ArgumentParser(description="Warm up River model on historical data")
    parser.add_argument("--data", default="ml/data/training_history.parquet", help="Training data path")
    args = parser.parse_args()
    warmup(Path(args.data))


if __name__ == "__main__":
    main()
