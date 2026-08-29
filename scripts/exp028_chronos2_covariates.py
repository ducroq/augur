"""EXP-028 — can a covariate-capable foundation model use the exogenous data LightGBM cannot?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29).

EXP-020 refuted exogenous features, but for **one model class**, and with a
mechanism that is explicitly LightGBM-specific ("redundant smoothed-level
columns diluting the split search"). A cross-attention transformer has no split
search to dilute, so the question re-opens with model class. The sharper
motivation: EXP-021's foundation model wins by 20.3% *while being strictly
information-poorer than the model it beats* — the incumbent gets wind, solar and
load; Chronos-Bolt gets nothing but price.

Chronos-**Bolt** is architecturally univariate and cannot take covariates under
any amount of retraining. **Chronos-2 takes them at inference time, no
retraining**: a list of dicts with `target`, `past_covariates` and
`future_covariates`. Augur's exogenous are the favourable known-future case —
wind/solar/load/temperature are *forecasts*, available over the horizon — while
`gas_ttf_eur_mwh` is a daily realised scalar with no forward curve and so is
past-only.

**Contamination control, stricter than EXP-021's.** Chronos-Bolt's weights were
frozen 2025-11-21, before the evaluation window, which is why EXP-021 could call
contamination impossible. `amazon/chronos-2` was last modified **2026-06-05 —
inside the window**. So every arm here is scored only on vintages with
`t0 > 2026-06-05`, and the Bolt / LightGBM comparators are re-scored on that
same restricted subset so all arms share an evaluation period.

Covariates are supplied at their parquet values, which for the forecast columns
are vintage-overwritten and therefore fresher than the live cron sees (ratio
1.84, refuted-hypothesis 2026-05-29). That bias favours *this* entry, so a null
is strong evidence and a positive result is an upper bound.

CLI (on b650-gpu, from ~/augur-run/repo):
    PYTHONPATH=.:scripts ~/augur-run/.venv/bin/python scripts/exp028_chronos2_covariates.py \
        --start 2026-06-06 --end 2026-08-22 --out ml/shadow/exp028_chronos2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.metrics import (
    diebold_mariano,
    per_observation_quantile_score,
    winkler_interval_score,
)

from exp018_stage0_ablation import MAX_HORIZON, vintage_t0s
from exp020_fundamentals_ablation import load_frame_ext, required_columns

WINDOW_DAYS = 56
HAC_LAGS = MAX_HORIZON - 1
QUANTILES = (0.1, 0.5, 0.9)
CTL_VARIANTS = ("full", "lean", "lean_load", "lean_residual")

# Known-future: genuinely available over the horizon (forecasts / calendar).
KNOWN_FUTURE = ["wind_speed_80m", "solar_ghi", "temperature", "load_forecast",
                "wind_gen_forecast_mw", "solar_gen_forecast_mw", "is_holiday_nl"]
# Past-only: a daily realised scalar with no forward curve.
PAST_ONLY = ["gas_ttf_eur_mwh"]

ARMS = {
    "c2_univariate": ([], []),
    "c2_known_future": (KNOWN_FUTURE, []),
    "c2_all": (KNOWN_FUTURE, PAST_ONLY),
    "c2_gasdrop": (KNOWN_FUTURE, []),   # identical to known_future; kept as the
                                        # Alternative-2 label for clarity
}


def build_inputs(features, prices, px, t0, known, past_only, offset_h=1):
    """One Chronos-2 input dict for a vintage, on a regular hourly grid.

    Context ends at t0 - offset_h to match the incumbent's shift(1) feature row
    (the EXP-021 code-review finding). Holes are marked NaN rather than
    compressed away, per the EXP-021 addendum — a sequence model reads its
    context as regularly spaced.
    """
    window_start = t0 - pd.Timedelta(hours=24 * WINDOW_DAYS)
    idx = features.index[(features.index > window_start) & (features.index <= t0)]
    if len(idx) <= MAX_HORIZON:
        return None
    y = prices.reindex(idx).dropna()
    if len(y) <= MAX_HORIZON:
        return None

    ctx_end = t0 - pd.Timedelta(hours=offset_h)
    grid = pd.date_range(y.index.min(), ctx_end, freq="h")
    fut = pd.date_range(t0 + pd.Timedelta(hours=1),
                        t0 + pd.Timedelta(hours=MAX_HORIZON), freq="h")
    pred_len = len(grid.union(fut)) - len(grid) if offset_h == 0 else MAX_HORIZON + offset_h
    full_fut = pd.date_range(ctx_end + pd.Timedelta(hours=1), periods=pred_len, freq="h")

    item: dict = {"target": y.reindex(grid).to_numpy(dtype=np.float32)}
    pc, fc = {}, {}
    for c in known:
        pc[c] = px[c].reindex(grid).to_numpy(dtype=np.float32)
        fc[c] = px[c].reindex(full_fut).to_numpy(dtype=np.float32)
    for c in past_only:
        pc[c] = px[c].reindex(grid).to_numpy(dtype=np.float32)
    if pc:
        item["past_covariates"] = pc
    if fc:
        item["future_covariates"] = fc
    return item, grid, full_fut, pred_len


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--model", default="amazon/chronos-2")
    ap.add_argument("--device", default="cuda:0")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--offset-h", type=int, default=1)
    ap.add_argument("--bolt", default="ml/shadow/exp021_foundation_aligned/fm_predictions.parquet")
    ap.add_argument("--incumbents", default="ml/shadow/exp020_fundamentals_ctl/predictions.parquet")
    ap.add_argument("--out", default="ml/shadow/exp028_chronos2")
    args = ap.parse_args()

    import torch
    from chronos import BaseChronosPipeline

    require = required_columns(list(CTL_VARIANTS))
    features, prices = load_frame_ext(Path(args.parquet), require)
    px = pd.read_parquet(args.parquet).tz_convert("UTC").sort_index()

    t0s = vintage_t0s(features, pd.Timestamp(args.start, tz="UTC"),
                      pd.Timestamp(args.end, tz="UTC"))
    print(f"{len(t0s)} vintages in [{args.start}, {args.end}) "
          f"(contamination control: chronos-2 weights modified 2026-06-05)", flush=True)

    pipe = BaseChronosPipeline.from_pretrained(args.model, device_map=args.device,
                                               torch_dtype=torch.float32)
    recs: list[dict] = []
    for arm, (known, past_only) in ARMS.items():
        built = []
        for t0 in t0s:
            b = build_inputs(features, prices, px, t0, known, past_only, args.offset_h)
            if b is not None:
                built.append((t0,) + b)
        if not built:
            continue
        pred_len = built[0][4]  # tuple is (t0, item, grid, full_fut, pred_len)
        for i in range(0, len(built), args.batch_size):
            chunk = built[i:i + args.batch_size]
            q, _ = pipe.predict_quantiles([c[1] for c in chunk],
                                          prediction_length=pred_len,
                                          quantile_levels=list(QUANTILES))
            for (t0, _item, _grid, fut, _pl), qq in zip(chunk, q):
                arr = qq.numpy() if hasattr(qq, "numpy") else np.asarray(qq)
                # chronos-2 returns (n_variates, horizon, n_quantiles); this is
                # univariate forecasting with covariates, so drop the variate axis.
                if arr.ndim == 3:
                    arr = arr[0]
                for h in range(1, MAX_HORIZON + 1):
                    ts = t0 + pd.Timedelta(hours=h)
                    y = prices.get(ts, np.nan)
                    if not np.isfinite(y):
                        continue
                    j = h - 1 + args.offset_h
                    raw = arr[j]
                    srt = np.sort(raw)
                    recs.append({"variant": arm, "t0": t0, "timestamp_utc": ts,
                                 "horizon_h": h, "realized": float(y),
                                 "p10_raw": float(raw[0]), "p50_raw": float(raw[1]),
                                 "p90_raw": float(raw[2]),
                                 "p10": float(srt[0]), "p50": float(srt[1]),
                                 "p90": float(srt[2])})
        print(f"  {arm}: {len(built)} vintages done", flush=True)

    c2 = pd.DataFrame.from_records(recs)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    c2.to_parquet(out / "c2_predictions.parquet")

    # comparators, re-scored on the SAME restricted subset
    bolt = pd.read_parquet(args.bolt).assign(variant="bolt_base")
    inc = pd.read_parquet(args.incumbents)
    inc = inc[inc["variant"].isin(["lean", "full"])]
    allp = pd.concat([c2, bolt[c2.columns.intersection(bolt.columns)],
                      inc[c2.columns.intersection(inc.columns)]], ignore_index=True)
    variants = list(dict.fromkeys(allp["variant"]))
    counts = allp.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(counts[counts == len(variants)].index)
    paired = allp[[k in shared for k in zip(allp["t0"], allp["timestamp_utc"])]]
    print(f"\npaired on {paired['t0'].nunique()} vintages x "
          f"{len(paired)//max(1,len(variants))} obs/arm across {len(variants)} arms")

    scored, losses = {}, {}
    for v in variants:
        s = paired[paired["variant"] == v]
        y = s["realized"].to_numpy()
        q = s[["p10_raw", "p50_raw", "p90_raw"]].to_numpy()
        L = per_observation_quantile_score(y, q, list(QUANTILES))
        losses[v] = L
        lo, hi = s["p10"].to_numpy(), s["p90"].to_numpy()
        scored[v] = {"n_obs": int(len(s)), "mae": float(np.abs(s["p50"].to_numpy() - y).mean()),
                     "quantile_score": float(L.mean()),
                     "coverage_lower": float((y >= lo).mean()),
                     "coverage_upper": float((y <= hi).mean()),
                     "coverage_band": float(((y >= lo) & (y <= hi)).mean()),
                     "band_width_median": float(np.median(hi - lo)),
                     "winkler": float(winkler_interval_score(y, lo, hi, alpha=0.20).mean()),
                     "pinball_p50": float(np.abs(s["p50_raw"].to_numpy() - y).mean() / 2)}

    base = "c2_univariate"
    for v in variants:
        e = scored[v]
        e["qs_delta_pct_vs_c2_univariate"] = 100 * (
            e["quantile_score"] / scored[base]["quantile_score"] - 1)
        if v != base:
            dm = diebold_mariano(losses[v], losses[base], hac_lags=HAC_LAGS)
            e["dm_beats_c2_univariate_p"] = float(dm.p_value_one_sided)

    T, B = scored["c2_known_future"], scored[base]
    gates = {
        "gate_1_dm_p_lt_0.10": bool(T.get("dm_beats_c2_univariate_p", 1) < 0.10),
        "gate_2_qs_ge_5pct_better": bool(T["qs_delta_pct_vs_c2_univariate"] <= -5.0),
        "gate_3_coverage": bool(T["coverage_lower"] >= B["coverage_lower"] - 0.02
                                and T["coverage_upper"] >= B["coverage_upper"] - 0.02),
        "gate_4_winkler": bool(T["winkler"] <= 1.05 * B["winkler"]),
        "mechanism_pinball_p50_ge_5pct": bool(
            100 * (1 - T["pinball_p50"] / B["pinball_p50"]) >= 5.0),
    }
    gates["ALL_PASS"] = all(gates[k] for k in
                            ("gate_1_dm_p_lt_0.10", "gate_2_qs_ge_5pct_better",
                             "gate_3_coverage", "gate_4_winkler"))
    summary = {"config": {"model": args.model, "start": args.start, "end": args.end,
                          "offset_h": args.offset_h, "window_days": WINDOW_DAYS,
                          "hac_lags": HAC_LAGS, "quantiles": list(QUANTILES),
                          "known_future": KNOWN_FUTURE, "past_only": PAST_ONLY,
                          "n_paired_vintages": int(paired["t0"].nunique()),
                          "contamination_note": "chronos-2 weights modified 2026-06-05; "
                                                "all arms restricted to t0 > 2026-06-05"},
               "arms": scored, "gates_primary": gates}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'arm':<18}{'MAE':>8}{'QS':>8}{'dQS%c2u':>10}{'cov_lo':>8}{'cov_hi':>8}"
          f"{'band':>7}{'Wink':>8}{'DM p':>9}")
    for v in variants:
        e = scored[v]
        p = e.get("dm_beats_c2_univariate_p")
        print(f"{v:<18}{e['mae']:>8.2f}{e['quantile_score']:>8.2f}"
              f"{e['qs_delta_pct_vs_c2_univariate']:>10.1f}{e['coverage_lower']:>8.3f}"
              f"{e['coverage_upper']:>8.3f}{e['coverage_band']:>7.3f}{e['winkler']:>8.1f}"
              f"{'—' if p is None else format(p,'.4f'):>9}")
    print(f"\nGATES (c2_known_future vs c2_univariate): {gates}")
    print(f"wrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
