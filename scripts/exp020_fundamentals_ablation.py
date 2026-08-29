"""EXP-020 — do market fundamentals carry price signal the three current exogenous columns cannot?

EXP-018 Stage 0 found the exogenous trio (`wind_speed_80m`, `solar_ghi`,
`load_forecast`) worth ~nothing: -0.3% / -0.3% / -0.4% individually, +0.8% QS
for all three at once. The obvious reading is "exogenous data does not help this
model." This sweep tests the narrower reading that the trio is the wrong *shape*
of exogenous, which an ablation that only ever *removes* columns could not
separate:

  1. It is not the merit-order quantity. External EPF work puts residual load
     (load minus renewable generation, in MW) at rho ~= 0.53 with day-ahead
     price, materially above load or renewables alone. LightGBM with axis-aligned
     splits on a ~1300-row window cannot reconstruct a three-way difference it is
     never handed, and one of the three terms it *is* handed (`wind_speed_80m`,
     a single offshore point's wind speed) is a nonlinear proxy for MW, not MW.
  2. There is no fuel-cost level anchor at all. Nothing in the 24-feature set
     carries the marginal generator's cost, so a trailing-56-day model can only
     infer level from its own price lags — the mechanism EXP-018 blamed for
     August 2026's upper-side coverage breach (upper 0.774, band 0.660, against
     the highest monthly mean in the parquet).

New columns come from `ml/data/consolidate.py` (EXP-020 Step 0, 2026-08-29);
`residual_load_mw` is derived here rather than stored:

    residual_load_mw = load_forecast - wind_gen_forecast_mw - solar_gen_forecast_mw

Variants (base -> treatment):

    full          24  production incumbent
    lean          15  EXP-018's winner (lags + calendar; no rolling, no exog)
    lean_load     16  lean + load_forecast          -- Alternative 3 control
    lean_residual 16  lean + residual_load_mw
    lean_gas      16  lean + gas_ttf_eur_mwh
    lean_fund     18  lean + residual + gas + holiday   -- PRIMARY treatment
    full_fund     27  full + residual + gas + holiday   -- confirmatory

Pre-committed gates (docs/hypothesis-log.md [2026-08-29], identical to EXP-018a):
the *primary* comparison is `lean_fund` vs `lean`; `full_fund` vs `full` is
confirmatory and must not degrade, or the result is base-dependent and does not
travel. `lean_load` vs `lean_residual` decides Alternative 3 (is the gain just
`load_forecast` made useful, rather than the residual construction?). The other
arms are diagnostic — they do not move the gates, which are fixed on the one
designated comparison.

Window: `gas_ttf_eur_mwh` does not exist before 2026-02-05 (EDH's market_proxies
collector added TTF on that date), so the full sweep runs 2026-02-05..2026-08-22
and the no-gas arms are replayed on 2025-12-01.. as a control that the shorter
window does not by itself change the residual-load conclusion. `--require`
controls which columns must be non-NaN, so the control run is not truncated to
the gas window by a variant it does not contain.

Everything else — walk-forward shape, scoring conventions, DM bandwidth, the
no-CQR and freshness-skew caveats — is inherited from
`scripts/exp018_stage0_ablation.py`; read its docstring first.

This is discovery, not confirmation: the window overlaps the one EXP-018 and
EXP-019 already explored, so any winner inherits that selection bias and must
clear fresh-vintage gates before it goes near production. EXP-018a Stage 1 has
priority on the fresh-vintage window.

CLI:
    # main sweep (all seven arms, gas window)
    PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python -u \
        scripts/exp020_fundamentals_ablation.py \
        --parquet ml/data/training_history_fundamentals.parquet \
        --start 2026-02-05 --end 2026-08-22 --jobs 14 \
        --out ml/shadow/exp020_fundamentals

    # control: no-gas arms on the full window
    PYTHONPATH=. OMP_NUM_THREADS=1 .venv/bin/python -u \
        scripts/exp020_fundamentals_ablation.py \
        --parquet ml/data/training_history_fundamentals.parquet \
        --start 2025-12-01 --end 2026-08-22 --jobs 14 \
        --variants full,lean,lean_load,lean_residual \
        --out ml/shadow/exp020_fundamentals_ctl
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
from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

from exp018_stage0_ablation import (  # noqa: E402  (same-directory sibling)
    FEATURE_GROUPS,
    HAC_LAGS,
    MAX_HORIZON,
    WINDOW_DAYS,
    by_horizon_group,
    force_single_thread_lgbm,
    summarize,
    variant_columns,
    vintage_t0s,
)

# Columns read straight from the parquet (not built by features_pandas).
RESIDUAL = "residual_load_mw"
GAS = "gas_ttf_eur_mwh"
HOLIDAY = "is_holiday_nl"
PARQUET_FUNDAMENTALS = ("wind_gen_forecast_mw", "solar_gen_forecast_mw", GAS, HOLIDAY)

LEAN = variant_columns("drop_rolling_and_exog")
FULL = variant_columns("full")

VARIANT_SPECS: dict[str, list[str]] = {
    "full": FULL,
    "lean": LEAN,
    "lean_load": LEAN + ["load_forecast"],
    "lean_residual": LEAN + [RESIDUAL],
    "lean_gas": LEAN + [GAS],
    "lean_fund": LEAN + [RESIDUAL, GAS, HOLIDAY],
    "full_fund": FULL + [RESIDUAL, GAS, HOLIDAY],
}

# Each treatment is judged against its own base, not against `full` for all.
# Fixed here, before the data is looked at.
DM_BASE: dict[str, str] = {
    "lean": "full",
    "lean_load": "lean",
    "lean_residual": "lean",
    "lean_gas": "lean",
    "lean_fund": "lean",
    "full_fund": "full",
}
PRIMARY = ("lean_fund", "lean")
CONFIRMATORY = ("full_fund", "full")


def load_frame_ext(
    parquet_path: Path, require: list[str]
) -> tuple[pd.DataFrame, pd.Series]:
    """Feature matrix incl. fundamentals, on rows where `require` is complete.

    Mirrors `exp018_stage0_ablation.load_frame` but joins the fundamentals
    columns from the parquet and derives `residual_load_mw`. The dropna set is
    the caller's `require` rather than every column, so a run that excludes the
    gas arms is not silently truncated to the post-2026-02-05 gas window.
    """
    df = pd.read_parquet(parquet_path)
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError(f"parquet index is not a DatetimeIndex: {df.index.dtype}")
    if df.index.tz is None:
        raise ValueError("parquet index must be tz-aware")
    df = df.tz_convert("UTC").sort_index()

    missing = [c for c in PARQUET_FUNDAMENTALS if c not in df.columns]
    if missing:
        raise SystemExit(
            f"parquet {parquet_path} lacks EXP-020 columns {missing} — rebuild it "
            f"with `python -m ml.data.consolidate` on a post-2026-08-29 checkout"
        )

    features = build_features(df)[list(FEATURE_COLUMNS)]
    for col in PARQUET_FUNDAMENTALS:
        features[col] = df[col]
    features[RESIDUAL] = (
        df["load_forecast"] - df["wind_gen_forecast_mw"] - df["solar_gen_forecast_mw"]
    )

    features = features.dropna(subset=require)
    return features, df["price_eur_mwh"]


_WORKER: dict = {}


def _init_worker(parquet_path: str, require: list[str]) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    force_single_thread_lgbm()
    features, prices = load_frame_ext(Path(parquet_path), require)
    _WORKER["features"] = features
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


def required_columns(variants: list[str]) -> list[str]:
    """Union of every column the selected variants need, deduped, order-stable."""
    seen: dict[str, None] = {}
    for v in variants:
        for c in VARIANT_SPECS[v]:
            seen.setdefault(c, None)
    return list(seen)


def gate_report(summary: dict) -> dict:
    """Evaluate the four pre-committed gates on the primary comparison.

    Gates (docs/hypothesis-log.md [2026-08-29], copied verbatim from EXP-018a):
      1. paired DM on per-observation quantile score, one-sided p < 0.10
      2. treatment QS at least 3% better than base
      3. lower- and upper-side coverage each not more than 0.02 worse than base
      4. mean Winkler (alpha=0.20) <= 1.05 x base
    """
    out: dict = {}
    for label, (treat, base) in {
        "primary": PRIMARY,
        "confirmatory": CONFIRMATORY,
    }.items():
        if treat not in summary["variants"] or base not in summary["variants"]:
            continue
        t, b = summary["variants"][treat], summary["variants"][base]
        dm = t.get("dm_variant_beats_base")
        if dm is None:
            continue
        g1 = dm["p_one_sided"] < 0.10
        g2 = (1 - t["quantile_score"] / b["quantile_score"]) >= 0.03
        g3 = (t["coverage_lower"] >= b["coverage_lower"] - 0.02) and (
            t["coverage_upper"] >= b["coverage_upper"] - 0.02
        )
        g4 = t["winkler"] <= 1.05 * b["winkler"]
        out[label] = {
            "treatment": treat,
            "base": base,
            "gate_1_dm_p_lt_0.10": {"value": dm["p_one_sided"], "pass": bool(g1)},
            "gate_2_qs_gain_ge_3pct": {
                "value": 100 * (1 - t["quantile_score"] / b["quantile_score"]),
                "pass": bool(g2),
            },
            "gate_3_coverage_not_worse_than_0.02": {
                "lower_delta": t["coverage_lower"] - b["coverage_lower"],
                "upper_delta": t["coverage_upper"] - b["coverage_upper"],
                "pass": bool(g3),
            },
            "gate_4_winkler_le_1.05x": {
                "ratio": t["winkler"] / b["winkler"],
                "pass": bool(g4),
            },
            "ALL_PASS": bool(g1 and g2 and g3 and g4),
        }
    return out


def monthly_panel(paired: pd.DataFrame, treat: str, base: str) -> dict:
    """Per-month QS delta for the primary comparison (Alternative 4 signal:
    is the gain confined to the recent level shift?)."""
    out: dict = {}
    t = paired[paired["variant"] == treat].set_index(["t0", "timestamp_utc"])
    b = paired[paired["variant"] == base].set_index(["t0", "timestamp_utc"])
    common = t.index.intersection(b.index)
    if len(common) == 0:
        return out
    t, b = t.loc[common], b.loc[common]
    qs_t = per_observation_quantile_score(
        t["realized"].to_numpy(),
        t[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
        list(DEFAULT_QUANTILES),
    )
    qs_b = per_observation_quantile_score(
        b["realized"].to_numpy(),
        b[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
        list(DEFAULT_QUANTILES),
    )
    months = pd.Index([ts for _, ts in common]).strftime("%Y-%m")
    frame = pd.DataFrame({"month": months, "qs_t": qs_t, "qs_b": qs_b})
    for month, sl in frame.groupby("month"):
        out[month] = {
            "n_obs": int(len(sl)),
            "qs_delta_pct": float(100 * (sl["qs_t"].mean() / sl["qs_b"].mean() - 1)),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--start", required=True, help="first vintage day (UTC, inclusive)")
    ap.add_argument("--end", required=True, help="last vintage day (UTC, exclusive)")
    ap.add_argument("--out", default="ml/shadow/exp020_fundamentals")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--variants", default=",".join(VARIANT_SPECS))
    ap.add_argument("--reuse-predictions", action="store_true")
    args = ap.parse_args()

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    unknown = set(variants) - set(VARIANT_SPECS)
    if unknown:
        raise SystemExit(
            f"unknown variants: {sorted(unknown)} (known: {list(VARIANT_SPECS)})"
        )

    parquet_path = Path(args.parquet)
    require = required_columns(variants)
    features, _ = load_frame_ext(parquet_path, require)
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
            f"({args.start} .. {args.end}, {args.jobs} workers, "
            f"{len(features)} clean rows)",
            flush=True,
        )
        records: list[dict] = []
        with ProcessPoolExecutor(
            max_workers=args.jobs,
            initializer=_init_worker,
            initargs=(str(parquet_path), require),
        ) as pool:
            for i, chunk in enumerate(pool.map(run_vintage, tasks, chunksize=1), 1):
                records.extend(chunk)
                if i % 100 == 0 or i == len(tasks):
                    print(f"  {i}/{len(tasks)} fits done", flush=True)
        preds = pd.DataFrame.from_records(records)
        preds.to_parquet(cached)

    # Restrict every variant to the timestamps all variants share, so pooled
    # metrics and the paired DM tests compare like with like.
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

    qs_by_variant = {v: qscore(paired[paired["variant"] == v]) for v in variants}

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
            "residual_load_definition": (
                "load_forecast - wind_gen_forecast_mw - solar_gen_forecast_mw"
            ),
            "primary_comparison": f"{PRIMARY[0]} vs {PRIMARY[1]}",
            "confirmatory_comparison": f"{CONFIRMATORY[0]} vs {CONFIRMATORY[1]}",
            "purpose": (
                "discovery — winners must clear fresh-vintage gates "
                "(docs/hypothesis-log.md [2026-08-29])"
            ),
        },
        "variants": {},
    }

    for v in variants:
        sl = paired[paired["variant"] == v]
        entry = summarize(sl)
        entry["n_features"] = len(VARIANT_SPECS[v])
        entry["columns"] = VARIANT_SPECS[v]
        entry["by_horizon_group"] = by_horizon_group(sl)
        base = DM_BASE.get(v)
        if base is not None and base in qs_by_variant:
            # H1: this variant beats its designated base.
            dm = diebold_mariano(qs_by_variant[v], qs_by_variant[base], hac_lags=HAC_LAGS)
            entry["dm_variant_beats_base"] = {
                "base": base,
                "statistic": float(dm.statistic),
                "p_one_sided": float(dm.p_value_one_sided),
                "mean_loss_diff_variant_minus_base": float(dm.mean_diff),
                "hac_lags": int(dm.hac_lags),
            }
        summary["variants"][v] = entry

    summary["gates"] = gate_report(summary)
    if PRIMARY[0] in variants and PRIMARY[1] in variants:
        summary["monthly_panel_primary"] = monthly_panel(paired, *PRIMARY)

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))

    ref = summary["variants"].get("full") or summary["variants"][variants[0]]
    print(
        f"\n{'variant':<16}{'nfeat':>6}{'MAE':>9}{'dMAE%':>8}{'QS':>9}{'dQS%':>8}"
        f"{'cov_lo':>9}{'cov_hi':>9}{'winkler':>10}{'base':>15}{'DM p':>9}"
    )
    for v in variants:
        e = summary["variants"][v]
        dm = e.get("dm_variant_beats_base")
        p_txt = "—" if dm is None else format(dm["p_one_sided"], ".4f")
        b_txt = "—" if dm is None else dm["base"]
        print(
            f"{v:<16}{e['n_features']:>6}{e['mae']:>9.2f}"
            f"{100 * (e['mae'] / ref['mae'] - 1):>8.1f}"
            f"{e['quantile_score']:>9.2f}"
            f"{100 * (e['quantile_score'] / ref['quantile_score'] - 1):>8.1f}"
            f"{e['coverage_lower']:>9.3f}{e['coverage_upper']:>9.3f}"
            f"{e['winkler']:>10.1f}{b_txt:>15}{p_txt:>9}"
        )
    print("  (dMAE% / dQS% are vs `full`; DM p is vs each variant's own base)")

    for label, g in summary["gates"].items():
        verdict = "PASS" if g["ALL_PASS"] else "FAIL"
        print(f"\n{label}: {g['treatment']} vs {g['base']} -> {verdict}")
        for k, val in g.items():
            if k.startswith("gate_"):
                print(f"    {k:<40} {'pass' if val['pass'] else 'FAIL'}  {val}")

    print(f"\nwrote {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
