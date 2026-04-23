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
    """Extract ENTSO-E NL hourly prices from an energy_price_forecast file.

    Returns wholesale prices only.  When ENTSO-E data is missing, logs a
    warning — Energy Zero consumer prices are NOT used as a substitute
    because they include VAT/surcharges and would corrupt the training target.
    """
    data = load_json_file(path)

    entsoe_source = data.get("entsoe")
    has_entsoe = (
        entsoe_source
        and isinstance(entsoe_source, dict)
        and "data" in entsoe_source
        and entsoe_source["data"]
    )
    if not has_entsoe:
        logger.warning(
            "ENTSO-E data missing in %s — skipping Energy Zero to avoid "
            "consumer/wholesale price contamination", path.name
        )

    # Merge wholesale sources only: entsoe preferred, then fill gaps from elspot/epex
    # Energy Zero is EXCLUDED — it's a consumer price (incl. VAT + surcharges)
    merged = {}
    for source_key in ("elspot", "epex", "entsoe"):
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


def _parse_single_source(path: Path, source_key: str, name: str) -> pd.Series:
    """Extract a single price source from an energy_price_forecast file."""
    data = load_json_file(path)
    source = data.get(source_key)
    if not source or not isinstance(source, dict) or "data" not in source:
        return pd.Series(dtype=float, name=name)
    ts_data = source["data"]
    if not isinstance(ts_data, dict):
        return pd.Series(dtype=float, name=name)
    units = source.get("metadata", {}).get("units", "EUR/MWh")
    multiplier = 1000 if "kwh" in units.lower() else 1
    series = {}
    for ts_str, price in ts_data.items():
        if not isinstance(price, (int, float)):
            continue
        ts_str = ts_str.replace("+00:18", "+01:00").replace("+00:09", "+01:00")
        try:
            ts = pd.Timestamp(ts_str).tz_convert("UTC")
            series[ts] = price * multiplier
        except Exception:
            continue
    if series:
        return pd.Series(series, name=name)
    return pd.Series(dtype=float, name=name)


def parse_energy_zero_consumer(path: Path) -> pd.Series:
    """Extract Energy Zero consumer prices (EUR/MWh incl. VAT) from a price file."""
    return _parse_single_source(path, "energy_zero", "ez_consumer_eur_mwh")


def parse_entsoe_wholesale(path: Path) -> pd.Series:
    """Extract ENTSO-E wholesale prices (EUR/MWh excl. VAT) from a price file."""
    return _parse_single_source(path, "entsoe", "entsoe_wholesale_eur_mwh")


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


def parse_market_history_file(path: Path) -> dict[str, pd.Series]:
    """Extract daily TTF gas closing prices from the market_history accumulator.

    TTF is yfinance daily closes keyed by "YYYY-MM-DD". Anchor each close to
    00:00 UTC of the *following* day — avoids leakage (close isn't knowable
    until after market close ~17:30 CET) and matches what the live pipeline
    sees at inference time on day D+1 morning.
    """
    data = load_json_file(path)
    container = data.get("data", data) if isinstance(data, dict) else {}
    gas_ttf = container.get("gas_ttf", {}) if isinstance(container, dict) else {}
    ttf_data = gas_ttf.get("data", {}) if isinstance(gas_ttf, dict) else {}

    series = {}
    for date_str, price in ttf_data.items():
        if not isinstance(price, (int, float)):
            continue
        try:
            ts = (pd.Timestamp(date_str) + pd.Timedelta(days=1)).tz_localize("UTC")
            series[ts] = float(price)
        except Exception:
            continue
    return {"gas_ttf_eur_mwh": pd.Series(series, name="gas_ttf_eur_mwh")}


def parse_generation_mix_file(path: Path) -> dict[str, pd.Series]:
    """Extract NL generation-mix forecasts (forecast-only to avoid train/serve skew).

    Returns four hourly series:
      - gen_nl_fossil_gas_mw:   NL fossil-gas generation forecast (marginal fuel)
      - gen_nl_wind_total_mw:   NL onshore + offshore wind forecast
      - gen_nl_solar_mw:        NL solar forecast
      - gen_nl_renewable_share: (wind + solar + hydro) / total forecast
    """
    ALL_FUEL_TYPES = (
        "nuclear", "fossil_gas", "fossil_hard_coal", "fossil_lignite",
        "hydro_pumped_storage", "hydro_run_of_river", "hydro_reservoir",
        "wind_onshore", "wind_offshore", "solar",
    )
    RENEWABLE_TYPES = {
        "wind_onshore", "wind_offshore", "solar",
        "hydro_run_of_river", "hydro_reservoir",
    }

    def _num(v):
        return float(v) if isinstance(v, (int, float)) else 0.0

    data = load_json_file(path)
    container = data.get("data", data) if isinstance(data, dict) else {}
    nl_data = container.get("NL", {}) if isinstance(container, dict) else {}

    gas, wind, solar, share = {}, {}, {}, {}
    for ts_str, fields in nl_data.items():
        if not isinstance(fields, dict):
            continue
        try:
            ts = pd.Timestamp(ts_str).tz_convert("UTC")
        except Exception:
            continue

        gas_val = fields.get("fossil_gas_forecast")
        solar_val = fields.get("solar_forecast")
        wind_on = fields.get("wind_onshore_forecast")
        wind_off = fields.get("wind_offshore_forecast")

        if isinstance(gas_val, (int, float)):
            gas[ts] = float(gas_val)
        if isinstance(solar_val, (int, float)):
            solar[ts] = float(solar_val)
        if isinstance(wind_on, (int, float)) or isinstance(wind_off, (int, float)):
            wind[ts] = _num(wind_on) + _num(wind_off)

        total = 0.0
        renewable = 0.0
        seen_any = False
        for fuel in ALL_FUEL_TYPES:
            val = fields.get(f"{fuel}_forecast")
            if isinstance(val, (int, float)):
                seen_any = True
                total += val
                if fuel in RENEWABLE_TYPES:
                    renewable += val
        if seen_any and total > 0:
            share[ts] = renewable / total

    return {
        "gen_nl_fossil_gas_mw":   pd.Series(gas,   name="gen_nl_fossil_gas_mw"),
        "gen_nl_wind_total_mw":   pd.Series(wind,  name="gen_nl_wind_total_mw"),
        "gen_nl_solar_mw":        pd.Series(solar, name="gen_nl_solar_mw"),
        "gen_nl_renewable_share": pd.Series(share, name="gen_nl_renewable_share"),
    }


def glob_sorted(data_dir: Path, pattern: str) -> list[Path]:
    """Find files matching pattern, sorted by filename (timestamp order)."""
    return sorted(data_dir.glob(pattern))


def consolidate(data_dir: Path, output: Path):
    """Build consolidated training dataset from energyDataHub historical files."""
    data_dir = Path(data_dir)
    if not data_dir.exists():
        raise FileNotFoundError(f"Data directory not found: {data_dir}")

    # Parsers keyed by glob pattern. Each returns either a single pd.Series
    # (named) or a dict[str, pd.Series] for multi-column outputs like
    # generation_mix. Later files overwrite earlier values per timestamp.
    parsers = {
        "*_energy_price_forecast.json": parse_price_file,
        "*_wind_forecast.json": parse_wind_file,
        "*_solar_forecast.json": parse_solar_file,
        "*_weather_forecast_multi_location.json": parse_weather_file,
        "*_load_forecast.json": parse_load_file,
        "*_market_history.json": parse_market_history_file,
        "*_generation_mix.json": parse_generation_mix_file,
    }

    combined_by_col: dict[str, dict] = {}
    for pattern, parser in parsers.items():
        files = glob_sorted(data_dir, pattern)
        logger.info(f"{pattern}: found {len(files)} files")

        for f in files:
            try:
                result = parser(f)
                if isinstance(result, pd.Series):
                    result = {result.name: result}
                for col_name, s in result.items():
                    bucket = combined_by_col.setdefault(col_name, {})
                    for ts, val in s.items():
                        bucket[ts] = val
            except Exception as e:
                logger.warning(f"  Failed to parse {f.name}: {e}")

    all_series = {col: pd.Series(data, name=col) for col, data in combined_by_col.items()}
    for col in sorted(all_series):
        logger.info(f"  {col}: {len(all_series[col])} data points")

    # Combine into DataFrame
    df = pd.DataFrame(all_series)
    df.index.name = "timestamp_utc"
    df = df.sort_index()

    # Resample to hourly (take mean if sub-hourly)
    df = df.resample("h").mean()

    # Forward-fill exogenous features (max 6 hours)
    hourly_ffill_cols = [
        "temperature", "load_forecast", "wind_speed_80m", "solar_ghi",
        "gen_nl_fossil_gas_mw", "gen_nl_wind_total_mw",
        "gen_nl_solar_mw", "gen_nl_renewable_share",
    ]
    for col in hourly_ffill_cols:
        if col in df.columns:
            df[col] = df[col].ffill(limit=6)

    # TTF gas is a daily close (trading days only) — extend ffill across
    # weekends/holidays. 72h covers a Fri close through Mon morning.
    if "gas_ttf_eur_mwh" in df.columns:
        df["gas_ttf_eur_mwh"] = df["gas_ttf_eur_mwh"].ffill(limit=72)

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
