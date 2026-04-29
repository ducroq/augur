"""Conformalized Quantile Regression (CQR) band correction for shadow predictions.

For each eval day D, computes the (1-alpha)-empirical quantile of the
nonconformity scores E_i = max(p10_i - y_i, y_i - p90_i) over the trailing
`calib_days` of prior predictions, and inflates bands by that amount.

Reference: Romano, Patterson, Candès (2019), "Conformalized Quantile Regression"
(NeurIPS 32). Exchangeability is approximate here because each day's predictions
come from a separately-fit model in the walk-forward harness, but for prices the
day-to-day structure is similar enough that the asymptotic coverage guarantee is
a useful target. Days without sufficient calibration history get zero inflation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_CALIB_DAYS = 7
MIN_CALIB_DAYS = 3
DEFAULT_TARGET_COVERAGE = 0.80


def apply_cqr(
    preds: pd.DataFrame,
    calib_days: int = DEFAULT_CALIB_DAYS,
    target_coverage: float = DEFAULT_TARGET_COVERAGE,
    min_calib_days: int = MIN_CALIB_DAYS,
) -> pd.DataFrame:
    """Add p10_cqr / p90_cqr columns to a predictions DataFrame.

    Args:
        preds: must contain timestamp_utc, eval_day, p10, p50, p90, realized.
        calib_days: trailing window in days for the calibration set.
        target_coverage: target empirical coverage (e.g. 0.80 for P80 bands).
        min_calib_days: minimum distinct days of calibration data to apply
            the correction. Days below this threshold get zero inflation.

    Returns:
        A copy of `preds` with added columns: nonconformity, cqr_q,
        p10_cqr, p90_cqr.
    """
    required = {"timestamp_utc", "eval_day", "p10", "p50", "p90", "realized"}
    missing = required - set(preds.columns)
    if missing:
        raise ValueError(f"preds missing columns: {sorted(missing)}")

    df = preds.copy().sort_values("timestamp_utc").reset_index(drop=True)
    df["nonconformity"] = np.maximum(df["p10"] - df["realized"], df["realized"] - df["p90"])

    ts = pd.to_datetime(df["timestamp_utc"])

    eval_days = sorted(df["eval_day"].unique())
    alpha = 1.0 - target_coverage
    day_to_q: dict[str, float] = {}

    for day in eval_days:
        cutoff_end = pd.Timestamp(day, tz="UTC")
        cutoff_start = cutoff_end - pd.Timedelta(days=calib_days)
        mask = (ts >= cutoff_start) & (ts < cutoff_end)
        calib = df.loc[mask, "nonconformity"].dropna()
        n_calib_days = ts[mask].dt.date.nunique()

        if n_calib_days < min_calib_days or len(calib) == 0:
            day_to_q[day] = 0.0
            continue

        # Standard split-conformal finite-sample correction:
        # rank = ceil((n + 1) * (1 - alpha)), 1-indexed; 0-indexed below.
        n = len(calib)
        rank = int(np.ceil((n + 1) * (1 - alpha))) - 1
        rank = min(max(rank, 0), n - 1)
        q = float(np.sort(calib.to_numpy())[rank])
        day_to_q[day] = max(q, 0.0)

    df["cqr_q"] = df["eval_day"].map(day_to_q).astype(float)
    df["p10_cqr"] = df["p10"] - df["cqr_q"]
    df["p90_cqr"] = df["p90"] + df["cqr_q"]
    return df
