"""Tests for the dashboard's day-type profile forecast (ml/shadow/update_profile.py)."""

import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.shadow import update_profile as up

TZ = "Europe/Amsterdam"


def test_nl_holidays_match_what_the_production_parquet_flags():
    # Every is_holiday_nl date in sadalsuud's parquet, 2025-09-28..2026-11-07
    # (read 2026-11-07). The calendar must agree with EDH's holidays.Netherlands().
    flagged = {
        date(2025, 12, 25), date(2025, 12, 26), date(2026, 1, 1), date(2026, 4, 3),
        date(2026, 4, 5), date(2026, 4, 6), date(2026, 4, 27), date(2026, 5, 14),
        date(2026, 5, 24), date(2026, 5, 25),
    }
    window = {d for d in up.nl_holidays([2025, 2026])
              if date(2025, 9, 28) <= d <= date(2026, 11, 7)}
    assert window == flagged


def test_liberation_day_only_in_lustrum_years_and_kings_day_moves_off_sunday():
    assert date(2025, 5, 5) in up.nl_holidays([2025])
    assert date(2026, 5, 5) not in up.nl_holidays([2026])
    assert date(2025, 4, 26) in up.nl_holidays([2025])  # 27 April 2025 is a Sunday


def _prices(start, end, holidays, weekday=100.0, weekend=50.0, holiday=10.0):
    idx = pd.date_range(start, end, freq="h", tz="UTC")
    out = {}
    for ts in idx:
        d = ts.tz_convert(TZ).date()
        out[ts] = holiday if d in holidays else weekend if d.weekday() >= 5 else weekday
    return out


def _setup(t0):
    hol = up.nl_holidays([2025, 2026, 2027])
    t0_day = t0.tz_convert(TZ).date()
    pool = up.weekend_pool(hol, t0_day - pd.Timedelta(days=120), t0_day + pd.Timedelta(days=4))
    prices = _prices(t0 - pd.Timedelta(days=100), t0, hol)
    return hol, pool, prices


def test_christmas_is_typed_as_holiday_and_filled_from_weekends():
    # t0 = local midnight starting Thursday 24 Dec 2026; 25th (Fri) and 26th (Sat)
    # are holidays with no 5 earlier holidays in reach -> weekend fallback.
    t0 = pd.Timestamp("2026-12-23 23:00", tz="UTC")
    hol, pool, prices = _setup(t0)
    preds, n_fallback = up.profile_forecast(t0, prices, hol, pool)
    assert len(preds) == 72
    assert n_fallback == 48
    by_day = {}
    for ts, v in preds.items():
        by_day.setdefault(ts.tz_convert(TZ).date(), set()).add(v)
    assert by_day[date(2026, 12, 24)] == {100.0}
    assert by_day[date(2026, 12, 25)] == by_day[date(2026, 12, 26)] == {50.0}


def test_without_the_fallback_a_holiday_is_a_hole():
    t0 = pd.Timestamp("2026-12-23 23:00", tz="UTC")
    hol, _, prices = _setup(t0)
    preds, _ = up.profile_forecast(t0, prices, hol, hol)  # pool == holidays: no weekends
    assert len(preds) == 24


def test_band_residuals_never_read_past_t0():
    t0 = pd.Timestamp("2026-11-07 22:00", tz="UTC")
    hol, pool, prices = _setup(t0)
    rng = np.random.default_rng(0)
    prices = {ts: v + rng.normal(0, 20) for ts, v in prices.items()}
    base = up.residual_quantiles(t0, prices, hol, pool)
    future = {t0 + pd.Timedelta(hours=h): 1e6 for h in range(1, 100)}
    assert up.residual_quantiles(t0, {**prices, **future}, hol, pool) == base
    for q in base.values():
        assert q["n"] == up.BAND_DAYS * 24
        assert q["q_lo"] < 0 < q["q_hi"]


def test_thin_block_gets_no_band():
    t0 = pd.Timestamp("2026-11-07 22:00", tz="UTC")
    hol, pool, prices = _setup(t0)
    q = up.residual_quantiles(t0, prices, hol, pool, days=3)
    assert all(v["q_lo"] is None for v in q.values())
    preds, _ = up.profile_forecast(t0, prices, hol, pool)
    forecast, upper, lower = up.format_profile_dicts(preds, t0, q)
    assert len(forecast) == 72 and upper == {} and lower == {}


def test_run_writes_the_shadow_schema_on_production_t0(tmp_path, monkeypatch):
    t0 = pd.Timestamp("2026-11-07 22:00", tz="UTC")
    hol, _, prices = _setup(t0)
    rng = np.random.default_rng(1)
    s = pd.Series({ts: v + rng.normal(0, 20) for ts, v in prices.items()})
    df = pd.DataFrame({"price_eur_mwh": s, "price_is_entsoe": 1.0, "is_holiday_nl": 0.0})
    parquet = tmp_path / "h.parquet"
    df.to_parquet(parquet)
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / up.SHADOW_STATE_FILENAME).write_text(json.dumps({"last_t0": t0.isoformat()}))
    monkeypatch.setattr(up, "read_arf_surcharge", lambda: 110.0)
    out = tmp_path / "profile.json"

    up.run_profile_update(shadow_dir, parquet, out)

    d = json.loads(out.read_text())
    assert set(d) == {"metadata", "forecast", "forecast_upper", "forecast_lower",
                      "consumer_forecast", "consumer_forecast_upper", "consumer_forecast_lower"}
    assert d["metadata"]["t0"] == t0.isoformat()
    assert d["metadata"]["display_name"] == up.DISPLAY_NAME
    first = (t0 + pd.Timedelta(hours=1)).isoformat()
    assert min(d["forecast"]) == first and len(d["forecast"]) == 72
    assert d["forecast_lower"][first] < d["forecast"][first] < d["forecast_upper"][first]
    assert d["consumer_forecast"][first] == pytest.approx(
        round(d["forecast"][first] * up.VAT_RATE + 110.0, 2))


def test_run_refuses_without_production_t0(tmp_path):
    (tmp_path / up.SHADOW_STATE_FILENAME).write_text("{}")
    with pytest.raises(ValueError, match="last_t0"):
        up.run_profile_update(tmp_path, tmp_path / "none.parquet", tmp_path / "o.json")
