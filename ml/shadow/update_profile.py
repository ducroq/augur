"""Nightly day-type profile forecast: the dashboard's forecaster (ADR-009).

CLI:
    python -m ml.shadow.update_profile

Writes ``static/data/augur_forecast_profile.json`` in the same schema as
``augur_forecast_shadow.json``, so ``dashboard.js:loadAugurForecast`` swaps
between them by path alone. LightGBM keeps running as a shadow.

Why each choice is what it is:

- **The rule is EXP-036's profile floor**, `evaluate_shadow.naive_profile_prediction`
  unchanged: the mean of the same hour over the last 5 matching day types
  (weekday / weekend / NL holiday). It steps back whole UTC days, so after a
  DST change its sources sit one local hour off; that is the scored estimator. Live since 2026-09-14 it picks the
  cheap hours about twice as well as LightGBM in every horizon block
  (augur#37). Reusing the function keeps the dashboard's forecast identical to
  the arm `regret.py` scores.
- **t0 is production's** (`shadow_state.json:last_t0`), so this step runs after
  `update_shadow` and the rule's regret rows stay paired with LightGBM's.
- **Holidays for the forecast window come from a built-in NL calendar.** The
  parquet's `is_holiday_nl` ends at t0, so without it a holiday inside the 72h
  would be typed as a weekday here, while `regret.py`, reading the parquet
  after the fact, would type it correctly: the scored arm and the shown
  forecast would differ exactly on holidays. `nl_holidays` reproduces the
  `holidays.Netherlands()` set EDH uses (pinned by a test against the dates
  the production parquet flags), and is unioned with the parquet's own.
- **Bands are the rule's own errors**, decided 2026-11-07: P10 and P90 of
  (actual - forecast) over target hours in the last `BAND_DAYS` days, per
  horizon block, recomputed nightly from anchors one day apart behind t0.
  Every target is at or before t0, so no residual reads the future. A block
  with fewer than `MIN_BAND_RESIDUALS` residuals gets no band rather than a
  thin one; the chart already skips missing band hours.
- **A holiday the rule can't fill falls back to weekends.** Five earlier
  holidays within 56 days exist only in the Easter-to-Whitsun cluster, so
  Christmas and New Year would otherwise be a 24h hole. On those hours, and
  only those, the holiday is pooled with weekend days (`predict_hour`). The
  arm `regret.py` scores returns None there, so nothing it measured changes.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.evaluate_shadow import (
    PROFILE_DAYS,
    PROFILE_MAX_LOOKBACK_DAYS,
    TZ_LOCAL,
    load_holiday_dates,
    load_price_history,
    naive_profile_prediction,
)
from ml.shadow.update_shadow import (
    DEFAULT_PARQUET,
    DEFAULT_SHADOW_DIR,
    SHADOW_STATE_FILENAME,
    VAT_RATE,
    _REPO_ROOT,
    format_consumer_dicts,
    load_shadow_state,
    read_arf_surcharge,
    write_forecast_json,
)

logger = logging.getLogger(__name__)

DEFAULT_FORECAST_OUT = _REPO_ROOT / "static" / "data" / "augur_forecast_profile.json"
HORIZON_HOURS = 72
BLOCKS = {"h1_24": (1, 24), "h25_48": (25, 48), "h49_72": (49, 72)}
BAND_DAYS = 28
BAND_QUANTILES = (0.10, 0.90)
MIN_BAND_RESIDUALS = 7 * 24
MIN_FORECAST_HOURS = 24
DISPLAY_NAME = f"Average of the last {PROFILE_DAYS} similar days"


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7  # noqa: E741 - the algorithm's name
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nl_holidays(years) -> set[date]:
    """NL public holidays as `holidays.Netherlands()` lists them (EDH's source).

    Good Friday is in; Liberation Day only in lustrum years (2025, 2030, ...).
    """
    out: set[date] = set()
    for y in years:
        easter = _easter(y)
        kings = date(y, 4, 27)
        if kings.weekday() == 6:  # Sunday: moved to Saturday the 26th
            kings = date(y, 4, 26)
        out |= {
            date(y, 1, 1),
            easter - timedelta(days=2),
            easter,
            easter + timedelta(days=1),
            kings,
            easter + timedelta(days=39),
            easter + timedelta(days=49),
            easter + timedelta(days=50),
            date(y, 12, 25),
            date(y, 12, 26),
        }
        if y % 5 == 0:
            out.add(date(y, 5, 5))
    return out


def weekend_pool(holidays: set, start: date, end: date) -> set[date]:
    """`holidays` plus every Saturday and Sunday in [start, end].

    Passed as the holiday set, it makes a holiday's day type match weekends
    too: the fallback for a holiday with fewer than 5 earlier holidays within
    the lookback (Christmas, New Year), which the rule alone leaves empty.
    """
    n = (end - start).days + 1
    days = (start + timedelta(days=i) for i in range(n))
    return holidays | {d for d in days if d.weekday() >= 5}


def predict_hour(
    ts: pd.Timestamp, anchor: pd.Timestamp, prices: dict, holidays: set, pool: set
) -> tuple[float | None, bool]:
    """The rule at `ts`; on an unfillable holiday, the weekend-pooled rule.

    Returns (value, used_fallback). The fallback differs from the arm
    `regret.py` scores only on hours where that arm returns None.
    """
    v = naive_profile_prediction(ts, anchor, prices, holidays)
    if v is not None:
        return v, False
    if ts.tz_convert(TZ_LOCAL).date() not in holidays:
        return None, False
    return naive_profile_prediction(ts, anchor, prices, pool), True


def profile_forecast(
    t0: pd.Timestamp, prices: dict, holidays: set, pool: set
) -> tuple[dict[pd.Timestamp, float], int]:
    """The rule for h = 1..72 from `t0`, and how many hours used the fallback.

    Hours it can't fill are left out.
    """
    out, n_fallback = {}, 0
    for h in range(1, HORIZON_HOURS + 1):
        ts = t0 + pd.Timedelta(h, unit="h")
        v, fell_back = predict_hour(ts, t0, prices, holidays, pool)
        if v is not None:
            out[ts] = v
            n_fallback += fell_back
    return out, n_fallback


def residual_quantiles(
    t0: pd.Timestamp, prices: dict, holidays: set, pool: set, days: int = BAND_DAYS
) -> dict[str, dict]:
    """P10/P90 of (actual - rule) per block, over targets in (t0 - days, t0]."""
    lo_cut = t0 - pd.Timedelta(days=days)
    errs: dict[str, list[float]] = {b: [] for b in BLOCKS}
    max_back = days + HORIZON_HOURS // 24
    for k in range(1, max_back + 1):
        anchor = t0 - pd.Timedelta(days=k)
        for block, (h_lo, h_hi) in BLOCKS.items():
            for h in range(h_lo, h_hi + 1):
                ts = anchor + pd.Timedelta(h, unit="h")
                if ts <= lo_cut or ts > t0:
                    continue
                actual = prices.get(ts)
                if actual is None or pd.isna(actual):
                    continue
                pred, _ = predict_hour(ts, anchor, prices, holidays, pool)
                if pred is not None:
                    errs[block].append(float(actual) - pred)
    out = {}
    for block, e in errs.items():
        if len(e) < MIN_BAND_RESIDUALS:
            out[block] = {"n": len(e), "q_lo": None, "q_hi": None}
        else:
            q_lo, q_hi = np.quantile(e, BAND_QUANTILES)
            out[block] = {"n": len(e), "q_lo": round(float(q_lo), 2), "q_hi": round(float(q_hi), 2)}
    return out


def _block_of(h: int) -> str:
    for block, (lo, hi) in BLOCKS.items():
        if lo <= h <= hi:
            return block
    raise ValueError(h)


def format_profile_dicts(
    preds: dict[pd.Timestamp, float], t0: pd.Timestamp, quantiles: dict[str, dict]
) -> tuple[dict, dict, dict]:
    forecast, upper, lower = {}, {}, {}
    for ts, v in sorted(preds.items()):
        key = ts.isoformat()
        forecast[key] = round(v, 2)
        q = quantiles[_block_of(int((ts - t0).total_seconds() // 3600))]
        if q["q_lo"] is not None:
            upper[key] = round(v + q["q_hi"], 2)
            lower[key] = round(v + q["q_lo"], 2)
    return forecast, upper, lower


def run_profile_update(
    shadow_dir: Path = DEFAULT_SHADOW_DIR,
    parquet_path: Path = DEFAULT_PARQUET,
    forecast_out: Path = DEFAULT_FORECAST_OUT,
) -> dict:
    """Write the profile forecast for production's t0. Returns its metadata."""
    last_t0 = load_shadow_state(shadow_dir / SHADOW_STATE_FILENAME).get("last_t0")
    if last_t0 is None:
        raise ValueError("production shadow state has no last_t0; run update_shadow first")
    t0 = pd.Timestamp(last_t0).tz_convert("UTC")

    history = load_price_history(parquet_path)
    if history is None:
        raise ValueError(f"no usable price history in {parquet_path}")
    prices = history.to_dict()
    holidays = nl_holidays(range(t0.year - 1, t0.year + 2)) | (load_holiday_dates(parquet_path) or set())

    t0_day = t0.tz_convert(TZ_LOCAL).date()
    pool = weekend_pool(
        holidays,
        t0_day - timedelta(days=BAND_DAYS + PROFILE_MAX_LOOKBACK_DAYS + 7),
        t0_day + timedelta(days=4),
    )
    preds, n_fallback = profile_forecast(t0, prices, holidays, pool)
    if len(preds) < MIN_FORECAST_HOURS:
        raise ValueError(f"profile rule filled only {len(preds)} of {HORIZON_HOURS} hours for t0={t0}")
    if len(preds) < HORIZON_HOURS:
        logger.warning("profile rule filled %d of %d hours (price holes)", len(preds), HORIZON_HOURS)

    quantiles = residual_quantiles(t0, prices, holidays, pool)
    for block, q in quantiles.items():
        if q["q_lo"] is None:
            logger.warning("block %s: %d residuals < %d, no band", block, q["n"], MIN_BAND_RESIDUALS)

    forecast, upper, lower = format_profile_dicts(preds, t0, quantiles)
    surcharge = read_arf_surcharge()
    consumer, consumer_upper, consumer_lower = format_consumer_dicts(forecast, upper, lower, surcharge)
    metadata = {
        "model": f"DayTypeProfile-{PROFILE_DAYS}",
        "display_name": DISPLAY_NAME,
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "t0": t0.isoformat(),
        "n_hours": len(forecast),
        "n_holiday_fallback_hours": n_fallback,
        "band_quantiles": list(BAND_QUANTILES),
        "band_residual_days": BAND_DAYS,
        "band_residuals": quantiles,
        "consumer_surcharge_eur_mwh": round(surcharge, 2),
        "consumer_vat_rate": VAT_RATE,
    }
    write_forecast_json(
        forecast_out, forecast, upper, lower, metadata,
        consumer=consumer, consumer_upper=consumer_upper, consumer_lower=consumer_lower,
    )
    logger.info("Wrote profile forecast for t0=%s (%d h) to %s", t0, len(forecast), forecast_out)
    return metadata


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--shadow-dir", type=Path, default=DEFAULT_SHADOW_DIR)
    ap.add_argument("--parquet", type=Path, default=DEFAULT_PARQUET)
    ap.add_argument("--forecast-out", type=Path, default=DEFAULT_FORECAST_OUT)
    args = ap.parse_args()
    run_profile_update(args.shadow_dir, args.parquet, args.forecast_out)


if __name__ == "__main__":
    main()
