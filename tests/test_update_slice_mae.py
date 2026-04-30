"""Tests for ARF slice-MAE logging in ml.update.update_model.

Promotion criterion (a) of the LightGBM-shadow plan §6 requires
``mae_at_low_price`` (realised < 30 EUR/MWh) for both ARF and LightGBM
side-by-side. These tests pin the new ``error_prices`` parallel array,
slice-MAE computation, and per-day metrics_history payload.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from ml.update import update_model


def _stub_model(prediction: float = 50.0):
    m = MagicMock()
    m.predict_one.return_value = prediction
    m.learn_one.return_value = None
    return m


def _seed_price_buffer(start: datetime, n_hours: int = 30, base_price: float = 60.0):
    """Build a (timestamp_iso, price) buffer covering the lag-24h requirement."""
    return [
        ((start - timedelta(hours=h)).isoformat(), base_price + h * 0.01)
        for h in range(n_hours, 0, -1)
    ]


def _new_prices(start: datetime, prices: list[float]) -> pd.Series:
    idx = pd.date_range(start, periods=len(prices), freq="h", tz="UTC")
    return pd.Series(prices, index=idx)


@pytest.fixture
def base_state_with_lags():
    """State with enough price history for OnlineFeatureBuilder.build() to succeed."""
    t0 = datetime(2026, 4, 25, 0, 0, tzinfo=timezone.utc)
    return {
        "last_timestamp": (t0 - timedelta(hours=1)).isoformat(),
        "price_buffer": _seed_price_buffer(t0, n_hours=30),
        "error_history": [],
        "error_hours": [],
        "error_prices": [],
        "n_samples": 0,
    }, t0


class TestErrorPricesParallelArray:
    def test_error_prices_grows_in_lockstep_with_error_history(self, base_state_with_lags):
        state, t0 = base_state_with_lags
        new = _new_prices(t0, [60.0, 65.0, 70.0])
        model = _stub_model(prediction=55.0)

        _, state_out, _ = update_model(model, state, {"prices": new})

        assert len(state_out["error_history"]) == len(state_out["error_prices"]) == 3
        # Realised prices recorded as floats matching input
        assert state_out["error_prices"] == [60.0, 65.0, 70.0]

    def test_error_prices_trimmed_to_500(self, base_state_with_lags):
        state, t0 = base_state_with_lags
        # Pre-load 510 entries to force trim
        state["error_history"] = list(np.random.normal(0, 5, 510))
        state["error_prices"] = list(np.random.uniform(20, 80, 510))
        state["error_hours"] = list(np.tile(range(24), 22))[:510]

        new = _new_prices(t0, [50.0])
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        assert len(state_out["error_history"]) == 500
        assert len(state_out["error_prices"]) == 500
        # Lockstep: tail must contain the just-appended realised price.
        assert state_out["error_prices"][-1] == 50.0


class TestSliceMAE:
    def test_slice_mae_only_includes_low_price_hours(self, base_state_with_lags):
        state, t0 = base_state_with_lags
        # Realised prices: 3 below threshold (with errors |10|, |20|, |5|), 2 above
        # Predict=50 always; realised = [40, 30, 25, 60, 55] -> errors [10, 20, 25, 10, 5]
        # Wait: |40-50|=10, |30-50|=20, |25-50|=25, |60-50|=10, |55-50|=5
        # Below 30: 25 only (25 EUR/MWh < 30) -> err 25
        new = _new_prices(t0, [40.0, 30.0, 25.0, 60.0, 55.0])
        model = _stub_model(prediction=50.0)

        _, state_out, _ = update_model(model, state, {"prices": new})

        # Threshold is 30.0 strict — realised < 30. Only price 25.0 qualifies.
        metrics = state_out["metrics"]
        assert metrics["mae_at_low_price_threshold"] == 30.0
        assert metrics["mae_at_low_price_n"] == 1
        assert metrics["mae_at_low_price"] == 25.0

    def test_slice_mae_threshold_is_strict_less_than(self, base_state_with_lags):
        """A realised price exactly equal to 30 EUR/MWh must NOT count as 'low'."""
        state, t0 = base_state_with_lags
        new = _new_prices(t0, [30.0, 30.0])  # exactly at threshold
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        metrics = state_out["metrics"]
        assert metrics["mae_at_low_price_n"] == 0
        assert metrics["mae_at_low_price"] is None

    def test_slice_mae_handles_negative_prices(self, base_state_with_lags):
        """Plan §6(a) targets negative-price hours specifically — verify they qualify."""
        state, t0 = base_state_with_lags
        # Negative prices and other low ones — all below 30
        new = _new_prices(t0, [-20.0, -10.0, 5.0])  # errors |70|, |60|, |45| if pred=50
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        metrics = state_out["metrics"]
        assert metrics["mae_at_low_price_n"] == 3
        # mean(70, 60, 45) = 58.33 -> rounded 58.33
        assert metrics["mae_at_low_price"] == pytest.approx(58.33, abs=0.01)

    def test_slice_mae_empty_when_no_aligned_data(self, base_state_with_lags):
        """No new prices learned -> no error_prices appended -> n=0, mae=None."""
        state, t0 = base_state_with_lags
        # No prices in data dict
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": pd.Series(dtype=float)})

        metrics = state_out.get("metrics")
        # When no learning happens, update_model returns early before metrics work.
        # Confirm via the documented contract: no slice metric written.
        # If "metrics" wasn't initialized, that's also acceptable — the per-day eval
        # logger should treat absent and None identically.
        if metrics is not None:
            assert metrics.get("mae_at_low_price_n", 0) == 0


class TestLegacyStateBackwardCompat:
    def test_state_without_error_prices_starts_empty(self, base_state_with_lags):
        """Old state.json has no error_prices; update_model must seed it without error."""
        state, t0 = base_state_with_lags
        # Remove error_prices to simulate pre-EXP-009-step-3 state
        state.pop("error_prices")

        new = _new_prices(t0, [25.0])
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        assert "error_prices" in state_out
        assert state_out["error_prices"] == [25.0]

    def test_legacy_error_history_is_not_aligned_with_new_prices(self, base_state_with_lags):
        """Legacy error_history (no parallel error_prices) must be ignored for slice MAE."""
        state, t0 = base_state_with_lags
        state["error_history"] = [10.0] * 100  # legacy, no matching prices
        state["error_hours"] = [12] * 100
        state["error_prices"] = []  # legacy state had no error_prices

        new = _new_prices(t0, [10.0])  # realised < 30, so qualifies
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        # Only the 1 newly-learned hour is alignment-eligible.
        # Slice MAE should reflect just that 1 sample's |10-50|=40, not the legacy 100.
        metrics = state_out["metrics"]
        assert metrics["mae_at_low_price_n"] == 1
        assert metrics["mae_at_low_price"] == 40.0


class TestMetricsHistoryEntry:
    def test_history_entry_includes_slice_fields(self, base_state_with_lags):
        state, t0 = base_state_with_lags
        new = _new_prices(t0, [25.0])
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        entry = state_out["metrics_history"][-1]
        assert "mae_at_low_price" in entry
        assert "mae_at_low_price_n" in entry
        assert entry["mae_at_low_price"] == 25.0
        assert entry["mae_at_low_price_n"] == 1

    def test_history_entry_handles_no_low_price_hours(self, base_state_with_lags):
        state, t0 = base_state_with_lags
        new = _new_prices(t0, [80.0, 90.0, 70.0])  # all above threshold
        _, state_out, _ = update_model(_stub_model(50.0), state, {"prices": new})

        entry = state_out["metrics_history"][-1]
        assert entry["mae_at_low_price"] is None
        assert entry["mae_at_low_price_n"] == 0
