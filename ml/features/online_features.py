"""
Online feature builder for River-based continuous learning.

Maintains a rolling price buffer and builds feature dicts one row at a time.
Used by both warmup (historical replay) and daily update (live).
"""

import math
from collections import deque
from datetime import datetime, timezone


# Lag offsets in hours
REQUIRED_LAGS = [1, 24, 168]
OPTIONAL_LAGS = [2, 3, 6, 12, 48]


def _safe(val: float | None) -> float:
    """Return 0.0 if value is None or NaN."""
    if val is None:
        return 0.0
    try:
        if val != val:  # NaN check
            return 0.0
    except (TypeError, ValueError):
        return 0.0
    return float(val)


class OnlineFeatureBuilder:
    """Builds feature dicts for River's predict_one/learn_one interface."""

    def __init__(self, price_buffer=None):
        """
        Args:
            price_buffer: Optional list of (timestamp_iso, price) tuples
                          to restore state from state.json.
        """
        self.price_history = deque(maxlen=200)  # ~8 days of hourly data
        if price_buffer:
            for ts, price in price_buffer:
                self.price_history.append((ts, price))

    def push_price(self, timestamp_iso: str, price: float):
        """Record an observed price."""
        self.price_history.append((timestamp_iso, price))

    def _get_lag(self, current_ts: datetime, hours: int) -> float | None:
        """Look up the price from `hours` ago."""
        target = current_ts.timestamp() - hours * 3600
        best = None
        best_diff = float("inf")
        for ts_iso, price in self.price_history:
            ts = datetime.fromisoformat(ts_iso)
            diff = abs(ts.timestamp() - target)
            if diff < best_diff:
                best_diff = diff
                best = price
        # Accept if within 30 minutes of target
        if best is not None and best_diff < 1800:
            return best
        return None

    def build(
        self,
        timestamp_iso: str,
        wind_speed_80m: float | None = None,
        solar_ghi: float | None = None,
        temperature: float | None = None,
        load_forecast: float | None = None,
    ) -> dict | None:
        """
        Build a feature dict for one timestamp.

        Returns None if required lag features are unavailable.
        """
        ts = datetime.fromisoformat(timestamp_iso)

        # Required lags — return None if any missing
        lags = {}
        for h in REQUIRED_LAGS:
            val = self._get_lag(ts, h)
            if val is None:
                return None
            lags[f"price_lag_{h}h"] = val

        # Optional lags — fill with 0 if missing
        for h in OPTIONAL_LAGS:
            val = self._get_lag(ts, h)
            lags[f"price_lag_{h}h"] = val if val is not None else 0.0

        # Calendar features
        hour = ts.hour
        dow = ts.weekday()
        features = {
            "hour_sin": math.sin(2 * math.pi * hour / 24),
            "hour_cos": math.cos(2 * math.pi * hour / 24),
            "dow_sin": math.sin(2 * math.pi * dow / 7),
            "dow_cos": math.cos(2 * math.pi * dow / 7),
            "is_weekend": 1.0 if dow >= 5 else 0.0,
            "month_sin": math.sin(2 * math.pi * ts.month / 12),
            "month_cos": math.cos(2 * math.pi * ts.month / 12),
        }

        features.update(lags)

        # Exogenous features — use 0 if unavailable or NaN
        features["wind_speed_80m"] = _safe(wind_speed_80m)
        features["solar_ghi"] = _safe(solar_ghi)
        features["temperature"] = _safe(temperature)
        features["load_forecast"] = _safe(load_forecast)

        return features

    def get_price_buffer(self) -> list:
        """Export price buffer for JSON serialization."""
        return list(self.price_history)
