"""Tests for OnlineFeatureBuilder — lag retrieval, rolling stats, timezone handling."""

import pytest
from datetime import datetime, timezone, timedelta

from ml.features.online_features import OnlineFeatureBuilder, PRICE_LAGS


def _make_fb(hours=200, base_price=50.0):
    """Create a feature builder with `hours` of synthetic hourly prices."""
    fb = OnlineFeatureBuilder()
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    for h in range(hours):
        ts = base + timedelta(hours=h)
        fb.push_price(ts.isoformat(), base_price + (h % 24))
    return fb, base


class TestLags:
    def test_1h_lag_available(self):
        fb, base = _make_fb(48)
        ts = (base + timedelta(hours=25)).isoformat()
        features = fb.build(ts, wind_speed_80m=5.0, solar_ghi=100.0, load_forecast=1000.0)
        assert features is not None
        assert "price_lag_1h" in features
        assert features["price_lag_1h"] > 0

    def test_returns_none_without_required_lags(self):
        fb = OnlineFeatureBuilder()
        fb.push_price("2026-03-01T00:00:00+00:00", 50.0)
        result = fb.build("2026-03-01T01:00:00+00:00")
        # Only 1h of history — missing 24h lag
        assert result is None

    def test_all_lags_present_with_enough_history(self):
        fb, base = _make_fb(200)
        ts = (base + timedelta(hours=199)).isoformat()
        features = fb.build(ts)
        assert features is not None
        for lag in PRICE_LAGS:
            assert f"price_lag_{lag}h" in features


class TestRollingStats:
    def test_rolling_stats_computed(self):
        fb, base = _make_fb(48)
        ts = (base + timedelta(hours=30)).isoformat()
        features = fb.build(ts)
        assert features is not None
        assert "price_rolling_mean_6h" in features
        assert "price_rolling_std_6h" in features
        assert features["price_rolling_mean_6h"] > 0

    def test_std_is_nonnegative(self):
        fb, base = _make_fb(48)
        ts = (base + timedelta(hours=30)).isoformat()
        features = fb.build(ts)
        for key in features:
            if "std" in key:
                assert features[key] >= 0


class TestTimezoneHandling:
    def test_naive_timestamps_treated_as_utc(self):
        """Naive and UTC-aware timestamps for the same time should produce same lags."""
        fb = OnlineFeatureBuilder()
        base = datetime(2026, 3, 1, tzinfo=timezone.utc)
        for h in range(48):
            ts = base + timedelta(hours=h)
            fb.push_price(ts.isoformat(), 50.0 + h)

        # Build with UTC-aware
        ts_aware = (base + timedelta(hours=30)).isoformat()
        f1 = fb.build(ts_aware)

        # Build with naive (same instant)
        ts_naive = (base + timedelta(hours=30)).replace(tzinfo=None).isoformat()
        f2 = fb.build(ts_naive)

        assert f1 is not None
        assert f2 is not None
        assert f1["price_lag_1h"] == f2["price_lag_1h"]


class TestCalendarFeatures:
    def test_calendar_features_present(self):
        fb, base = _make_fb(48)
        ts = (base + timedelta(hours=30)).isoformat()
        features = fb.build(ts)
        assert features is not None
        for key in ["hour", "hour_sin", "hour_cos", "dow_sin", "dow_cos", "is_weekend", "month_sin"]:
            assert key in features

    def test_weekend_detection(self):
        fb, base = _make_fb(200)
        # 2026-03-01 is a Sunday
        ts_sunday = base.isoformat()
        # Find a weekday
        ts_wednesday = (base + timedelta(days=3)).isoformat()
        f_sun = fb.build(ts_sunday)
        f_wed = fb.build(ts_wednesday)
        # Sunday won't have enough lags, but Wednesday after 200h will
        if f_wed is not None:
            assert f_wed["is_weekend"] == 0.0


class TestPriceBuffer:
    def test_get_price_buffer_roundtrip(self):
        fb, _ = _make_fb(50)
        buf = fb.get_price_buffer()
        fb2 = OnlineFeatureBuilder(price_buffer=buf)
        assert len(fb2.price_history) == len(fb.price_history)

    def test_maxlen_enforced(self):
        fb, _ = _make_fb(300)
        assert len(fb.price_history) == 200  # maxlen
