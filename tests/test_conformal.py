"""Tests for ml.shadow.conformal — CQR correction correctness + no-leakage."""

import numpy as np
import pandas as pd
import pytest

from ml.shadow.conformal import (
    DEFAULT_CALIB_DAYS,
    MIN_CALIB_DAYS,
    apply_cqr,
)


def _make_preds(n_days: int = 14, hours_per_day: int = 24, miss_rate: float = 0.5, seed: int = 0):
    """Synthetic predictions where the band is too narrow on purpose.

    Realized prices are drawn from a wider distribution than [p10, p90], so
    coverage on the raw bands is well below 80%. CQR on calibration days
    should inflate bands to approach 80%.
    """
    rng = np.random.default_rng(seed)
    rows = []
    start = pd.Timestamp("2026-01-01", tz="UTC")
    for d in range(n_days):
        day = start + pd.Timedelta(days=d)
        for h in range(hours_per_day):
            ts = day + pd.Timedelta(hours=h)
            p50 = 50.0
            # Tight raw band: p10=45, p90=55
            p10, p90 = 45.0, 55.0
            # Realized often falls outside [45, 55] — std=20 so most miss.
            realized = p50 + rng.normal(0, 20)
            rows.append(
                {
                    "timestamp_utc": ts,
                    "eval_day": day.date().isoformat(),
                    "realized": realized,
                    "p10": p10,
                    "p50": p50,
                    "p90": p90,
                    "n_train": 600,
                }
            )
    return pd.DataFrame(rows)


class TestSchema:
    def test_returns_extra_columns(self):
        out = apply_cqr(_make_preds())
        for col in ("nonconformity", "cqr_q", "p10_cqr", "p90_cqr"):
            assert col in out.columns

    def test_rejects_missing_columns(self):
        df = _make_preds().drop(columns=["p10"])
        with pytest.raises(ValueError, match="missing columns"):
            apply_cqr(df)


class TestCalibrationLeakage:
    """The critical no-leakage property: CQR for day D may only use prior days."""

    def test_day_zero_has_zero_inflation(self):
        out = apply_cqr(_make_preds(n_days=14))
        # First MIN_CALIB_DAYS have insufficient history -> zero inflation.
        for d in range(MIN_CALIB_DAYS):
            day = (pd.Timestamp("2026-01-01") + pd.Timedelta(days=d)).date().isoformat()
            day_q = out.loc[out["eval_day"] == day, "cqr_q"].unique()
            assert len(day_q) == 1
            assert day_q[0] == 0.0, f"day {d} got non-zero inflation"

    def test_perturbing_future_does_not_change_today_inflation(self):
        df = _make_preds(n_days=14)
        out_a = apply_cqr(df)

        # Corrupt the realized of the LAST day only.
        df_b = df.copy()
        last_day = df_b["eval_day"].max()
        df_b.loc[df_b["eval_day"] == last_day, "realized"] += 10000.0
        out_b = apply_cqr(df_b)

        # CQR for any day < last_day must be unchanged.
        for day in sorted(df["eval_day"].unique()):
            if day == last_day:
                continue
            qa = out_a.loc[out_a["eval_day"] == day, "cqr_q"].iloc[0]
            qb = out_b.loc[out_b["eval_day"] == day, "cqr_q"].iloc[0]
            assert qa == pytest.approx(qb), f"future leaked into day {day}"


class TestCoverageImprovement:
    def test_synthetic_coverage_improves(self):
        """On synthetic with deliberately tight bands, CQR should pull coverage up."""
        df = _make_preds(n_days=21, miss_rate=0.5, seed=42)
        out = apply_cqr(df)

        # Look only at days with active calibration.
        active = out[out["cqr_q"] > 0]
        raw_in = ((active["realized"] >= active["p10"]) & (active["realized"] <= active["p90"])).mean()
        cqr_in = ((active["realized"] >= active["p10_cqr"]) & (active["realized"] <= active["p90_cqr"])).mean()

        assert raw_in < 0.50, f"raw coverage already high: {raw_in:.2%}"
        assert cqr_in > raw_in + 0.20, f"cqr coverage {cqr_in:.2%} not meaningfully higher than raw {raw_in:.2%}"


class TestOrdering:
    def test_p10_cqr_le_p90_cqr(self):
        out = apply_cqr(_make_preds())
        assert (out["p10_cqr"] <= out["p90_cqr"]).all()

    def test_q_nonneg(self):
        out = apply_cqr(_make_preds())
        assert (out["cqr_q"] >= 0.0).all()


class TestParametrization:
    def test_calib_days_changes_q(self):
        df = _make_preds(n_days=21, seed=99)
        out_short = apply_cqr(df, calib_days=3)
        out_long = apply_cqr(df, calib_days=14)
        # With different calibration windows the inflation should differ on
        # at least one day (otherwise the parameter is dead).
        last_day = df["eval_day"].max()
        q_short = out_short.loc[out_short["eval_day"] == last_day, "cqr_q"].iloc[0]
        q_long = out_long.loc[out_long["eval_day"] == last_day, "cqr_q"].iloc[0]
        assert q_short != pytest.approx(q_long)

    def test_default_calib_days_value(self):
        assert DEFAULT_CALIB_DAYS == 7
