"""Tests for ml.shadow.backtest — walk-forward correctness, no leakage."""

import numpy as np
import pandas as pd
import pytest

from ml.shadow.backtest import (
    BacktestConfig,
    compute_metrics,
    per_day_metrics,
    walk_forward_backtest,
)


@pytest.fixture
def synthetic_parquet(tmp_path):
    """60 days of hourly synthetic data — enough for a small walk-forward run."""
    n = 60 * 24
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    rng = np.random.default_rng(7)
    df = pd.DataFrame(
        {
            "price_eur_mwh": 50 + 20 * np.sin(2 * np.pi * np.arange(n) / 24)
            + rng.normal(0, 5, n),
            "wind_speed_80m": rng.uniform(0, 15, n),
            "solar_ghi": rng.uniform(0, 800, n),
            "temperature": rng.uniform(0, 25, n),
            "load_forecast": rng.uniform(8000, 18000, n),
        },
        index=idx,
    )
    df.index.name = "timestamp_utc"
    path = tmp_path / "synth.parquet"
    df.to_parquet(path)
    return path


class TestWalkForward:
    def test_runs_end_to_end(self, synthetic_parquet):
        cfg = BacktestConfig(
            parquet_path=synthetic_parquet,
            eval_start=pd.Timestamp("2026-02-01", tz="UTC"),
            eval_end=pd.Timestamp("2026-02-04", tz="UTC"),
            window_days=14,
        )
        preds = walk_forward_backtest(cfg)
        # 3 days × 24 hours, allowing for any boundary drops.
        assert 60 <= len(preds) <= 72
        assert preds["eval_day"].nunique() == 3

    def test_predictions_are_quantile_ordered(self, synthetic_parquet):
        cfg = BacktestConfig(
            parquet_path=synthetic_parquet,
            eval_start=pd.Timestamp("2026-02-01", tz="UTC"),
            eval_end=pd.Timestamp("2026-02-03", tz="UTC"),
            window_days=14,
        )
        preds = walk_forward_backtest(cfg)
        assert (preds["p10"] <= preds["p50"]).all()
        assert (preds["p50"] <= preds["p90"]).all()

    def test_eval_window_uses_only_past_data_for_training(self, synthetic_parquet, monkeypatch):
        """If we corrupt eval-day prices, predictions for that day must be unaffected
        by the corruption (training cuts off at day_start, eval features for day D
        use pre-D lags only since lag_1h at D 00:00 = price at D-1 23:00)."""
        df = pd.read_parquet(synthetic_parquet)
        cfg = BacktestConfig(
            parquet_path=synthetic_parquet,
            eval_start=pd.Timestamp("2026-02-15", tz="UTC"),
            eval_end=pd.Timestamp("2026-02-16", tz="UTC"),
            window_days=14,
        )
        preds_clean = walk_forward_backtest(cfg)

        # Corrupt the realized prices on the eval day itself (but not before).
        corrupt_mask = (df.index >= cfg.eval_start) & (df.index < cfg.eval_end)
        df_corrupt = df.copy()
        df_corrupt.loc[corrupt_mask, "price_eur_mwh"] += 10000.0
        corrupt_path = synthetic_parquet.parent / "corrupt.parquet"
        df_corrupt.to_parquet(corrupt_path)

        cfg_corrupt = BacktestConfig(
            parquet_path=corrupt_path,
            eval_start=cfg.eval_start,
            eval_end=cfg.eval_end,
            window_days=cfg.window_days,
        )
        preds_corrupt = walk_forward_backtest(cfg_corrupt)

        # Training cuts off before eval_start. The first eval hour at 00:00 UTC has
        # lag_1h = price at the prior day's 23:00 (clean in both runs), so its P50
        # must be identical. Later hours of the same day differ because lag features
        # at e.g. 12:00 use the corrupted 11:00 price — that's the whole point of
        # "perfect-lag" eval, and confirms the harness consumes the realized series
        # for lags rather than ignoring the eval data.
        first_clean = preds_clean.iloc[0]
        first_corrupt = preds_corrupt.iloc[0]
        assert first_clean["timestamp_utc"] == first_corrupt["timestamp_utc"]
        assert first_clean["p50"] == pytest.approx(first_corrupt["p50"])


class TestMetrics:
    def test_compute_metrics_shape(self):
        preds = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-04-15", periods=48, freq="h", tz="UTC"),
                "eval_day": (["2026-04-15"] * 24) + (["2026-04-16"] * 24),
                "realized": np.linspace(-20, 80, 48),
                "p10": np.linspace(-30, 70, 48),
                "p50": np.linspace(-15, 85, 48),
                "p90": np.linspace(0, 100, 48),
                "n_train": [600] * 48,
            }
        )
        m = compute_metrics(preds)
        assert m["n_hours"] == 48
        assert m["n_eval_days"] == 2
        assert m["mae_overall"] > 0
        assert 0.0 <= m["p80_band_coverage"] <= 1.0
        assert m["n_low_price_hours"] > 0  # synthetic data has some <30
        # 2026-04-15 is Wed, 04-16 is Thu — both weekdays — so 16-19 UTC hits.
        assert m["n_evening_peak_hours"] == 8

    def test_per_day_metrics(self):
        preds = pd.DataFrame(
            {
                "timestamp_utc": pd.date_range("2026-04-15", periods=48, freq="h", tz="UTC"),
                "eval_day": (["2026-04-15"] * 24) + (["2026-04-16"] * 24),
                "realized": np.linspace(0, 100, 48),
                "p10": np.linspace(-10, 90, 48),
                "p50": np.linspace(0, 100, 48),  # exact match → MAE=0
                "p90": np.linspace(10, 110, 48),
                "n_train": [600] * 48,
            }
        )
        d = per_day_metrics(preds)
        assert len(d) == 2
        assert (d["mae"] < 1e-9).all()
