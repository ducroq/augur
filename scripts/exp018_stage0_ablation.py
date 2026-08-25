"""EXP-018 Stage 0 — per-feature-group ablation of the production feature set.

Pre-committed in `docs/hypothesis-log.md` [2026-08-20]: before spending effort on
*new* features (fundamentals, volatility), measure what the *existing* 24 features
are worth. Drop one group at a time, re-run a production-shaped walk-forward
backtest, and report MAE + mean quantile score + per-side coverage.

Production shape (mirrors `ml/shadow/update_shadow.py`):
  - vintage day D -> t0 = last clean feature row of D
  - train `MultiHorizonLightGBMQuantileForecaster` on the 56-day window ending t0
  - predict h+1..h+72 from the single feature row at t0
  - score against realised prices

Deliberate deltas vs production, documented rather than fixed here:
  - **No CQR.** Stage 0 asks what the *raw* quantiles are worth; the conformal
    layer is the thing EXP-015/016 already showed cannot rescue them. Coverage
    numbers here are therefore raw-band coverage, not comparable to the
    CQR-widened `calibration_history` figures.
  - **Fixed row set across variants.** Rows are those with a complete *full*
    feature vector, so every variant trains and predicts on identical timestamps.
    Without this, dropping an exogenous column would hand that variant extra
    training rows wherever that column is NaN, confounding the ablation. (In
    practice the exogenous NaNs are all in 2025-09..11, before collection
    started; the rate is ~0% from December on, so this costs nothing on recent
    windows — but it keeps the winter vintages honest.)
  - **Backtest optimism.** `consolidate.py` overwrites parquet rows with later
    forecast vintages, so exogenous inputs here are fresher than the live cron
    sees (refuted-hypothesis 2026-05-29, ratio 1.84). Treat absolute numbers as
    an upper bound; the *relative* ordering between variants is the deliverable.

Scoring conventions:
  - pinball / quantile score uses **raw** tau outputs (`sort=False`) — sorting
    makes "p10" the row minimum and biases pinball-at-p10 (EXP-013 finding).
  - coverage and Winkler use **sorted** quantiles, since those are the band the
    product would actually ship.
  - paired Diebold-Mariano vs the full-feature variant on per-observation
    quantile-score differentials, HAC bandwidth 71 (= max_horizon - 1, promoted
    2026-05-29).

CLI:
    OMP_NUM_THREADS=1 .venv/bin/python scripts/exp018_stage0_ablation.py \
        --start 2026-04-27 --end 2026-08-22 --jobs 14 \
        --out ml/shadow/exp018_stage0
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.features_pandas import FEATURE_COLUMNS, build_features
from ml.shadow.lightgbm_quantile import (
    DEFAULT_QUANTILES,
    MultiHorizonLightGBMQuantileForecaster,
)
from ml.shadow.metrics import (
    diebold_mariano,
    per_observation_quantile_score,
    winkler_interval_score,
)

WINDOW_DAYS = 56
MAX_HORIZON = 72
HAC_LAGS = MAX_HORIZON - 1

FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "lags": tuple(c for c in FEATURE_COLUMNS if c.startswith("price_lag_")),
    "rolling": tuple(c for c in FEATURE_COLUMNS if c.startswith("price_rolling_")),
    "calendar": (
        "hour",
        "hour_sin",
        "hour_cos",
        "dow_sin",
        "dow_cos",
        "is_weekend",
        "month_sin",
    ),
    "wind": ("wind_speed_80m",),
    "solar": ("solar_ghi",),
    "load": ("load_forecast",),
}
# Composite: all three exogenous series at once.
FEATURE_GROUPS["exog"] = (
    FEATURE_GROUPS["wind"] + FEATURE_GROUPS["solar"] + FEATURE_GROUPS["load"]
)
# Mechanism split for the rolling group — the first pass showed dropping all six
# rolling features *improves* skill, so localise which half (or which window)
# carries the damage.
FEATURE_GROUPS["rolling_mean"] = tuple(
    c for c in FEATURE_COLUMNS if c.startswith("price_rolling_mean_")
)
FEATURE_GROUPS["rolling_std"] = tuple(
    c for c in FEATURE_COLUMNS if c.startswith("price_rolling_std_")
)
FEATURE_GROUPS["rolling_168h"] = tuple(
    c for c in FEATURE_COLUMNS if c.startswith("price_rolling_") and c.endswith("_168h")
)
FEATURE_GROUPS["rolling_short"] = tuple(
    c
    for c in FEATURE_COLUMNS
    if c.startswith("price_rolling_") and not c.endswith("_168h")
)
# Lean candidate: everything the first pass found non-contributing at once.
FEATURE_GROUPS["rolling_and_exog"] = FEATURE_GROUPS["rolling"] + FEATURE_GROUPS["exog"]

VARIANTS: tuple[str, ...] = ("full",) + tuple(f"drop_{g}" for g in FEATURE_GROUPS)


def variant_columns(variant: str) -> list[str]:
    if variant == "full":
        return list(FEATURE_COLUMNS)
    group = variant.removeprefix("drop_")
    dropped = set(FEATURE_GROUPS[group])
    return [c for c in FEATURE_COLUMNS if c not in dropped]


def load_frame(parquet_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Return (clean feature matrix, realised price series) on a UTC index."""
    df = pd.read_parquet(parquet_path)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"parquet index is not a DatetimeIndex: {df.index.dtype}")
    if df.index.tz is None:
        raise ValueError("parquet index must be tz-aware")
    df = df.tz_convert("UTC").sort_index()

    features = build_features(df)[list(FEATURE_COLUMNS)].dropna()
    return features, df["price_eur_mwh"]


def vintage_t0s(
    features: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> list[pd.Timestamp]:
    """One t0 per vintage day: the last clean feature row of that day."""
    idx = features.index[(features.index >= start) & (features.index < end)]
    if len(idx) == 0:
        return []
    by_day = pd.Series(idx, index=idx).groupby(idx.date).max()
    return list(by_day)


def run_vintage(task: tuple[str, pd.Timestamp]) -> list[dict]:
    """Train one variant on the window ending t0, predict h+1..h+72."""
    variant, t0 = task
    features, prices = _WORKER["features"], _WORKER["prices"]
    cols = variant_columns(variant)

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


_WORKER: dict = {}


def force_single_thread_lgbm() -> None:
    """Make each LightGBM fit single-threaded.

    ``LGBMRegressor`` defaults to ``n_jobs=-1``, which sets num_threads
    explicitly and therefore ignores ``OMP_NUM_THREADS``. With one process per
    vintage that oversubscribes the box badly (observed: 4 workers each pulling
    ~4 cores). Patch the symbol the forecaster module imported rather than the
    production hyperparams, so `ml/shadow` behaviour is unchanged.
    """
    import lightgbm

    import ml.shadow.lightgbm_quantile as lq

    def _single_thread_lgbm_regressor(**kwargs):
        kwargs.setdefault("n_jobs", 1)
        return lightgbm.LGBMRegressor(**kwargs)

    lq.LGBMRegressor = _single_thread_lgbm_regressor


def _init_worker(parquet_path: str) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    force_single_thread_lgbm()
    features, prices = load_frame(Path(parquet_path))
    _WORKER["features"] = features
    _WORKER["prices"] = prices


def summarize(preds: pd.DataFrame) -> dict:
    """Pooled metrics for one variant."""
    y = preds["realized"].to_numpy()
    q_raw = preds[["p10_raw", "p50_raw", "p90_raw"]].to_numpy()
    lo, mid, hi = (preds[c].to_numpy() for c in ("p10", "p50", "p90"))

    qs = per_observation_quantile_score(y, q_raw, list(DEFAULT_QUANTILES))
    return {
        "n_obs": int(len(preds)),
        "n_vintages": int(preds["t0"].nunique()),
        "mae": float(np.abs(mid - y).mean()),
        "quantile_score": float(qs.mean()),
        "coverage_lower": float((y >= lo).mean()),
        "coverage_upper": float((y <= hi).mean()),
        "coverage_band": float(((y >= lo) & (y <= hi)).mean()),
        "band_width_median": float(np.median(hi - lo)),
        "winkler": float(winkler_interval_score(y, lo, hi, alpha=0.20).mean()),
    }


def by_horizon_group(preds: pd.DataFrame) -> dict:
    out = {}
    for label, (a, b) in {"h1_6": (1, 6), "h7_24": (7, 24), "h25_72": (25, 72)}.items():
        sl = preds[(preds["horizon_h"] >= a) & (preds["horizon_h"] <= b)]
        if len(sl):
            s = summarize(sl)
            out[label] = {
                k: s[k] for k in ("n_obs", "mae", "quantile_score", "coverage_lower", "coverage_upper")
            }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history.parquet")
    ap.add_argument("--start", required=True, help="first vintage day (UTC, inclusive)")
    ap.add_argument("--end", required=True, help="last vintage day (UTC, exclusive)")
    ap.add_argument("--out", default="ml/shadow/exp018_stage0")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument(
        "--reuse-predictions",
        action="store_true",
        help="score an existing <out>/predictions.parquet instead of refitting",
    )
    args = ap.parse_args()

    parquet_path = Path(args.parquet)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = set(variants) - set(VARIANTS)
    if unknown:
        raise SystemExit(f"unknown variants: {sorted(unknown)} (known: {list(VARIANTS)})")

    features, _ = load_frame(parquet_path)
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    t0s = vintage_t0s(features, start, end)
    if not t0s:
        raise SystemExit(f"no vintages in [{start}, {end})")

    tasks = [(v, t0) for v in variants for t0 in t0s]
    print(
        f"{len(variants)} variants x {len(t0s)} vintages = {len(tasks)} fits "
        f"({args.start} .. {args.end}, {args.jobs} workers)",
        flush=True,
    )

    out_dir = Path(args.out)
    cached = out_dir / "predictions.parquet"
    if args.reuse_predictions:
        if not cached.exists():
            raise SystemExit(f"--reuse-predictions given but {cached} does not exist")
        preds = pd.read_parquet(cached)
        preds = preds[preds["variant"].isin(variants)]
        print(f"reusing {len(preds)} rows from {cached}")
        return score(preds, variants, t0s, args, out_dir, parquet_path)

    records: list[dict] = []
    with ProcessPoolExecutor(
        max_workers=args.jobs, initializer=_init_worker, initargs=(str(parquet_path),)
    ) as pool:
        for i, chunk in enumerate(pool.map(run_vintage, tasks, chunksize=1), start=1):
            records.extend(chunk)
            if i % 50 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} fits done", flush=True)

    preds = pd.DataFrame.from_records(records)
    out_dir.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(cached)
    score(preds, variants, t0s, args, out_dir, parquet_path)


def score(
    preds: pd.DataFrame,
    variants: list[str],
    t0s: list[pd.Timestamp],
    args: argparse.Namespace,
    out_dir: Path,
    parquet_path: Path,
) -> None:
    """Pool metrics, run the paired DM tests, write summary.json, print a table."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Restrict every variant to the timestamps all variants share, so pooled
    # metrics and the paired DM test compare like with like.
    counts = preds.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(counts[counts == len(variants)].index)
    paired = preds[
        [k in shared for k in zip(preds["t0"], preds["timestamp_utc"])]
    ].sort_values(["variant", "t0", "horizon_h"])

    base = paired[paired["variant"] == "full"]
    base_qs = per_observation_quantile_score(
        base["realized"].to_numpy(),
        base[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
        list(DEFAULT_QUANTILES),
    )

    summary: dict = {
        "config": {
            "parquet": str(parquet_path),
            "vintage_start": args.start,
            "vintage_end": args.end,
            "window_days": WINDOW_DAYS,
            "max_horizon": MAX_HORIZON,
            "hac_lags": HAC_LAGS,
            "quantiles": list(DEFAULT_QUANTILES),
            "cqr_applied": False,
            "n_vintages": len(t0s),
        },
        "variants": {},
    }

    for v in variants:
        sl = paired[paired["variant"] == v]
        entry = summarize(sl)
        entry["n_features"] = len(variant_columns(v))
        entry["dropped"] = (
            [] if v == "full" else list(FEATURE_GROUPS[v.removeprefix("drop_")])
        )
        entry["by_horizon_group"] = by_horizon_group(sl)
        if v != "full":
            qs = per_observation_quantile_score(
                sl["realized"].to_numpy(),
                sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
                list(DEFAULT_QUANTILES),
            )
            # H1: the full feature set beats the ablated variant. Small p means
            # the dropped group was carrying signal; mean_diff < 0 confirms it.
            dm = diebold_mariano(base_qs, qs, hac_lags=HAC_LAGS)
            entry["dm_full_beats_variant"] = {
                "statistic": float(dm.statistic),
                "p_one_sided": float(dm.p_value_one_sided),
                "mean_loss_diff_full_minus_variant": float(dm.mean_diff),
                "hac_lags": int(dm.hac_lags),
            }
        summary["variants"][v] = entry

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    full = summary["variants"]["full"]
    print(
        f"\n{'variant':<16}{'nfeat':>6}{'MAE':>9}{'dMAE%':>8}{'QS':>9}{'dQS%':>8}"
        f"{'cov_lo':>9}{'cov_hi':>9}{'DM p':>9}"
    )
    for v in variants:
        e = summary["variants"][v]
        dm = e.get("dm_full_beats_variant")
        p_txt = "—" if dm is None else format(dm["p_one_sided"], ".3f")
        print(
            f"{v:<16}{e['n_features']:>6}{e['mae']:>9.2f}"
            f"{100 * (e['mae'] / full['mae'] - 1):>8.1f}"
            f"{e['quantile_score']:>9.2f}"
            f"{100 * (e['quantile_score'] / full['quantile_score'] - 1):>8.1f}"
            f"{e['coverage_lower']:>9.3f}{e['coverage_upper']:>9.3f}"
            f"{p_txt:>9}"
        )
    print(f"\nwrote {out_dir/'summary.json'} and {out_dir/'predictions.parquet'}")


if __name__ == "__main__":
    main()
