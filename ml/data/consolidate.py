"""
Consolidate energyDataHub historical data into a single training dataset.

Reads timestamped JSON files from energyDataHub's data/ directory,
extracts relevant features, aligns on hourly UTC timestamps,
and outputs a parquet file for model training.

Usage:
    python -m ml.data.consolidate --data-dir /path/to/energyDataHub/data
"""

import argparse
import base64
import json
import logging
import os
from pathlib import Path
from datetime import datetime

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DEFAULT = Path(__file__).parent / "training_history.parquet"

# Lazy-loaded decryption handler
_handler = None


def _get_handler():
    """Get or create SecureDataHandler from environment variables."""
    global _handler
    if _handler is not None:
        return _handler

    from utils.secure_data_handler import SecureDataHandler

    enc_key = os.environ.get("ENCRYPTION_KEY_B64")
    hmac_key = os.environ.get("HMAC_KEY_B64")
    if not enc_key or not hmac_key:
        raise RuntimeError(
            "ENCRYPTION_KEY_B64 and HMAC_KEY_B64 must be set. "
            "Source your .env file: export $(cat .env | xargs)"
        )
    _handler = SecureDataHandler(
        base64.b64decode(enc_key),
        base64.b64decode(hmac_key),
    )
    return _handler


def load_json_file(path: Path) -> dict:
    """Load a JSON file, decrypting if necessary."""
    with open(path) as f:
        raw = f.read().strip()

    # Try plain JSON first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # Must be encrypted — decrypt
    handler = _get_handler()
    return handler.decrypt_and_verify(raw)


def resolve_weather_value(val):
    """Unwrap nested weather values like {degrees: N}."""
    if isinstance(val, (int, float)):
        return val
    if isinstance(val, dict):
        for key in ("degrees", "distance", "percent", "meanSeaLevelMillibars"):
            if key in val and isinstance(val[key], (int, float)):
                return val[key]
    return None


def parse_price_file(path: Path) -> pd.Series:
    """Extract ENTSO-E NL hourly prices from an energy_price_forecast file."""
    data = load_json_file(path)

    # Merge all wholesale sources: entsoe preferred, then fill gaps from others
    merged = {}
    for source_key in ("energy_zero", "elspot", "epex", "entsoe"):
        # Process in reverse priority so entsoe overwrites others
        source = data.get(source_key)
        if not source or not isinstance(source, dict) or "data" not in source:
            continue
        ts_data = source["data"]
        if not isinstance(ts_data, dict):
            continue
        units = source.get("metadata", {}).get("units", "EUR/MWh")
        multiplier = 1000 if "kwh" in units.lower() else 1
        for ts_str, price in ts_data.items():
            if not isinstance(price, (int, float)):
                continue
            ts_str = ts_str.replace("+00:18", "+01:00").replace("+00:09", "+01:00")
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                merged[ts] = price * multiplier
            except Exception:
                continue
    if merged:
        return pd.Series(merged, name="price_eur_mwh")
    return pd.Series(dtype=float, name="price_eur_mwh")


def parse_wind_file(path: Path) -> pd.Series:
    """Extract NL offshore wind speed (80m) from a wind_forecast file."""
    data = load_json_file(path)

    offshore = data.get("offshore_wind", {})
    if not isinstance(offshore, dict) or "data" not in offshore:
        return pd.Series(dtype=float, name="wind_speed_80m")

    # Find first NL location
    nl_key = next((k for k in offshore["data"] if "NL" in k), None)
    if not nl_key:
        return pd.Series(dtype=float, name="wind_speed_80m")

    series = {}
    for ts_str, fields in offshore["data"][nl_key].items():
        if isinstance(fields, dict) and isinstance(fields.get("wind_speed_80m"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["wind_speed_80m"]
            except Exception:
                continue
    return pd.Series(series, name="wind_speed_80m")


def parse_solar_file(path: Path) -> pd.Series:
    """Extract NL solar GHI from a solar_forecast file."""
    data = load_json_file(path)

    solar_data = data.get("data", {})
    nl_key = next((k for k in solar_data if "NL" in k), None)
    if not nl_key:
        return pd.Series(dtype=float, name="solar_ghi")

    series = {}
    for ts_str, fields in solar_data[nl_key].items():
        if isinstance(fields, dict) and isinstance(fields.get("ghi"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["ghi"]
            except Exception:
                continue
    return pd.Series(series, name="solar_ghi")


def parse_weather_file(path: Path) -> pd.Series:
    """Extract NL temperature from a weather_forecast file."""
    data = load_json_file(path)

    weather_data = data.get("data", {})
    nl_key = next((k for k in weather_data if "NL" in k), None)
    if not nl_key:
        return pd.Series(dtype=float, name="temperature")

    series = {}
    for ts_str, fields in weather_data[nl_key].items():
        if isinstance(fields, dict) and "temperature" in fields:
            temp = resolve_weather_value(fields["temperature"])
            if temp is not None:
                try:
                    ts = pd.Timestamp(ts_str).tz_convert("UTC")
                    series[ts] = temp
                except Exception:
                    continue
    return pd.Series(series, name="temperature")


def parse_load_file(path: Path) -> pd.Series:
    """Extract NL load forecast from a load_forecast file."""
    data = load_json_file(path)

    load_data = data.get("data", {})
    nl_data = load_data.get("NL", {})

    series = {}
    for ts_str, fields in nl_data.items():
        if isinstance(fields, dict) and isinstance(fields.get("load_forecast"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["load_forecast"]
            except Exception:
                continue
    return pd.Series(series, name="load_forecast")


def glob_sorted(data_dir: Path, pattern: str) -> list[Path]:
    """Find files matching pattern, sorted by filename (timestamp order)."""
    return sorted(data_dir.glob(pattern))


def consolidate(data_dir: Path, output: Path):
    """Build consolidated training dataset from energyDataHub historical files."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    parsers = {
        "price_eur_mwh": ("*_energy_price_forecast.json", parse_price_file),
        "wind_speed_80m": ("*_wind_forecast.json", parse_wind_file),
        "solar_ghi": ("*_solar_forecast.json", parse_solar_file),
        "temperature": ("*_weather_forecast_multi_location.json", parse_weather_file),
        "load_forecast": ("*_load_forecast.json", parse_load_file),
    }

    all_series = {}
    for col_name, (pattern, parser) in parsers.items():
        files = glob_sorted(data_dir, pattern)
        logger.info(f"{col_name}: found {len(files)} files")

        combined = {}
        for f in files:
            try:
                s = parser(f)
                for ts, val in s.items():
                    combined[ts] = val  # Later files overwrite earlier ones
            except Exception as e:
                logger.warning(f"  Failed to parse {f.name}: {e}")

        all_series[col_name] = pd.Series(combined, name=col_name)
        logger.info(f"  {col_name}: {len(combined)} data points")

    # Combine into DataFrame
    df = pd.DataFrame(all_series)
    df.index.name = "timestamp_utc"
    df = df.sort_index()

    # Resample to hourly (take mean if sub-hourly)
    df = df.resample("h").mean()

    # Forward-fill slow-changing features (max 6 hours)
    for col in ["temperature", "load_forecast", "wind_speed_80m", "solar_ghi"]:
        if col in df.columns:
            df[col] = df[col].ffill(limit=6)

    # Drop rows with no price (target)
    before = len(df)
    df = df.dropna(subset=["price_eur_mwh"])
    logger.info(f"Dropped {before - len(df)} rows without price data")

    # Save
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output)

    # Summary
    logger.info(f"\nDataset saved to {output}")
    logger.info(f"Date range: {df.index.min()} to {df.index.max()}")
    logger.info(f"Total rows: {len(df)}")
    logger.info(f"Columns: {list(df.columns)}")
    logger.info(f"NaN percentages:")
    for col in df.columns:
        pct = df[col].isna().mean() * 100
        logger.info(f"  {col}: {pct:.1f}%")


def main():
    parser = argparse.ArgumentParser(description="Consolidate energyDataHub data for ML training")
    parser.add_argument("--data-dir", required=True, help="Path to energyDataHub data/ directory")
    parser.add_argument("--output", default=str(OUTPUT_DEFAULT), help="Output parquet path")
    args = parser.parse_args()
    consolidate(args.data_dir, args.output)


if __name__ == "__main__":
    main()
