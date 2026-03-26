"""
Daily model update — learn from new data and generate forecast.

This is the main entry point for the daily cron job on sadalsuud:
  1. Load model + state
  2. Parse latest data from energyDataHub
  3. Learn from new actual prices
  4. Generate 24-48h forecast
  5. Save updated model + forecast JSON

Usage:
    python -m ml.update --data-dir /path/to/energyDataHub/data
    python -m ml.update --data-dir /path/to/energyDataHub/data --augur-dir /path/to/augur
"""

import argparse
import json
import logging
import os
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.consolidate import (
    parse_price_file,
    parse_wind_file,
    parse_solar_file,
    parse_weather_file,
    parse_load_file,
    glob_sorted,
    _get_handler,  # ensure decryption keys are loaded
)
from ml.features.online_features import OnlineFeatureBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_DIR = Path(__file__).parent / "models"


def load_model_and_state():
    """Load persisted model and state."""
    model_path = MODEL_DIR / "river_model.pkl"
    state_path = MODEL_DIR / "state.json"

    if not model_path.exists():
        raise FileNotFoundError(f"No model found at {model_path}. Run warmup first.")

    with open(model_path, "rb") as f:
        model = pickle.load(f)

    state = {}
    if state_path.exists():
        with open(state_path) as f:
            state = json.load(f)

    return model, state


def get_latest_data(data_dir: Path):
    """Parse the latest data files from energyDataHub."""
    data = {}

    # Price
    price_files = glob_sorted(data_dir, "*_energy_price_forecast.json")
    if price_files:
        data["prices"] = parse_price_file(price_files[-1])
        logger.info(f"Prices: {len(data['prices'])} points from {price_files[-1].name}")

    # Wind
    wind_files = glob_sorted(data_dir, "*_wind_forecast.json")
    if wind_files:
        data["wind"] = parse_wind_file(wind_files[-1])
        logger.info(f"Wind: {len(data['wind'])} points from {wind_files[-1].name}")

    # Solar
    solar_files = glob_sorted(data_dir, "*_solar_forecast.json")
    if solar_files:
        data["solar"] = parse_solar_file(solar_files[-1])
        logger.info(f"Solar: {len(data['solar'])} points from {solar_files[-1].name}")

    # Weather
    weather_files = glob_sorted(data_dir, "*_weather_forecast_multi_location.json")
    if weather_files:
        data["temperature"] = parse_weather_file(weather_files[-1])
        logger.info(f"Weather: {len(data['temperature'])} points from {weather_files[-1].name}")

    # Load
    load_files = glob_sorted(data_dir, "*_load_forecast.json")
    if load_files:
        data["load"] = parse_load_file(load_files[-1])
        logger.info(f"Load: {len(data['load'])} points from {load_files[-1].name}")

    return data


def update_model(model, state, data):
    """Learn from new actual prices and return updated state."""
    last_ts = state.get("last_timestamp")
    if last_ts:
        last_ts = pd.Timestamp(last_ts)
        if last_ts.tzinfo is None:
            last_ts = last_ts.tz_localize("UTC")

    # Restore feature builder with price buffer
    price_buffer = state.get("price_buffer", [])
    fb = OnlineFeatureBuilder(price_buffer)

    prices = data.get("prices", pd.Series(dtype=float))
    if prices.empty:
        logger.warning("No price data found")
        return model, state, fb

    # Filter to new data only
    if last_ts is not None:
        new_prices = prices[prices.index > last_ts].sort_index()
    else:
        new_prices = prices.sort_index()

    if new_prices.empty:
        logger.info("No new prices since last update")
        return model, state, fb

    logger.info(f"Learning from {len(new_prices)} new price observations")

    # Build aligned exogenous data
    wind = data.get("wind", pd.Series(dtype=float))
    solar = data.get("solar", pd.Series(dtype=float))
    temp = data.get("temperature", pd.Series(dtype=float))
    load = data.get("load", pd.Series(dtype=float))

    # Rolling error history for confidence bands (keep last 500 errors)
    error_history = state.get("error_history", [])

    errors = []
    for ts, price in new_prices.items():
        if np.isnan(price):
            continue

        ts_iso = ts.isoformat()
        features = fb.build(
            ts_iso,
            wind_speed_80m=_nearest(wind, ts),
            solar_ghi=_nearest(solar, ts),
            temperature=_nearest(temp, ts),
            load_forecast=_nearest(load, ts),
        )

        if features is None:
            fb.push_price(ts_iso, price)
            continue

        y_pred = model.predict_one(features)
        model.learn_one(features, price)
        fb.push_price(ts_iso, price)

        err = price - y_pred  # signed error (not abs)
        errors.append(abs(err))
        error_history.append(err)

    # Trim to last 500
    error_history = error_history[-500:]

    # Update state
    n_new = len(errors)
    prev_n = state.get("n_samples", 0)
    mae = np.mean(errors) if errors else None

    state["last_timestamp"] = new_prices.index.max().isoformat()
    state["n_samples"] = prev_n + n_new
    state["price_buffer"] = fb.get_price_buffer()
    state["error_history"] = error_history
    if mae is not None:
        state.setdefault("metrics", {})["update_mae"] = round(mae, 2)

    logger.info(f"Learned {n_new} new samples, MAE: {mae:.2f}" if mae else "No valid samples")

    return model, state, fb


def generate_forecast(model, fb, data, state, hours=48):
    """Generate price forecast with confidence bands for the next N hours."""
    wind = data.get("wind", pd.Series(dtype=float))
    solar = data.get("solar", pd.Series(dtype=float))
    temp = data.get("temperature", pd.Series(dtype=float))
    load = data.get("load", pd.Series(dtype=float))

    # Compute confidence band widths from error history
    error_history = state.get("error_history", [])
    if len(error_history) >= 20:
        abs_errors = sorted(abs(e) for e in error_history)
        # 80% confidence interval: 10th and 90th percentile of absolute errors
        p80 = abs_errors[int(len(abs_errors) * 0.80)]
        p50 = abs_errors[int(len(abs_errors) * 0.50)]
    else:
        p80 = 30.0  # fallback before enough history
        p50 = 15.0

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    forecast = {}
    forecast_upper = {}
    forecast_lower = {}

    for h in range(hours):
        ts = now + timedelta(hours=h)
        ts_utc = ts.replace(tzinfo=timezone.utc)
        ts_iso = ts_utc.isoformat()

        features = fb.build(
            ts_iso,
            wind_speed_80m=_nearest(wind, pd.Timestamp(ts_utc)),
            solar_ghi=_nearest(solar, pd.Timestamp(ts_utc)),
            temperature=_nearest(temp, pd.Timestamp(ts_utc)),
            load_forecast=_nearest(load, pd.Timestamp(ts_utc)),
        )

        if features is None:
            continue

        pred = model.predict_one(features)

        # Widen confidence band for further-out predictions
        # Linear growth: at h=0 use p50, at h=48 use p80
        band_width = p50 + (p80 - p50) * min(h / hours, 1.0)

        forecast[ts_iso] = round(pred, 2)
        forecast_upper[ts_iso] = round(pred + band_width, 2)
        forecast_lower[ts_iso] = round(max(pred - band_width, 0), 2)  # prices can't go far below 0

        # Feed prediction back as price lag for subsequent hours
        fb.push_price(ts_iso, pred)

    logger.info(f"Generated {len(forecast)}-hour forecast (band: ±{p50:.0f} to ±{p80:.0f} EUR/MWh)")
    return forecast, forecast_upper, forecast_lower


def _nearest(series: pd.Series, target_ts: pd.Timestamp, tolerance_hours=3) -> float | None:
    """Find nearest value in a time series within tolerance."""
    if series.empty:
        return None
    if target_ts.tzinfo is None:
        target_ts = target_ts.tz_localize("UTC")
    idx = series.index.get_indexer([target_ts], method="nearest")[0]
    if idx < 0 or idx >= len(series):
        return None
    val = series.iloc[idx]
    ts = series.index[idx]
    if abs((ts - target_ts).total_seconds()) > tolerance_hours * 3600:
        return None
    return float(val) if not np.isnan(val) else None


def save_model_and_state(model, state):
    """Persist model and state with atomic writes."""
    MODEL_DIR.mkdir(parents=True, exist_ok=True)

    model_path = MODEL_DIR / "river_model.pkl"
    tmp = model_path.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(model, f)
    os.replace(tmp, model_path)

    state_path = MODEL_DIR / "state.json"
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2, default=str)

    logger.info(f"Model and state saved to {MODEL_DIR}")


def write_forecast_json(forecast, forecast_upper, forecast_lower, state, output_dir: Path):
    """Write forecast JSON with confidence bands for the dashboard."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "augur_forecast.json"

    output = {
        "metadata": {
            "model": "HoeffdingAdaptiveTreeRegressor",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "n_training_samples": state.get("n_samples", 0),
            "metrics": state.get("metrics", {}),
        },
        "forecast": forecast,
        "forecast_upper": forecast_upper,
        "forecast_lower": forecast_lower,
    }

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Forecast written to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Daily Augur model update")
    parser.add_argument("--data-dir", required=True, help="energyDataHub data/ directory")
    parser.add_argument("--augur-dir", default=".", help="Augur repo root (default: current dir)")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    augur_dir = Path(args.augur_dir)

    logger.info("=" * 60)
    logger.info("Augur Daily Model Update")
    logger.info("=" * 60)

    # Load model
    model, state = load_model_and_state()
    logger.info(f"Model loaded: {state.get('n_samples', 0)} samples trained")

    # Get latest data
    data = get_latest_data(data_dir)

    # Update model with new observations
    model, state, fb = update_model(model, state, data)

    # Generate forecast with confidence bands
    forecast, forecast_upper, forecast_lower = generate_forecast(model, fb, data, state)

    # Save everything
    save_model_and_state(model, state)
    write_forecast_json(forecast, forecast_upper, forecast_lower, state, augur_dir / "static" / "data")

    logger.info("=" * 60)
    logger.info("Update complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
