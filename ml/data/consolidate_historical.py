"""
Consolidate historical data for the long-history warmup mini-experiment.

Pulls ENTSO-E day-ahead prices + load forecasts, Open-Meteo archive wind
and solar for a single time range, applies calibrated weather noise to
approximate as-of-date forecast uncertainty, and emits a parquet with the
exact schema the production OnlineFeatureBuilder expects.

Scope of this module is the 1-day mini-warmup check: hourly-only era
(pre-2025-10-01 EU 15-min MTU rollout). Output is 15-min indexed with
forward-fill from hourly sources.

Secrets:
    ENTSO-E key is read from:
      - $ENTSOE_API_KEY env var (preferred), or
      - the HAN secrets.ini on Windows
    None written to disk by this script.

Usage:
    python -m ml.data.consolidate_historical \
        --start 2025-01-01 --end 2025-10-31 \
        --out ml/data/historical_mini.parquet \
        [--no-noise]
"""

from __future__ import annotations

import argparse
import configparser
import logging
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Locations for weather pulls
WIND_LAT, WIND_LON = 54.0, 5.97  # Offshore, near Gemini wind farm
SOLAR_LAT, SOLAR_LON = 51.4416, 5.4697  # Eindhoven

# Measured weather-noise budget from long-history-implementation-plan.md section 16.3
# Linear with horizon; applied during training only if --noise is on.
# For the mini, forecast "horizon" is approximated by a flat per-sample draw,
# since we only have actuals here (no multi-horizon chain). Use the 24h budget
# as representative.
NOISE_SIGMA_WIND_24H = 1.8  # m/s at h+24h
NOISE_SIGMA_SOLAR_24H = 30.0  # W/m^2 at h+24h (daytime only)

# 100m -> 80m wind speed correction via offshore power-law shear (alpha ~= 0.143)
WIND_SHEAR_100_TO_80 = (80 / 100) ** 0.143  # ~0.968


def get_entsoe_key() -> str:
    """Load ENTSO-E API key from env or HAN secrets file."""
    key = os.environ.get("ENTSOE_API_KEY")
    if key:
        return key
    secrets_path = Path(
        r"C:\Users\scbry\HAN\HAN H2 LAB IPKW - Projects - WebBasedControl"
        r"\01. Software\energyDataHub\secrets.ini"
    )
    if not secrets_path.exists():
        raise RuntimeError(
            f"No ENTSOE_API_KEY env var and {secrets_path} not found. "
            "Set ENTSOE_API_KEY on sadalsuud via a gitignored .env file."
        )
    c = configparser.ConfigParser()
    c.read(secrets_path)
    return c["api_keys"]["entsoe"]


def fetch_entsoe_prices(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Pull ENTSO-E NL day-ahead prices. Retries transient 503s with backoff."""
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=get_entsoe_key())
    logger.info(f"Fetching ENTSO-E NL prices {start.date()} to {end.date()}")

    # Chunk by month to stay below any long-window issues
    out = []
    t0 = time.time()
    month_starts = pd.date_range(start, end, freq="MS", tz="UTC")
    if len(month_starts) == 0 or month_starts[0] > start:
        month_starts = pd.DatetimeIndex([start]).append(month_starts)
    for i, chunk_start in enumerate(month_starts):
        chunk_end = month_starts[i + 1] if i + 1 < len(month_starts) else end
        if chunk_start >= chunk_end:
            continue
        for attempt in range(4):
            try:
                s = client.query_day_ahead_prices("NL", start=chunk_start, end=chunk_end)
                s.index = s.index.tz_convert("UTC")
                out.append(s)
                logger.info(f"  {chunk_start.date()} -> {chunk_end.date()}: {len(s)} rows")
                break
            except Exception as e:
                # Scrub token from message before logging (entsoe-py includes URL)
                msg = _redact(str(e))
                logger.warning(f"  attempt {attempt + 1}: {type(e).__name__}: {msg[:160]}")
                time.sleep(2 ** attempt)
        else:
            raise RuntimeError(f"ENTSO-E prices failed after 4 attempts for {chunk_start}")
    series = pd.concat(out).sort_index()
    series = series[~series.index.duplicated(keep="first")]
    logger.info(f"ENTSO-E prices: {len(series)} rows in {time.time() - t0:.1f}s")
    return series.rename("price_eur_mwh")


def fetch_entsoe_load_forecast(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Pull ENTSO-E NL day-ahead load forecast."""
    from entsoe import EntsoePandasClient

    client = EntsoePandasClient(api_key=get_entsoe_key())
    logger.info(f"Fetching ENTSO-E NL load forecast {start.date()} to {end.date()}")

    out = []
    month_starts = pd.date_range(start, end, freq="MS", tz="UTC")
    if len(month_starts) == 0 or month_starts[0] > start:
        month_starts = pd.DatetimeIndex([start]).append(month_starts)
    for i, chunk_start in enumerate(month_starts):
        chunk_end = month_starts[i + 1] if i + 1 < len(month_starts) else end
        if chunk_start >= chunk_end:
            continue
        for attempt in range(4):
            try:
                s = client.query_load_forecast("NL", start=chunk_start, end=chunk_end)
                # Returns DataFrame with 'Forecasted Load' column
                col = s.columns[0] if hasattr(s, "columns") else None
                s = s[col] if col else s
                s.index = s.index.tz_convert("UTC")
                out.append(s)
                break
            except Exception as e:
                logger.warning(
                    f"  load {chunk_start.date()} attempt {attempt + 1}: {_redact(str(e))[:160]}"
                )
                time.sleep(2 ** attempt)
        else:
            logger.error(f"load forecast failed for {chunk_start}; emitting NaN")
    if not out:
        return pd.Series(dtype=float, name="load_forecast")
    series = pd.concat(out).sort_index()
    series = series[~series.index.duplicated(keep="first")]
    logger.info(f"ENTSO-E load forecast: {len(series)} rows")
    return series.rename("load_forecast")


def fetch_openmeteo_wind(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Pull offshore wind_speed_100m from ERA5 archive; scale to 80m."""
    logger.info(f"Fetching Open-Meteo wind {start.date()} to {end.date()}")
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": WIND_LAT,
            "longitude": WIND_LON,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "hourly": "wind_speed_100m",
            "timezone": "UTC",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    times = pd.to_datetime(d["hourly"]["time"], utc=True)
    vals = np.array(d["hourly"]["wind_speed_100m"], dtype=float)
    # Open-Meteo returns km/h; convert to m/s
    vals_ms = vals / 3.6
    # Scale 100m -> 80m via offshore power-law shear
    vals_80 = vals_ms * WIND_SHEAR_100_TO_80
    s = pd.Series(vals_80, index=times, name="wind_speed_80m").sort_index()
    logger.info(f"Open-Meteo wind: {len(s)} rows (scaled 100m->80m via shear)")
    return s


def fetch_openmeteo_solar(start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Pull Eindhoven shortwave_radiation (GHI) from ERA5 archive."""
    logger.info(f"Fetching Open-Meteo solar {start.date()} to {end.date()}")
    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": SOLAR_LAT,
            "longitude": SOLAR_LON,
            "start_date": start.strftime("%Y-%m-%d"),
            "end_date": end.strftime("%Y-%m-%d"),
            "hourly": "shortwave_radiation",
            "timezone": "UTC",
        },
        timeout=60,
    )
    r.raise_for_status()
    d = r.json()
    times = pd.to_datetime(d["hourly"]["time"], utc=True)
    vals = np.array(d["hourly"]["shortwave_radiation"], dtype=float)
    s = pd.Series(vals, index=times, name="solar_ghi").sort_index()
    logger.info(f"Open-Meteo solar: {len(s)} rows")
    return s


def apply_weather_noise(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Add calibrated noise to wind and solar to simulate forecast error.

    Uses a flat-per-sample 24h-horizon σ as a starting budget; solar noise
    is GHI-gated (only applied when baseline GHI > 0).
    """
    rng = np.random.default_rng(seed)
    n = len(df)
    # Wind noise — constant σ
    wind_noise = rng.normal(0, NOISE_SIGMA_WIND_24H, size=n)
    df["wind_speed_80m"] = np.maximum(df["wind_speed_80m"] + wind_noise, 0.0)
    # Solar noise — gated on GHI > 0
    solar_noise = rng.normal(0, NOISE_SIGMA_SOLAR_24H, size=n)
    gate = df["solar_ghi"] > 0
    df.loc[gate, "solar_ghi"] = np.maximum(df.loc[gate, "solar_ghi"] + solar_noise[gate], 0.0)
    logger.info(
        f"Applied noise: wind σ={NOISE_SIGMA_WIND_24H} m/s (all), "
        f"solar σ={NOISE_SIGMA_SOLAR_24H} W/m² (GHI>0 only, {gate.sum()}/{n} samples)"
    )
    return df


def _redact(s: str) -> str:
    """Strip securityToken query param from URLs in error messages."""
    import re
    return re.sub(r"(securityToken=)[^&\s]+", r"\1<redacted>", s)


def consolidate(
    start: pd.Timestamp, end: pd.Timestamp, apply_noise: bool = True
) -> pd.DataFrame:
    """Produce the 15-min indexed feature-ready DataFrame for the given range."""
    # Pull sources
    prices = fetch_entsoe_prices(start, end)
    load = fetch_entsoe_load_forecast(start, end)
    wind = fetch_openmeteo_wind(start, end)
    solar = fetch_openmeteo_solar(start, end)

    # Build 15-min UTC index spanning the common range
    full_idx = pd.date_range(start, end, freq="15min", tz="UTC")

    # Forward-fill each source to 15-min; align on full_idx
    def ff_15(s: pd.Series) -> pd.Series:
        return s.reindex(s.index.union(full_idx).sort_values()).ffill().reindex(full_idx)

    df = pd.DataFrame(index=full_idx)
    df["price_eur_mwh"] = ff_15(prices)
    df["wind_speed_80m"] = ff_15(wind)
    df["solar_ghi"] = ff_15(solar)
    df["load_forecast"] = ff_15(load)

    # Drop rows where any source is NaN (typically at range edges or gaps)
    before = len(df)
    df = df.dropna()
    after = len(df)
    logger.info(f"After align + ffill + dropna: {after}/{before} rows retained")

    if apply_noise:
        df = apply_weather_noise(df)

    return df


def main():
    parser = argparse.ArgumentParser(description="Consolidate historical training data")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD (UTC)")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD (UTC)")
    parser.add_argument("--out", required=True, help="Output parquet path")
    parser.add_argument("--no-noise", action="store_true", help="Skip calibrated weather noise")
    args = parser.parse_args()

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = consolidate(start, end, apply_noise=not args.no_noise)
    df.to_parquet(out_path)
    logger.info(f"Wrote {len(df)} rows to {out_path}")
    logger.info(
        f"Summary: price [{df['price_eur_mwh'].min():.1f}, {df['price_eur_mwh'].max():.1f}] "
        f"mean {df['price_eur_mwh'].mean():.1f}"
    )


if __name__ == "__main__":
    main()
