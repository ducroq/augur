"""Daily LightGBM-vs-ARF evaluation for the EXP-009 shadow pipeline.

CLI:
    python -m ml.shadow.evaluate_shadow --augur-dir /path/to/augur

For every fully-realised eval day in shadow_state.json's calibration_history
that is not yet present in eval_log.jsonl, computes the side-by-side metrics
specified in the LightGBM-shadow plan §5 and appends one row to the JSONL log.

Schema (one row per fully-realised eval day):
    date                          str  YYYY-MM-DD UTC
    n_overlap_hours               int  hours where both models predicted
    lightgbm_mae                  float
    arf_mae                       float | null  (null when no ARF archive overlaps)
    lightgbm_mae_at_low_price     float | null  (realised < 30 EUR/MWh; null when n=0)
    arf_mae_at_low_price          float | null
    lightgbm_band_coverage_p80    float  (post-CQR — p10/p90 in pending are CQR-widened)
    peak_hour_mae_delta           float | null  (lightgbm - arf MAE on weekday 16-19 UTC)

Promotion criteria (plan §6) read this log:
    (a) lightgbm_mae_at_low_price ≤ 0.75 * arf_mae_at_low_price (>=25% relative win)
    (b) lightgbm_band_coverage_p80 in [0.75, 0.85]
    (c) peak_hour_mae_delta ≤ 0.10 * arf_peak (no more than +10% worse)

This module evaluates per day; the 14-day promotion decision is a separate
manual reading of the log (plan §6 explicitly: "Doesn't auto-promote").
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.update_shadow import (
    DEFAULT_SHADOW_DIR,
    SHADOW_STATE_FILENAME,
    load_shadow_state,
)

logger = logging.getLogger(__name__)

LOW_PRICE_THRESHOLD = 30.0
PEAK_HOUR_START = 16  # UTC inclusive
PEAK_HOUR_END = 20    # UTC exclusive (16-19 inclusive == [16, 20) half-open)
MIN_HOURS_FOR_FULL_DAY = 24

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_EVAL_LOG = _REPO_ROOT / "ml" / "shadow" / "eval_log.jsonl"
DEFAULT_ARF_FORECASTS_DIR = _REPO_ROOT / "ml" / "forecasts"

_ARCHIVE_FILENAME_RE = re.compile(r"^(?P<ts>\d{8}_\d{4})_forecast\.json$")


# ---------- ARF archive discovery -------------------------------------------


def find_arf_archive_for_day(forecasts_dir: Path, eval_day: str) -> Path | None:
    """Return the most recent ARF archive whose run-time precedes eval_day's start.

    ARF archives names are like ``20260428_1645_forecast.json``.
    """
    if not forecasts_dir.exists():
        return None
    cutoff = pd.Timestamp(eval_day, tz="UTC")
    candidates: list[tuple[pd.Timestamp, Path]] = []
    for p in forecasts_dir.glob("*_forecast.json"):
        m = _ARCHIVE_FILENAME_RE.match(p.name)
        if not m:
            continue
        try:
            ts = pd.Timestamp(
                pd.to_datetime(m.group("ts"), format="%Y%m%d_%H%M")
            ).tz_localize("UTC")
        except Exception:
            continue
        if ts < cutoff:
            candidates.append((ts, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1]


def load_arf_predictions(archive_path: Path) -> dict[pd.Timestamp, float]:
    with open(archive_path) as f:
        payload = json.load(f)
    forecasts = payload.get("forecast", {})
    out: dict[pd.Timestamp, float] = {}
    for ts_iso, val in forecasts.items():
        try:
            ts = pd.Timestamp(ts_iso)
        except Exception:
            continue
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        if val is None:
            continue
        out[ts] = float(val)
    return out


# ---------- per-day evaluation ----------------------------------------------


def _abs_err(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    return (series_a - series_b).abs()


def evaluate_one_day(
    eval_day: str,
    calibration_history: list[dict],
    arf_predictions: dict[pd.Timestamp, float] | None,
) -> dict | None:
    """Compute one row for eval_log.jsonl. Returns None if no realised hours for the day."""
    rows = [
        r
        for r in calibration_history
        if r.get("eval_day") == eval_day and r.get("realized") is not None
    ]
    if not rows:
        return None

    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["lgbm_abs_err"] = _abs_err(df["p50"], df["realized"])
    df = df.sort_values("timestamp_utc").reset_index(drop=True)

    n_overlap = len(df)

    lgbm_mae = float(df["lgbm_abs_err"].mean())
    low_mask = df["realized"] < LOW_PRICE_THRESHOLD
    lgbm_low_mae = (
        float(df.loc[low_mask, "lgbm_abs_err"].mean()) if low_mask.any() else None
    )

    band_coverage = float(
        ((df["realized"] >= df["p10"]) & (df["realized"] <= df["p90"])).mean()
    )

    arf_mae: float | None = None
    arf_low_mae: float | None = None
    peak_delta: float | None = None

    if arf_predictions:
        df["arf_pred"] = df["timestamp_utc"].map(arf_predictions)
        with_arf = df.dropna(subset=["arf_pred"]).copy()
        if not with_arf.empty:
            with_arf["arf_abs_err"] = _abs_err(with_arf["arf_pred"], with_arf["realized"])
            arf_mae = float(with_arf["arf_abs_err"].mean())
            arf_low_mask = with_arf["realized"] < LOW_PRICE_THRESHOLD
            if arf_low_mask.any():
                arf_low_mae = float(with_arf.loc[arf_low_mask, "arf_abs_err"].mean())
            # Peak hours: weekday 16-19 UTC (Mon-Fri). Compare both models on
            # the same hours so the delta is apples-to-apples.
            ts = with_arf["timestamp_utc"]
            peak_mask = (
                (ts.dt.hour >= PEAK_HOUR_START)
                & (ts.dt.hour < PEAK_HOUR_END)
                & (ts.dt.weekday < 5)
            )
            if peak_mask.any():
                lgbm_peak = float(with_arf.loc[peak_mask, "lgbm_abs_err"].mean())
                arf_peak = float(with_arf.loc[peak_mask, "arf_abs_err"].mean())
                peak_delta = lgbm_peak - arf_peak

    def _round(x: float | None, n: int = 3) -> float | None:
        return None if x is None else round(x, n)

    return {
        "date": eval_day,
        "n_overlap_hours": int(n_overlap),
        "lightgbm_mae": _round(lgbm_mae),
        "arf_mae": _round(arf_mae),
        "lightgbm_mae_at_low_price": _round(lgbm_low_mae),
        "arf_mae_at_low_price": _round(arf_low_mae),
        "lightgbm_band_coverage_p80": _round(band_coverage, 4),
        "peak_hour_mae_delta": _round(peak_delta),
    }


# ---------- eligibility & log management ------------------------------------


def find_eligible_eval_days(
    calibration_history: list[dict],
    eval_log_path: Path,
    min_realised_hours: int = MIN_HOURS_FOR_FULL_DAY,
) -> list[str]:
    """Return eval days with >=min_realised_hours realised AND not yet in eval_log."""
    realised_per_day: dict[str, int] = {}
    for r in calibration_history:
        if r.get("realized") is None:
            continue
        d = r.get("eval_day")
        if not d:
            continue
        realised_per_day[d] = realised_per_day.get(d, 0) + 1
    full = {d for d, n in realised_per_day.items() if n >= min_realised_hours}

    already_logged = read_logged_days(eval_log_path)
    return sorted(full - already_logged)


def read_logged_days(eval_log_path: Path) -> set[str]:
    if not eval_log_path.exists():
        return set()
    days: set[str] = set()
    with open(eval_log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed eval_log line: %r", line[:60])
                continue
            d = row.get("date")
            if d:
                days.add(d)
    return days


def append_eval_row(row: dict, eval_log_path: Path) -> None:
    eval_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(eval_log_path, "a") as f:
        f.write(json.dumps(row, default=str) + "\n")


# ---------- orchestration ---------------------------------------------------


def run_evaluation(
    shadow_dir: Path = DEFAULT_SHADOW_DIR,
    arf_forecasts_dir: Path = DEFAULT_ARF_FORECASTS_DIR,
    eval_log_path: Path = DEFAULT_EVAL_LOG,
) -> list[dict]:
    """Evaluate every newly-eligible day. Returns the rows appended to eval_log."""
    state_path = shadow_dir / SHADOW_STATE_FILENAME
    state = load_shadow_state(state_path)
    eligible = find_eligible_eval_days(state["calibration_history"], eval_log_path)
    if not eligible:
        logger.info("No new fully-realised days to evaluate.")
        return []

    logger.info("Evaluating %d day(s): %s", len(eligible), eligible)
    appended: list[dict] = []
    for day in eligible:
        archive = find_arf_archive_for_day(arf_forecasts_dir, day)
        arf_preds = load_arf_predictions(archive) if archive else None
        if archive is None:
            logger.warning(
                "No ARF archive precedes %s — arf_* fields will be null", day
            )
        row = evaluate_one_day(day, state["calibration_history"], arf_preds)
        if row is None:
            continue
        append_eval_row(row, eval_log_path)
        appended.append(row)
        logger.info(
            "Logged %s: n=%d lgbm_mae=%s arf_mae=%s coverage=%s",
            day,
            row["n_overlap_hours"],
            row["lightgbm_mae"],
            row["arf_mae"],
            row["lightgbm_band_coverage_p80"],
        )
    return appended


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Daily shadow eval (EXP-009)")
    parser.add_argument("--shadow-dir", default=str(DEFAULT_SHADOW_DIR))
    parser.add_argument("--arf-forecasts-dir", default=str(DEFAULT_ARF_FORECASTS_DIR))
    parser.add_argument("--eval-log", default=str(DEFAULT_EVAL_LOG))
    args = parser.parse_args()

    run_evaluation(
        shadow_dir=Path(args.shadow_dir),
        arf_forecasts_dir=Path(args.arf_forecasts_dir),
        eval_log_path=Path(args.eval_log),
    )


if __name__ == "__main__":
    main()
