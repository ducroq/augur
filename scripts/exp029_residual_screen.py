"""EXP-029 — do the foundation model's residuals carry any exploitable exogenous signal?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29) as
the near-free CPU pre-screen for EXP-028. EXP-028 (Chronos-2 with covariates) is
worth GPU time only if the exogenous carry information the FM's residuals do not
already contain, and that is directly measurable on prediction files that
already exist, with no new model of any kind.

The Position is deliberately a *null*: the FM's residuals should be close to
exogenous-orthogonal (out-of-sample R^2 < 0.05, residual correction worth <2%
MAE), because EXP-020 found exogenous inert for a model that had price lags and
calendar, and EXP-022 localised the FM's advantage to a distributional prior
rather than a conditional-mean gain. **This entry expects EXP-028 to fail**; a
surprise here is what would justify the GPU work.

Per Alternative 3 in the pre-commit, a null here is *evidence against* EXP-028,
not proof of absence — a tree on pooled residuals can miss interactions a
covariate-conditioned sequence model would find. A null lowers EXP-028's
priority; it does not cancel it.

Splits are **temporal**, never random (project hard constraint): fit on the
first 70% of vintages, score the last 30%.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp029_residual_screen.py \
        --fm ml/shadow/exp021_foundation_aligned/fm_predictions.parquet \
        --parquet ml/data/training_history_fundamentals.parquet \
        --out ml/shadow/exp029_residual_screen
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from ml.shadow.metrics import per_observation_quantile_score

QUANTILES = (0.1, 0.5, 0.9)
COVARIATES = [
    "wind_speed_80m", "solar_ghi", "temperature", "load_forecast",
    "wind_gen_forecast_mw", "solar_gen_forecast_mw", "gas_ttf_eur_mwh",
    "is_holiday_nl", "residual_load_mw",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fm", default="ml/shadow/exp021_foundation_aligned/fm_predictions.parquet")
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--out", default="ml/shadow/exp029_residual_screen")
    args = ap.parse_args()

    fm = pd.read_parquet(args.fm)
    px = pd.read_parquet(args.parquet).tz_convert("UTC").sort_index()
    px["residual_load_mw"] = (
        px["load_forecast"] - px["wind_gen_forecast_mw"] - px["solar_gen_forecast_mw"]
    )

    d = fm.copy()
    for c in COVARIATES:
        d[c] = px[c].reindex(d["timestamp_utc"]).to_numpy()
    d["residual"] = d["realized"] - d["p50"]
    d = d.dropna(subset=["residual"])

    # (1) marginal association, pooled and by horizon group
    corr = {}
    for c in COVARIATES:
        s = d[[c, "residual"]].dropna()
        corr[c] = {
            "n": int(len(s)),
            "pearson": float(s[c].corr(s["residual"])) if len(s) > 10 else None,
            "spearman": float(s[c].corr(s["residual"], method="spearman")) if len(s) > 10 else None,
        }
    by_h = {}
    for lab, (a, b) in {"h1_6": (1, 6), "h7_24": (7, 24), "h25_72": (25, 72)}.items():
        sl = d[(d.horizon_h >= a) & (d.horizon_h <= b)]
        by_h[lab] = {c: (float(sl[[c, "residual"]].dropna().corr().iloc[0, 1])
                         if sl[c].notna().sum() > 10 else None) for c in COVARIATES}

    # (2) temporal split, never random
    vintages = np.sort(d["t0"].unique())
    cut = vintages[int(len(vintages) * 0.70)]
    tr, te = d[d.t0 < cut], d[d.t0 >= cut]
    feats = COVARIATES + ["horizon_h"]
    trc = tr.dropna(subset=feats + ["residual"])
    tec = te.dropna(subset=feats + ["residual"])

    # Covariate sets. `all` is the pre-committed screen; the rest test
    # Alternative 2 ("signal exists but only in one column") and the mechanism
    # EXP-019/020 established — that added LEVEL columns (gas, temperature,
    # absolute load) destroy out-of-sample generalisation while flow quantities
    # need not. Running these together is diagnosis of the same screen, not a
    # loosened gate: the promotion gate below is still read off `all`.
    LEVELS = {"gas_ttf_eur_mwh", "temperature", "load_forecast", "residual_load_mw"}
    SETS = {
        "all": COVARIATES,
        "no_gas": [c for c in COVARIATES if c != "gas_ttf_eur_mwh"],
        "no_levels": [c for c in COVARIATES if c not in LEVELS],
        "wind_only": ["wind_gen_forecast_mw", "wind_speed_80m"],
    }

    def fit_set(cols: list[str]) -> dict:
        f = cols + ["horizon_h"]
        a = tr.dropna(subset=f + ["residual"])
        b = te.dropna(subset=f + ["residual"])
        m = LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31,
                          min_child_samples=40, random_state=42, verbose=-1)
        m.fit(a[f], a["residual"])
        pr = m.predict(b[f])
        yr = b["residual"].to_numpy()
        sst = float(((yr - yr.mean()) ** 2).sum())
        r = 1.0 - float(((yr - pr) ** 2).sum()) / sst if sst > 0 else float("nan")
        yy = b["realized"].to_numpy()
        bm = float(np.abs(b["p50"].to_numpy() - yy).mean())
        cm = float(np.abs((b["p50"].to_numpy() + pr) - yy).mean())
        return {"cols": cols, "oos_r2": r, "base_mae": bm, "corrected_mae": cm,
                "delta_mae_pct": 100 * (1 - cm / bm), "n_test": int(len(b)),
                "feature_importance": dict(sorted(zip(f, m.feature_importances_.tolist()),
                                                  key=lambda kv: -kv[1]))}

    set_results = {k: fit_set(v) for k, v in SETS.items()}

    model = LGBMRegressor(n_estimators=300, learning_rate=0.05, num_leaves=31,
                          min_child_samples=40, random_state=42, verbose=-1)
    model.fit(trc[feats], trc["residual"])
    pred = model.predict(tec[feats])
    y_res = tec["residual"].to_numpy()
    ss_res = float(((y_res - pred) ** 2).sum())
    ss_tot = float(((y_res - y_res.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")

    # (3) apply the correction on held-out vintages
    y = tec["realized"].to_numpy()
    base_mae = float(np.abs(tec["p50"].to_numpy() - y).mean())
    corr_mae = float(np.abs((tec["p50"].to_numpy() + pred) - y).mean())
    q_base = tec[["p10", "p50", "p90"]].to_numpy()
    q_corr = q_base + pred[:, None]
    qs_base = float(per_observation_quantile_score(y, q_base, list(QUANTILES)).mean())
    qs_corr = float(per_observation_quantile_score(y, q_corr, list(QUANTILES)).mean())

    imp = dict(sorted(zip(feats, model.feature_importances_.tolist()),
                      key=lambda kv: -kv[1]))
    d_mae_pct = 100 * (1 - corr_mae / base_mae)
    d_qs_pct = 100 * (1 - qs_corr / qs_base)
    gates = {
        "oos_r2": r2,
        "delta_mae_pct": d_mae_pct,
        "delta_qs_pct": d_qs_pct,
        "signal_r2_ge_0.05": bool(r2 >= 0.05),
        "signal_mae_ge_2pct": bool(d_mae_pct >= 2.0),
        "promotes_exp028": bool(r2 >= 0.05 or d_mae_pct >= 2.0),
    }
    summary = {
        "config": {"fm": args.fm, "parquet": args.parquet, "covariates": COVARIATES,
                   "split": "temporal 70/30 by vintage (never random)",
                   "train_vintages": int(tr.t0.nunique()), "test_vintages": int(te.t0.nunique()),
                   "cut_vintage": str(cut), "n_train_rows": int(len(trc)), "n_test_rows": int(len(tec)),
                   "purpose": "pre-screen for EXP-028 — advisory gates, not a promotion decision"},
        "marginal_correlations": corr,
        "correlations_by_horizon_group": by_h,
        "residual_model": {"oos_r2": r2, "feature_importance": imp,
                           "base_mae": base_mae, "corrected_mae": corr_mae,
                           "base_qs": qs_base, "corrected_qs": qs_corr},
        "gates": gates,
        "covariate_sets": set_results,
    }
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"paired rows {len(d)} | train {len(trc)} ({tr.t0.nunique()} vintages) "
          f"| test {len(tec)} ({te.t0.nunique()} vintages), cut {str(cut)[:10]}")
    print(f"\n{'covariate':<24}{'pearson':>10}{'spearman':>10}")
    for c, v in sorted(corr.items(), key=lambda kv: -abs(kv[1]['pearson'] or 0)):
        print(f"{c:<24}{(v['pearson'] or 0):>10.4f}{(v['spearman'] or 0):>10.4f}")
    print(f"\nresidual model  OOS R2 = {r2:.4f}")
    print(f"  MAE {base_mae:.3f} -> {corr_mae:.3f}  ({d_mae_pct:+.2f}%)")
    print(f"  QS  {qs_base:.3f} -> {qs_corr:.3f}  ({d_qs_pct:+.2f}%)")
    print(f"  top features: {list(imp)[:4]}")
    print(f"\n{'covariate set':<14}{'noos R2':>10}{'dMAE%':>9}  top features")
    for k, v in set_results.items():
        print(f"{k:<14}{v['oos_r2']:>10.4f}{v['delta_mae_pct']:>9.2f}  {list(v['feature_importance'])[:3]}")
    print(f"\nGATES: R2>=0.05 {gates['signal_r2_ge_0.05']} | dMAE>=2% {gates['signal_mae_ge_2pct']} "
          f"-> promotes EXP-028: {gates['promotes_exp028']}")
    print(f"wrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
