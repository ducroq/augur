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

from ml.shadow.features_pandas import build_features
from ml.shadow.lightgbm_quantile import MultiHorizonLightGBMQuantileForecaster
from ml.shadow.secure_pickle import HMAC_KEY_ENV, sidecar_path
from ml.shadow.update_shadow import (
    DEFAULT_PARQUET,
    HORIZONS,
    MAX_HISTORY_DAYS,
    SHADOW_MODEL_FILENAME,
    SHADOW_STATE_FILENAME,
    backfill_realized,
    classify_t0_advance,
    compute_cqr_q,
    format_forecast_dicts,
    latest_feasible_t0,
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

    def test_n_calib_days_counts_only_window(self):
        """n_calib_days must reflect days actually in apply_cqr's [cutoff_start, cutoff_end)
        window, not the entire calibration_history (which can span much longer)."""
        rows = []
        # 30 days of calibration but apply_cqr will only use the trailing 7
        for d in range(30):
            day_str = (pd.Timestamp("2026-04-01") + pd.Timedelta(days=d)).strftime("%Y-%m-%d")
            for h in range(24):
                ts = f"{day_str}T{h:02d}:00:00+00:00"
                rows.append({
                    "timestamp_utc": ts, "eval_day": day_str,
                    "p10": 10.0, "p50": 20.0, "p90": 30.0, "realized": 25.0,
                })
        # today is 2026-04-30; calib_days=7 → window is [2026-04-23, 2026-04-30)
        # which contains 7 distinct days (4-23 .. 4-29)
        _, n_days = compute_cqr_q(rows, today="2026-04-30", calib_days=7)
        assert n_days == 7

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


# --- t0-advance guard --------------------------------------------------------


class TestClassifyT0Advance:
    """Guard against the two ways the vintage stream breaks silently.

    Both shapes were live 2026-08-23..27 behind a late EDH publish and stayed
    invisible for three days; see memory/gotcha-log.md.
    """

    def test_healthy_one_day_step_is_silent(self):
        advance, alarm = classify_t0_advance(
            "2026-08-26T21:00:00+00:00", pd.Timestamp("2026-08-27T21:00:00+00:00")
        )
        assert advance == 1
        assert alarm is None

    def test_partial_delivery_day_still_counts_as_one_step(self):
        """08-26T21 -> 08-27T20 is 23h, not 24 — a healthy step all the same.

        How much of the delivery day EDH has published moves the last realised
        hour around, so the guard compares calendar dates, not elapsed hours.
        """
        advance, alarm = classify_t0_advance(
            "2026-08-26T21:00:00+00:00", pd.Timestamp("2026-08-27T20:00:00+00:00")
        )
        assert advance == 1
        assert alarm is None

    def test_repeated_t0_alarms(self):
        """The 2026-08-27 shape: stale parquet, vintage overwritten by dedup."""
        advance, alarm = classify_t0_advance(
            "2026-08-27T20:00:00+00:00", pd.Timestamp("2026-08-27T20:00:00+00:00")
        )
        assert advance == 0
        assert alarm is not None and "did not advance" in alarm

    def test_jumped_t0_alarms_with_skipped_count(self):
        """The 2026-08-25 shape: parquet caught up two days, one vintage lost."""
        advance, alarm = classify_t0_advance(
            "2026-08-24T21:00:00+00:00", pd.Timestamp("2026-08-26T21:00:00+00:00")
        )
        assert advance == 2
        assert alarm is not None and "1 vintage(s) skipped" in alarm

    def test_backwards_t0_alarms(self):
        advance, alarm = classify_t0_advance(
            "2026-08-27T21:00:00+00:00", pd.Timestamp("2026-08-26T21:00:00+00:00")
        )
        assert advance == -1
        assert alarm is not None and "BACKWARDS" in alarm

    def test_first_run_has_nothing_to_compare(self):
        assert classify_t0_advance(None, pd.Timestamp("2026-08-27T21:00:00+00:00")) == (
            None,
            None,
        )

    def test_accepts_timestamp_as_well_as_iso_string(self):
        advance, _ = classify_t0_advance(
            pd.Timestamp("2026-08-26T21:00:00+00:00"),
            pd.Timestamp("2026-08-27T21:00:00+00:00"),
        )
        assert advance == 1


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

        # Signed pickle round-trips through the model's HMAC-verified loader
        model = MultiHorizonLightGBMQuantileForecaster.load(
            shadow_dir / SHADOW_MODEL_FILENAME
        )
        assert hasattr(model, "predict_horizons")


class TestLatestFeasibleT0:
    """t0 must be an hour the model can actually build a feature row for.

    Regression cover for the 2026-08-30 production failure: EDH's load feed
    halved from 48h to 24h while the price feed stayed at 48h, so
    `t0 = price.dropna().index.max()` landed on an hour with a part-NaN
    feature row and `predict_72h` raised, losing the vintage.
    """

    @staticmethod
    def _frame(price_end, load_end, start="2026-06-01 00:00"):
        """Parquet-shaped frame where price and load can end at different hours."""
        idx = pd.date_range(start, price_end, freq="h", tz="UTC")
        rng = np.random.default_rng(0)
        df = pd.DataFrame(
            {
                "price_eur_mwh": rng.normal(100, 20, len(idx)),
                "wind_speed_80m": rng.normal(8, 2, len(idx)),
                "solar_ghi": rng.uniform(0, 400, len(idx)),
                "temperature": rng.normal(15, 5, len(idx)),
                "load_forecast": rng.normal(14000, 1500, len(idx)),
            },
            index=idx,
        )
        df.index.name = "timestamp_utc"
        df.loc[df.index > pd.Timestamp(load_end, tz="UTC"), "load_forecast"] = np.nan
        return df

    def test_matched_horizons_leave_t0_at_the_price_max(self):
        df = self._frame("2026-08-31 21:00", "2026-08-31 21:00")
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, short = latest_feasible_t0(df, price_t0)
        assert t0 == price_t0
        assert short == []

    def test_short_load_feed_holds_t0_back_to_the_last_complete_row(self):
        """The exact 2026-08-30 shape: price to 48h, load to 24h."""
        df = self._frame("2026-08-31 21:00", "2026-08-30 21:00")
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, short = latest_feasible_t0(df, price_t0)
        assert t0 == pd.Timestamp("2026-08-30 21:00", tz="UTC")
        assert t0 < price_t0
        assert short == ["load_forecast"]

    def test_the_held_back_t0_actually_yields_a_usable_feature_row(self):
        """The point of the fix — predict_72h must stop raising."""
        df = self._frame("2026-08-31 21:00", "2026-08-30 21:00")
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, _ = latest_feasible_t0(df, price_t0)
        feats = build_features(df.loc[df.index <= t0])
        assert not feats.loc[[t0]].dropna().empty
        # and the naive anchor is exactly what used to blow up
        assert build_features(df.loc[df.index <= price_t0]).loc[[price_t0]].dropna().empty

    def test_every_short_feed_is_named_for_the_upstream_diagnostic(self):
        df = self._frame("2026-08-31 21:00", "2026-08-30 21:00")
        df.loc[df.index > pd.Timestamp("2026-08-29 21:00", tz="UTC"), "solar_ghi"] = np.nan
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, short = latest_feasible_t0(df, price_t0)
        assert set(short) == {"load_forecast", "solar_ghi"}
        # t0 is bounded by the SHORTEST feed, not the first one found
        assert t0 == pd.Timestamp("2026-08-29 21:00", tz="UTC")

    def test_all_nan_column_is_not_reported_as_short(self):
        """A column that is empty everywhere is a different problem; do not
        blame it for truncation or it drowns the real signal."""
        df = self._frame("2026-08-31 21:00", "2026-08-31 21:00")
        df["gas_ttf_eur_mwh"] = np.nan
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        _, short = latest_feasible_t0(df, price_t0)
        assert "gas_ttf_eur_mwh" not in short

    def test_no_clean_row_anywhere_returns_none(self):
        df = self._frame("2026-08-31 21:00", "2026-08-31 21:00")
        df["load_forecast"] = np.nan
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, _ = latest_feasible_t0(df, price_t0)
        assert t0 is None

    def test_holding_t0_back_can_restore_a_healthy_advance(self):
        """Scenario-dependent, and deliberately not claimed as a general property.

        Holding t0 back changes what the advance guard sees. WHEN the last
        complete row happens to sit one day on from the previous run, the guard
        reads healthy. It does NOT follow that the fix repairs a skipped
        vintage: on the live 2026-08-31 parquet the held-back anchor is
        2026-08-31 03:00, still two calendar days on from 08-29, and `t0 jumped
        2d` fires — correctly, because the 08-30 vintage really was lost. The
        fix stops the crash; it does not resurrect data."""
        df = self._frame("2026-08-31 21:00", "2026-08-30 21:00")
        price_t0 = df["price_eur_mwh"].dropna().index.max()
        t0, _ = latest_feasible_t0(df, price_t0)
        advance, alarm = classify_t0_advance("2026-08-29T21:00:00+00:00", t0)
        assert advance == 1
        assert alarm is None
        # the naive anchor is what produced the 2-day jump
        advance_naive, alarm_naive = classify_t0_advance(
            "2026-08-29T21:00:00+00:00", price_t0
        )
        assert advance_naive == 2
        assert alarm_naive is not None
