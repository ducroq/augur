"""Tests for ml/shadow/evaluate_shadow.py — daily LightGBM-vs-ARF eval logger."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from ml.shadow.evaluate_shadow import (
    LOW_PRICE_THRESHOLD,
    PEAK_HOUR_END,
    PEAK_HOUR_START,
    append_eval_row,
    evaluate_one_day,
    find_arf_archive_for_day,
    find_eligible_eval_days,
    load_arf_predictions,
    load_price_history,
    naive_source_timestamp,
    t0_for_eval_day,
    read_logged_days,
    run_evaluation,
)


# ---------- helpers ---------------------------------------------------------


def _calib_row(ts: pd.Timestamp, day: str, p10: float, p50: float, p90: float, realised: float | None) -> dict:
    return {
        "timestamp_utc": ts.isoformat(),
        "eval_day": day,
        "p10": p10,
        "p50": p50,
        "p90": p90,
        "realized": realised,
    }


def _full_day_calibration(day: str, lgbm_pred: float, realised: float, p10: float, p90: float) -> list[dict]:
    rows = []
    base = pd.Timestamp(day, tz="UTC")
    for h in range(24):
        ts = base + pd.Timedelta(hours=h)
        rows.append(_calib_row(ts, day, p10, lgbm_pred, p90, realised))
    return rows


def _write_arf_archive(forecasts_dir: Path, run_ts: str, predictions: dict[pd.Timestamp, float]) -> Path:
    forecasts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {"model": "ARFRegressor"},
        "forecast": {ts.isoformat(): val for ts, val in predictions.items()},
        "forecast_upper": {},
        "forecast_lower": {},
    }
    path = forecasts_dir / f"{run_ts}_forecast.json"
    with open(path, "w") as f:
        json.dump(payload, f)
    return path


# ---------- ARF archive discovery -------------------------------------------


class TestFindArfArchive:
    def test_picks_most_recent_before_eval_day(self, tmp_path):
        d = tmp_path / "forecasts"
        _write_arf_archive(d, "20260427_1645", {})
        _write_arf_archive(d, "20260428_1645", {})  # one we want
        _write_arf_archive(d, "20260429_1645", {})  # too late, equal-day cutoff
        archive = find_arf_archive_for_day(d, "2026-04-29")
        assert archive is not None
        assert archive.name == "20260428_1645_forecast.json"

    def test_no_archive_returns_none(self, tmp_path):
        d = tmp_path / "forecasts"
        d.mkdir()
        assert find_arf_archive_for_day(d, "2026-04-29") is None

    def test_missing_dir_returns_none(self, tmp_path):
        assert find_arf_archive_for_day(tmp_path / "missing", "2026-04-29") is None

    def test_ignores_malformed_filenames(self, tmp_path):
        d = tmp_path / "forecasts"
        d.mkdir()
        (d / "garbage.json").write_text("{}")
        (d / "no_match_forecast.json").write_text("{}")
        assert find_arf_archive_for_day(d, "2026-04-29") is None


class TestLoadArfPredictions:
    def test_round_trips_iso_keys(self, tmp_path):
        d = tmp_path / "forecasts"
        ts = pd.Timestamp("2026-04-29T12:00:00", tz="UTC")
        archive = _write_arf_archive(d, "20260428_1645", {ts: 50.0})
        preds = load_arf_predictions(archive)
        assert ts in preds
        assert preds[ts] == 50.0

    def test_skips_null_values(self, tmp_path):
        d = tmp_path / "forecasts"
        d.mkdir()
        archive = d / "x_forecast.json"
        with open(archive, "w") as f:
            json.dump({"forecast": {"2026-04-29T01:00:00+00:00": None}}, f)
        assert load_arf_predictions(archive) == {}


# ---------- evaluate_one_day -----------------------------------------------


class TestEvaluateOneDay:
    def test_lightgbm_only_when_no_arf(self):
        # 24 hours, predicted 50.0, realised 60.0 → MAE 10.0
        rows = _full_day_calibration("2026-04-29", lgbm_pred=50.0, realised=60.0, p10=40.0, p90=70.0)
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=None)
        assert out is not None
        assert out["n_overlap_hours"] == 24
        assert out["n_low_price_hours"] == 0
        assert out["lightgbm_mae"] == 10.0
        # realised 60 >= 30, so no low-price slice
        assert out["lightgbm_mae_at_low_price"] is None
        # realised 60 inside [40, 70] → coverage 1.0
        assert out["lightgbm_band_coverage_p80"] == 1.0
        assert out["arf_mae"] is None
        assert out["arf_mae_at_low_price"] is None
        # No ARF predictions → peak fields all null
        assert out["lightgbm_peak_hour_mae"] is None
        assert out["arf_peak_hour_mae"] is None
        assert out["peak_hour_mae_delta"] is None

    def test_lightgbm_vs_arf_full_overlap(self):
        # LightGBM MAE 10 (pred 50, real 60). ARF pred 70 → MAE 10. Delta 0.
        rows = _full_day_calibration("2026-04-29", 50.0, 60.0, 40.0, 70.0)
        ts_to_pred = {pd.Timestamp(r["timestamp_utc"]): 70.0 for r in rows}
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=ts_to_pred)
        assert out["n_overlap_hours"] == 24
        assert out["lightgbm_mae"] == 10.0
        assert out["arf_mae"] == 10.0
        # 2026-04-29 is a Wednesday (UTC). Peak hours 16,17,18,19 = 4 hours.
        # Both models have constant errors on every hour so peak MAE == full-day MAE.
        assert out["lightgbm_peak_hour_mae"] == 10.0
        assert out["arf_peak_hour_mae"] == 10.0
        assert out["peak_hour_mae_delta"] == 0.0

    def test_low_price_slice(self):
        rows = []
        base = pd.Timestamp("2026-04-29", tz="UTC")
        # 12 hours below threshold (real=20, pred=50 → err 30); 12 above (real=60, err 10)
        for h in range(12):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0.0, 50.0, 80.0, 20.0))
        for h in range(12, 24):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0.0, 50.0, 80.0, 60.0))
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=None)
        # Aggregate MAE = (12*30 + 12*10)/24 = 20
        assert out["lightgbm_mae"] == 20.0
        # Slice MAE on real<30 = 30
        assert out["lightgbm_mae_at_low_price"] == 30.0
        # 12 of the 24 hours had realised < 30
        assert out["n_low_price_hours"] == 12

    def test_band_coverage_uses_p10_p90(self):
        # Realised 60, p10=70, p90=80 -> realised below p10 -> coverage 0
        rows = _full_day_calibration("2026-04-29", 75.0, 60.0, 70.0, 80.0)
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=None)
        assert out["lightgbm_band_coverage_p80"] == 0.0

    def test_peak_delta_only_uses_weekday_16_19_utc(self):
        rows = []
        base = pd.Timestamp("2026-04-29", tz="UTC")  # Wednesday (weekday)
        # All 24 hours: lgbm pred 50, arf pred 60, realised 70. Same delta everywhere.
        # Peak: hours 16-19 -> 4 of 24. lgbm_mae 20, arf_mae 10 -> delta = +10
        for h in range(24):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0.0, 50.0, 80.0, 70.0))
        ts_to_arf = {pd.Timestamp(r["timestamp_utc"]): 60.0 for r in rows}
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=ts_to_arf)
        # Both models constant: peak MAE == full-day MAE
        assert out["lightgbm_peak_hour_mae"] == 20.0
        assert out["arf_peak_hour_mae"] == 10.0
        assert out["peak_hour_mae_delta"] == 10.0
        # Sanity: criterion (c) reader can compute relative delta directly from log
        assert out["peak_hour_mae_delta"] / out["arf_peak_hour_mae"] == 1.0

    def test_weekend_has_no_peak_delta(self):
        # 2026-05-02 is a Saturday — no weekday peak hours
        rows = _full_day_calibration("2026-05-02", 50.0, 60.0, 40.0, 70.0)
        ts_to_arf = {pd.Timestamp(r["timestamp_utc"]): 70.0 for r in rows}
        out = evaluate_one_day("2026-05-02", rows, arf_predictions=ts_to_arf)
        # No weekday peak hours → peak fields all null
        assert out["lightgbm_peak_hour_mae"] is None
        assert out["arf_peak_hour_mae"] is None
        assert out["peak_hour_mae_delta"] is None
        # MAE still computed
        assert out["lightgbm_mae"] == 10.0

    def test_missing_realised_skips_hours(self):
        rows = []
        base = pd.Timestamp("2026-04-29", tz="UTC")
        for h in range(20):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0.0, 50.0, 80.0, 60.0))
        for h in range(20, 24):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0.0, 50.0, 80.0, None))
        out = evaluate_one_day("2026-04-29", rows, arf_predictions=None)
        assert out["n_overlap_hours"] == 20

    def test_no_realised_returns_none(self):
        rows = [_calib_row(pd.Timestamp("2026-04-29T01:00", tz="UTC"), "2026-04-29", 0, 0, 0, None)]
        assert evaluate_one_day("2026-04-29", rows, arf_predictions=None) is None


# ---------- eligibility -----------------------------------------------------


class TestFindEligibleEvalDays:
    def test_full_day_unlogged_eligible(self, tmp_path):
        rows = _full_day_calibration("2026-04-29", 50.0, 60.0, 40.0, 70.0)
        log = tmp_path / "eval_log.jsonl"
        eligible = find_eligible_eval_days(rows, log)
        assert eligible == ["2026-04-29"]

    def test_partial_day_excluded(self, tmp_path):
        # Only 12 hours realised
        rows = []
        base = pd.Timestamp("2026-04-29", tz="UTC")
        for h in range(12):
            ts = base + pd.Timedelta(hours=h)
            rows.append(_calib_row(ts, "2026-04-29", 0, 50, 80, 60))
        log = tmp_path / "eval_log.jsonl"
        assert find_eligible_eval_days(rows, log) == []

    def test_logged_day_excluded(self, tmp_path):
        rows = _full_day_calibration("2026-04-29", 50.0, 60.0, 40.0, 70.0)
        log = tmp_path / "eval_log.jsonl"
        log.write_text(json.dumps({"date": "2026-04-29", "n_overlap_hours": 24}) + "\n")
        assert find_eligible_eval_days(rows, log) == []

    def test_multiple_eligible_days_sorted(self, tmp_path):
        rows = (
            _full_day_calibration("2026-04-30", 50, 60, 40, 70)
            + _full_day_calibration("2026-04-29", 50, 60, 40, 70)
        )
        log = tmp_path / "eval_log.jsonl"
        assert find_eligible_eval_days(rows, log) == ["2026-04-29", "2026-04-30"]


class TestReadLoggedDays:
    def test_skips_malformed_lines(self, tmp_path):
        log = tmp_path / "eval_log.jsonl"
        log.write_text(
            json.dumps({"date": "2026-04-28"}) + "\n"
            + "{not json\n"
            + json.dumps({"date": "2026-04-29"}) + "\n"
        )
        assert read_logged_days(log) == {"2026-04-28", "2026-04-29"}

    def test_missing_log_returns_empty(self, tmp_path):
        assert read_logged_days(tmp_path / "missing.jsonl") == set()


# ---------- file IO ---------------------------------------------------------


class TestAppendEvalRow:
    def test_appends_one_line(self, tmp_path):
        log = tmp_path / "eval_log.jsonl"
        append_eval_row({"date": "2026-04-29", "n_overlap_hours": 24}, log)
        append_eval_row({"date": "2026-04-30", "n_overlap_hours": 24}, log)
        lines = log.read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["date"] == "2026-04-29"
        assert json.loads(lines[1])["date"] == "2026-04-30"


# ---------- orchestration ---------------------------------------------------


class TestRunEvaluation:
    def test_appends_eligible_days_only(self, tmp_path):
        shadow_dir = tmp_path / "shadow"
        shadow_dir.mkdir()
        # Build a calibration_history with one full day + one partial
        full_rows = _full_day_calibration("2026-04-29", 50.0, 60.0, 40.0, 70.0)
        # Partial day
        base_partial = pd.Timestamp("2026-04-30", tz="UTC")
        partial_rows = [
            _calib_row(base_partial + pd.Timedelta(hours=h), "2026-04-30", 0, 50, 80, 60)
            for h in range(12)
        ]
        state = {
            "pending_predictions": [],
            "calibration_history": full_rows + partial_rows,
            "last_run_utc": None,
            "last_train_window": None,
            "n_train_samples": 0,
            "last_cqr_q": 0.0,
            "last_cqr_n_calib_days": 0,
        }
        with open(shadow_dir / "shadow_state.json", "w") as f:
            json.dump(state, f)

        forecasts_dir = tmp_path / "forecasts"
        eval_log = tmp_path / "eval_log.jsonl"

        appended = run_evaluation(
            shadow_dir=shadow_dir,
            arf_forecasts_dir=forecasts_dir,
            eval_log_path=eval_log,
        )
        assert len(appended) == 1
        assert appended[0]["date"] == "2026-04-29"
        # Re-running should be a no-op (already logged)
        appended2 = run_evaluation(
            shadow_dir=shadow_dir,
            arf_forecasts_dir=forecasts_dir,
            eval_log_path=eval_log,
        )
        assert appended2 == []


# ---------- seasonal-naive baseline (2026-09-06) ----------------------------


def _vintage(
    t0: pd.Timestamp,
    lgbm_pred: float,
    realised: float,
    record_t0: bool = True,
) -> list[dict]:
    """A production-shaped vintage: 72 hours from t0+1h, `eval_day` == t0's DATE.

    This is the shape update_shadow actually writes (step 4/7): the rows span
    three calendar dates and are all tagged with t0's date, not their own. A
    fixture aligned to a single calendar day cannot exercise the 48h/72h
    lookback branches, and hides anchor-inference bugs entirely.
    """
    day = t0.strftime("%Y-%m-%d")
    rows = []
    for h in range(1, 73):
        row = _calib_row(t0 + pd.Timedelta(hours=h), day, 0.0, lgbm_pred, 999.0, realised)
        if record_t0:
            row["t0_utc"] = t0.isoformat()
        rows.append(row)
    return rows


def _flat_history(start: pd.Timestamp, hours: int, value: float) -> pd.Series:
    idx = pd.date_range(start, periods=hours, freq="h")
    return pd.Series([value] * hours, index=idx)


class TestNaiveSourceTimestamp:
    """The baseline may only use hours that were already known at t0."""

    def test_first_horizon_day_looks_back_24h(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        ts = t0 + pd.Timedelta(hours=1)
        assert naive_source_timestamp(ts, t0) == ts - pd.Timedelta(hours=24)

    def test_hour_24_still_looks_back_24h(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        ts = t0 + pd.Timedelta(hours=24)
        assert naive_source_timestamp(ts, t0) == ts - pd.Timedelta(hours=24)

    def test_second_horizon_day_looks_back_48h(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        for h in (25, 36, 48):
            ts = t0 + pd.Timedelta(hours=h)
            assert naive_source_timestamp(ts, t0) == ts - pd.Timedelta(hours=48)

    def test_third_horizon_day_looks_back_72h(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        for h in (49, 60, 72):
            ts = t0 + pd.Timedelta(hours=h)
            assert naive_source_timestamp(ts, t0) == ts - pd.Timedelta(hours=72)

    def test_source_is_never_after_t0(self):
        """The whole point: no peeking at prices the model could not have seen."""
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        for h in range(1, 73):
            ts = t0 + pd.Timedelta(hours=h)
            assert naive_source_timestamp(ts, t0) <= t0

    def test_preserves_clock_hour(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        for h in (1, 25, 49, 72):
            ts = t0 + pd.Timedelta(hours=h)
            assert naive_source_timestamp(ts, t0).hour == ts.hour


class TestLoadPriceHistory:
    def test_missing_parquet_returns_none(self, tmp_path):
        assert load_price_history(tmp_path / "nope.parquet") is None

    def test_unreadable_parquet_returns_none(self, tmp_path):
        bad = tmp_path / "bad.parquet"
        bad.write_text("not a parquet")
        assert load_price_history(bad) is None

    def test_excludes_non_entsoe_hours(self, tmp_path):
        idx = pd.date_range(pd.Timestamp("2026-05-01T00:00:00Z"), periods=4, freq="h")
        df = pd.DataFrame(
            {"price_eur_mwh": [10.0, 20.0, 30.0, 40.0],
             "price_is_entsoe": [1.0, 0.0, 1.0, float("nan")]},
            index=idx,
        )
        path = tmp_path / "h.parquet"
        df.to_parquet(path)
        out = load_price_history(path)
        assert list(out.to_numpy()) == [10.0, 30.0]

    def test_naive_index_is_localised_to_utc(self, tmp_path):
        idx = pd.date_range("2026-05-01", periods=3, freq="h")  # tz-naive
        df = pd.DataFrame({"price_eur_mwh": [1.0, 2.0, 3.0]}, index=idx)
        path = tmp_path / "h.parquet"
        df.to_parquet(path)
        out = load_price_history(path)
        assert str(out.index.tz) == "UTC"


class TestT0Resolution:
    """The anchor must be known exactly, or not used at all.

    `eval_day` IS `t0.strftime("%Y-%m-%d")` in production (update_shadow step 4),
    and `calibration_history` holds realised rows ONLY — so inferring the anchor
    from surviving rows breaks precisely when leading hours were withheld.
    """

    def test_prefers_recorded_t0(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        calib = _vintage(t0, lgbm_pred=100.0, realised=100.0, record_t0=True)
        assert t0_for_eval_day(calib, "2026-05-01") == t0

    def test_recorded_t0_wins_over_a_gap_in_leading_hours(self):
        """The whole point: withheld leading hours no longer move the anchor."""
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        calib = _vintage(t0, 100.0, 100.0, record_t0=True)[30:]  # first 30h withheld
        assert t0_for_eval_day(calib, "2026-05-01") == t0

    def test_legacy_rows_infer_when_leading_hours_are_intact(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        calib = _vintage(t0, 100.0, 100.0, record_t0=False)
        assert t0_for_eval_day(calib, "2026-05-01") == t0

    def test_legacy_rows_refuse_to_infer_when_leading_hours_are_gone(self):
        """The bug this guard exists for — must be None, not a shifted anchor."""
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        calib = _vintage(t0, 100.0, 100.0, record_t0=False)[30:]
        assert t0_for_eval_day(calib, "2026-05-01") is None

    def test_disagreeing_recorded_t0_is_refused(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        calib = _vintage(t0, 100.0, 100.0, record_t0=True)
        calib[5] = {**calib[5], "t0_utc": pd.Timestamp("2026-04-30T21:00:00Z").isoformat()}
        assert t0_for_eval_day(calib, "2026-05-01") is None

    def test_unknown_day_is_none(self):
        t0 = pd.Timestamp("2026-05-01T21:00:00Z")
        assert t0_for_eval_day(_vintage(t0, 100.0, 100.0), "2026-01-01") is None


class TestNaiveSkillInRow:
    """End-to-end on production-shaped vintages: 72h from t0, eval_day == t0's date."""

    T0 = pd.Timestamp("2026-05-01T21:00:00Z")
    DAY = "2026-05-01"

    def test_perfect_model_scores_skill_one(self):
        calib = _vintage(self.T0, lgbm_pred=100.0, realised=100.0)
        history = _flat_history(self.T0 - pd.Timedelta(days=4), hours=24 * 5, value=50.0)
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["n_naive_hours"] == 72
        assert row["naive_mae"] == 50.0
        assert row["lightgbm_skill_vs_naive"] == 1.0

    def test_model_worse_than_naive_gives_negative_skill(self):
        """The case that motivated the field — it must be visible, not hidden."""
        calib = _vintage(self.T0, lgbm_pred=80.0, realised=100.0)
        history = _flat_history(self.T0 - pd.Timedelta(days=4), hours=24 * 5, value=90.0)
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["naive_mae"] == 10.0
        assert row["lightgbm_mae_on_naive_hours"] == 20.0
        assert row["lightgbm_skill_vs_naive"] == -1.0

    def test_every_horizon_day_sources_the_same_final_known_day(self):
        """All 72 horizons draw from `[t0-23h, t0]` — the last day known at t0.

        Not an accident of the fixture: h=1..24 looks back 24h, h=25..48 looks
        back 48h, h=49..72 looks back 72h, and all three land in the same window.
        Pinned because it is the property that makes the baseline honest — no
        horizon ever reads a day the forecaster had not yet seen.
        """
        calib = _vintage(self.T0, lgbm_pred=100.0, realised=100.0)
        idx = pd.date_range(self.T0 - pd.Timedelta(days=3), periods=24 * 4, freq="h")
        # 40.0 across the last known day [t0-23h, t0]; 10.0 everywhere earlier.
        # Any horizon reaching further back would drag the mean off 60.0.
        window_start = self.T0 - pd.Timedelta(hours=23)
        history = pd.Series(
            [40.0 if window_start <= t <= self.T0 else 10.0 for t in idx], index=idx
        )
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["n_naive_hours"] == 72
        assert row["naive_min_horizon_h"] == 1
        assert row["naive_max_horizon_h"] == 72
        assert row["naive_mae"] == 60.0  # |100 realised - 40|, on all 72 hours

    def test_horizon_span_reflects_withheld_leading_hours(self):
        """A row covering h=31..72 must say so — naive MAE is horizon-dependent."""
        calib = _vintage(self.T0, 100.0, 100.0, record_t0=True)[30:]
        history = _flat_history(self.T0 - pd.Timedelta(days=4), hours=24 * 5, value=90.0)
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["naive_min_horizon_h"] == 31
        assert row["naive_max_horizon_h"] == 72

    def test_legacy_gappy_vintage_leaves_fields_null_rather_than_leaking(self):
        """No recorded t0 and no leading hours: refuse, do not guess."""
        calib = _vintage(self.T0, 100.0, 100.0, record_t0=False)[30:]
        history = _flat_history(self.T0 - pd.Timedelta(days=4), hours=24 * 5, value=90.0)
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["n_naive_hours"] == 0
        assert row["naive_mae"] is None
        assert row["lightgbm_skill_vs_naive"] is None

    def test_absent_history_leaves_fields_null_not_zero(self):
        """Null means 'not computed'; 0.0 would read as 'no edge'."""
        calib = _vintage(self.T0, lgbm_pred=80.0, realised=100.0)
        row = evaluate_one_day(self.DAY, calib, None, None)
        assert row["n_naive_hours"] == 0
        assert row["naive_mae"] is None
        assert row["lightgbm_skill_vs_naive"] is None

    def test_lgbm_is_restricted_to_the_paired_hours(self):
        """A gappy baseline must not be compared against a full-day LGBM MAE.

        History holds 12 of the 24 usable source hours; each maps to one horizon
        per horizon-day, so 36 of 72 rows pair.
        """
        calib = _vintage(self.T0, lgbm_pred=80.0, realised=100.0)
        history = _flat_history(self.T0 - pd.Timedelta(hours=23), hours=12, value=90.0)
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["n_naive_hours"] == 36
        assert row["n_overlap_hours"] == 72
        assert row["lightgbm_mae_on_naive_hours"] == 20.0

    def test_baseline_never_reads_the_forecast_own_future(self):
        """History stamped strictly after t0 is unusable, however accurate it is."""
        calib = _vintage(self.T0, lgbm_pred=100.0, realised=100.0)
        idx = pd.date_range(self.T0 + pd.Timedelta(hours=1), periods=72, freq="h")
        history = pd.Series([100.0] * 72, index=idx)  # exact, and entirely post-t0
        row = evaluate_one_day(self.DAY, calib, None, history)
        assert row["n_naive_hours"] == 0
        assert row["naive_mae"] is None

    def test_hour_24_may_source_t0_itself(self):
        """t0 is the last hour known when the forecast was made — fair game."""
        calib = _vintage(self.T0, lgbm_pred=100.0, realised=100.0)
        history = pd.Series([42.0], index=pd.DatetimeIndex([self.T0]))
        row = evaluate_one_day(self.DAY, calib, None, history)
        # h=24, 48 and 72 all source exactly t0.
        assert row["n_naive_hours"] == 3
        assert row["naive_mae"] == 58.0
        assert row["naive_min_horizon_h"] == 24
        assert row["naive_max_horizon_h"] == 72
