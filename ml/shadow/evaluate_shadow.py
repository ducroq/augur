"""Daily LightGBM-vs-ARF evaluation for the EXP-009 shadow pipeline.

CLI:
    python -m ml.shadow.evaluate_shadow \\
        --shadow-dir <path>/ml/models/shadow \\
        --arf-forecasts-dir <path>/ml/forecasts \\
        --eval-log <path>/ml/shadow/eval_log.jsonl
    # All three default from _REPO_ROOT for in-repo runs.

For every fully-realised eval day in shadow_state.json's calibration_history
that is not yet present in eval_log.jsonl, computes the side-by-side metrics
specified in the LightGBM-shadow plan §5 and appends one row to the JSONL log.

Schema (one row per fully-realised eval day):
    date                          str  YYYY-MM-DD UTC
    n_overlap_hours               int  hours where both models predicted
    n_low_price_hours             int  hours where realised < 30 EUR/MWh (transparency for criterion (a))
    lightgbm_mae                  float
    arf_mae                       float | null  (null when no ARF archive overlaps)
    lightgbm_mae_at_low_price     float | null  (realised < 30 EUR/MWh; null when n=0)
    arf_mae_at_low_price          float | null
    lightgbm_band_coverage_p80    float  (post-CQR — p10/p90 in pending are CQR-widened)
    lightgbm_peak_hour_mae        float | null  (weekday 16-19 UTC; null when no weekday peak in day)
    arf_peak_hour_mae             float | null
    peak_hour_mae_delta           float | null  (lightgbm_peak - arf_peak; same hours, apples-to-apples)
    n_naive_hours                 int  hours where the seasonal-naive baseline was computable
    naive_mae                     float | null  (seasonal-naive; null when n_naive_hours == 0)
    lightgbm_mae_on_naive_hours   float | null  (LGBM restricted to those same hours)
    lightgbm_skill_vs_naive       float | null  (1 - lgbm/naive on paired hours; >0 means LGBM better)
    naive_min_horizon_h           int | null  horizon span the naive_* numbers cover —
    naive_max_horizon_h           int | null  naive MAE is horizon-dependent, so rows
                                              are only comparable within a span

Why the naive baseline is here (added 2026-09-06):
    Every metric above compares LightGBM against ARF, and nothing compared
    either against a trivial baseline. Measured over 2026-07-30..08-24 on
    horizon-matched pairs, LGBM's p50 lost to "same hour, last day available at
    t0" at EVERY horizon (26.9 vs 23.3 at 1-24h, 33.9 vs 28.9 at 25-48h, 36.9
    vs 32.7 at 49-72h), and over 96 mixed-horizon eval days it beat that
    baseline on 42 — 44%, worse than a coin flip. Two models racing each other
    to last place read as a healthy log because the log had no floor in it.
    `lightgbm_skill_vs_naive` is that floor: negative means the model is not
    earning its place. See docs/hypothesis-log.md [2026-09-06].

    The baseline is honest about information: at horizon h it may only use the
    same clock hour from `24 * ceil(h / 24)` hours earlier, which is the last
    same-hour value actually known at t0. It never reads a price from the
    forecast's own future.

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
    _normalize_parquet_index,
    DEFAULT_PARQUET,
    DEFAULT_SHADOW_DIR,
    PROVENANCE_COLUMN,
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


# ---------- seasonal-naive baseline -----------------------------------------


def load_price_history(parquet_path: Path) -> pd.Series | None:
    """Realised ENTSO-E hourly prices, for scoring the seasonal-naive baseline.

    Returns None (rather than an empty Series) for EVERY unusable parquet —
    absent, unreadable, wrong index type, no price column, or duplicated
    timestamps — so a bad file degrades one metric instead of aborting the
    nightly eval and losing the whole row. The caller then leaves naive_* null
    instead of
    logging a zero-skill row that would read as "the model has no edge" when it
    actually means "the baseline could not be computed".

    Hours whose price did not come from ENTSO-E are dropped, matching
    `update_shadow.pair_pending_against_parquet`: a fallback (elspot) price is
    not the target this model is scored against, and consolidate.py marks
    rather than drops those rows precisely so readers can exclude them here.
    """
    if not parquet_path.exists():
        logger.warning(
            "No parquet at %s — naive baseline fields will be null", parquet_path
        )
        return None
    try:
        parquet = _normalize_parquet_index(pd.read_parquet(parquet_path))
    except Exception as exc:  # noqa: BLE001 - see the contract above
        logger.warning("Could not read %s (%s) — naive fields null", parquet_path, exc)
        return None
    if parquet.empty or "price_eur_mwh" not in parquet.columns:
        logger.warning("Parquet has no price column — naive fields null")
        return None

    prices = parquet["price_eur_mwh"].dropna()
    if PROVENANCE_COLUMN in parquet.columns:
        provenance = parquet[PROVENANCE_COLUMN].reindex(prices.index)
        prices = prices[provenance >= 1.0]  # NaN fails this: unknown is not ENTSO-E
    else:
        logger.warning(
            "Parquet has no %s column — the naive baseline may be scored against "
            "fallback prices. Regenerate with the current ml/data/consolidate.py.",
            PROVENANCE_COLUMN,
        )
    if prices.empty:
        return None
    if prices.index.has_duplicates:
        # `reindex` raises on a duplicated source index. Unreachable through
        # consolidate (it resamples hourly) but reachable via --parquet.
        logger.warning(
            "Price history has duplicate timestamps — naive fields null. "
            "Regenerate the parquet with ml/data/consolidate.py."
        )
        return None
    return prices.astype(float)


def naive_source_timestamp(ts: pd.Timestamp, t0: pd.Timestamp) -> pd.Timestamp:
    """Same clock hour on the most recent day whose value was known at t0.

    For a forecast anchored at `t0`, the hour `ts` sits at horizon
    `h = ts - t0`. The last same-hour observation available when that forecast
    was made is `24 * ceil(h / 24)` hours back — 24h back for the first day of
    the horizon, 48h for the second, 72h for the third. Anything closer would
    hand the baseline a price the model itself never saw.
    """
    hours = (ts - t0).total_seconds() / 3600.0
    days_back = max(1, int(np.ceil(hours / 24.0)))
    # days=, not hours=24*n: identical in UTC and it keeps NumPy from warning
    # about a bare-integer timedelta unit.
    return ts - pd.Timedelta(days=days_back)


def _as_utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def t0_for_eval_day(calibration_history: list[dict], eval_day: str) -> pd.Timestamp | None:
    """Anchor of the forecast that produced `eval_day`'s rows, or None if unknowable.

    Prefers the recorded `t0_utc` (written by update_shadow since 2026-09-06).
    Falls back to `earliest predicted hour - 1h` for rows written before that,
    but ONLY when the inferred anchor's date matches `eval_day` — because
    `eval_day` IS `t0.strftime("%Y-%m-%d")` (update_shadow.py, step 4).

    Why the fallback needs that check, and why failure returns None rather than a
    best guess: `calibration_history` holds REALISED rows only. `backfill_realized`
    leaves unrealised and non-ENTSO-E hours in `pending_predictions` and never
    promotes them, so a vintage whose LEADING hours were withheld has its earliest
    surviving row well after t0+1h. Inference then puts the anchor too late, every
    horizon is under-counted, and `naive_source_timestamp` hands the baseline a
    price from AFTER the true t0 — a lookahead leak that flatters the baseline and
    biases `lightgbm_skill_vs_naive` downward, toward the very conclusion the field
    exists to test. A null row costs one day of evidence; a leaking row corrupts
    the verdict. Found in review 2026-09-06, before any naive_* row was written.
    """
    rows = [r for r in calibration_history if r.get("eval_day") == eval_day]
    if not rows:
        return None

    recorded = {r["t0_utc"] for r in rows if r.get("t0_utc")}
    if len(recorded) == 1:
        return _as_utc(pd.Timestamp(recorded.pop()))
    if len(recorded) > 1:
        logger.warning(
            "%s: calibration rows disagree on t0_utc (%s) — naive fields null",
            eval_day,
            ", ".join(sorted(recorded)),
        )
        return None

    stamps = [pd.Timestamp(r["timestamp_utc"]) for r in rows if r.get("timestamp_utc")]
    if not stamps:
        return None
    inferred = _as_utc(min(stamps)) - pd.Timedelta(hours=1)
    if inferred.strftime("%Y-%m-%d") != eval_day:
        logger.warning(
            "%s: no recorded t0_utc and the inferred anchor %s falls on a different "
            "day — leading hours were withheld, so the horizon of every row is "
            "unknown. Naive fields left null rather than leaked.",
            eval_day,
            inferred.isoformat(),
        )
        return None
    return inferred


# ---------- per-day evaluation ----------------------------------------------


def _abs_err(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    return (series_a - series_b).abs()


def evaluate_one_day(
    eval_day: str,
    calibration_history: list[dict],
    arf_predictions: dict[pd.Timestamp, float] | None,
    price_history: pd.Series | None = None,
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
    n_low_price = int(low_mask.sum())
    lgbm_low_mae = (
        float(df.loc[low_mask, "lgbm_abs_err"].mean()) if low_mask.any() else None
    )

    band_coverage = float(
        ((df["realized"] >= df["p10"]) & (df["realized"] <= df["p90"])).mean()
    )

    arf_mae: float | None = None
    arf_low_mae: float | None = None
    lgbm_peak_mae: float | None = None
    arf_peak_mae: float | None = None
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
                lgbm_peak_mae = float(with_arf.loc[peak_mask, "lgbm_abs_err"].mean())
                arf_peak_mae = float(with_arf.loc[peak_mask, "arf_abs_err"].mean())
                peak_delta = lgbm_peak_mae - arf_peak_mae

    n_naive_hours = 0
    naive_mae: float | None = None
    lgbm_mae_on_naive: float | None = None
    naive_skill: float | None = None
    naive_min_horizon_h: int | None = None
    naive_max_horizon_h: int | None = None

    t0 = t0_for_eval_day(calibration_history, eval_day)
    if price_history is not None and t0 is not None:
        source_ts = [naive_source_timestamp(ts, t0) for ts in df["timestamp_utc"]]
        df["naive_pred"] = price_history.reindex(pd.DatetimeIndex(source_ts)).to_numpy()
        paired = df.dropna(subset=["naive_pred"])
        n_naive_hours = len(paired)
        if n_naive_hours:
            # Which horizons this row actually covers. A vintage becomes eligible
            # at 24 realised hours, but WHICH 24 varies, and naive MAE is strongly
            # horizon-dependent (23.3 / 28.9 / 32.7 at 1-24 / 25-48 / 49-72h).
            # Averaging skill across rows that span different horizons compares
            # numbers on different scales, so the span travels with the number.
            horizons = ((paired["timestamp_utc"] - t0).dt.total_seconds() / 3600).round()
            naive_min_horizon_h = int(horizons.min())
            naive_max_horizon_h = int(horizons.max())
            naive_mae = float(_abs_err(paired["naive_pred"], paired["realized"]).mean())
            # Restrict LGBM to the SAME hours: the baseline has gaps wherever the
            # source day is missing or non-ENTSO-E, and comparing a full-day MAE
            # against a partial-day one would invent skill out of the gaps.
            lgbm_mae_on_naive = float(paired["lgbm_abs_err"].mean())
            if naive_mae > 0:
                naive_skill = 1.0 - lgbm_mae_on_naive / naive_mae

    def _round(x: float | None, n: int = 3) -> float | None:
        return None if x is None else round(x, n)

    return {
        "date": eval_day,
        "n_overlap_hours": int(n_overlap),
        "n_low_price_hours": n_low_price,
        "lightgbm_mae": _round(lgbm_mae),
        "arf_mae": _round(arf_mae),
        "lightgbm_mae_at_low_price": _round(lgbm_low_mae),
        "arf_mae_at_low_price": _round(arf_low_mae),
        "lightgbm_band_coverage_p80": _round(band_coverage, 4),
        "lightgbm_peak_hour_mae": _round(lgbm_peak_mae),
        "arf_peak_hour_mae": _round(arf_peak_mae),
        "peak_hour_mae_delta": _round(peak_delta),
        "n_naive_hours": int(n_naive_hours),
        "naive_mae": _round(naive_mae),
        "lightgbm_mae_on_naive_hours": _round(lgbm_mae_on_naive),
        "lightgbm_skill_vs_naive": _round(naive_skill, 4),
        "naive_min_horizon_h": naive_min_horizon_h,
        "naive_max_horizon_h": naive_max_horizon_h,
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
    parquet_path: Path = DEFAULT_PARQUET,
) -> list[dict]:
    """Evaluate every newly-eligible day. Returns the rows appended to eval_log."""
    state_path = shadow_dir / SHADOW_STATE_FILENAME
    state = load_shadow_state(state_path)
    eligible = find_eligible_eval_days(state["calibration_history"], eval_log_path)
    if not eligible:
        logger.info("No new fully-realised days to evaluate.")
        return []

    # After the early-out: on a no-op night there is no row to attach a
    # "parquet missing" warning to, and reading it would be wasted I/O.
    price_history = load_price_history(parquet_path)

    logger.info("Evaluating %d day(s): %s", len(eligible), eligible)
    appended: list[dict] = []
    for day in eligible:
        archive = find_arf_archive_for_day(arf_forecasts_dir, day)
        arf_preds = load_arf_predictions(archive) if archive else None
        if archive is None:
            logger.warning(
                "No ARF archive precedes %s — arf_* fields will be null", day
            )
        row = evaluate_one_day(
            day, state["calibration_history"], arf_preds, price_history
        )
        if row is None:
            continue
        append_eval_row(row, eval_log_path)
        appended.append(row)
        logger.info(
            "Logged %s: n=%d lgbm_mae=%s arf_mae=%s naive_mae=%s skill=%s coverage=%s",
            day,
            row["n_overlap_hours"],
            row["lightgbm_mae"],
            row["arf_mae"],
            row["naive_mae"],
            row["lightgbm_skill_vs_naive"],
            row["lightgbm_band_coverage_p80"],
        )
        if row["lightgbm_skill_vs_naive"] is not None and row["lightgbm_skill_vs_naive"] < 0:
            logger.warning(
                "%s: LightGBM lost to the seasonal-naive baseline "
                "(%.2f vs %.2f MAE over %d h). Not an error — a result.",
                day,
                row["lightgbm_mae_on_naive_hours"],
                row["naive_mae"],
                row["n_naive_hours"],
            )
    return appended


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Daily shadow eval (EXP-009)")
    parser.add_argument("--shadow-dir", default=str(DEFAULT_SHADOW_DIR))
    parser.add_argument("--arf-forecasts-dir", default=str(DEFAULT_ARF_FORECASTS_DIR))
    parser.add_argument("--eval-log", default=str(DEFAULT_EVAL_LOG))
    parser.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    args = parser.parse_args()

    run_evaluation(
        shadow_dir=Path(args.shadow_dir),
        arf_forecasts_dir=Path(args.arf_forecasts_dir),
        eval_log_path=Path(args.eval_log),
        parquet_path=Path(args.parquet),
    )


if __name__ == "__main__":
    main()
