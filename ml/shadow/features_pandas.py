"""Vectorized feature builder for the EXP-009 shadow backtest.

Pandas equivalent of `ml.features.online_features.OnlineFeatureBuilder`. Produces
the same 24 columns from a UTC-indexed hourly DataFrame containing
`price_eur_mwh` and the three exogenous columns. All lag/rolling features are
shifted by one row before computation so feature[t] depends only on prices
strictly before t — required for both training and walk-forward eval.

Deliberate deltas vs OnlineFeatureBuilder:
- Exogenous NaNs stay NaN (LightGBM splits on NaN natively); the streaming
  builder coerces to 0.0 via `_safe`. Documented; not a bug.
- Rolling windows use pandas `min_periods=2` (matching the streaming builder's
  `len(recent) >= 3` guard for std, slightly looser for mean).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

PRICE_LAGS = (1, 2, 3, 6, 12, 24, 48, 168)
ROLLING_WINDOWS = (6, 24, 168)

REQUIRED_COLUMNS = ("price_eur_mwh", "wind_speed_80m", "solar_ghi", "load_forecast")

FEATURE_COLUMNS: tuple[str, ...] = (
    *(f"price_lag_{h}h" for h in PRICE_LAGS),
    *(f"price_rolling_mean_{w}h" for w in ROLLING_WINDOWS),
    *(f"price_rolling_std_{w}h" for w in ROLLING_WINDOWS),
    "hour",
    "hour_sin",
    "hour_cos",
    "dow_sin",
    "dow_cos",
    "is_weekend",
    "month_sin",
    "wind_speed_80m",
    "solar_ghi",
    "load_forecast",
)


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build feature matrix from a UTC-indexed hourly DataFrame.

    Args:
        df: index must be a tz-aware DatetimeIndex (UTC), spaced hourly.
            Must contain `price_eur_mwh` plus the three exogenous columns.

    Returns:
        DataFrame with the same index and FEATURE_COLUMNS. Early rows that
        lack required lag history (lag_1h or lag_24h) are present but the
        relevant lag columns are NaN — caller should drop NaN before fit.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise TypeError("df must have a DatetimeIndex")
    if df.index.tz is None:
        raise ValueError("df.index must be tz-aware (UTC)")

    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Missing required columns: {sorted(missing)}")

    price_prev = df["price_eur_mwh"].shift(1)

    out = pd.DataFrame(index=df.index)

    for h in PRICE_LAGS:
        out[f"price_lag_{h}h"] = df["price_eur_mwh"].shift(h)

    for w in ROLLING_WINDOWS:
        roll = price_prev.rolling(window=w, min_periods=2)
        out[f"price_rolling_mean_{w}h"] = roll.mean()
        out[f"price_rolling_std_{w}h"] = roll.std(ddof=0)

    idx = df.index
    hour = idx.hour.to_numpy(dtype=float)
    dow = idx.dayofweek.to_numpy(dtype=float)
    month = idx.month.to_numpy(dtype=float)

    out["hour"] = hour
    out["hour_sin"] = np.sin(2 * math.pi * hour / 24.0)
    out["hour_cos"] = np.cos(2 * math.pi * hour / 24.0)
    out["dow_sin"] = np.sin(2 * math.pi * dow / 7.0)
    out["dow_cos"] = np.cos(2 * math.pi * dow / 7.0)
    out["is_weekend"] = (dow >= 5).astype(float)
    out["month_sin"] = np.sin(2 * math.pi * month / 12.0)

    out["wind_speed_80m"] = df["wind_speed_80m"].to_numpy(dtype=float)
    out["solar_ghi"] = df["solar_ghi"].to_numpy(dtype=float)
    out["load_forecast"] = df["load_forecast"].to_numpy(dtype=float)

    return out[list(FEATURE_COLUMNS)]
