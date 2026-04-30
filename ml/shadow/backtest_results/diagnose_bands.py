"""Diagnose the EXP-009 milestone-2 P80 band under-coverage.

Headline gap: 56.3% empirical coverage vs 75-85% target. Question: is the
miss chronic across all days, or concentrated on regime-shift days where the
training window doesn't contain comparable tails?

Outputs are descriptive only — no decisions about remedies here.
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PREDS = ROOT / "ml" / "shadow" / "backtest_results" / "predictions.parquet"
OUT = ROOT / "ml" / "shadow" / "backtest_results" / "band_diagnostic.csv"


def main():
    df = pd.read_parquet(PREDS).copy()
    df["in_band"] = (df["realized"] >= df["p10"]) & (df["realized"] <= df["p90"])
    df["above_band"] = df["realized"] > df["p90"]
    df["below_band"] = df["realized"] < df["p10"]
    df["band_width"] = df["p90"] - df["p10"]
    df["abs_err"] = np.abs(df["p50"] - df["realized"])
    df["ts"] = pd.to_datetime(df["timestamp_utc"])
    df["hour_utc"] = df["ts"].dt.hour

    # --- Per-day breakdown -------------------------------------------------
    by_day = (
        df.groupby("eval_day")
        .agg(
            coverage=("in_band", "mean"),
            above=("above_band", "mean"),
            below=("below_band", "mean"),
            band_width=("band_width", "median"),
            mae=("abs_err", "mean"),
            min_realized=("realized", "min"),
            max_realized=("realized", "max"),
            realized_std=("realized", "std"),
        )
        .reset_index()
    )
    by_day.to_csv(OUT, index=False, float_format="%.3f")

    # --- Headline aggregates ----------------------------------------------
    n_days = len(by_day)
    target_lo, target_hi = 0.75, 0.85
    days_in_target = ((by_day["coverage"] >= target_lo) & (by_day["coverage"] <= target_hi)).sum()
    days_above = (by_day["coverage"] > target_hi).sum()
    days_below_50 = (by_day["coverage"] < 0.50).sum()
    days_below_25 = (by_day["coverage"] < 0.25).sum()

    overall_above = df["above_band"].mean()
    overall_below = df["below_band"].mean()

    print("=" * 60)
    print("Per-day P80 coverage — chronic or concentrated?")
    print("=" * 60)
    print(f"Total eval days:                {n_days}")
    print(f"Days in [75%, 85%] target:      {days_in_target}")
    print(f"Days above 85%:                 {days_above}")
    print(f"Days below 75%:                 {n_days - days_in_target - days_above}")
    print(f"Days below 50%:                 {days_below_50}")
    print(f"Days below 25%:                 {days_below_25}")
    print()
    print("Overall miss direction:")
    print(f"  realized > P90 (under-band):  {overall_above:.1%}")
    print(f"  realized < P10 (over-band):   {overall_below:.1%}")
    print(f"  total miss:                   {overall_above + overall_below:.1%}")
    print()
    print("Coverage vs realized-volatility correlation:")
    corr = by_day[["coverage", "realized_std", "band_width", "mae"]].corr()
    print(corr.round(2).to_string())
    print()

    # --- Per-hour-of-day breakdown ----------------------------------------
    by_hour = (
        df.groupby("hour_utc")
        .agg(coverage=("in_band", "mean"), above=("above_band", "mean"), below=("below_band", "mean"))
        .reset_index()
    )
    print("Hour-of-day coverage:")
    print(by_hour.round(3).to_string(index=False))
    print()

    # --- Per-day with worst miss ------------------------------------------
    worst = by_day.nsmallest(5, "coverage")
    best = by_day.nlargest(5, "coverage")
    print("5 worst days (lowest coverage):")
    print(worst.round(3).to_string(index=False))
    print()
    print("5 best days (highest coverage):")
    print(best.round(3).to_string(index=False))


if __name__ == "__main__":
    main()
