#!/usr/bin/env python3
"""EXP-036: is the seasonal-naive floor too weak?

Pre-committed in docs/experiment-backlog.md on 2026-09-10 (pinned 2113e1f)
before any profile baseline had been computed. Method is fixed there; this file
only executes it.

The question
------------
`evaluate_shadow.py`'s floor is a SINGLE-DAY CARRY: the same clock hour
`24*ceil(h/24)` back, which for a 72h vintage is always the one window
`[t0-23h, t0]`. That is one sample per forecast hour. EXP-035 measured LightGBM
`full` at +5.1% over it across nine months. How much of that is skill, and how
much is the floor being a single draw from a noisy distribution?

The obvious strengthening is a PROFILE: the mean of the same clock hour over
the last N days. Averaging K days cuts the baseline's variance roughly as 1/K
while leaving the diurnal shape, which is the part that actually repeats.

Arms (exactly as pre-committed)
-------------------------------
    N1        same clock hour, 1 day back -- the incumbent floor, for continuity
    N2/N3/N5/N7   unweighted mean, same clock hour, last 2/3/5/7 days
    N5_decay  exponentially weighted over 5 days, half-life 2 days
    N5_dt     mean over the last 5 MATCHING day types (weekday/weekend/holiday)

Every arm is built only from prices at or before `t0`, read from the same
context tape EXP-035 uses, so each baseline's information set stays a subset of
the candidate's by construction. `NK` requires all K sources present -- a mean
"over the last K days" computed from fewer is a different estimator, and the
pre-commitment says drop, never fill. All arms are then scored on the
intersection of rows where every arm and every candidate is defined.

Usage
-----
    python scripts/exp036_profile_floor.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from ml.shadow.metrics import diebold_mariano, mean_quantile_score  # noqa: E402
from exp035_naive_floor import CONTEXTS, FM_PREDS, LGBM_PREDS, HAC_LAGS  # noqa: E402

FUNDAMENTALS = REPO / "ml" / "data" / "training_history_fundamentals.parquet"
OUT = REPO / "ml" / "shadow" / "exp036_profile_floor"
TZ = "Europe/Amsterdam"
MAX_LOOKBACK_DAYS = 56          # the context tape's own depth
TAUS = np.array([0.10, 0.50, 0.90])
GROUPS = (("h1_24", 1, 24), ("h25_48", 25, 48), ("h49_72", 49, 72))

# Pre-committed gates.
ADOPT_MIN_GAIN = 0.03           # >= 3% MAE over N1
ADOPT_MAX_P = 0.05              # DM p < 0.05
SIMPLICITY_BAND = 0.01          # simplest arm within 1% of the best


def holiday_dates() -> set:
    """NL public-holiday local dates, from the parquet's is_holiday_nl column."""
    if not FUNDAMENTALS.exists():
        return set()
    f = pd.read_parquet(FUNDAMENTALS, columns=["is_holiday_nl"])
    idx = f.index
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    local = idx.tz_convert(TZ)
    # fillna BEFORE the bool cast. The column is float64 with 1440 NaNs, and
    # numpy casts NaN to True -- which silently typed ~1680 hours as holidays
    # instead of 240, i.e. most of the series, wrecking the day-type matching
    # in exactly the arm this experiment was most likely to adopt.
    flag = f["is_holiday_nl"].fillna(0).to_numpy().astype(bool)
    return set(pd.Series(local.date)[flag])


def day_type(ts: pd.DatetimeIndex, holidays: set) -> np.ndarray:
    """0 weekday, 1 weekend, 2 NL holiday -- on the LOCAL calendar.

    Weekend and holiday are local-calendar notions; deciding them in UTC would
    mis-type the hours either side of midnight.
    """
    local = ts.tz_convert(TZ)
    out = np.where(local.weekday >= 5, 1, 0)
    if holidays:
        out = np.where(pd.Series(local.date).isin(holidays).to_numpy(), 2, out)
    return out


def build_baselines(grid: pd.DataFrame, price: pd.Series,
                    holidays: set) -> pd.DataFrame:
    """Attach every pre-committed baseline arm to the target grid."""
    out = grid.copy()
    days_back = np.ceil(out["horizon_h"] / 24.0).astype(int).clip(lower=1)
    source0 = out["timestamp_utc"] - pd.to_timedelta(days_back * 24, unit="h")

    # Lag matrix: column j is the same clock hour, j further days back.
    lags = np.full((len(out), MAX_LOOKBACK_DAYS), np.nan)
    for j in range(MAX_LOOKBACK_DAYS):
        src = source0 - pd.to_timedelta(j * 24, unit="h")
        idx = pd.MultiIndex.from_arrays([out["t0"], src])
        lags[:, j] = price.reindex(idx).to_numpy()

    out["N1"] = lags[:, 0]
    for k in (2, 3, 5, 7):
        block = lags[:, :k]
        # All k sources required: a mean "over the last k days" built from
        # fewer is a different estimator, and the pre-commitment says drop.
        ok = ~np.isnan(block).any(axis=1)
        out[f"N{k}"] = np.where(ok, np.nanmean(block, axis=1), np.nan)

    # Exponential weights over the same 5 sources, half-life 2 days.
    w = 0.5 ** (np.arange(5) / 2.0)
    block = lags[:, :5]
    ok = ~np.isnan(block).any(axis=1)
    out["N5_decay"] = np.where(ok, (block * w).sum(axis=1) / w.sum(), np.nan)

    # Day-type matched: walk back until 5 sources share the TARGET's day type.
    tgt_type = day_type(pd.DatetimeIndex(out["timestamp_utc"]), holidays)
    src_types = np.empty((len(out), MAX_LOOKBACK_DAYS), dtype=int)
    for j in range(MAX_LOOKBACK_DAYS):
        src = source0 - pd.to_timedelta(j * 24, unit="h")
        src_types[:, j] = day_type(pd.DatetimeIndex(src), holidays)
    match = (src_types == tgt_type[:, None]) & ~np.isnan(lags)
    # First 5 matching columns per row; rows with fewer stay NaN.
    take = match.cumsum(axis=1) <= 5
    sel = match & take
    n_sel = sel.sum(axis=1)
    summed = np.where(sel, np.nan_to_num(lags), 0.0).sum(axis=1)
    out["N5_dt"] = np.where(n_sel == 5, summed / 5.0, np.nan)
    return out


ARMS = ["N1", "N2", "N3", "N5", "N7", "N5_decay", "N5_dt"]
# Simplicity order for gate 3 -- fewer moving parts first.
SIMPLICITY = ["N1", "N2", "N3", "N5", "N7", "N5_decay", "N5_dt"]


def mae(a, b) -> float:
    return float(np.abs(np.asarray(a) - np.asarray(b)).mean())


def main() -> None:
    ap = argparse.ArgumentParser(description="EXP-036 profile floor")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    price = pd.read_parquet(CONTEXTS).set_index(["t0", "timestamp_utc"])["price"]
    lgbm = pd.read_parquet(LGBM_PREDS)
    fm = pd.read_parquet(FM_PREDS)

    grid = (lgbm[lgbm["variant"] == "full"]
            [["t0", "timestamp_utc", "horizon_h", "realized"]]
            .drop_duplicates(["t0", "timestamp_utc"]).reset_index(drop=True))
    base = build_baselines(grid, price, holiday_dates())

    cands = {
        "lgbm_full": lgbm[lgbm["variant"] == "full"],
        "lgbm_drop_rolling": lgbm[lgbm["variant"] == "drop_rolling"],
        "chronos_bolt_base": fm[fm["variant"] == "chronos_bolt_base"],
    }
    d = base.copy()
    for name, c in cands.items():
        c = c[["t0", "timestamp_utc", "p10", "p50", "p90"]].drop_duplicates(
            ["t0", "timestamp_utc"])
        d = d.merge(c.rename(columns={q: f"{name}__{q}" for q in
                                      ("p10", "p50", "p90")}),
                    on=["t0", "timestamp_utc"], how="left")

    need = ARMS + ["realized"] + [f"{n}__p50" for n in cands]
    before = len(d)
    d = d.dropna(subset=need).sort_values(["t0", "horizon_h"]).reset_index(drop=True)

    summary = {
        "precommit": "docs/experiment-backlog.md EXP-036 (2026-09-10), pinned 2113e1f",
        "hac_lags": HAC_LAGS,
        "rows_before_intersection": int(before),
        "n_rows": int(len(d)),
        "n_vintages": int(d["t0"].nunique()),
        "window": [str(d["t0"].min())[:10], str(d["t0"].max())[:10]],
        "note_nk_strict": "NK requires all k sources present; rows short of that are dropped for every arm",
        "baselines": {}, "candidates": {}, "monthly": {},
    }

    y = d["realized"].to_numpy()
    n1 = d["N1"].to_numpy()
    for arm in ARMS:
        p = d[arm].to_numpy()
        row = {"mae": round(mae(p, y), 4),
               "gain_vs_N1": round(float(1 - mae(p, y) / mae(n1, y)), 4)}
        if arm != "N1":
            dm = diebold_mariano(np.abs(y - p), np.abs(y - n1), hac_lags=HAC_LAGS)
            row["dm_p_one_sided"] = round(float(dm.p_value_one_sided), 6)
        for lab, lo, hi in GROUPS:
            m = (d["horizon_h"] >= lo) & (d["horizon_h"] <= hi)
            row[f"mae_{lab}"] = round(mae(d.loc[m, arm], d.loc[m, "realized"]), 4)
        summary["baselines"][arm] = row

    # Gate 1 + gate 3.
    elig = [a for a in ARMS if a != "N1"
            and summary["baselines"][a]["gain_vs_N1"] >= ADOPT_MIN_GAIN
            and summary["baselines"][a]["dm_p_one_sided"] < ADOPT_MAX_P]
    best = max(ARMS, key=lambda a: summary["baselines"][a]["gain_vs_N1"])
    best_gain = summary["baselines"][best]["gain_vs_N1"]
    chosen = next((a for a in SIMPLICITY if a in elig
                   and summary["baselines"][a]["gain_vs_N1"] >= best_gain - SIMPLICITY_BAND),
                  None)
    summary["gates"] = {
        "G1_arms_passing_adoption": elig,
        "G1_any_adopted": bool(elig),
        "best_arm": best, "best_gain_vs_N1": best_gain,
        "G3_chosen_simplest_within_1pct": chosen,
    }

    for name in cands:
        p50 = d[f"{name}__p50"].to_numpy()
        qp = d[[f"{name}__p10", f"{name}__p50", f"{name}__p90"]].to_numpy()
        row = {"mae": round(mae(p50, y), 4),
               "quantile_score_3tau_biased": round(
                   float(mean_quantile_score(y, qp, TAUS)), 4)}
        for arm in ARMS:
            row[f"skill_vs_{arm}"] = round(
                float(1 - mae(p50, y) / mae(d[arm].to_numpy(), y)), 4)
        for lab, lo, hi in GROUPS:
            m = (d["horizon_h"] >= lo) & (d["horizon_h"] <= hi)
            row[f"skill_vs_N1_{lab}"] = round(float(
                1 - mae(d.loc[m, f"{name}__p50"], d.loc[m, "realized"])
                / mae(d.loc[m, "N1"], d.loc[m, "realized"])), 4)
            if best != "N1":
                row[f"skill_vs_best_{lab}"] = round(float(
                    1 - mae(d.loc[m, f"{name}__p50"], d.loc[m, "realized"])
                    / mae(d.loc[m, best], d.loc[m, "realized"])), 4)
        summary["candidates"][name] = row

        mo = d.assign(month=d["t0"].dt.tz_convert("UTC").dt.strftime("%Y-%m"))
        summary["monthly"][name] = {
            m: {"mean_price": round(float(g["realized"].mean()), 2),
                "skill_vs_N1": round(float(
                    1 - mae(g[f"{name}__p50"], g["realized"])
                    / mae(g["N1"], g["realized"])), 4),
                f"skill_vs_{best}": round(float(
                    1 - mae(g[f"{name}__p50"], g["realized"])
                    / mae(g[best], g["realized"])), 4)}
            for m, g in mo.groupby("month")}
        summary["monthly"][name]["n_months_below_N1"] = sum(
            1 for k, v in summary["monthly"][name].items()
            if isinstance(v, dict) and v["skill_vs_N1"] < 0)
        summary["monthly"][name][f"n_months_below_{best}"] = sum(
            1 for k, v in summary["monthly"][name].items()
            if isinstance(v, dict) and v[f"skill_vs_{best}"] < 0)

    # The pre-committed Alternative signals, computed here rather than by hand
    # afterwards, so every number a write-up quotes is in the artifact.
    def gain_at(arm, lab):
        return round(float(1 - summary["baselines"][arm][f"mae_{lab}"]
                           / summary["baselines"]["N1"][f"mae_{lab}"]), 4)

    summary["signals"] = {
        "alt1_every_multiday_arm_worse_than_N1": all(
            summary["baselines"][a]["gain_vs_N1"] < 0
            for a in ARMS if a != "N1"),
        "alt2_daytype_is_the_whole_effect": (
            summary["baselines"]["N5_dt"]["gain_vs_N1"] >= 0.03
            and summary["baselines"]["N5"]["gain_vs_N1"] < 0.03),
        "alt3_gain_by_group": {a: {lab: gain_at(a, lab)
                                   for lab, _, _ in GROUPS} for a in ARMS},
    }
    sp = {a: round(100 * (gain_at(a, "h49_72") - gain_at(a, "h1_24")), 2)
          for a in ARMS if a != "N1"}
    summary["signals"]["alt3_horizon_spread_pp"] = sp
    summary["signals"]["alt3_fired"] = any(abs(v) > 5 for v in sp.values())
    best_arm = max(ARMS, key=lambda a: summary["baselines"][a]["gain_vs_N1"])
    fm = summary["candidates"]["chronos_bolt_base"]
    closed = fm["skill_vs_N1"] - fm[f"skill_vs_{best_arm}"]
    summary["signals"]["alt4_chronos_margin_closed_pp"] = round(100 * closed, 2)
    summary["signals"]["alt4_fraction_of_margin_closed"] = round(
        float(closed / fm["skill_vs_N1"]), 4)
    summary["signals"]["alt4_fired"] = bool(closed / fm["skill_vs_N1"] > 1 / 3)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print(f"rows={summary['n_rows']} (of {before} before intersection)  "
          f"vintages={summary['n_vintages']}  "
          f"{summary['window'][0]}..{summary['window'][1]}\n")
    print(f"{'baseline arm':<12}{'MAE':>9}{'vs N1':>9}{'DM p':>10}"
          f"{'h1-24':>9}{'h25-48':>9}{'h49-72':>9}")
    for arm in ARMS:
        r = summary["baselines"][arm]
        p = f"{r['dm_p_one_sided']:>10.5f}" if "dm_p_one_sided" in r else f"{'-':>10}"
        print(f"{arm:<12}{r['mae']:>9.3f}{r['gain_vs_N1']:>+9.4f}{p}"
              f"{r['mae_h1_24']:>9.3f}{r['mae_h25_48']:>9.3f}{r['mae_h49_72']:>9.3f}")
    print(f"\n{'candidate':<20}{'MAE':>9}" +
          "".join(f"{a:>11}" for a in ARMS))
    for name, r in summary["candidates"].items():
        print(f"{name:<20}{r['mae']:>9.3f}" +
              "".join(f"{r[f'skill_vs_{a}']:>+11.4f}" for a in ARMS))
    print("\ngates (pre-committed 2026-09-10):")
    for k, v in summary["gates"].items():
        print(f"  {k:<34} {v}")
    print(f"\nWritten to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
