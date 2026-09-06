"""Nightly shadow update for the EXP-009 LightGBM-Quantile pipeline.

CLI:
    python -m ml.shadow.update_shadow
    # All paths default from _REPO_ROOT; override individually with
    # --parquet / --shadow-dir / --forecast-out for ad-hoc runs.

Order of operations per run:
    1. Load shadow state and the consolidated parquet
    2. Backfill realised prices into pending predictions from prior runs
    3. Move backfilled rows into calibration_history; trim both lists to a
       rolling window
    3b. Guard: check t0 advanced exactly one calendar day since the last run
       (a repeated t0 means a stale parquet and a wasted vintage; a jump
       means a permanently unevaluable day) — non-fatal, surfaced as an
       ALARM in the daily commit subject
    4. Compute CQR q for today from calibration_history (final design from
       EXP-009 milestone 2.5: 7-day calibration, target 0.80)
    5. Train ``MultiHorizonLightGBMQuantileForecaster`` on the rolling
       56-day training window ending at t0 = parquet.index.max()
    6. Predict 72 hourly horizons from t0; widen [P10, P90] by q
    7. Append today's predictions to pending_predictions
    8. Save HMAC-signed model pickle, shadow_state.json, and
       augur_forecast_shadow.json

Plan §5: ``augur_forecast_shadow.json`` is NOT consumed by the dashboard
during shadow phase. Schema mirrors ``augur_forecast.json`` so a config flag
could swap it later.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd

from ml.shadow.conformal import (
    DEFAULT_CALIB_DAYS,
    DEFAULT_TARGET_COVERAGE,
    apply_cqr,
)
from ml.shadow.features_pandas import build_features
from ml.shadow.lightgbm_quantile import (
    DEFAULT_GROUPS,
    MultiHorizonLightGBMQuantileForecaster,
)
# save/load on MultiHorizonLightGBMQuantileForecaster are HMAC-protected via
# secure_pickle as of EXP-009 M3 review fixup B.

logger = logging.getLogger(__name__)

WINDOW_DAYS = 56  # EXP-009 milestone 2.5 final design (vs plan §4's 28)
HORIZONS: tuple[int, ...] = tuple(range(1, 73))
MAX_HISTORY_DAYS = 30  # rolling cap on pending and calibration_history

# Resolve relative to repo root so sadalsuud's module-mode invocation finds the
# right paths regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PARQUET = _REPO_ROOT / "ml" / "data" / "training_history.parquet"
DEFAULT_SHADOW_DIR = _REPO_ROOT / "ml" / "models" / "shadow"
DEFAULT_FORECAST_OUT = _REPO_ROOT / "static" / "data" / "augur_forecast_shadow.json"

SHADOW_STATE_FILENAME = "shadow_state.json"
SHADOW_MODEL_FILENAME = "shadow_model.pkl"


# ---------- state I/O -------------------------------------------------------


def load_shadow_state(path: Path) -> dict:
    if not path.exists():
        return {
            "pending_predictions": [],
            "calibration_history": [],
            "last_run_utc": None,
            "last_t0": None,
            "t0_advance_days": None,
            "t0_held_back_hours": 0.0,
            "t0_short_feeds": [],
            "last_train_window": None,
            "n_train_samples": 0,
            "last_cqr_q": 0.0,
            "last_cqr_n_calib_days": 0,
        }
    with open(path) as f:
        return json.load(f)


def save_shadow_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2, default=str)
    os.replace(tmp, path)


# ---------- pending / calibration management --------------------------------


# Provenance column written by ml/data/consolidate.py: 1.0 where ENTSO-E supplied
# the hour's price, 0.0 where a fallback (epex/elspot) did.
PROVENANCE_COLUMN = "price_is_entsoe"


def backfill_realized(
    pending: list[dict], parquet: pd.DataFrame
) -> tuple[list[dict], list[dict]]:
    """Return (newly_realized_rows, still_pending) by pairing pending against the parquet.

    A pending entry is "realized" if its ``timestamp_utc`` is present in the
    parquet ``price_eur_mwh`` column (non-NaN) AND that hour's price came from
    ENTSO-E.

    Why the provenance gate (2026-09-01): this function is the single point where
    realised prices enter the system -- calibration_history, the CQR band width
    and, through calibration_history, every eval_log row all descend from it. The
    fallback sources are not the same series as the target: epex runs +16.13 mean
    / +10.72 median EUR/MWh against entsoe over 7886 matched hours. Scoring a
    forecast against one is measuring against the wrong ground truth. It had
    reached 46 of 477 rows (9.6%) of the live CQR window and 21 of the 24 hours of
    eval day 2026-08-27, whose logged MAE of 14.679 is smaller than the bias in
    its own ground truth.

    Withheld entries simply stay pending and age out via trim_to_recent_days, so
    a day that never accumulates enough ENTSO-E hours is left UNEVALUATED rather
    than evaluated wrongly -- find_eligible_eval_days needs
    MIN_HOURS_FOR_FULL_DAY of them. That is the intended outcome: no row beats a
    misleading one, the same reasoning that declined reconstructed vintages in
    augur#14.
    """
    if not pending:
        return [], []
    if parquet.empty or "price_eur_mwh" not in parquet.columns:
        return [], list(pending)
    prices = parquet["price_eur_mwh"].dropna()
    if PROVENANCE_COLUMN in parquet.columns:
        provenance = parquet[PROVENANCE_COLUMN].reindex(prices.index)
        # NaN provenance fails this comparison and is therefore withheld:
        # unknown origin is treated as not-ENTSO-E, never as ENTSO-E.
        is_entsoe = provenance >= 1.0
        withheld = int((~is_entsoe).sum())
        if withheld:
            logger.warning(
                "Withholding %d realised hour(s) from scoring: price came from a "
                "fallback source, not ENTSO-E (%s < 1.0). Affected day(s): %s",
                withheld,
                PROVENANCE_COLUMN,
                ", ".join(sorted({str(ts.date()) for ts in prices.index[~is_entsoe]})),
            )
        prices = prices[is_entsoe]
    else:
        logger.warning(
            "Parquet has no %s column — cannot separate ENTSO-E prices from "
            "fallback ones, so every realised hour is being scored. Regenerate "
            "the parquet with the current ml/data/consolidate.py.",
            PROVENANCE_COLUMN,
        )
    realized_lookup: dict[str, float] = {}
    for ts, price in prices.items():
        ts_norm = pd.Timestamp(ts)
        if ts_norm.tzinfo is None:
            ts_norm = ts_norm.tz_localize("UTC")
        else:
            ts_norm = ts_norm.tz_convert("UTC")
        realized_lookup[ts_norm.isoformat()] = float(price)
    realized_rows: list[dict] = []
    still_pending: list[dict] = []
    for entry in pending:
        ts = entry["timestamp_utc"]
        if ts in realized_lookup:
            realized_rows.append({**entry, "realized": realized_lookup[ts]})
        else:
            still_pending.append(entry)
    return realized_rows, still_pending


def trim_to_recent_days(rows: list[dict], max_days: int) -> list[dict]:
    """Keep rows whose ``eval_day`` is within the last ``max_days`` distinct calendar days."""
    if not rows or max_days <= 0:
        return [] if max_days <= 0 else rows
    days = sorted({r["eval_day"] for r in rows})
    if len(days) <= max_days:
        return rows
    cutoff = days[-max_days]
    return [r for r in rows if r["eval_day"] >= cutoff]


# ---------- CQR -------------------------------------------------------------


def compute_cqr_q(
    calibration_history: list[dict],
    today: str,
    calib_days: int = DEFAULT_CALIB_DAYS,
    target_coverage: float = DEFAULT_TARGET_COVERAGE,
) -> tuple[float, int]:
    """Compute the CQR q value to apply to today's predictions.

    Returns (q, n_distinct_calib_days_used). q==0 when calibration is too sparse
    (apply_cqr's MIN_CALIB_DAYS guard handles this internally).
    """
    if not calibration_history:
        return 0.0, 0
    df = pd.DataFrame(calibration_history)
    required = {"timestamp_utc", "eval_day", "p10", "p50", "p90", "realized"}
    missing = required - set(df.columns)
    if missing:
        return 0.0, 0
    df = df.dropna(subset=["realized"])
    if df.empty:
        return 0.0, 0
    # Insert a placeholder row for `today` so apply_cqr returns its q. The
    # placeholder has realized=NaN, which produces nonconformity=NaN in
    # apply_cqr (line 49) and is therefore dropped by the .dropna() at line 61
    # — that's why it doesn't contaminate the calibration set, NOT the
    # `ts < cutoff_end` timestamp filter. Multiple rows with `eval_day == today`
    # are fine; apply_cqr maps them all to the same `day_to_q[today]` value.
    today_row = pd.DataFrame(
        [
            {
                "timestamp_utc": f"{today}T00:00:00+00:00",
                "eval_day": today,
                "p10": 0.0,
                "p50": 0.0,
                "p90": 0.0,
                "realized": np.nan,
            }
        ]
    )
    full = pd.concat([df, today_row], ignore_index=True)
    out = apply_cqr(full, calib_days=calib_days, target_coverage=target_coverage)
    today_rows = out.loc[out["eval_day"] == today]
    if today_rows.empty:
        return 0.0, 0
    q = float(today_rows["cqr_q"].iloc[0])
    # Count distinct calibration days actually inside the trailing window
    # apply_cqr used (rather than the entire history) so the reported number
    # matches the data behind q.
    cutoff_end = pd.Timestamp(today, tz="UTC")
    cutoff_start = cutoff_end - pd.Timedelta(days=calib_days)
    ts_series = pd.to_datetime(df["timestamp_utc"], utc=True)
    in_window = (ts_series >= cutoff_start) & (ts_series < cutoff_end)
    n_calib_days = int(ts_series[in_window].dt.date.nunique())
    return q, n_calib_days


# ---------- training & prediction -------------------------------------------


def select_training_window(
    parquet: pd.DataFrame, t0: pd.Timestamp, window_days: int = WINDOW_DAYS
) -> pd.DataFrame:
    """Return the window-day slice of parquet ending at t0 (inclusive)."""
    start = t0 - pd.Timedelta(days=window_days)
    mask = (parquet.index >= start) & (parquet.index <= t0)
    return parquet.loc[mask]


MIN_WINDOW_DENSITY = 0.75  # warn if clean rows < 75% of expected hours


def fit_multi_horizon(
    parquet_window: pd.DataFrame,
    window_days: int = WINDOW_DAYS,
) -> tuple[MultiHorizonLightGBMQuantileForecaster, int]:
    features = build_features(parquet_window)
    target = parquet_window["price_eur_mwh"]
    X = features.dropna()
    y = target.loc[X.index]
    if len(X) <= max(g[1] for g in DEFAULT_GROUPS):
        raise ValueError(
            f"too few clean rows in training window ({len(X)}); "
            f"need > {max(g[1] for g in DEFAULT_GROUPS)}"
        )
    expected_hours = window_days * 24
    if len(X) < MIN_WINDOW_DENSITY * expected_hours:
        logger.warning(
            "Training window is sparse: %d clean rows out of %d expected "
            "(%.0f%% density) — possible upstream data gap",
            len(X), expected_hours, 100 * len(X) / expected_hours,
        )
    model = MultiHorizonLightGBMQuantileForecaster()
    model.fit(X, y)
    return model, len(X)


def predict_72h(
    model: MultiHorizonLightGBMQuantileForecaster,
    parquet: pd.DataFrame,
    t0: pd.Timestamp,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Return DataFrame with columns timestamp_utc, p10, p50, p90 plus raw
    columns p10_raw, p50_raw, p90_raw — one row per horizon.

    The non-raw p10/p50/p90 columns are row-sorted (p10 <= p50 <= p90 always).
    The _raw columns hold the actual tau=0.10/0.50/0.90 model outputs; they
    can differ when independent quantile regressions cross. Pinball-at-tau
    scoring should use the _raw columns; band-coverage display can use
    either. Added 2026-05-29 after code-review battery on EXP-012 caught
    that pinball-at-p10 on the sorted "p10" is min(q0.10, q0.50, q0.90),
    not the true 10th-percentile prediction.
    """
    horizons_list = list(horizons)
    features = build_features(parquet.loc[parquet.index <= t0])
    feat_t0 = features.loc[[t0]].dropna()
    if feat_t0.empty:
        raise ValueError(f"No clean feature row at t0={t0!r} (NaNs in lags)")
    # Sorted (default) — used for CQR widening + dashboard band display.
    preds_sorted = model.predict_horizons(feat_t0, horizons=horizons_list, sort=True)
    p10, p50, p90 = preds_sorted[0, :, 0], preds_sorted[0, :, 1], preds_sorted[0, :, 2]
    # Raw (unsorted) — preserve actual tau=0.10/0.50/0.90 model outputs.
    preds_raw = model.predict_horizons(feat_t0, horizons=horizons_list, sort=False)
    # raw columns are in the order of self.quantiles = (0.10, 0.50, 0.90).
    p10_raw = preds_raw[0, :, 0]
    p50_raw = preds_raw[0, :, 1]
    p90_raw = preds_raw[0, :, 2]
    timestamps = [t0 + pd.Timedelta(hours=h) for h in horizons_list]
    return pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "p10": p10,
            "p50": p50,
            "p90": p90,
            "p10_raw": p10_raw,
            "p50_raw": p50_raw,
            "p90_raw": p90_raw,
        }
    )


def widen_with_cqr(preds: pd.DataFrame, q: float) -> pd.DataFrame:
    out = preds.copy()
    out["p10_cqr"] = out["p10"] - q
    out["p90_cqr"] = out["p90"] + q
    return out


# ---------- forecast file ---------------------------------------------------


def format_forecast_dicts(
    preds: pd.DataFrame,
) -> tuple[dict, dict, dict]:
    forecast: dict[str, float] = {}
    upper: dict[str, float] = {}
    lower: dict[str, float] = {}
    for _, row in preds.iterrows():
        ts_iso = pd.Timestamp(row["timestamp_utc"]).isoformat()
        forecast[ts_iso] = round(float(row["p50"]), 2)
        upper[ts_iso] = round(float(row["p90_cqr"]), 2)
        lower[ts_iso] = round(float(row["p10_cqr"]), 2)
    return forecast, upper, lower


# EXP-014 promotion (2026-05-29): the shadow now drives the dashboard, so it
# needs to produce consumer-pricing fields the same way ARF did. We read the
# surcharge from ARF's state.json (which the production cron updates daily
# from EZ/ENTSO-E overlap) rather than re-deriving — keeps the two pipelines
# coupled to the same calibration without duplicating derive_surcharge logic.
ARF_STATE_PATH = _REPO_ROOT / "ml" / "models" / "state.json"
VAT_RATE = 1.21
DEFAULT_SURCHARGE_EUR_MWH = 95.0


def read_arf_surcharge() -> float:
    """Read the consumer surcharge cached by ARF's state.json.

    ARF's daily cron derives this from overlapping Energy Zero / ENTSO-E data
    and caches it in `consumer_surcharge.value_eur_mwh`. Falls back to the
    default if ARF state is missing or the field is absent — same fallback
    semantics as ml.update.derive_surcharge.
    """
    try:
        with open(ARF_STATE_PATH) as f:
            arf_state = json.load(f)
        value = arf_state.get("consumer_surcharge", {}).get("value_eur_mwh")
        if value is None:
            logger.warning(
                "ARF state.json missing consumer_surcharge; using default %.2f",
                DEFAULT_SURCHARGE_EUR_MWH,
            )
            return DEFAULT_SURCHARGE_EUR_MWH
        return float(value)
    except FileNotFoundError:
        logger.warning(
            "ARF state.json not found at %s; using default surcharge %.2f",
            ARF_STATE_PATH,
            DEFAULT_SURCHARGE_EUR_MWH,
        )
        return DEFAULT_SURCHARGE_EUR_MWH


def format_consumer_dicts(
    forecast: dict, upper: dict, lower: dict, surcharge: float
) -> tuple[dict, dict, dict]:
    """Apply consumer markup: price * VAT + surcharge. Lower band floored at 0.

    Mirrors ml.update.generate_consumer_forecast so the dashboard's consumer-
    pricing chart sees the same shape of data it did under ARF.
    """
    consumer: dict[str, float] = {}
    consumer_upper: dict[str, float] = {}
    consumer_lower: dict[str, float] = {}
    for ts, price in forecast.items():
        consumer[ts] = round(price * VAT_RATE + surcharge, 2)
    for ts, price in upper.items():
        consumer_upper[ts] = round(price * VAT_RATE + surcharge, 2)
    for ts, price in lower.items():
        consumer_lower[ts] = round(max(price * VAT_RATE + surcharge, 0.0), 2)
    return consumer, consumer_upper, consumer_lower


def write_forecast_json(
    out_path: Path,
    forecast: dict,
    upper: dict,
    lower: dict,
    metadata: dict,
    consumer: dict | None = None,
    consumer_upper: dict | None = None,
    consumer_lower: dict | None = None,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": metadata,
        "forecast": forecast,
        "forecast_upper": upper,
        "forecast_lower": lower,
    }
    if consumer is not None:
        payload["consumer_forecast"] = consumer
        payload["consumer_forecast_upper"] = consumer_upper or {}
        payload["consumer_forecast_lower"] = consumer_lower or {}
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, out_path)


# ---------- orchestration ---------------------------------------------------


def _normalize_parquet_index(parquet: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(parquet.index, pd.DatetimeIndex):
        raise ValueError("parquet must have DatetimeIndex")
    if parquet.index.tz is None:
        parquet = parquet.tz_localize("UTC")
    elif str(parquet.index.tz) != "UTC":
        parquet = parquet.tz_convert("UTC")
    return parquet.sort_index()


def latest_feasible_t0(
    parquet: pd.DataFrame, price_t0: pd.Timestamp
) -> tuple[pd.Timestamp | None, list[str]]:
    """Last timestamp <= price_t0 that has a COMPLETE feature row.

    Why this is not simply `price_t0`: the parquet's columns do not share a
    horizon. EDH publishes each feed independently, so `price_eur_mwh` can
    reach 48h ahead while `load_forecast` reaches only 24h. Anchoring t0 on
    the price column alone then picks an hour whose feature row is part NaN,
    and `predict_72h` raises `No clean feature row at t0=...`. That is exactly
    what killed the 2026-08-30 production run: EDH's load feed halved from 48h
    to 24h in its 19:02 UTC publish while price stayed at 48h.

    Returns (t0, short_columns) where `short_columns` names the raw parquet
    columns whose coverage ends before `price_t0` — the upstream diagnostic
    that says *which* feed truncated. `t0` is None when no clean row exists at
    all, which is a different and much worse problem than a short feed.
    """
    feats = build_features(parquet.loc[parquet.index <= price_t0])
    clean = feats.dropna().index
    t0 = clean.max() if len(clean) else None

    short = [
        col
        for col in parquet.columns
        if parquet[col].notna().any()
        and parquet[col].dropna().index.max() < price_t0
    ]
    return t0, short


# Expected calendar-day advance of t0 between consecutive runs.
#
# Why this guard exists: t0 is `parquet["price_eur_mwh"].dropna().index.max()`,
# so it tracks the DATA, not the clock, and nothing checked that it moved.
# Two failure shapes follow, both observed live 2026-08-23..27. EDH skipped
# its scheduled publish entirely on 08-23 and 08-27, and the catch-up commit
# for the first of those released Augur's gate early on 08-24 (see
# scripts/wait_for_edh.sh):
#   advance == 0  the run sees the same parquet as yesterday, so the
#                 (timestamp_utc, eval_day) dedup below silently OVERWRITES an
#                 identical prediction set. The run retrains, republishes an
#                 unchanged forecast, exits 0 — and adds nothing evaluable.
#   advance >= 2  the parquet caught up by more than a day, so the skipped
#                 day never gets a prediction set at all and can NEVER be
#                 evaluated. 2026-08-25 was lost this way.
# Neither was visible for three days; both surfaced only as the downstream
# "eval stale" alarm, which points at evaluate_shadow.py instead of at the
# stale parquet that actually caused it. See memory/gotcha-log.md.
T0_EXPECTED_ADVANCE_DAYS = 1


def classify_t0_advance(
    prev_t0: str | pd.Timestamp | None, t0: pd.Timestamp
) -> tuple[int | None, str | None]:
    """Return ``(advance_days, alarm_message)`` for this run's t0 vs the last run's.

    Compares calendar DATES, not raw hours: a healthy step is 08-26T21:00 →
    08-27T20:00 (23h) as readily as a clean 24h, depending on how much of the
    delivery day EDH had published. Returns ``(None, None)`` on the first run
    (or after a state reset), when there is no previous t0 to compare against.
    """
    if prev_t0 is None:
        return None, None
    prev = pd.Timestamp(prev_t0)
    advance = (t0.date() - prev.date()).days
    if advance == T0_EXPECTED_ADVANCE_DAYS:
        return advance, None
    if advance == 0:
        return advance, (
            f"ALARM: t0 did not advance (still {t0.date()}) — parquet is stale, "
            "this run overwrites yesterday's vintage and produces nothing new "
            "to evaluate."
        )
    if advance < 0:
        return advance, (
            f"ALARM: t0 went BACKWARDS ({prev.date()} -> {t0.date()}) — parquet "
            "lost realised prices; investigate consolidate.py before trusting "
            "this run."
        )
    return advance, (
        f"ALARM: t0 jumped {advance}d ({prev.date()} -> {t0.date()}) — "
        f"{advance - 1} vintage(s) skipped and permanently unevaluable."
    )


def run_shadow_update(
    parquet_path: Path = DEFAULT_PARQUET,
    shadow_dir: Path = DEFAULT_SHADOW_DIR,
    forecast_out: Path = DEFAULT_FORECAST_OUT,
    horizons: Sequence[int] = HORIZONS,
    window_days: int = WINDOW_DAYS,
) -> dict:
    """Run one full shadow update cycle. Returns the updated state dict."""
    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet not found: {parquet_path}")

    parquet = _normalize_parquet_index(pd.read_parquet(parquet_path))
    if parquet.empty:
        raise ValueError("Parquet is empty")

    state_path = shadow_dir / SHADOW_STATE_FILENAME
    state = load_shadow_state(state_path)

    # 2. Backfill pending → calibration
    realized_rows, still_pending = backfill_realized(state["pending_predictions"], parquet)
    state["calibration_history"] = trim_to_recent_days(
        list(state["calibration_history"]) + realized_rows, MAX_HISTORY_DAYS
    )
    state["pending_predictions"] = trim_to_recent_days(still_pending, MAX_HISTORY_DAYS)
    logger.info(
        "Backfilled %d pending predictions; %d calibration rows; %d still pending",
        len(realized_rows),
        len(state["calibration_history"]),
        len(state["pending_predictions"]),
    )

    # 3. Pick t0 = last timestamp we can actually build a feature row for.
    #
    #    NOT simply the last realised price: the feeds have different horizons,
    #    so the price column can reach a day further than load_forecast, and an
    #    hour that has a price but no load has an unusable (part-NaN) feature
    #    row. Holding t0 back to the last complete row degrades the forecast
    #    horizon by a day; anchoring on price crashes the run and loses the
    #    vintage outright (2026-08-30). See latest_feasible_t0.
    realized_index = parquet["price_eur_mwh"].dropna().index
    if len(realized_index) == 0:
        raise ValueError("No realised prices in parquet")
    price_t0 = realized_index.max()
    t0, short_cols = latest_feasible_t0(parquet, price_t0)
    if t0 is None:
        raise ValueError(
            f"No complete feature row anywhere at or before price_t0={price_t0!r}"
        )
    held_back_h = (price_t0 - t0).total_seconds() / 3600
    if t0 < price_t0:
        logger.warning(
            "ALARM: t0 held back %.0fh to %s (last price is %s) — short feeds: %s. "
            "The forecast anchor is behind the price horizon; upstream truncation.",
            held_back_h,
            t0,
            price_t0,
            ", ".join(short_cols) or "none identified",
        )

    # 3b. Guard: did t0 actually advance one day since the last run?
    t0_advance_days, t0_alarm = classify_t0_advance(state.get("last_t0"), t0)
    if t0_alarm:
        logger.warning(t0_alarm)

    # 4. Compute CQR q for today
    today = t0.strftime("%Y-%m-%d")
    q, n_calib_days = compute_cqr_q(state["calibration_history"], today)
    logger.info(
        "CQR q=%.3f from %d calibration day(s); applying to bands", q, n_calib_days
    )

    # 5. Train multi-horizon model on rolling window
    window = select_training_window(parquet, t0, window_days)
    model, n_train_samples = fit_multi_horizon(window, window_days=window_days)
    logger.info(
        "Trained MultiHorizon model on %d clean rows from window %s..%s",
        n_train_samples,
        window.index.min(),
        window.index.max(),
    )

    # 6. Predict + widen with CQR
    preds = predict_72h(model, parquet, t0, horizons=horizons)
    preds = widen_with_cqr(preds, q)

    # 7. Append today's preds (without realised) to pending.
    # p10/p50/p90 are sorted-and-CQR-widened (used for band coverage + dashboard).
    # p10_raw/p50_raw/p90_raw are the raw tau=0.10/0.50/0.90 model outputs
    # (used for pinball-at-tau scoring; see predict_72h docstring).
    new_pending = [
        {
            "timestamp_utc": pd.Timestamp(row["timestamp_utc"]).isoformat(),
            "eval_day": today,
            # The anchor, recorded rather than left to be re-derived. evaluate_shadow's
            # seasonal-naive baseline needs the horizon of every hour, and inferring t0
            # from the surviving rows is unsafe: only REALISED hours reach
            # calibration_history, so a vintage whose leading hours were withheld
            # (unrealised, or non-ENTSO-E per backfill_realized) would infer an anchor
            # LATER than the truth and hand the baseline prices from after t0.
            # Added 2026-09-06; rows written before then have no t0_utc.
            "t0_utc": t0.isoformat(),
            "p10": float(row["p10_cqr"]),
            "p50": float(row["p50"]),
            "p90": float(row["p90_cqr"]),
            "p10_raw": float(row["p10_raw"]),
            "p50_raw": float(row["p50_raw"]),
            "p90_raw": float(row["p90_raw"]),
        }
        for _, row in preds.iterrows()
    ]
    # Dedup by (timestamp_utc, eval_day) so repeat runs against the same
    # parquet don't stack duplicate prediction sets in pending_predictions.
    # Bit us on 2026-05-08 during the silent-failure recovery: three runs
    # within one day all saw the same parquet, stacked 144 then 216
    # predictions for the same eval_day, and polluted the M4 promotion
    # metrics when realised prices arrived. Last entry per key wins, which
    # in this idiom is the most recent run because new_pending appends
    # AFTER the existing state. Idempotent: re-running gives the same
    # output state.
    merged = list(state["pending_predictions"]) + new_pending
    deduped = {(r["timestamp_utc"], r["eval_day"]): r for r in merged}
    state["pending_predictions"] = trim_to_recent_days(
        list(deduped.values()), MAX_HISTORY_DAYS
    )

    # 8. Persist artifacts
    shadow_dir.mkdir(parents=True, exist_ok=True)
    model_path = shadow_dir / SHADOW_MODEL_FILENAME
    model.save(model_path)  # HMAC-signed via secure_pickle (see lightgbm_quantile.py)
    logger.info("Saved HMAC-signed model to %s", model_path)

    forecast, upper, lower = format_forecast_dicts(preds)
    surcharge = read_arf_surcharge()
    consumer, consumer_upper, consumer_lower = format_consumer_dicts(
        forecast, upper, lower, surcharge
    )
    metadata = {
        "model": "LightGBM-Quantile-Multi-Horizon",
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "t0": t0.isoformat(),
        "window_days": window_days,
        "n_train_samples": n_train_samples,
        "horizon_groups": [list(g) for g in DEFAULT_GROUPS],
        "cqr_q": round(q, 4),
        "cqr_calib_days_used": n_calib_days,
        "cqr_calib_window_days": DEFAULT_CALIB_DAYS,
        "cqr_target_coverage": DEFAULT_TARGET_COVERAGE,
        "consumer_surcharge_eur_mwh": round(surcharge, 2),
        "consumer_vat_rate": VAT_RATE,
    }
    write_forecast_json(
        forecast_out,
        forecast,
        upper,
        lower,
        metadata,
        consumer=consumer,
        consumer_upper=consumer_upper,
        consumer_lower=consumer_lower,
    )
    logger.info(
        "Wrote shadow forecast (with consumer fields, surcharge=%.2f) to %s",
        surcharge,
        forecast_out,
    )

    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    # Persisted for the next run's t0 guard and for daily_update.sh's
    # post-run alarm, which reads both fields out of shadow_state.json.
    state["last_t0"] = t0.isoformat()
    state["t0_advance_days"] = t0_advance_days
    # Persist the hold-back, do not merely log it. A run whose anchor is held
    # back produces a SHORTER, degraded forecast while exiting 0 with a clean
    # `shadow rc=0` — the exact soft-failure-with-no-reader shape that hid the
    # 2026-08-30 outage for a day. daily_update.sh turns these into a commit
    # subject marker, which is what heartbeat_check.sh reads.
    state["t0_held_back_hours"] = round(held_back_h, 1)
    state["t0_short_feeds"] = short_cols
    state["last_train_window"] = {
        "start": pd.Timestamp(window.index.min()).isoformat(),
        "end": pd.Timestamp(window.index.max()).isoformat(),
    }
    state["n_train_samples"] = n_train_samples
    state["last_cqr_q"] = round(q, 4)
    state["last_cqr_n_calib_days"] = n_calib_days

    save_shadow_state(state, state_path)
    return state


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Nightly shadow update (EXP-009)")
    parser.add_argument(
        "--parquet",
        default=str(DEFAULT_PARQUET),
        help=f"Path to training_history.parquet (default: {DEFAULT_PARQUET})",
    )
    parser.add_argument(
        "--shadow-dir",
        default=str(DEFAULT_SHADOW_DIR),
        help="Directory for shadow_state.json and shadow_model.pkl(.hmac)",
    )
    parser.add_argument(
        "--forecast-out",
        default=str(DEFAULT_FORECAST_OUT),
        help="Output path for augur_forecast_shadow.json",
    )
    args = parser.parse_args()

    run_shadow_update(
        parquet_path=Path(args.parquet),
        shadow_dir=Path(args.shadow_dir),
        forecast_out=Path(args.forecast_out),
    )


if __name__ == "__main__":
    main()
