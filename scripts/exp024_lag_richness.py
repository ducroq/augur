"""EXP-024 — is the bottleneck *derived* features, not feature count?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29).

There is a real tension in the record. EXP-018 found that *removing* features
improves skill (lean 15 beats full 24 by 7-8% QS, replicated on three windows).
EXP-022 found the FM's edge is partly **information the incumbent never
receives** — it predicts all 72 horizons from a single ~14-number feature row
while the FM reads 1343 raw points. Both cannot be naively true.

Position: the resolution is that **kind matters, not count**. Adding raw price
lags out to 168h recovers >=4 of the ~8 percentage points EXP-022 attributed to
context volume, while adding the same *number* of derived columns does not.

Mechanism, extending EXP-019 rather than contradicting it: raw price lags are
absolute levels and are **harmless**, whereas smoothed level columns
(`price_rolling_mean_168h`) **cost significantly** — read as redundant
smoothed-level columns diluting the split search. Raw, non-redundant lags are
the one input type never shown to hurt.

**The control arm is load-bearing and must not be dropped.** `lean_lag168_derived`
adds an equal *count* of derived columns, so a positive result can distinguish
"more input helps" from "more *raw* input helps". Without it a positive result
is uninterpretable. Interpretive requirement from the pre-commit: if BOTH the
raw-lag and derived arms pass, the mechanism claim is wrong even though the
Position's number is right, and that must be recorded as such.

CLI:
    PYTHONPATH=.:scripts .venv/bin/python scripts/exp024_lag_richness.py \
        --start 2025-12-01 --end 2026-08-22 --jobs 14 \
        --out ml/shadow/exp024_lag_richness
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.features_pandas import PRICE_LAGS, build_features
from ml.shadow.lightgbm_quantile import (
    DEFAULT_QUANTILES,
    MultiHorizonLightGBMQuantileForecaster,
)
from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

from exp018_stage0_ablation import (  # noqa: E402
    MAX_HORIZON,
    WINDOW_DAYS,
    by_horizon_group,
    force_single_thread_lgbm,
    summarize,
    variant_columns,
)

HAC_LAGS = MAX_HORIZON - 1
LEAN = variant_columns("drop_rolling_and_exog")

# Raw lags not already in the lean set.
EXTRA_LAGS_24 = [h for h in range(2, 25) if h not in PRICE_LAGS]
EXTRA_LAGS_168 = EXTRA_LAGS_24 + [h for h in (48, 72, 96, 120, 144, 168) if h not in PRICE_LAGS]
LAG24_COLS = [f"price_lag_{h}h" for h in EXTRA_LAGS_24]
LAG168_COLS = [f"price_lag_{h}h" for h in EXTRA_LAGS_168]

# Derived control, matched to len(LAG168_COLS) exactly. All computed off
# price.shift(1), mirroring features_pandas, so no contemporaneous leakage.
DERIVED_ROLL_WINDOWS = (3, 9, 36, 48, 72, 96, 120, 336)
DERIVED_EWM_SPANS = (6, 12, 48, 96)
DERIVED_COLS = (
    [f"d_roll_mean_{w}h" for w in DERIVED_ROLL_WINDOWS]
    + [f"d_roll_std_{w}h" for w in DERIVED_ROLL_WINDOWS]
    + [f"d_ewm_mean_{s}h" for s in DERIVED_EWM_SPANS]
    + ["d_roll_min_24h", "d_roll_max_24h"]
)

VARIANTS = {
    "lean": LEAN,
    "lean_lag24": LEAN + LAG24_COLS,
    "lean_lag168": LEAN + LAG168_COLS,
    "lean_lag168_derived": LEAN + DERIVED_COLS,
}
DM_BASE = {"lean_lag24": "lean", "lean_lag168": "lean", "lean_lag168_derived": "lean"}
PRIMARY = ("lean_lag168", "lean")
CONTROL = ("lean_lag168_derived", "lean")

_W: dict = {}


def build_extended(parquet_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    df = pd.read_parquet(parquet_path)
    if df.index.tz is None:
        raise ValueError("parquet index must be tz-aware")
    df = df.tz_convert("UTC").sort_index()
    price = df["price_eur_mwh"]
    prev = price.shift(1)

    feats = build_features(df)
    for h in EXTRA_LAGS_168:
        feats[f"price_lag_{h}h"] = price.shift(h)
    for w in DERIVED_ROLL_WINDOWS:
        r = prev.rolling(window=w, min_periods=2)
        feats[f"d_roll_mean_{w}h"] = r.mean()
        feats[f"d_roll_std_{w}h"] = r.std(ddof=0)
    for s in DERIVED_EWM_SPANS:
        feats[f"d_ewm_mean_{s}h"] = prev.ewm(span=s, min_periods=2).mean()
    r24 = prev.rolling(window=24, min_periods=2)
    feats["d_roll_min_24h"] = r24.min()
    feats["d_roll_max_24h"] = r24.max()

    need = sorted({c for cols in VARIANTS.values() for c in cols})
    # Fixed row set across every variant, exactly as EXP-018 does: rows must be
    # complete for the UNION of all variants' columns, so no variant is handed
    # extra training rows where another variant's column is NaN.
    feats = feats.dropna(subset=need)
    return feats, price


def _init(parquet_path: str) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    force_single_thread_lgbm()
    f, p = build_extended(Path(parquet_path))
    _W["features"], _W["prices"] = f, p


def run_one(task: tuple[str, pd.Timestamp]) -> list[dict]:
    variant, t0 = task
    features, prices = _W["features"], _W["prices"]
    cols = VARIANTS[variant]
    ws = t0 - pd.Timedelta(days=WINDOW_DAYS)
    mask = (features.index > ws) & (features.index <= t0)
    X = features.loc[mask, cols]
    if len(X) <= MAX_HORIZON:
        return []
    y = prices.reindex(X.index)
    if y.isna().any():
        keep = y.notna()
        X, y = X.loc[keep], y.loc[keep]
    model = MultiHorizonLightGBMQuantileForecaster().fit(X, y)
    hz = list(range(1, MAX_HORIZON + 1))
    raw = model.predict_horizons(features.loc[[t0], cols], horizons=hz, sort=False)[0]
    srt = np.sort(raw, axis=1)
    out = []
    for j, h in enumerate(hz):
        ts = t0 + pd.Timedelta(hours=h)
        yy = prices.get(ts, np.nan)
        if not np.isfinite(yy):
            continue
        out.append({"variant": variant, "t0": t0, "timestamp_utc": ts, "horizon_h": h,
                    "realized": float(yy), "p10_raw": float(raw[j, 0]),
                    "p50_raw": float(raw[j, 1]), "p90_raw": float(raw[j, 2]),
                    "p10": float(srt[j, 0]), "p50": float(srt[j, 1]),
                    "p90": float(srt[j, 2]), "n_train": int(len(X))})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--out", default="ml/shadow/exp024_lag_richness")
    args = ap.parse_args()

    features, _ = build_extended(Path(args.parquet))
    idx = features.index[(features.index >= pd.Timestamp(args.start, tz="UTC"))
                         & (features.index < pd.Timestamp(args.end, tz="UTC"))]
    t0s = list(pd.Series(idx, index=idx).groupby(idx.date).max())
    print(f"variants: {[(k, len(v)) for k, v in VARIANTS.items()]}")
    print(f"added raw lags: {len(LAG168_COLS)} | derived control: {len(DERIVED_COLS)} "
          f"(matched: {len(LAG168_COLS) == len(DERIVED_COLS)})")
    tasks = [(v, t) for v in VARIANTS for t in t0s]
    print(f"{len(VARIANTS)} variants x {len(t0s)} vintages = {len(tasks)} fits", flush=True)

    recs = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init,
                             initargs=(str(args.parquet),)) as pool:
        for i, ch in enumerate(pool.map(run_one, tasks, chunksize=1), start=1):
            recs.extend(ch)
            if i % 100 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} fits", flush=True)

    preds = pd.DataFrame.from_records(recs)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(out / "predictions.parquet")

    cnt = preds.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(cnt[cnt == len(VARIANTS)].index)
    paired = preds[[k in shared for k in zip(preds["t0"], preds["timestamp_utc"])]]

    qsl, summary = {}, {"config": {"parquet": args.parquet, "start": args.start,
                                   "end": args.end, "window_days": WINDOW_DAYS,
                                   "hac_lags": HAC_LAGS, "cqr_applied": False,
                                   "n_added_raw_lags": len(LAG168_COLS),
                                   "n_derived_control": len(DERIVED_COLS),
                                   "n_vintages": int(paired["t0"].nunique())},
                        "variants": {}}
    for v in VARIANTS:
        sl = paired[paired["variant"] == v]
        e = summarize(sl)
        e["n_features"] = len(VARIANTS[v])
        e["by_horizon_group"] = by_horizon_group(sl)
        qsl[v] = per_observation_quantile_score(
            sl["realized"].to_numpy(), sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
            list(DEFAULT_QUANTILES))
        summary["variants"][v] = e
    b = summary["variants"]["lean"]
    for v in VARIANTS:
        e = summary["variants"][v]
        e["qs_delta_pct_vs_lean"] = 100 * (e["quantile_score"] / b["quantile_score"] - 1)
        if v in DM_BASE:
            dm = diebold_mariano(qsl[v], qsl["lean"], hac_lags=HAC_LAGS)
            e["dm_beats_lean"] = {"statistic": float(dm.statistic),
                                  "p_one_sided": float(dm.p_value_one_sided)}

    def gate(treat: str) -> dict:
        t_, b_ = summary["variants"][treat], b
        dm = t_.get("dm_beats_lean", {})
        g = {"g1_dm_p_lt_0.10": bool(dm.get("p_one_sided", 1) < 0.10),
             "g2_qs_ge_3pct_better": bool(t_["qs_delta_pct_vs_lean"] <= -3.0),
             "g3_coverage": bool(t_["coverage_lower"] >= b_["coverage_lower"] - 0.02
                                 and t_["coverage_upper"] >= b_["coverage_upper"] - 0.02),
             "g4_winkler": bool(t_["winkler"] <= 1.05 * b_["winkler"])}
        g["ALL_PASS"] = all(g.values())
        return g

    gp, gc = gate(PRIMARY[0]), gate(CONTROL[0])
    summary["gates"] = {
        "primary_lean_lag168_vs_lean": gp,
        "control_derived_vs_lean": gc,
        "interpretive_requirement_control_must_not_pass": not gc["ALL_PASS"],
        "mechanism_supported": bool(gp["ALL_PASS"] and not gc["ALL_PASS"]),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'variant':<22}{'nfeat':>6}{'MAE':>9}{'QS':>8}{'dQS%':>8}{'cov_lo':>8}"
          f"{'cov_hi':>8}{'Wink':>8}{'DM p':>9}")
    for v in VARIANTS:
        e = summary["variants"][v]
        p = e.get("dm_beats_lean", {}).get("p_one_sided")
        print(f"{v:<22}{e['n_features']:>6}{e['mae']:>9.2f}{e['quantile_score']:>8.2f}"
              f"{e['qs_delta_pct_vs_lean']:>8.1f}{e['coverage_lower']:>8.3f}"
              f"{e['coverage_upper']:>8.3f}{e['winkler']:>8.1f}"
              f"{'—' if p is None else format(p,'.4f'):>9}")
    print(f"\nprimary {PRIMARY[0]}: {gp}")
    print(f"control {CONTROL[0]}: {gc}")
    print(f"mechanism supported (primary passes AND control does not): "
          f"{summary['gates']['mechanism_supported']}")
    print(f"wrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
