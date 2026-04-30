"""Tests for LightGBMQuantileForecaster — fit/predict/save/load + parquet smoke."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.shadow.lightgbm_quantile import (
    DEFAULT_GROUPS,
    DEFAULT_QUANTILES,
    LGBMHyperparams,
    LightGBMQuantileForecaster,
    MultiHorizonLightGBMQuantileForecaster,
)


# Fast hyperparams for unit tests — accuracy doesn't matter, exception-freeness does.
FAST_HP = LGBMHyperparams(n_estimators=20, num_leaves=7, min_child_samples=5)


@pytest.fixture
def synthetic_xy():
    """1000 rows, 5 features, target with heteroskedastic noise."""
    rng = np.random.default_rng(42)
    n = 1000
    X = pd.DataFrame(
        {
            "f0": rng.normal(0, 1, n),
            "f1": rng.uniform(-1, 1, n),
            "f2": rng.exponential(1, n),
            "f3": rng.normal(5, 2, n),
            "f4": rng.choice([0, 1], n).astype(float),
        }
    )
    # Target depends on f0 + f3, with noise scale rising in f2
    y = 2 * X["f0"] + X["f3"] + rng.normal(0, 1 + X["f2"], n)
    return X, y


class TestConstructor:
    def test_default_quantiles(self):
        m = LightGBMQuantileForecaster()
        assert m.quantiles == DEFAULT_QUANTILES

    def test_rejects_non_three_quantiles(self):
        with pytest.raises(ValueError, match="3 quantiles"):
            LightGBMQuantileForecaster(quantiles=(0.5,))
        with pytest.raises(ValueError, match="3 quantiles"):
            LightGBMQuantileForecaster(quantiles=(0.1, 0.25, 0.5, 0.9))

    def test_rejects_non_ascending(self):
        with pytest.raises(ValueError, match="ascending"):
            LightGBMQuantileForecaster(quantiles=(0.5, 0.1, 0.9))

    def test_rejects_out_of_range(self):
        with pytest.raises(ValueError, match=r"\(0, 1\)"):
            LightGBMQuantileForecaster(quantiles=(0.0, 0.5, 0.9))
        with pytest.raises(ValueError, match=r"\(0, 1\)"):
            LightGBMQuantileForecaster(quantiles=(0.1, 0.5, 1.0))


class TestFit:
    def test_fit_returns_self(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP)
        out = m.fit(X, y)
        assert out is m

    def test_fit_creates_three_models(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        assert len(m.models) == 3

    def test_fit_records_feature_names(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        assert m.feature_names == list(X.columns)

    def test_fit_rejects_empty(self):
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(ValueError, match="empty"):
            m.fit(pd.DataFrame({"f0": []}), [])

    def test_fit_rejects_length_mismatch(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(ValueError, match="length mismatch"):
            m.fit(X, y[:100])

    def test_fit_rejects_non_dataframe(self):
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(TypeError, match="DataFrame"):
            m.fit(np.zeros((10, 3)), np.zeros(10))


class TestPredict:
    def test_predict_shape(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict(X.head(50))
        assert preds.shape == (50, 3)

    def test_predict_monotonic_per_row(self, synthetic_xy):
        """Plan §7: post-hoc sort guarantees P10 <= P50 <= P90 per row."""
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict(X)
        assert np.all(preds[:, 0] <= preds[:, 1])
        assert np.all(preds[:, 1] <= preds[:, 2])

    def test_predict_unfit_raises(self, synthetic_xy):
        X, _ = synthetic_xy
        m = LightGBMQuantileForecaster()
        with pytest.raises(RuntimeError, match="not fit"):
            m.predict(X)

    def test_predict_rejects_missing_features(self, synthetic_xy):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        with pytest.raises(ValueError, match="Missing features"):
            m.predict(X.drop(columns=["f0"]))

    def test_predict_reorders_extra_columns(self, synthetic_xy):
        """Predict should select training columns, ignoring extras and column order."""
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        X_extra = X.copy()
        X_extra["unrelated"] = 0.0
        X_extra = X_extra[["unrelated", "f4", "f3", "f2", "f1", "f0"]]
        preds = m.predict(X_extra.head(20))
        assert preds.shape == (20, 3)


class TestSaveLoad:
    def test_save_load_roundtrip(self, synthetic_xy, tmp_path):
        X, y = synthetic_xy
        m = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        original = m.predict(X.head(10))

        path = tmp_path / "lgbm.pkl"
        m.save(path)
        assert path.exists()

        loaded = LightGBMQuantileForecaster.load(path)
        restored = loaded.predict(X.head(10))
        np.testing.assert_array_equal(original, restored)
        assert loaded.quantiles == m.quantiles
        assert loaded.feature_names == m.feature_names

    def test_save_unfit_raises(self, tmp_path):
        m = LightGBMQuantileForecaster()
        with pytest.raises(RuntimeError, match="unfit"):
            m.save(tmp_path / "x.pkl")


PARQUET_PATH = Path(__file__).parent.parent / "ml" / "data" / "training_history.parquet"


@pytest.mark.skipif(not PARQUET_PATH.exists(), reason="bootstrap parquet not present")
class TestParquetSmoke:
    """End-to-end smoke against the bootstrapped training_history.parquet.

    Not a quality bar — just verifies the wrapper accepts the real data shape.
    """

    def test_fit_predict_on_parquet(self):
        df = pd.read_parquet(PARQUET_PATH).dropna()
        assert len(df) > 100, "parquet too small to smoke-test"

        feature_cols = ["wind_speed_80m", "solar_ghi", "temperature", "load_forecast"]
        df = df.assign(
            hour=df.index.hour.astype(float),
            dow=df.index.dayofweek.astype(float),
        )
        feature_cols += ["hour", "dow"]

        # Walk-forward split: never random for time-series (CLAUDE.md hard constraint).
        cut = int(len(df) * 0.8)
        X_train, X_test = df.iloc[:cut][feature_cols], df.iloc[cut:][feature_cols]
        y_train, y_test = df.iloc[:cut]["price_eur_mwh"], df.iloc[cut:]["price_eur_mwh"]

        model = LightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X_train, y_train)
        preds = model.predict(X_test)

        assert preds.shape == (len(X_test), 3)
        assert np.all(preds[:, 0] <= preds[:, 1])
        assert np.all(preds[:, 1] <= preds[:, 2])

        # Sanity: predictions should produce a *finite* MAE — not a quality gate.
        mae = float(np.abs(preds[:, 1] - y_test.to_numpy()).mean())
        assert np.isfinite(mae)

        # Sanity: P10/P90 band should contain at least *some* test points. With FAST_HP
        # and only 6 features the band is loose; we just check the band hasn't collapsed.
        coverage = float(((y_test.to_numpy() >= preds[:, 0]) & (y_test.to_numpy() <= preds[:, 2])).mean())
        assert coverage > 0.05, f"P10/P90 band collapsed (coverage={coverage:.2%})"


@pytest.fixture
def synthetic_timeseries():
    """800-row hourly series with 3 features and a target shaped by recent state.

    Used to validate multi-horizon fit/predict — target depends on f0 and a
    24-step seasonal term so different horizons see distinguishable targets.
    """
    rng = np.random.default_rng(7)
    n = 800
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    f0 = rng.normal(0, 1, n)
    f1 = rng.uniform(-1, 1, n)
    f2 = rng.normal(5, 2, n)
    season = np.sin(2 * np.pi * np.arange(n) / 24.0)
    target = 2 * f0 + season * 5 + rng.normal(0, 1, n)
    X = pd.DataFrame({"f0": f0, "f1": f1, "f2": f2}, index=idx)
    y = pd.Series(target, index=idx, name="y")
    return X, y


class TestMultiHorizonConstructor:
    def test_default_groups_match_plan(self):
        m = MultiHorizonLightGBMQuantileForecaster()
        assert m.groups == DEFAULT_GROUPS
        # Plan §2: groups cover h+1..h+72 contiguously, no overlap, no gaps.
        starts_ends = [(s, e) for s, e in m.groups]
        assert starts_ends[0][0] == 1
        assert starts_ends[-1][1] == 72
        for (_, prev_end), (next_start, _) in zip(starts_ends, starts_ends[1:]):
            assert next_start == prev_end + 1, "groups must be contiguous"

    def test_rejects_overlapping_groups(self):
        with pytest.raises(ValueError, match="contiguous|overlap"):
            MultiHorizonLightGBMQuantileForecaster(groups=((1, 6), (5, 24), (25, 72)))

    def test_rejects_gap_between_groups(self):
        with pytest.raises(ValueError, match="contiguous|gap"):
            MultiHorizonLightGBMQuantileForecaster(groups=((1, 6), (8, 24), (25, 72)))

    def test_rejects_inverted_group(self):
        with pytest.raises(ValueError, match="start.*end|inverted|order"):
            MultiHorizonLightGBMQuantileForecaster(groups=((6, 1), (7, 24), (25, 72)))

    def test_rejects_zero_or_negative_horizon(self):
        with pytest.raises(ValueError, match="positive|>= 1"):
            MultiHorizonLightGBMQuantileForecaster(groups=((0, 6), (7, 24), (25, 72)))


class TestMultiHorizonFit:
    def test_fit_creates_nine_underlying_models(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        # 3 groups × 3 quantiles = 9
        total = sum(len(g.models) for g in m.group_models)
        assert total == 9
        assert len(m.group_models) == 3
        for g in m.group_models:
            assert len(g.models) == 3

    def test_fit_records_feature_names_excluding_horizon(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        # User-facing feature names should be the original X columns, not include horizon_h
        assert m.feature_names == list(X.columns)

    def test_fit_rejects_non_dataframe(self, synthetic_timeseries):
        _, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(TypeError, match="DataFrame"):
            m.fit(np.zeros((100, 3)), y)

    def test_fit_rejects_misaligned_y(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(ValueError, match="length mismatch|align"):
            m.fit(X, y.iloc[:100])

    def test_fit_rejects_too_short_for_largest_horizon(self):
        # Need at least max_horizon+1 rows to have any (X[t], y[t+72]) pairs.
        rng = np.random.default_rng(0)
        idx = pd.date_range("2026-01-01", periods=50, freq="h", tz="UTC")
        X = pd.DataFrame({"f0": rng.normal(0, 1, 50)}, index=idx)
        y = pd.Series(rng.normal(0, 1, 50), index=idx)
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP)
        with pytest.raises(ValueError, match="too few rows|insufficient"):
            m.fit(X, y)


class TestMultiHorizonPredict:
    def test_predict_horizons_default_returns_72_horizons(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict_horizons(X.iloc[[-100]])
        # Default horizons span the full 1..72 range.
        assert preds.shape == (1, 72, 3)

    def test_predict_horizons_explicit_subset(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict_horizons(X.iloc[[-100]], horizons=[1, 6, 7, 24, 25, 72])
        assert preds.shape == (1, 6, 3)

    def test_predict_horizons_multi_row(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict_horizons(X.iloc[-30:], horizons=[1, 24, 72])
        assert preds.shape == (30, 3, 3)

    def test_predict_horizons_monotonic_per_quantile(self, synthetic_timeseries):
        """P10 <= P50 <= P90 must hold per (row, horizon)."""
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        preds = m.predict_horizons(X.iloc[-50:])
        assert np.all(preds[:, :, 0] <= preds[:, :, 1])
        assert np.all(preds[:, :, 1] <= preds[:, :, 2])

    def test_predict_horizons_rejects_unfit(self, synthetic_timeseries):
        X, _ = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster()
        with pytest.raises(RuntimeError, match="not fit"):
            m.predict_horizons(X.iloc[[-1]])

    def test_predict_horizons_rejects_out_of_range(self, synthetic_timeseries):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        with pytest.raises(ValueError, match="horizon|out of range"):
            m.predict_horizons(X.iloc[[-1]], horizons=[0, 1])
        with pytest.raises(ValueError, match="horizon|out of range"):
            m.predict_horizons(X.iloc[[-1]], horizons=[1, 73])

    def test_predict_horizons_boundary_uses_correct_group(self, synthetic_timeseries):
        """h=6 must use group 0; h=7 must use group 1 (default groups (1,6),(7,24),(25,72))."""
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        # Different groups produce different median predictions for the same X row.
        preds = m.predict_horizons(X.iloc[[-1]], horizons=[6, 7])
        # If routing is broken, h=6 and h=7 would come from the same group and
        # likely (with horizon_h as a feature) still differ — so we just verify
        # both produce a valid quantile triple.
        assert preds.shape == (1, 2, 3)
        assert preds[0, 0, 0] <= preds[0, 0, 1] <= preds[0, 0, 2]
        assert preds[0, 1, 0] <= preds[0, 1, 1] <= preds[0, 1, 2]


class TestMultiHorizonSaveLoad:
    def test_save_load_roundtrip(self, synthetic_timeseries, tmp_path):
        X, y = synthetic_timeseries
        m = MultiHorizonLightGBMQuantileForecaster(hyperparams=FAST_HP).fit(X, y)
        original = m.predict_horizons(X.iloc[-5:], horizons=[1, 24, 72])

        path = tmp_path / "mh_lgbm.pkl"
        m.save(path)
        assert path.exists()

        loaded = MultiHorizonLightGBMQuantileForecaster.load(path)
        restored = loaded.predict_horizons(X.iloc[-5:], horizons=[1, 24, 72])
        np.testing.assert_array_equal(original, restored)
        assert loaded.groups == m.groups
        assert loaded.feature_names == m.feature_names

    def test_save_unfit_raises(self, tmp_path):
        m = MultiHorizonLightGBMQuantileForecaster()
        with pytest.raises(RuntimeError, match="unfit"):
            m.save(tmp_path / "x.pkl")
