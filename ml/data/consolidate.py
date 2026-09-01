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


def _unwrap_v22_envelope(data: dict) -> dict:
    # EDH v2.2 (commit 3dfc7fb, 2026-06-07) wraps per-source feeds under
    # {metadata, data: {<source>: ...}}; pre-v2.2 was flat. Mirrors the JS
    # unwrap in static/js/modules/data-processor.js (commit 4a557c8).
    inner = data.get("data")
    if isinstance(inner, dict):
        logger.debug("EDH v2.2 envelope detected — unwrapping 'data' layer")
        return inner
    return data


# Wholesale sources that may supply the training target, in ASCENDING priority:
# a later entry overwrites an earlier one on the same timestamp.
#
# `epex` IS KNOWN BAD AND IS STILL HERE ON PURPOSE (2026-09-01). Measured
# against entsoe over 7886 matched hours it runs +16.13 mean / +10.72 median
# EUR/MWh, corr 0.859, MAE 21.16, agreeing within 1 EUR on only 13.0% of hours.
# elspot over 7079 matched hours is +0.86 mean / 0.00 median, corr 0.954,
# agreeing within 1 EUR on 39.5%. The offset is flat across lags -4h..+4h, so it
# is a level bias, not a misalignment. energyDataHub labels it country_code='NL'
# "EPEX SPOT day-ahead" via Awattar; whatever it prices, it is not the NL
# day-ahead series this model trains on. And it OUTRANKS elspot here, so on the
# hours entsoe misses it supplies the target and discards the accurate fallback.
#
# Why it has not simply been deleted. entsoe has hourly holes even inside files
# that contain it, so 141 of 8013 parquet hours (1.76%) resolve to a fallback --
# including 21 of the 24 hours of 2026-08-27. (An earlier pass said 93/1.16%; it
# asked whether ANY file ever carried entsoe for an hour, but the combine loop
# lets the LAST file to write a timestamp win, so the question is whether the
# winning write was entsoe. 141 is that number, and it is what price_is_entsoe
# reports.) The affected days come in a telling shape -- 1-2 hours on one day
# then 21-23 on the next: 10-20/21, 02-15/16, 03-01/02, 06-29/30 + 07-01,
# 08-26/27. That is an EDH missed-publish signature (energyDataHub#50), the same
# root cause as the lost vintages, not a separate ENTSO-E fault.
# Removing epex sends those hours to
# NaN, and `dropna(subset=["price_eur_mwh"])` below then deletes the ROWS. But
# ml/shadow/features_pandas.py builds lags with a POSITIONAL
# `df["price_eur_mwh"].shift(h)`, and PRICE_LAGS/ROLLING_WINDOWS reach 168, so a
# 21h hole would silently misalign every lag and rolling feature for ~7 days
# after it -- 2026-08-27..09-03, exactly the vintages EXP-018a/021a/028a score.
# The live window (from 2026-07-06) is otherwise gap-free; the only runs of
# missing hours (48h/24h/5h) are all in Oct-Nov 2025, well outside it.
#
# So: MARK, do not drop. `price_is_entsoe` below labels every hour, and readers
# that score against realised prices should exclude `price_is_entsoe < 1.0`
# rather than relying on the row being absent. Deleting epex becomes safe once
# consolidate stops dropping price-less rows, so the hourly grid stays complete
# and `shift(h)` means h hours everywhere. That is a separate reviewed change;
# the removal is kept on branch wip/drop-epex-target.
#
# Energy Zero stays excluded for an unrelated and permanent reason: it is a
# CONSUMER price including VAT and surcharges, so it would corrupt the target.
WHOLESALE_SOURCES: tuple[str, ...] = ("elspot", "epex", "entsoe")
PRIMARY_SOURCE = "entsoe"


def _merge_wholesale(data: dict) -> tuple[dict, dict]:
    """Merge wholesale sources once, returning prices and their provenance.

    Returns ``({ts: price}, {ts: 1.0 if entsoe else 0.0})``. Both mappings come
    from a single pass so provenance can never drift from the price it labels.
    """
    merged: dict = {}
    source: dict = {}
    for source_key in WHOLESALE_SOURCES:
        block = data.get(source_key)
        if not block or not isinstance(block, dict) or "data" not in block:
            continue
        ts_data = block["data"]
        if not isinstance(ts_data, dict):
            continue
        units = block.get("metadata", {}).get("units", "EUR/MWh")
        multiplier = 1000 if "kwh" in units.lower() else 1
        for ts_str, price in ts_data.items():
            if not isinstance(price, (int, float)):
                continue
            ts_str = ts_str.replace("+00:18", "+01:00").replace("+00:09", "+01:00")
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
            except Exception:
                continue
            merged[ts] = price * multiplier
            source[ts] = 1.0 if source_key == PRIMARY_SOURCE else 0.0
    return merged, source


def parse_price_file(path: Path) -> pd.Series:
    """Extract NL wholesale hourly prices from an energy_price_forecast file.

    entsoe preferred, then elspot/epex filling hours entsoe does not cover.
    Returns wholesale prices only -- Energy Zero is excluded because it is a
    consumer price. See WHOLESALE_SOURCES for why epex is known bad, still
    present, and to be read via `price_is_entsoe` rather than trusted.
    """
    data = _unwrap_v22_envelope(load_json_file(path))

    entsoe_source = data.get("entsoe")
    has_entsoe = (
        entsoe_source
        and isinstance(entsoe_source, dict)
        and "data" in entsoe_source
        and entsoe_source["data"]
    )
    if not has_entsoe:
        logger.warning(
            "ENTSO-E data missing in %s — target falls back to epex/elspot; "
            "those hours are flagged price_is_entsoe=0.0", path.name
        )

    merged, _ = _merge_wholesale(data)
    if merged:
        return pd.Series(merged, name="price_eur_mwh")
    return pd.Series(dtype=float, name="price_eur_mwh")


def parse_price_source_file(path: Path) -> pd.Series:
    """Provenance for `price_eur_mwh`: 1.0 where entsoe supplied it, else 0.0.

    0.0 means a fallback source (epex or elspot) supplied that hour. epex is
    measurably biased (see WHOLESALE_SOURCES), so anything SCORING a forecast
    against realised prices should exclude `price_is_entsoe < 1.0`.

    Numeric on purpose. `consolidate` resamples every column with
    `.resample("h").mean()`, which raises on object dtype -- and the mean of a
    0/1 flag over a sub-hourly bin is exactly the right reading: the fraction of
    that hour sourced from ENTSO-E, so a partially-filled hour is visible rather
    than rounded to one label.
    """
    data = _unwrap_v22_envelope(load_json_file(path))
    _, source = _merge_wholesale(data)
    if source:
        return pd.Series(source, name="price_is_entsoe")
    return pd.Series(dtype=float, name="price_is_entsoe")


def _parse_single_source(path: Path, source_key: str, name: str) -> pd.Series:
    """Extract a single price source from an energy_price_forecast file."""
    data = _unwrap_v22_envelope(load_json_file(path))
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
    data = _unwrap_v22_envelope(load_json_file(path))

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
    if not isinstance(solar_data, dict):
        return pd.Series(dtype=float, name="solar_ghi")
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
    if not isinstance(weather_data, dict):
        return pd.Series(dtype=float, name="temperature")
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
    if not isinstance(load_data, dict):
        return pd.Series(dtype=float, name="load_forecast")
    nl_data = load_data.get("NL", {})
    if not isinstance(nl_data, dict):
        return pd.Series(dtype=float, name="load_forecast")

    series = {}
    for ts_str, fields in nl_data.items():
        if isinstance(fields, dict) and isinstance(fields.get("load_forecast"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["load_forecast"]
            except Exception:
                continue
    return pd.Series(series, name="load_forecast")


def parse_wind_generation_file(path: Path) -> pd.Series:
    """Extract the ENTSO-E NL day-ahead wind generation forecast (MW).

    Same file as `parse_wind_file`, different sub-dataset: `offshore_wind` is
    Open-Meteo wind *speed* at one offshore point, `entsoe_wind_generation` is
    the TSO's own day-ahead wind *generation* forecast in MW for the whole NL
    bidding zone. Quarter-hourly; `consolidate` resamples to hourly.
    """
    data = _unwrap_v22_envelope(load_json_file(path))

    gen = data.get("entsoe_wind_generation", {})
    if not isinstance(gen, dict) or "data" not in gen:
        return pd.Series(dtype=float, name="wind_gen_forecast_mw")

    nl_data = gen["data"].get("NL", {})
    if not isinstance(nl_data, dict):
        return pd.Series(dtype=float, name="wind_gen_forecast_mw")

    series = {}
    for ts_str, fields in nl_data.items():
        if isinstance(fields, dict) and isinstance(fields.get("wind_total"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["wind_total"]
            except Exception:
                continue
    return pd.Series(series, name="wind_gen_forecast_mw")


def parse_solar_generation_file(path: Path) -> pd.Series:
    """Extract the NED.nl NL solar generation forecast (MW).

    NED's `capacity_kw` is not installed capacity — it is the block's average
    power in kW, and satisfies `capacity_kw == volume_kwh * 4` for the
    quarter-hourly blocks (pinned by test). `utilization_pct` is measured
    against true installed capacity (~25 GW), so it cannot be used directly.
    """
    data = _unwrap_v22_envelope(load_json_file(path))

    solar = data.get("solar", {})
    if not isinstance(solar, dict):
        return pd.Series(dtype=float, name="solar_gen_forecast_mw")
    forecast = solar.get("forecast", {})
    if not isinstance(forecast, dict):
        return pd.Series(dtype=float, name="solar_gen_forecast_mw")

    series = {}
    for ts_str, fields in forecast.items():
        if isinstance(fields, dict) and isinstance(fields.get("capacity_kw"), (int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = fields["capacity_kw"] / 1000.0
            except Exception:
                continue
    return pd.Series(series, name="solar_gen_forecast_mw")


def parse_gas_price_file(path: Path) -> pd.Series:
    """Extract the TTF gas settlement price (EUR/MWh) from a market_proxies file.

    One scalar per file, stamped with its own trade `date` rather than the
    file's collection timestamp. Indexed at that date's 00:00 UTC; TTF is a
    business-day series, so `consolidate` forward-fills it over weekends.
    """
    data = _unwrap_v22_envelope(load_json_file(path))

    ttf = data.get("gas_ttf", {})
    if not isinstance(ttf, dict):
        return pd.Series(dtype=float, name="gas_ttf_eur_mwh")

    price = ttf.get("price")
    date = ttf.get("date")
    if not isinstance(price, (int, float)) or not isinstance(date, str):
        return pd.Series(dtype=float, name="gas_ttf_eur_mwh")

    try:
        ts = pd.Timestamp(date, tz="UTC")
    except Exception:
        return pd.Series(dtype=float, name="gas_ttf_eur_mwh")
    return pd.Series({ts: float(price)}, name="gas_ttf_eur_mwh")


def parse_calendar_file(path: Path) -> pd.Series:
    """Extract the NL public-holiday flag from a calendar_features file.

    Hourly, keyed by local timestamp. The 24-feature set encodes hour/dow/month
    cyclically but has no holiday flag, and NL holidays shift demand into a
    weekend-like shape on days the `is_weekend` feature calls working days.
    """
    data = _unwrap_v22_envelope(load_json_file(path))
    if not isinstance(data, dict):
        return pd.Series(dtype=float, name="is_holiday_nl")

    series = {}
    for ts_str, fields in data.items():
        if isinstance(fields, dict) and isinstance(fields.get("is_holiday_nl"), (bool, int, float)):
            try:
                ts = pd.Timestamp(ts_str).tz_convert("UTC")
                series[ts] = float(fields["is_holiday_nl"])
            except Exception:
                continue
    return pd.Series(series, name="is_holiday_nl")


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
        # Provenance for the target (additive; never a feature). Lets the
        # experiment harness exclude non-ENTSO-E hours instead of inferring them.
        "price_is_entsoe": ("*_energy_price_forecast.json", parse_price_source_file),
        "wind_speed_80m": ("*_wind_forecast.json", parse_wind_file),
        "solar_ghi": ("*_solar_forecast.json", parse_solar_file),
        "temperature": ("*_weather_forecast_multi_location.json", parse_weather_file),
        "load_forecast": ("*_load_forecast.json", parse_load_file),
        # EXP-020 fundamentals (additive; not yet in FEATURE_COLUMNS).
        "wind_gen_forecast_mw": ("*_wind_forecast.json", parse_wind_generation_file),
        "solar_gen_forecast_mw": ("*_ned_production.json", parse_solar_generation_file),
        "gas_ttf_eur_mwh": ("*_market_proxies.json", parse_gas_price_file),
        "is_holiday_nl": ("*_calendar_features.json", parse_calendar_file),
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
    # A feed with zero matching files yields an EMPTY series whose index is an
    # object Index, and unioning that with the datetime-indexed feeds produces a
    # plain object Index -- which makes the `.resample("h")` below raise
    # "Only valid with DatetimeIndex". Never reached while all nine feeds have
    # history, but it would take the nightly consolidate down the first night EDH
    # stopped publishing any one of them. Found 2026-09-01 by an end-to-end test.
    df.index = pd.DatetimeIndex(df.index)
    df.index.name = "timestamp_utc"
    df = df.sort_index()

    # Resample to hourly (take mean if sub-hourly)
    df = df.resample("h").mean()

    # Forward-fill slow-changing features (max 6 hours)
    for col in [
        "temperature",
        "load_forecast",
        "wind_speed_80m",
        "solar_ghi",
        "wind_gen_forecast_mw",
        "solar_gen_forecast_mw",
        "is_holiday_nl",
    ]:
        if col in df.columns:
            df[col] = df[col].ffill(limit=6)

    # TTF gas settles once per business day; carry it across weekends and
    # holidays (5 days covers a long weekend plus a market holiday).
    if "gas_ttf_eur_mwh" in df.columns:
        df["gas_ttf_eur_mwh"] = df["gas_ttf_eur_mwh"].ffill(limit=120)

    # Drop rows with no price (target)
    before = len(df)
    df = df.dropna(subset=["price_eur_mwh"])
    logger.info(f"Dropped {before - len(df)} rows without price data")

    # Say out loud how much of the target is not ENTSO-E. This went unnoticed for
    # a year because nothing ever printed it.
    if "price_is_entsoe" in df.columns:
        flag = df["price_is_entsoe"]
        n_fallback = int((flag < 1.0).sum())
        if n_fallback:
            days = sorted({ts.date().isoformat() for ts in flag.index[flag < 1.0]})
            logger.warning(
                "price provenance: %d of %d hours (%.2f%%) are NOT fully ENTSO-E "
                "(elspot fallback) on %d day(s): %s",
                n_fallback, len(flag), 100 * n_fallback / len(flag),
                len(days), ", ".join(days[:10]) + ("..." if len(days) > 10 else ""),
            )
        else:
            logger.info("price provenance: all %d hours are ENTSO-E", len(flag))

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
