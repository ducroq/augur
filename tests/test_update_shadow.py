"""Tests for ml/shadow/update_shadow.py — orchestration + helpers.

Pure-helper tests cover backfill / trim / CQR-q logic with synthetic data.
Parquet smoke verifies the full run_shadow_update against the bootstrapped
parquet when present (skipped otherwise).
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.shadow.secure_pickle import HMAC_KEY_ENV, load_verified_pickle, sidecar_path
from ml.shadow.update_shadow import (
    DEFAULT_PARQUET,
    HORIZONS,
    MAX_HISTORY_DAYS,
    SHADOW_MODEL_FILENAME,
    SHADOW_STATE_FILENAME,
    backfill_realized,
    compute_cqr_q,
    format_forecast_dicts,
    load_shadow_state,
    run_shadow_update,
    save_shadow_state,
    select_training_window,
    trim_to_recent_days,
    widen_with_cqr,
    write_forecast_json,
)


@pytest.fixture
def hmac_key_env(monkeypatch):
    monkeypatch.setenv(HMAC_KEY_ENV, base64.b64encode(b"k" * 32).decode("ascii"))


# --- helper: pending/realized -----------------------------------------------


def _pending_entry(ts: str, eval_day: str, p10=10.0, p50=20.0, p90=30.0) -> dict:
    return {"timestamp_utc": ts, "eval_day": eval_day, "p10": p10, "p50": p50, "p90": p90}


class TestBackfillRealized:
    def test_pending_with_known_realized_moves(self):
        ts1 = "2026-04-29T12:00:00+00:00"
        ts2 = "2026-04-29T13:00:00+00:00"
        pending = [
            _pending_entry(ts1, "2026-04-29"),
            _pending_entry(ts2, "2026-04-29"),
        ]
        idx = pd.DatetimeIndex(
            [pd.Timestamp(ts1), pd.Timestamp(ts2)], tz="UTC"
        )
        parquet = pd.DataFrame({"price_eur_mwh": [50.0, 55.0]}, index=idx)

        realized, still_pending = backfill_realized(pending, parquet)

        assert len(realized) == 2
        assert all("realized" in r for r in realized)
        assert realized[0]["realized"] == 50.0
        assert realized[1]["realized"] == 55.0
        assert still_pending == []

    def test_pending_with_unknown_timestamps_stays_pending(self):
        pending = [_pending_entry("2026-04-30T12:00:00+00:00", "2026-04-30")]
        parquet = pd.DataFrame(
            {"price_eur_mwh": [40.0]},
            index=pd.DatetimeIndex(["2026-04-29T00:00:00+00:00"], tz="UTC"),
        )
        realized, still_pending = backfill_realized(pending, parquet)
        assert realized == []
        assert len(still_pending) == 1

    def test_empty_pending(self):
        parquet = pd.DataFrame(
            {"price_eur_mwh": [40.0]},
            index=pd.DatetimeIndex(["2026-04-29T00:00:00+00:00"], tz="UTC"),
        )
        assert backfill_realized([], parquet) == ([], [])

    def test_empty_parquet_keeps_pending(self):
        pending = [_pending_entry("2026-04-30T12:00:00+00:00", "2026-04-30")]
        empty = pd.DataFrame({"price_eur_mwh": pd.Series([], dtype=float)})
        realized, still_pending = backfill_realized(pending, empty)
        assert realized == []
        assert still_pending == pending

    def test_nan_realised_in_parquet_is_skipped(self):
        ts = "2026-04-29T12:00:00+00:00"
        pending = [_pending_entry(ts, "2026-04-29")]
        idx = pd.DatetimeIndex([pd.Timestamp(ts)], tz="UTC")
        parquet = pd.DataFrame({"price_eur_mwh": [np.nan]}, index=idx)
        realized, still_pending = backfill_realized(pending, parquet)
        assert realized == []
        assert len(still_pending) == 1


class TestTrimToRecentDays:
    def test_trim_keeps_max_days(self):
        rows = []
        for d in range(40):
            day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
            for h in range(24):
                ts = f"{day}T{h:02d}:00:00+00:00"
                rows.append(_pending_entry(ts, day))
        trimmed = trim_to_recent_days(rows, max_days=MAX_HISTORY_DAYS)
        days = sorted({r["eval_day"] for r in trimmed})
        assert len(days) == MAX_HISTORY_DAYS
        assert days[-1] == "2026-02-09"  # 2026-01-01 + 39 days

    def test_trim_zero_days_returns_empty(self):
        rows = [_pending_entry("2026-04-29T12:00:00+00:00", "2026-04-29")]
        assert trim_to_recent_days(rows, max_days=0) == []

    def test_trim_no_op_below_cap(self):
        rows = [
            _pending_entry("2026-04-29T12:00:00+00:00", "2026-04-29"),
            _pending_entry("2026-04-30T12:00:00+00:00", "2026-04-30"),
        ]
        out = trim_to_recent_days(rows, max_days=30)
        assert out == rows


class TestComputeCqrQ:
    def test_no_history_returns_zero(self):
        q, n_days = compute_cqr_q([], today="2026-04-30")
        assert q == 0.0
        assert n_days == 0

    def test_history_without_realized_returns_zero(self):
        # Predictions logged but never realised
        rows = [
            _pending_entry("2026-04-29T12:00:00+00:00", "2026-04-29"),
        ]
        q, n_days = compute_cqr_q(rows, today="2026-04-30")
        assert q == 0.0

    def test_q_increases_when_realised_breaks_band(self):
        """Realised values OUTSIDE [p10, p90] yield positive q to widen bands."""
        rows = []
        # 4 days x 24 hourly, realised systematically above p90 → q > 0
        for d in range(4):
            day_str = (pd.Timestamp("2026-04-25") + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
            for h in range(24):
                ts = f"{day_str}T{h:02d}:00:00+00:00"
                rows.append({
                    "timestamp_utc": ts,
                    "eval_day": day_str,
                    "p10": 10.0, "p50": 20.0, "p90": 30.0,
                    "realized": 100.0,  # way above p90 → nonconformity 70
                })
        q, n_days = compute_cqr_q(rows, today="2026-04-29", calib_days=7)
        assert q > 0
        assert n_days == 4

    def test_q_zero_when_not_enough_calib_days(self):
        # apply_cqr's MIN_CALIB_DAYS=3 — give 2 distinct days only
        rows = []
        for d in range(2):
            day_str = (pd.Timestamp("2026-04-28") + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
            ts = f"{day_str}T12:00:00+00:00"
            rows.append({
                "timestamp_utc": ts,
                "eval_day": day_str,
                "p10": 10.0, "p50": 20.0, "p90": 30.0,
                "realized": 100.0,
            })
        q, n_days = compute_cqr_q(rows, today="2026-04-30")
        assert q == 0.0


class TestSelectTrainingWindow:
    def test_window_inclusive_endpoints(self):
        idx = pd.date_range("2026-01-01", periods=200, freq="h", tz="UTC")
        df = pd.DataFrame({"price_eur_mwh": np.arange(200, dtype=float)}, index=idx)
        t0 = pd.Timestamp("2026-01-08T00:00:00", tz="UTC")
        window = select_training_window(df, t0, window_days=2)
        # 2 days back + t0 → 49 hourly rows (inclusive)
        assert len(window) == 49
        assert window.index.min() == pd.Timestamp("2026-01-06T00:00:00", tz="UTC")
        assert window.index.max() == t0


class TestWidenWithCqr:
    def test_q_widens_symmetrically(self):
        df = pd.DataFrame({
            "timestamp_utc": [pd.Timestamp("2026-04-30T01:00:00", tz="UTC")],
            "p10": [10.0], "p50": [20.0], "p90": [30.0],
        })
        out = widen_with_cqr(df, q=5.0)
        assert out["p10_cqr"].iloc[0] == 5.0
        assert out["p90_cqr"].iloc[0] == 35.0
        # Original p10/p90 should remain
        assert out["p10"].iloc[0] == 10.0
        assert out["p90"].iloc[0] == 30.0


class TestFormatForecastDicts:
    def test_round_to_two_decimals_and_iso_keys(self):
        df = pd.DataFrame({
            "timestamp_utc": [
                pd.Timestamp("2026-04-30T01:00:00", tz="UTC"),
                pd.Timestamp("2026-04-30T02:00:00", tz="UTC"),
            ],
            "p10": [9.5, 11.5], "p50": [20.0, 21.0], "p90": [30.5, 31.5],
            "p10_cqr": [4.5, 6.5], "p90_cqr": [35.5, 36.5],
        })
        forecast, upper, lower = format_forecast_dicts(df)
        keys = list(forecast.keys())
        assert "2026-04-30T01:00:00+00:00" in keys
        assert forecast[keys[0]] == 20.0
        assert upper[keys[0]] == 35.5
        assert lower[keys[0]] == 4.5


class TestStateRoundtrip:
    def test_load_missing_returns_empty_state(self, tmp_path):
        state = load_shadow_state(tmp_path / SHADOW_STATE_FILENAME)
        assert state["pending_predictions"] == []
        assert state["calibration_history"] == []
        assert state["last_run_utc"] is None

    def test_save_load_roundtrip(self, tmp_path):
        path = tmp_path / SHADOW_STATE_FILENAME
        state = {
            "pending_predictions": [_pending_entry("2026-04-30T01:00:00+00:00", "2026-04-30")],
            "calibration_history": [],
            "last_run_utc": "2026-04-30T17:00:00+00:00",
            "last_train_window": {"start": "...", "end": "..."},
            "n_train_samples": 1024,
            "last_cqr_q": 4.2,
            "last_cqr_n_calib_days": 7,
        }
        save_shadow_state(state, path)
        restored = load_shadow_state(path)
        assert restored == state


class TestWriteForecastJson:
    def test_payload_shape_matches_dashboard_schema(self, tmp_path):
        out_path = tmp_path / "augur_forecast_shadow.json"
        write_forecast_json(
            out_path,
            forecast={"2026-04-30T01:00:00+00:00": 20.0},
            upper={"2026-04-30T01:00:00+00:00": 35.0},
            lower={"2026-04-30T01:00:00+00:00": 5.0},
            metadata={"model": "LightGBM-Quantile-Multi-Horizon", "cqr_q": 5.0},
        )
        with open(out_path) as f:
            payload = json.load(f)
        assert set(payload.keys()) == {"metadata", "forecast", "forecast_upper", "forecast_lower"}
        assert payload["metadata"]["model"] == "LightGBM-Quantile-Multi-Horizon"
        assert payload["forecast"]["2026-04-30T01:00:00+00:00"] == 20.0


# --- end-to-end parquet smoke -----------------------------------------------


@pytest.mark.skipif(not DEFAULT_PARQUET.exists(), reason="bootstrap parquet not present")
class TestRunShadowUpdateSmoke:
    """Full pipeline smoke: parquet -> trained model -> signed pickle + JSON.

    Not a quality bar — just verifies orchestration runs without exceptions
    and produces the expected file layout.
    """

    def test_first_run_produces_artifacts(self, tmp_path, hmac_key_env):
        shadow_dir = tmp_path / "shadow_models"
        forecast_out = tmp_path / "augur_forecast_shadow.json"

        state = run_shadow_update(
            parquet_path=DEFAULT_PARQUET,
            shadow_dir=shadow_dir,
            forecast_out=forecast_out,
        )

        # Files present
        assert (shadow_dir / SHADOW_STATE_FILENAME).exists()
        assert (shadow_dir / SHADOW_MODEL_FILENAME).exists()
        assert sidecar_path(shadow_dir / SHADOW_MODEL_FILENAME).exists()
        assert forecast_out.exists()

        # Pending_predictions populated with 72 entries (h=1..72)
        assert len(state["pending_predictions"]) == 72
        # Calibration empty (no prior runs)
        assert state["calibration_history"] == []

        # Forecast JSON is a 72-hour band-shaped payload
        with open(forecast_out) as f:
            payload = json.load(f)
        assert len(payload["forecast"]) == 72
        assert len(payload["forecast_upper"]) == 72
        assert len(payload["forecast_lower"]) == 72
        # Metadata pins the design
        meta = payload["metadata"]
        assert meta["model"] == "LightGBM-Quantile-Multi-Horizon"
        assert meta["window_days"] == 56
        assert meta["cqr_target_coverage"] == 0.80
        assert meta["cqr_calib_days_used"] == 0  # first run

        # Signed pickle round-trips
        model = load_verified_pickle(shadow_dir / SHADOW_MODEL_FILENAME)
        assert hasattr(model, "predict_horizons")
