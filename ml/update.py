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
import math
import os
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml.data.consolidate import (
    parse_price_file,
    parse_energy_zero_consumer,
    parse_entsoe_wholesale,
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
VAT_RATE = 1.21
# Fallback surcharge (EUR/MWh incl. VAT) when no EZ/ENTSO-E overlap is available.
# Based on typical NL energy tax + ODE + transport costs. Updated 2026-03.
DEFAULT_SURCHARGE_EUR_MWH = 95.0


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
    load = data.get("load", pd.Series(dtype=float))

    # Rolling error history for confidence bands (keep last 500 errors)
    error_history = state.get("error_history", [])
    error_hours = state.get("error_hours", [])

    errors = []
    for ts, price in new_prices.items():
        if np.isnan(price):
            continue

        ts_iso = ts.isoformat()
        features = fb.build(
            ts_iso,
            wind_speed_80m=_nearest(wind, ts),
            solar_ghi=_nearest(solar, ts),
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
        error_hours.append(ts.hour)

    # Trim to last 500 (parallel arrays — must stay aligned)
    error_history = error_history[-500:]
    error_hours = error_hours[-500:]

    # Update state
    n_new = len(errors)
    prev_n = state.get("n_samples", 0)
    mae = np.mean(errors) if errors else None

    state["last_timestamp"] = new_prices.index.max().isoformat()
    state["n_samples"] = prev_n + n_new
    state["price_buffer"] = fb.get_price_buffer()
    state["error_history"] = error_history
    state["error_hours"] = error_hours

    if mae is not None:
        state.setdefault("metrics", {})["update_mae"] = round(mae, 2)

    # Append to metrics history (one entry per daily update, cap at 365 days)
    if mae is not None:
        history_entry = {
            "date": new_prices.index.max().strftime("%Y-%m-%d"),
            "update_mae": round(mae, 2),
            "mae": round(state["metrics"].get("mae", mae), 2),
            "last_week_mae": round(state["metrics"].get("last_week_mae", mae), 2),
            "n_samples": prev_n + n_new,
            "mae_vs_exchange": None,  # backfilled in main() if exchange data available
        }
        metrics_history = state.get("metrics_history", [])
        metrics_history.append(history_entry)
        state["metrics_history"] = metrics_history[-365:]

    logger.info(f"Learned {n_new} new samples, MAE: {mae:.2f}" if mae else "No valid samples")

    return model, state, fb


def generate_forecast(model, fb, data, state, hours=72):
    """Generate price forecast with confidence bands for the next N hours.

    Uses known exchange day-ahead prices as lag features where available,
    falling back to recursive ML predictions beyond the exchange horizon.
    """
    prices = data.get("prices", pd.Series(dtype=float))
    wind = data.get("wind", pd.Series(dtype=float))
    solar = data.get("solar", pd.Series(dtype=float))
    load = data.get("load", pd.Series(dtype=float))

    # Confidence bands from exponentially-weighted error stats
    # Half-life 24 samples (~1 day) — recent errors dominate
    error_history = state.get("error_history", [])
    MIN_BAND = 8.0  # EUR/MWh floor

    if len(error_history) >= 2:
        alpha = 1 - math.exp(-math.log(2) / 24)
        ewm_abs = abs(error_history[0])
        ewm_mean = error_history[0]
        ewm_sq = error_history[0] ** 2
        for e in error_history[1:]:
            ewm_abs = alpha * abs(e) + (1 - alpha) * ewm_abs
            ewm_mean = alpha * e + (1 - alpha) * ewm_mean
            ewm_sq = alpha * e ** 2 + (1 - alpha) * ewm_sq
        ewm_std = max(0.0, ewm_sq - ewm_mean ** 2) ** 0.5
    else:
        ewm_abs = 30.0
        ewm_std = 15.0

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    # Feed known exchange prices into the feature builder first
    # This gives the ML model real lag values instead of recursive predictions
    n_exchange = 0
    if not prices.empty:
        future_prices = prices[prices.index > now].sort_index()
        for ts, price in future_prices.items():
            if not np.isnan(price):
                fb.push_price(ts.isoformat(), price)
                n_exchange += 1

    if n_exchange > 0:
        logger.info(f"Fed {n_exchange} known exchange prices as lag features")

    forecast = {}
    forecast_upper = {}
    forecast_lower = {}
    n_ml_only = 0

    for h in range(hours):
        ts = now + timedelta(hours=h)
        ts_utc = ts.replace(tzinfo=timezone.utc)
        ts_iso = ts_utc.isoformat()

        # Check if we have a known exchange price for this hour
        exchange_price = _nearest(prices, pd.Timestamp(ts_utc), tolerance_hours=0.6)

        features = fb.build(
            ts_iso,
            wind_speed_80m=_nearest(wind, pd.Timestamp(ts_utc)),
            solar_ghi=_nearest(solar, pd.Timestamp(ts_utc)),
            load_forecast=_nearest(load, pd.Timestamp(ts_utc)),
        )

        if features is None:
            continue

        pred = model.predict_one(features)

        # Current price volatility (already computed by feature builder)
        vol_6h = features.get("price_rolling_std_6h", 0.0)
        vol_scale = max(1.0, min(vol_6h / max(ewm_abs, 1.0), 5.0))

        # Narrow band where exchange price is known, wide beyond exchange horizon
        if exchange_price is not None:
            band_width = ewm_abs * 0.5 * vol_scale
        else:
            horizon_factor = 1.0 + (ewm_std / max(ewm_abs, 1.0)) * min(h / hours, 1.0)
            band_width = ewm_abs * horizon_factor * vol_scale
            n_ml_only += 1

        band_width = max(band_width, MIN_BAND)

        forecast[ts_iso] = round(pred, 2)
        forecast_upper[ts_iso] = round(pred + band_width, 2)
        forecast_lower[ts_iso] = round(max(pred - band_width, 0), 2)

        # Only push ML predictions as lags — exchange prices were pre-loaded above
        if exchange_price is None:
            fb.push_price(ts_iso, pred)

    logger.info(
        f"Generated {len(forecast)}-hour forecast: "
        f"{len(forecast) - n_ml_only} hours with exchange lags, "
        f"{n_ml_only} hours ML-only "
        f"(ewm_abs={ewm_abs:.1f}, ewm_std={ewm_std:.1f}, "
        f"min_band={MIN_BAND} EUR/MWh)"
    )
    return forecast, forecast_upper, forecast_lower


def _nearest(series: pd.Series, target_ts: pd.Timestamp, tolerance_hours=3) -> float | None:
    """Find nearest value in a time series within tolerance."""
    if series.empty:
        return None
    if target_ts.tzinfo is None:
        target_ts = target_ts.tz_localize("UTC")
    if not series.index.is_monotonic_increasing:
        series = series.sort_index()
    idx = series.index.get_indexer([target_ts], method="nearest")[0]
    if idx < 0 or idx >= len(series):
        return None
    val = series.iloc[idx]
    ts = series.index[idx]
    if abs((ts - target_ts).total_seconds()) > tolerance_hours * 3600:
        return None
    return float(val) if not np.isnan(val) else None


def derive_surcharge(data_dir: Path, state: dict) -> float:
    """Derive consumer surcharge (incl. VAT, EUR/MWh) from overlapping EZ/ENTSO-E data.

    surcharge = median(ez_consumer - entsoe_wholesale * VAT_RATE)

    Tries up to 5 most recent price files, falls back to last known surcharge
    from state, then to DEFAULT_SURCHARGE_EUR_MWH.
    """
    price_files = glob_sorted(data_dir, "*_energy_price_forecast.json")
    if not price_files:
        fallback = state.get("consumer_surcharge", {}).get("value_eur_mwh", DEFAULT_SURCHARGE_EUR_MWH)
        logger.info(f"Surcharge: no price files, using fallback {fallback:.2f}")
        return fallback

    # Try recent files (newest first) — the latest may have missing sources
    for pf in reversed(price_files[-5:]):
        ez = parse_energy_zero_consumer(pf)
        ws = parse_entsoe_wholesale(pf)

        if ez.empty or ws.empty:
            continue

        ez_hourly = ez.resample("h").mean().dropna()
        ws_hourly = ws.resample("h").mean().dropna()

        overlap_idx = ez_hourly.index.intersection(ws_hourly.index)
        if len(overlap_idx) < 3:
            continue

        surcharges = ez_hourly[overlap_idx] - ws_hourly[overlap_idx] * VAT_RATE
        surcharge = float(np.median(surcharges))

        logger.info(
            f"Surcharge derived: {surcharge:.2f} EUR/MWh (incl. VAT) "
            f"from {len(overlap_idx)} overlapping hours in {pf.name}, "
            f"range [{surcharges.min():.2f}, {surcharges.max():.2f}]"
        )
        return surcharge

    fallback = state.get("consumer_surcharge", {}).get("value_eur_mwh", DEFAULT_SURCHARGE_EUR_MWH)
    logger.warning(f"Surcharge: no usable EZ/ENTSO-E overlap in recent files, using fallback {fallback:.2f}")
    return fallback


def generate_consumer_forecast(forecast, forecast_upper, forecast_lower, surcharge):
    """Transform wholesale forecast into consumer forecast (incl. VAT + surcharges)."""
    consumer = {}
    consumer_upper = {}
    consumer_lower = {}

    for ts, price in forecast.items():
        consumer[ts] = round(price * VAT_RATE + surcharge, 2)
    for ts, price in forecast_upper.items():
        consumer_upper[ts] = round(price * VAT_RATE + surcharge, 2)
    for ts, price in forecast_lower.items():
        consumer_lower[ts] = round(max(price * VAT_RATE + surcharge, 0), 2)

    return consumer, consumer_upper, consumer_lower


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


def compute_exchange_comparison(forecast, data):
    """Compare ML forecast with known exchange prices where they overlap."""
    prices = data.get("prices", pd.Series(dtype=float))
    if prices.empty:
        return None

    errors = []
    for ts_iso, pred in forecast.items():
        ts = pd.Timestamp(ts_iso)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        exchange = _nearest(prices, ts, tolerance_hours=0.6)
        if exchange is not None:
            errors.append(abs(pred - exchange))

    if not errors:
        return None

    return {
        "n_overlap_hours": len(errors),
        "mae_vs_exchange": round(np.mean(errors), 2),
    }


def write_forecast_json(forecast, forecast_upper, forecast_lower, state, output_dir: Path,
                        exchange_comparison=None, consumer_forecast=None,
                        consumer_upper=None, consumer_lower=None):
    """Write forecast JSON with confidence bands for the dashboard."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "augur_forecast.json"

    metrics = state.get("metrics", {})
    if exchange_comparison:
        metrics["vs_exchange"] = exchange_comparison

    output = {
        "metadata": {
            "model": "ARFRegressor",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "n_training_samples": state.get("n_samples", 0),
            "metrics": metrics,
            "metrics_history": state.get("metrics_history", []),
            "error_history": state.get("error_history", []),
            "error_hours": state.get("error_hours", []),
        },
        "forecast": forecast,
        "forecast_upper": forecast_upper,
        "forecast_lower": forecast_lower,
    }

    if consumer_forecast:
        output["consumer_forecast"] = consumer_forecast
        output["consumer_forecast_upper"] = consumer_upper
        output["consumer_forecast_lower"] = consumer_lower

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    # Save timestamped archive copy for backtesting
    archive_dir = output_dir.parent / "ml" / "forecasts"
    archive_dir.mkdir(parents=True, exist_ok=True)
    datestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    archive_path = archive_dir / f"{datestamp}_forecast.json"
    with open(archive_path, "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Forecast written to {output_path}")
    logger.info(f"Archived to {archive_path}")


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

    # Compare forecast with exchange prices where they overlap
    exchange_comparison = compute_exchange_comparison(forecast, data)
    if exchange_comparison:
        logger.info(
            f"Forecast vs exchange: MAE {exchange_comparison['mae_vs_exchange']:.1f} EUR/MWh "
            f"over {exchange_comparison['n_overlap_hours']} hours"
        )
        # Backfill mae_vs_exchange into the latest metrics_history entry
        if state.get("metrics_history"):
            state["metrics_history"][-1]["mae_vs_exchange"] = exchange_comparison["mae_vs_exchange"]

    # Derive consumer surcharge and generate consumer forecast
    surcharge = derive_surcharge(data_dir, state)
    consumer_forecast, consumer_upper, consumer_lower = generate_consumer_forecast(
        forecast, forecast_upper, forecast_lower, surcharge
    )
    state["consumer_surcharge"] = {
        "value_eur_mwh": round(surcharge, 2),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Consumer forecast generated with surcharge {surcharge:.2f} EUR/MWh")

    # Save everything
    save_model_and_state(model, state)
    write_forecast_json(
        forecast, forecast_upper, forecast_lower, state,
        augur_dir / "static" / "data", exchange_comparison,
        consumer_forecast=consumer_forecast,
        consumer_upper=consumer_upper,
        consumer_lower=consumer_lower,
    )

    logger.info("=" * 60)
    logger.info("Update complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
