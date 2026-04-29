"""Tests for ml.shadow.features_pandas — column parity, no leakage, NaN handling."""

import numpy as np
import pandas as pd
import pytest

from ml.shadow.features_pandas import (
    FEATURE_COLUMNS,
    PRICE_LAGS,
    ROLLING_WINDOWS,
    build_features,
)


def _make_df(n: int = 240) -> pd.DataFrame:
    """n hours of hourly UTC data starting 2025-01-01."""
    idx = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(0)
    return pd.DataFrame(
        {
            "price_eur_mwh": rng.normal(50, 20, n),
            "wind_speed_80m": rng.uniform(0, 15, n),
            "solar_ghi": rng.uniform(0, 800, n),
            "temperature": rng.uniform(0, 25, n),
            "load_forecast": rng.uniform(8000, 18000, n),
        },
        index=idx,
    )


class TestColumns:
    def test_returns_expected_columns(self):
        out = build_features(_make_df())
        assert list(out.columns) == list(FEATURE_COLUMNS)

    def test_column_count(self):
        # 8 lags + 3*2 rolling + 7 calendar + 3 exogenous = 24
        assert len(FEATURE_COLUMNS) == 24


class TestSchema:
    def test_rejects_non_datetime_index(self):
        df = _make_df()
        df.index = range(len(df))
        with pytest.raises(TypeError, match="DatetimeIndex"):
            build_features(df)

    def test_rejects_naive_index(self):
        df = _make_df()
        df.index = df.index.tz_localize(None)
        with pytest.raises(ValueError, match="tz-aware"):
            build_features(df)

    def test_rejects_missing_columns(self):
        df = _make_df().drop(columns=["solar_ghi"])
        with pytest.raises(ValueError, match="Missing required"):
            build_features(df)


class TestNoLeakage:
    """The critical correctness property: feature[t] must not depend on price[t]."""

    def test_perturbing_price_at_t_does_not_change_features_at_t(self):
        df = _make_df()
        out_a = build_features(df)
        df2 = df.copy()
        # Perturb only the last row's price.
        df2.iloc[-1, df2.columns.get_loc("price_eur_mwh")] += 1000.0
        out_b = build_features(df2)
        # All feature columns at the last row must be identical.
        np.testing.assert_array_equal(
            out_a.iloc[-1].to_numpy(),
            out_b.iloc[-1].to_numpy(),
        )

    def test_lag_1h_equals_previous_price(self):
        df = _make_df()
        out = build_features(df)
        # At row i (i>=1), lag_1h should equal price at row i-1.
        np.testing.assert_array_equal(
            out["price_lag_1h"].iloc[1:].to_numpy(),
            df["price_eur_mwh"].iloc[:-1].to_numpy(),
        )

    def test_rolling_mean_excludes_current(self):
        """rolling_mean_6h at row i = mean of prices [i-6, i-5, ..., i-1]."""
        df = _make_df()
        out = build_features(df)
        i = 100
        expected = df["price_eur_mwh"].iloc[i - 6 : i].mean()
        assert out["price_rolling_mean_6h"].iloc[i] == pytest.approx(expected)


class TestEarlyRowsHaveNaN:
    def test_lag_168h_nan_in_first_168_rows(self):
        df = _make_df(200)
        out = build_features(df)
        assert out["price_lag_168h"].iloc[:168].isna().all()
        assert out["price_lag_168h"].iloc[168:].notna().all()

    def test_rolling_168h_nan_in_first_two_rows(self):
        df = _make_df(50)
        out = build_features(df)
        # min_periods=2: rows 0 and 1 NaN, row 2+ defined.
        assert out["price_rolling_mean_168h"].iloc[:2].isna().all()
        assert out["price_rolling_mean_168h"].iloc[2:].notna().all()


class TestCalendarFeatures:
    def test_hour_matches_index(self):
        df = _make_df()
        out = build_features(df)
        np.testing.assert_array_equal(
            out["hour"].to_numpy(), df.index.hour.to_numpy(dtype=float)
        )

    def test_is_weekend(self):
        df = _make_df(7 * 24)  # one full week
        out = build_features(df)
        # 2025-01-01 is a Wednesday (weekday=2). Saturday is index 4 days later.
        for i in range(len(df)):
            dow = df.index[i].dayofweek
            assert out["is_weekend"].iloc[i] == (1.0 if dow >= 5 else 0.0)
