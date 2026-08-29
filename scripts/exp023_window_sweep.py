"""EXP-023 — is the incumbent's 56-day training window too short?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29).
EXP-020 closed features and left two levers: window length and model class.
EXP-021/022 resolved model class and showed context length is worth ~8
percentage points *to the foundation model* (-12.5% QS at a 7-day context,
-20.3% at 56-day). The incumbent's 56-day window is simultaneously its training
set and its context, and it has never been tuned — it is an artifact of when the
pipeline was built.

Position: QS improves monotonically out to at least 112 days, the optimum is
>=5% better than 56 days, and the gain concentrates in the tail quantiles
(p10/p90) rather than the median — because quantile heads are the part a
~1344-row sample estimates worst.

**Confound controlled by construction.** A longer window needs more history
*before* the first vintage, so the rungs would otherwise be scored on different
vintage sets. The vintage set is fixed to those where the **longest** rung is
fully available, and every rung runs on that identical set. Comparing a 168d
rung on 150 vintages against a 56d rung on 260 would confound window length with
evaluation period, so this is not optional.

Everything else matches EXP-018/019/020: `lean` feature set, one t0 per vintage
day, h+1..h+72, no CQR, raw quantiles for pinball, sorted for coverage/Winkler,
paired DM with HAC bandwidth 71.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp023_window_sweep.py \
        --parquet ml/data/training_history_fundamentals.parquet \
        --start 2025-12-01 --end 2026-08-22 --windows 28,56,84,112,168 \
        --jobs 14 --out ml/shadow/exp023_window_sweep
"""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.lightgbm_quantile import (
    DEFAULT_QUANTILES,
    MultiHorizonLightGBMQuantileForecaster,
)
from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

from exp018_stage0_ablation import (  # noqa: E402
    MAX_HORIZON,
    by_horizon_group,
    force_single_thread_lgbm,
    summarize,
    variant_columns,
    vintage_t0s,
)
from exp020_fundamentals_ablation import load_frame_ext, required_columns

HAC_LAGS = MAX_HORIZON - 1
BASE_WINDOW = 56
CTL_VARIANTS = ("full", "lean", "lean_load", "lean_residual")

_W: dict = {}


def _init(parquet_path: str, require: list[str]) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    force_single_thread_lgbm()
    f, p = load_frame_ext(Path(parquet_path), require)
    _W["features"], _W["prices"] = f, p


def run_one(task: tuple[int, pd.Timestamp]) -> list[dict]:
    window_days, t0 = task
    features, prices = _W["features"], _W["prices"]
    cols = variant_columns("drop_rolling_and_exog")  # the lean 15-feature set

    window_start = t0 - pd.Timedelta(days=int(window_days))
    mask = (features.index > window_start) & (features.index <= t0)
    X = features.loc[mask, cols]
    if len(X) <= MAX_HORIZON:
        return []
    yq = prices.reindex(X.index)
    if yq.isna().any():
        keep = yq.notna()
        X, yq = X.loc[keep], yq.loc[keep]

    model = MultiHorizonLightGBMQuantileForecaster().fit(X, yq)
    horizons = list(range(1, MAX_HORIZON + 1))
    raw = model.predict_horizons(features.loc[[t0], cols], horizons=horizons, sort=False)[0]
    srt = np.sort(raw, axis=1)

    out = []
    for j, h in enumerate(horizons):
        ts = t0 + pd.Timedelta(hours=h)
        y = prices.get(ts, np.nan)
        if not np.isfinite(y):
            continue
        out.append({
            "variant": f"w{window_days}", "window_days": int(window_days), "t0": t0,
            "timestamp_utc": ts, "horizon_h": h, "realized": float(y),
            "p10_raw": float(raw[j, 0]), "p50_raw": float(raw[j, 1]), "p90_raw": float(raw[j, 2]),
            "p10": float(srt[j, 0]), "p50": float(srt[j, 1]), "p90": float(srt[j, 2]),
            "n_train": int(len(X)),
        })
    return out


def pinball_by_tau(y: np.ndarray, q: np.ndarray) -> dict:
    out = {}
    for i, tau in enumerate(DEFAULT_QUANTILES):
        e = y - q[:, i]
        out[f"pinball_p{int(tau*100)}"] = float(np.maximum(tau * e, (tau - 1) * e).mean())
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--windows", default="28,56,84,112,168")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--out", default="ml/shadow/exp023_window_sweep")
    args = ap.parse_args()

    windows = [int(w) for w in args.windows.split(",")]
    longest = max(windows)
    require = required_columns(list(CTL_VARIANTS))
    features, _ = load_frame_ext(Path(args.parquet), require)

    t0s = vintage_t0s(features, pd.Timestamp(args.start, tz="UTC"), pd.Timestamp(args.end, tz="UTC"))
    # THE confound control: keep only vintages where the LONGEST window is fully
    # available, so every rung is scored on an identical vintage set.
    first = features.index.min()
    kept = [t for t in t0s if (t - pd.Timedelta(days=longest)) >= first]
    dropped = len(t0s) - len(kept)
    print(f"{len(t0s)} vintages in range; {dropped} dropped so the {longest}d rung is "
          f"fully available; {len(kept)} used by every rung", flush=True)
    if len(kept) < 30:
        raise SystemExit(f"only {len(kept)} vintages survive the {longest}d requirement")

    tasks = [(w, t) for w in windows for t in kept]
    print(f"{len(windows)} rungs x {len(kept)} vintages = {len(tasks)} fits, {args.jobs} workers", flush=True)

    recs: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init,
                             initargs=(str(args.parquet), require)) as pool:
        for i, chunk in enumerate(pool.map(run_one, tasks, chunksize=1), start=1):
            recs.extend(chunk)
            if i % 50 == 0 or i == len(tasks):
                print(f"  {i}/{len(tasks)} fits", flush=True)

    preds = pd.DataFrame.from_records(recs)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    preds.to_parquet(out / "predictions.parquet")

    counts = preds.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(counts[counts == len(windows)].index)
    paired = preds[[k in shared for k in zip(preds["t0"], preds["timestamp_utc"])]]

    qsl = {}
    summary = {"config": {"parquet": args.parquet, "windows": windows,
                          "base_window": BASE_WINDOW, "n_vintages": len(kept),
                          "n_vintages_dropped_for_confound_control": dropped,
                          "hac_lags": HAC_LAGS, "cqr_applied": False,
                          "feature_set": "lean (15)", "max_horizon": MAX_HORIZON},
               "rungs": {}}
    for w in windows:
        sl = paired[paired["variant"] == f"w{w}"]
        e = summarize(sl)
        e["by_horizon_group"] = by_horizon_group(sl)
        e.update(pinball_by_tau(sl["realized"].to_numpy(),
                                sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy()))
        e["n_train_median"] = float(sl["n_train"].median())
        qsl[w] = per_observation_quantile_score(
            sl["realized"].to_numpy(), sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
            list(DEFAULT_QUANTILES))
        summary["rungs"][f"w{w}"] = e

    base = qsl[BASE_WINDOW]
    b = summary["rungs"][f"w{BASE_WINDOW}"]
    for w in windows:
        e = summary["rungs"][f"w{w}"]
        e["qs_delta_pct_vs_56d"] = 100 * (e["quantile_score"] / b["quantile_score"] - 1)
        if w != BASE_WINDOW:
            dm = diebold_mariano(qsl[w], base, hac_lags=HAC_LAGS)
            e["dm_beats_56d"] = {"statistic": float(dm.statistic),
                                 "p_one_sided": float(dm.p_value_one_sided)}
    best = min(windows, key=lambda w: summary["rungs"][f"w{w}"]["quantile_score"])
    bb = summary["rungs"][f"w{best}"]
    dmb = bb.get("dm_beats_56d", {})
    summary["gates"] = {
        "best_window": best,
        "gate_1_dm_p_lt_0.10": bool(dmb.get("p_one_sided", 1.0) < 0.10),
        "gate_2_qs_ge_3pct_better": bool(bb["qs_delta_pct_vs_56d"] <= -3.0),
        "gate_3_coverage": bool(bb["coverage_lower"] >= b["coverage_lower"] - 0.02
                                and bb["coverage_upper"] >= b["coverage_upper"] - 0.02),
        "gate_4_winkler": bool(bb["winkler"] <= 1.05 * b["winkler"]),
        "position_5pct_met": bool(bb["qs_delta_pct_vs_56d"] <= -5.0),
        "monotone_to_112d": bool(all(
            summary["rungs"][f"w{windows[i+1]}"]["quantile_score"]
            <= summary["rungs"][f"w{windows[i]}"]["quantile_score"]
            for i in range(len(windows) - 1) if windows[i + 1] <= 112)),
    }
    summary["gates"]["ALL_PASS"] = all(summary["gates"][k] for k in
                                       ("gate_1_dm_p_lt_0.10", "gate_2_qs_ge_3pct_better",
                                        "gate_3_coverage", "gate_4_winkler"))
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'window':<9}{'ntrain':>8}{'MAE':>8}{'QS':>8}{'dQS%':>8}{'p10':>7}{'p50':>7}{'p90':>7}"
          f"{'cov_lo':>8}{'cov_hi':>8}{'Wink':>8}{'DM p':>8}")
    for w in windows:
        e = summary["rungs"][f"w{w}"]
        p = e.get("dm_beats_56d", {}).get("p_one_sided")
        print(f"{w:<9}{e['n_train_median']:>8.0f}{e['mae']:>8.2f}{e['quantile_score']:>8.2f}"
              f"{e['qs_delta_pct_vs_56d']:>8.1f}{e['pinball_p10']:>7.2f}{e['pinball_p50']:>7.2f}"
              f"{e['pinball_p90']:>7.2f}{e['coverage_lower']:>8.3f}{e['coverage_upper']:>8.3f}"
              f"{e['winkler']:>8.1f}{'—' if p is None else format(p,'.4f'):>8}")
    print(f"\nbest={best}d  gates: {summary['gates']}")
    print(f"wrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
