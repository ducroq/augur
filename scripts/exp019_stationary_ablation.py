"""EXP-019 — is the lever *stationarity* rather than removal?

EXP-018 Stage 0 found that deleting the six rolling-stat features improves skill
(-6.0% MAE / -7.8% quantile score) and that the 15-feature "lean" set is the best
of eight variants. The proposed mechanism was drift: `price_rolling_mean_168h`
and friends encode an absolute price *level*, and a tree that splits on absolute
thresholds learned inside a 56-day window mis-generalises the moment the level
moves — the same failure behind August 2026's upper-side coverage breach.

If that mechanism is right, deletion is the crude fix and reparameterisation is
the good one: keep the information, express it in a form that survives a level
shift. This sweep tests that directly.

Reparameterisation (anchor + deviations):
  anchor        = price_rolling_mean_168h                      (the level itself)
  spread_lag_H  = price_lag_Hh          - anchor               (8 columns)
  spread_mean_W = price_rolling_mean_Wh - anchor, W in {6, 24} (2 columns)
  price_rolling_std_*                                           (kept as-is: a
                  scale, already invariant to the level)
Everything is a linear function of columns the production builder already
computes, so no new data, no leakage, identical row set.

Variants:
  full                 24 features — the production incumbent
  lean                 15 — EXP-018's winner (lags + calendar, no rolling, no exog)
  stat_full            24 — spreads + spread_means + stds + anchor + calendar + exog
  stat_lean            16 — spreads + anchor + calendar
  stat_lean_noanchor   15 — spreads + calendar, no level anchor at all

`stat_lean_noanchor` is the diagnostic: the target is an absolute price, so a
model with no level feature can only predict the training window's mean level.
If it collapses, that confirms the anchor is load-bearing and that "delete the
level features" is a lucky escape rather than a principled fix.

Everything else — walk-forward shape, scoring conventions, DM bandwidth, the
no-CQR and freshness-skew caveats — is inherited from
`scripts/exp018_stage0_ablation.py`; read its docstring first.

This is discovery, not confirmation: it runs on the same 263-vintage window
EXP-018 explored, so any winner here inherits that selection bias and must go
through the EXP-018a fresh-vintage gates (docs/hypothesis-log.md [2026-08-25])
before it is allowed near production.

CLI:
    PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python -u \
        scripts/exp019_stationary_ablation.py \
        --start 2025-12-01 --end 2026-08-22 --jobs 14 \
        --out ml/shadow/exp019_stationary
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.features_pandas import PRICE_LAGS, ROLLING_WINDOWS
from ml.shadow.lightgbm_quantile import (
    DEFAULT_QUANTILES,
    MultiHorizonLightGBMQuantileForecaster,
)
from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

from exp018_stage0_ablation import (  # noqa: E402  (same-directory sibling)
    FEATURE_GROUPS,
    HAC_LAGS,
    MAX_HORIZON,
    WINDOW_DAYS,
    by_horizon_group,
    force_single_thread_lgbm,
    load_frame,
    summarize,
    variant_columns,
    vintage_t0s,
)

ANCHOR = "price_rolling_mean_168h"
CALENDAR = list(FEATURE_GROUPS["calendar"])
EXOG = list(FEATURE_GROUPS["exog"])
STDS = list(FEATURE_GROUPS["rolling_std"])
SPREAD_LAGS = [f"spread_lag_{h}h" for h in PRICE_LAGS]
SPREAD_MEANS = [f"spread_mean_{w}h" for w in ROLLING_WINDOWS if w != 168]

VARIANT_SPECS: dict[str, list[str]] = {
    "full": variant_columns("full"),
    "lean": variant_columns("drop_rolling_and_exog"),
    "stat_full": SPREAD_LAGS + SPREAD_MEANS + STDS + [ANCHOR] + CALENDAR + EXOG,
    "stat_lean": SPREAD_LAGS + [ANCHOR] + CALENDAR,
    "stat_lean_noanchor": SPREAD_LAGS + CALENDAR,
}


def add_stationary_columns(features: pd.DataFrame) -> pd.DataFrame:
    """Append anchor-relative spreads to the production feature frame.

    Pure column algebra on the existing builder output: same index, same row
    set, no new inputs. The anchor column itself is left in place so variants
    can choose whether to keep an explicit level.
    """
    out = features.copy()
    anchor = features[ANCHOR]
    for h in PRICE_LAGS:
        out[f"spread_lag_{h}h"] = features[f"price_lag_{h}h"] - anchor
    for w in ROLLING_WINDOWS:
        if w == 168:
            continue
        out[f"spread_mean_{w}h"] = features[f"price_rolling_mean_{w}h"] - anchor
    return out


_WORKER: dict = {}


def _init_worker(parquet_path: str) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    force_single_thread_lgbm()
    features, prices = load_frame(Path(parquet_path))
    _WORKER["features"] = add_stationary_columns(features)
    _WORKER["prices"] = prices


def run_vintage(task: tuple[str, pd.Timestamp]) -> list[dict]:
    variant, t0 = task
    features, prices = _WORKER["features"], _WORKER["prices"]
    cols = VARIANT_SPECS[variant]

    window_start = t0 - pd.Timedelta(days=WINDOW_DAYS)
    train_mask = (features.index > window_start) & (features.index <= t0)
    X_train = features.loc[train_mask, cols]
    if len(X_train) <= MAX_HORIZON:
        return []
    y_train = prices.reindex(X_train.index)
    if y_train.isna().any():
        keep = y_train.notna()
        X_train, y_train = X_train.loc[keep], y_train.loc[keep]

    model = MultiHorizonLightGBMQuantileForecaster().fit(X_train, y_train)

    feat_t0 = features.loc[[t0], cols]
    horizons = list(range(1, MAX_HORIZON + 1))
    raw = model.predict_horizons(feat_t0, horizons=horizons, sort=False)[0]
    srt = np.sort(raw, axis=1)

    records: list[dict] = []
    for j, h in enumerate(horizons):
        ts = t0 + pd.Timedelta(hours=h)
        y = prices.get(ts, np.nan)
        if not np.isfinite(y):
            continue
        records.append(
            {
                "variant": variant,
                "t0": t0,
                "timestamp_utc": ts,
                "horizon_h": h,
                "realized": float(y),
                "p10_raw": float(raw[j, 0]),
                "p50_raw": float(raw[j, 1]),
                "p90_raw": float(raw[j, 2]),
                "p10": float(srt[j, 0]),
                "p50": float(srt[j, 1]),
                "p90": float(srt[j, 2]),
                "n_train": int(len(X_train)),
            }
        )
    return records


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history.parquet")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--out", default="ml/shadow/exp019_stationary")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--variants", default=",".join(VARIANT_SPECS))
    ap.add_argument("--reuse-predictions", action="store_true")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = set(variants) - set(VARIANT_SPECS)
    if unknown:
        raise SystemExit(f"unknown variants: {sorted(unknown)}")

    parquet_path = Path(args.parquet)
    features, _ = load_frame(parquet_path)
    t0s = vintage_t0s(
        features, pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC")
    )
    if not t0s:
        raise SystemExit(f"no vintages in [{args.start}, {args.end})")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cached = out_dir / "predictions.parquet"

    if args.reuse_predictions:
        if not cached.exists():
            raise SystemExit(f"--reuse-predictions given but {cached} missing")
        preds = pd.read_parquet(cached)
        preds = preds[preds["variant"].isin(variants)]
        print(f"reusing {len(preds)} rows from {cached}")
    else:
        tasks = [(v, t0) for v in variants for t0 in t0s]
        print(
            f"{len(variants)} variants x {len(t0s)} vintages = {len(tasks)} fits "
            f"({args.jobs} workers)",
            flush=True,
        )
        records: list[dict] = []
        with ProcessPoolExecutor(
            max_workers=args.jobs,
            initializer=_init_worker,
            initargs=(str(parquet_path),),
        ) as pool:
            for i, chunk in enumerate(pool.map(run_vintage, tasks, chunksize=1), 1):
                records.extend(chunk)
                if i % 100 == 0 or i == len(tasks):
                    print(f"  {i}/{len(tasks)} fits done", flush=True)
        preds = pd.DataFrame.from_records(records)
        preds.to_parquet(cached)

    counts = preds.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(counts[counts == len(variants)].index)
    paired = preds[
        [k in shared for k in zip(preds["t0"], preds["timestamp_utc"])]
    ].sort_values(["variant", "t0", "horizon_h"])

    def qscore(sl: pd.DataFrame) -> np.ndarray:
        return per_observation_quantile_score(
            sl["realized"].to_numpy(),
            sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
            list(DEFAULT_QUANTILES),
        )

    base = paired[paired["variant"] == "full"]
    base_qs = qscore(base)

    summary: dict = {
        "config": {
            "parquet": str(parquet_path),
            "vintage_start": args.start,
            "vintage_end": args.end,
            "window_days": WINDOW_DAYS,
            "max_horizon": MAX_HORIZON,
            "hac_lags": HAC_LAGS,
            "cqr_applied": False,
            "n_vintages": len(t0s),
            "anchor": ANCHOR,
            "purpose": "discovery — winners must clear the EXP-018a fresh-vintage gates",
        },
        "variants": {},
    }

    for v in variants:
        sl = paired[paired["variant"] == v]
        entry = summarize(sl)
        entry["n_features"] = len(VARIANT_SPECS[v])
        entry["columns"] = VARIANT_SPECS[v]
        entry["by_horizon_group"] = by_horizon_group(sl)
        if v != "full":
            qs = qscore(sl)
            # H1: this variant beats the production incumbent.
            dm = diebold_mariano(qs, base_qs, hac_lags=HAC_LAGS)
            entry["dm_variant_beats_full"] = {
                "statistic": float(dm.statistic),
                "p_one_sided": float(dm.p_value_one_sided),
                "mean_loss_diff_variant_minus_full": float(dm.mean_diff),
            }
        summary["variants"][v] = entry

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    full = summary["variants"]["full"]
    print(
        f"\n{'variant':<20}{'nfeat':>6}{'MAE':>9}{'dMAE%':>8}{'QS':>9}{'dQS%':>8}"
        f"{'cov_lo':>9}{'cov_hi':>9}{'winkler':>10}{'DM p':>9}"
    )
    for v in variants:
        e = summary["variants"][v]
        dm = e.get("dm_variant_beats_full")
        p_txt = "—" if dm is None else format(dm["p_one_sided"], ".4f")
        print(
            f"{v:<20}{e['n_features']:>6}{e['mae']:>9.2f}"
            f"{100 * (e['mae'] / full['mae'] - 1):>8.1f}"
            f"{e['quantile_score']:>9.2f}"
            f"{100 * (e['quantile_score'] / full['quantile_score'] - 1):>8.1f}"
            f"{e['coverage_lower']:>9.3f}{e['coverage_upper']:>9.3f}"
            f"{e['winkler']:>10.1f}{p_txt:>9}"
        )
    print(f"\nwrote {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
