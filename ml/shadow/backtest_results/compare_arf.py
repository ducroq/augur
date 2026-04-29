"""Build LightGBM-vs-ARF per-day comparison for the EXP-009 milestone-2 summary.

ARF baseline: docs/figures/arf-retrospective/data/metrics_history.csv `update_mae`
column (per-day next-hour MAE). Honest from 2026-04-14 onward — earlier days had
frozen `mae` until the 2026-04-14 forecast-fix commit.

Output: ml/shadow/backtest_results/comparison.csv
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
ARF_CSV = ROOT / "docs" / "figures" / "arf-retrospective" / "data" / "metrics_history.csv"
LGBM_CSV = ROOT / "ml" / "shadow" / "backtest_results" / "per_day_metrics.csv"
OUT_CSV = ROOT / "ml" / "shadow" / "backtest_results" / "comparison.csv"


def main():
    arf = pd.read_csv(ARF_CSV)[["date", "update_mae"]].rename(columns={"update_mae": "arf_mae"})
    lgbm = pd.read_csv(LGBM_CSV)[["eval_day", "mae", "min_realized"]].rename(
        columns={"eval_day": "date", "mae": "lgbm_mae"}
    )
    df = arf.merge(lgbm, on="date", how="inner")
    # Window of honest ARF metrics: 2026-04-14 onward (pre-fix days had frozen mae=13.8).
    df = df[df["date"] >= "2026-04-14"].copy()
    df["delta"] = df["lgbm_mae"] - df["arf_mae"]
    df["pct_improvement"] = -df["delta"] / df["arf_mae"] * 100.0
    df.to_csv(OUT_CSV, index=False, float_format="%.2f")

    print(f"window: {df['date'].min()} -> {df['date'].max()} ({len(df)} days)")
    print(f"ARF mean update_mae:  {df['arf_mae'].mean():.2f}")
    print(f"LGBM mean mae:        {df['lgbm_mae'].mean():.2f}")
    print(f"mean delta:           {df['delta'].mean():.2f}")
    print(f"mean pct improvement: {df['pct_improvement'].mean():.1f}%")
    print(f"days LGBM wins:       {(df['delta'] < 0).sum()}/{len(df)}")
    print()
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
