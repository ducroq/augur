"""
Online feature builder for River-based continuous learning.

Maintains a rolling price buffer and builds feature dicts one row at a time.
Used by both warmup (historical replay) and daily update (live).

Feature selection based on Lasso/Ridge analysis (R²=0.934):
- Top features: rolling_mean_6h, price lags (1,2,3,6h), hour, wind_speed
- Dropped: temperature (no signal after controlling for calendar)
- Added: rolling mean/std, raw hour (more predictive than sin/cos alone)
"""

import math
from collections import deque
from datetime import datetime, timezone, timedelta


# Lag offsets in hours — all required for good autoregressive signal
PRICE_LAGS = [1, 2, 3, 6, 12, 24, 48, 168]

# Rolling windows for statistics
ROLLING_WINDOWS = [6, 24, 168]


def _safe(val: float | None) -> float:
    """Return 0.0 if value is None or NaN."""
    if val is None:
        return 0.0
    try:
        fval = float(val)
        return 0.0 if math.isnan(fval) else fval
    except (TypeError, ValueError):
        return 0.0


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

    @staticmethod
    def _ensure_utc(ts: datetime) -> datetime:
        """Ensure a datetime is UTC-aware."""
        if ts.tzinfo is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    def _get_lag(self, current_ts: datetime, hours: int) -> float | None:
        """Look up the price from `hours` ago."""
        current_ts = self._ensure_utc(current_ts)
        target = current_ts.timestamp() - hours * 3600
        best = None
        best_diff = float("inf")
        for ts_iso, price in self.price_history:
            ts = self._ensure_utc(datetime.fromisoformat(ts_iso))
            diff = abs(ts.timestamp() - target)
            if diff < best_diff:
                best_diff = diff
                best = price
        # Accept if within 30 minutes of target
        if best is not None and best_diff < 1800:
            return best
        return None

    def _get_recent_prices(self, current_ts: datetime, hours: int) -> list[float]:
        """Get the last N hours of prices for rolling stats."""
        current_ts = self._ensure_utc(current_ts)
        cutoff = current_ts.timestamp() - hours * 3600
        prices = []
        for ts_iso, price in self.price_history:
            ts = self._ensure_utc(datetime.fromisoformat(ts_iso))
            if ts.timestamp() >= cutoff:
                prices.append(price)
        return prices

    def build(
        self,
        timestamp_iso: str,
        wind_speed_80m: float | None = None,
        solar_ghi: float | None = None,
        load_forecast: float | None = None,
        gas_ttf_eur_mwh: float | None = None,
        gen_nl_fossil_gas_mw: float | None = None,
        gen_nl_wind_total_mw: float | None = None,
        gen_nl_solar_mw: float | None = None,
        gen_nl_renewable_share: float | None = None,
    ) -> dict | None:
        """
        Build a feature dict for one timestamp.

        Returns None if required lag features (1h, 24h) are unavailable.
        """
        ts = self._ensure_utc(datetime.fromisoformat(timestamp_iso))

        # Required lags — must have at least 1h and 24h
        lag_1h = self._get_lag(ts, 1)
        lag_24h = self._get_lag(ts, 24)
        if lag_1h is None or lag_24h is None:
            return None

        # All lags
        lags = {}
        for h in PRICE_LAGS:
            val = self._get_lag(ts, h)
            lags[f"price_lag_{h}h"] = val if val is not None else 0.0

        # Rolling statistics (the #1 feature per Lasso analysis)
        rolling = {}
        for w in ROLLING_WINDOWS:
            recent = self._get_recent_prices(ts, w)
            if len(recent) >= max(w // 4, 2):  # need at least 25% coverage
                rolling[f"price_rolling_mean_{w}h"] = sum(recent) / len(recent)
                if len(recent) >= 3:
                    mean = rolling[f"price_rolling_mean_{w}h"]
                    rolling[f"price_rolling_std_{w}h"] = (
                        sum((p - mean) ** 2 for p in recent) / len(recent)
                    ) ** 0.5
                else:
                    rolling[f"price_rolling_std_{w}h"] = 0.0
            else:
                rolling[f"price_rolling_mean_{w}h"] = 0.0
                rolling[f"price_rolling_std_{w}h"] = 0.0

        # Calendar features — raw hour is more predictive than sin/cos alone
        hour = ts.hour
        dow = ts.weekday()
        features = {
            "hour": float(hour),
            "hour_sin": math.sin(2 * math.pi * hour / 24),
            "hour_cos": math.cos(2 * math.pi * hour / 24),
            "dow_sin": math.sin(2 * math.pi * dow / 7),
            "dow_cos": math.cos(2 * math.pi * dow / 7),
            "is_weekend": 1.0 if dow >= 5 else 0.0,
            "month_sin": math.sin(2 * math.pi * ts.month / 12),
        }

        features.update(lags)
        features.update(rolling)

        # Exogenous features (temperature dropped per Lasso — no signal)
        features["wind_speed_80m"] = _safe(wind_speed_80m)
        features["solar_ghi"] = _safe(solar_ghi)
        features["load_forecast"] = _safe(load_forecast)

        # Phase 1 new features (TTF gas + NL generation mix, forecast-only).
        # Keys are only added when the caller passes the kwarg — lets the
        # training harness toggle baseline vs Phase 1 runs on the same parquet.
        # NaN values (from ffill gaps) still add the key via _safe → 0.0, so a
        # Phase 1 run keeps a stable feature set across rows.
        if gas_ttf_eur_mwh is not None:
            features["gas_ttf_eur_mwh"] = _safe(gas_ttf_eur_mwh)
        if gen_nl_fossil_gas_mw is not None:
            features["gen_nl_fossil_gas_mw"] = _safe(gen_nl_fossil_gas_mw)
        if gen_nl_wind_total_mw is not None:
            features["gen_nl_wind_total_mw"] = _safe(gen_nl_wind_total_mw)
        if gen_nl_solar_mw is not None:
            features["gen_nl_solar_mw"] = _safe(gen_nl_solar_mw)
        if gen_nl_renewable_share is not None:
            features["gen_nl_renewable_share"] = _safe(gen_nl_renewable_share)

        return features

    def get_price_buffer(self) -> list:
        """Export price buffer for JSON serialization."""
        return list(self.price_history)
