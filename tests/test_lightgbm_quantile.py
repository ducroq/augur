"""Tests for LightGBMQuantileForecaster — fit/predict/save/load + parquet smoke."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.shadow.lightgbm_quantile import (
    DEFAULT_QUANTILES,
    LGBMHyperparams,
    LightGBMQuantileForecaster,
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
