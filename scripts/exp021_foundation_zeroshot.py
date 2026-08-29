"""EXP-021 — is a zero-shot time-series foundation model competitive with the tuned LightGBM incumbent?

Pre-committed in `docs/hypothesis-log.md` [2026-08-29]. EXP-018/019/020 closed
the feature lever with a test that could have refuted it: at a 56-day window this
model gains nothing from added exogenous columns and *loses* from added level
columns, whatever their provenance. Two levers remain — window length and model
class. This is the model-class arm, and the first arm of augur#15.

The bet: `amazon/chronos-bolt-base`, zero-shot, given *nothing but the price
history the incumbent trains on* — no features, no exogenous, no NL-specific
training — lands within 5% of the lean LightGBM's quantile score, because its
quantile heads were pretrained across many series and regimes rather than
recalibrated nightly to one 56-day price level.

Everything except the estimator is held fixed against EXP-020's control run:
same parquet, same t0 grid, same 56-day context, same h+1..h+72, same scoring
functions, same HAC bandwidth 71, exact pairing on `(t0, timestamp_utc)`.

Three modes, because the GPU box has no Augur checkout and the scoring must stay
bit-identical to EXP-018/019/020:

    contexts   (situla)   derive the t0 grid + per-vintage price context from the
                          parquet, using the *same loader call* the EXP-020
                          control used, and write them to a portable parquet.
    predict    (b650-gpu) pure inference: contexts in, EXP-018-schema
                          predictions out. Imports only torch/chronos/pandas.
    score      (situla)   pair against the EXP-020 control's `full` and `lean`
                          arms, run the pre-committed gates, write summary.json.

Deliberate deltas, documented rather than fixed here:
  - **No CQR**, same as EXP-018/019/020: this asks what the raw quantiles are
    worth. Coverage here is raw-band coverage, not comparable to the
    CQR-widened `calibration_history` figures.
  - **Chronos-Bolt, not Chronos-T5.** Bolt has a direct multi-quantile head and
    is deterministic, so there is no sampling seed to tune and no sample-size
    confound. Its native quantile levels include 0.1/0.5/0.9 exactly, so
    p10/p50/p90 are read off, never interpolated.
  - **72h > Bolt's native 64h `prediction_length`**, so h+65..h+72 comes from an
    autoregressive rollout and is off-distribution. Pre-committed as Alternative
    3; `score` reports h<=64 vs h>64 separately so the contamination is visible
    rather than pooled away.
  - **Backtest optimism** carries over from the EXP-018 harness: `consolidate.py`
    overwrites parquet rows with later forecast vintages, so realised exogenous
    is fresher than the live cron sees. It biases the *incumbent*, not the FM
    (which gets no exogenous at all), so if anything it handicaps this entry.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py contexts \
        --parquet ml/data/training_history_fundamentals.parquet \
        --start 2025-12-01 --end 2026-08-22 --out ml/shadow/exp021_foundation

    # on b650-gpu, with only torch/chronos/pandas installed:
    ~/augur-fm/.venv/bin/python exp021_foundation_zeroshot.py predict \
        --out ~/augur-fm/exp021 --model amazon/chronos-bolt-base

    PYTHONPATH=. .venv/bin/python scripts/exp021_foundation_zeroshot.py score \
        --out ml/shadow/exp021_foundation \
        --incumbents ml/shadow/exp020_fundamentals_ctl/predictions.parquet
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

# Fixed here rather than derived, so `predict` never has to know them.
QUANTILE_LEVELS = (0.1, 0.5, 0.9)
MAX_HORIZON = 72
WINDOW_DAYS = 56
HAC_LAGS = MAX_HORIZON - 1
FM_VARIANT = "chronos_bolt_base"

# The EXP-020 control run's variant list. Reproduced verbatim so `contexts`
# builds its row set from the identical `required_columns(...)` dropna set, and
# the pairing against that run's `full`/`lean` arms is exact rather than
# approximate. Changing this silently changes which rows the FM sees.
CTL_VARIANTS = ("full", "lean", "lean_load", "lean_residual")

# Pre-committed baselines: primary gate against `lean` (the stronger of the two
# on this window), reported against `full` as well because EXP-018a Stage 1 has
# not fired and the identity of "the incumbent" is genuinely still open.
PRIMARY_BASE = "lean"
SECONDARY_BASE = "full"


# --------------------------------------------------------------------------
# mode: contexts  (situla — needs the Augur checkout)
# --------------------------------------------------------------------------


def mode_contexts(args: argparse.Namespace) -> None:
    from exp018_stage0_ablation import vintage_t0s
    from exp020_fundamentals_ablation import load_frame_ext, required_columns

    require = required_columns(list(CTL_VARIANTS))
    features, prices = load_frame_ext(Path(args.parquet), require)

    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC")
    t0s = vintage_t0s(features, start, end)
    if not t0s:
        raise SystemExit(f"no vintages in [{start}, {end})")

    ctx_rows: list[dict] = []
    tgt_rows: list[dict] = []
    skipped: list[str] = []
    max_gap_h = 0.0
    max_run_missing = 0
    n_missing_total = 0
    n_present_total = 0

    for t0 in t0s:
        # Mirrors `exp020_fundamentals_ablation.run_vintage` exactly: same
        # window mask, same "too short" skip, same NaN-target drop. What the
        # incumbent trained on is what the FM is handed.
        window_start = t0 - pd.Timedelta(days=WINDOW_DAYS)
        train_mask = (features.index > window_start) & (features.index <= t0)
        idx = features.index[train_mask]
        if len(idx) <= MAX_HORIZON:
            skipped.append(str(t0))
            continue
        y = prices.reindex(idx)
        y = y[y.notna()]
        if len(y) <= MAX_HORIZON:
            skipped.append(str(t0))
            continue

        gaps = y.index.to_series().diff().dt.total_seconds().div(3600).dropna()
        if len(gaps):
            max_gap_h = max(max_gap_h, float(gaps.max()))

        # Addendum 2026-08-29: the kept rows are NOT contiguous — `load_frame_ext`
        # drops rows on exogenous NaNs, which cost 125 of 260 vintages a single
        # 18h block. The incumbent is a tabular model and does not care; Bolt
        # reads its context as regularly spaced, so handing it the compressed
        # array would silently shift every hour-of-day in the context across the
        # hole. Re-index onto the complete hourly grid and mark the holes NaN:
        # the value set is unchanged (no data added), the spacing becomes real,
        # and the FM gets the same calendar alignment the incumbent gets
        # explicitly from its `hour`/`dow`/`month` features.
        ctx_end = t0 - pd.Timedelta(hours=args.context_end_offset_h)
        grid = pd.date_range(y.index.min(), ctx_end, freq="h")
        ctx_series = y.reindex(grid)
        if not ctx_series.notna().any():
            skipped.append(str(t0))
            continue
        present = ctx_series.notna().to_numpy()
        n_present_total += int(present.sum())
        n_missing_total += int((~present).sum())
        if (~present).any():
            runs = np.diff(np.flatnonzero(np.diff(np.r_[0, ~present, 0])))[::2]
            max_run_missing = max(max_run_missing, int(runs.max()))

        for pos, (ts, price) in enumerate(ctx_series.items()):
            ctx_rows.append(
                {
                    "t0": t0,
                    "pos": pos,
                    "timestamp_utc": ts,
                    "price": float(price) if np.isfinite(price) else np.nan,
                }
            )

        for h in range(1, MAX_HORIZON + 1):
            ts = t0 + pd.Timedelta(hours=h)
            realized = prices.get(ts, np.nan)
            if not np.isfinite(realized):
                continue
            tgt_rows.append(
                {
                    "t0": t0,
                    "timestamp_utc": ts,
                    "horizon_h": h,
                    "realized": float(realized),
                }
            )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    ctx = pd.DataFrame.from_records(ctx_rows)
    tgt = pd.DataFrame.from_records(tgt_rows)
    ctx.to_parquet(out_dir / "contexts.parquet")
    tgt.to_parquet(out_dir / "targets.parquet")

    lengths = ctx.groupby("t0").size()
    meta = {
        "parquet": str(args.parquet),
        "vintage_start": args.start,
        "vintage_end": args.end,
        "window_days": WINDOW_DAYS,
        "max_horizon": MAX_HORIZON,
        "ctl_variants_defining_row_set": list(CTL_VARIANTS),
        "require_columns": require,
        "n_vintages": int(lengths.size),
        "n_skipped_short": len(skipped),
        "skipped": skipped,
        "context_len_min": int(lengths.min()),
        "context_len_median": int(lengths.median()),
        "context_len_max": int(lengths.max()),
        "grid": "complete hourly, holes marked NaN (addendum 2026-08-29)",
        "context_end_offset_h": args.context_end_offset_h,
        "max_intra_context_gap_h_before_regridding": max_gap_h,
        "n_context_present": n_present_total,
        "n_context_missing": n_missing_total,
        "missing_fraction": n_missing_total / max(1, n_present_total + n_missing_total),
        "max_consecutive_missing_h": max_run_missing,
        "n_targets": int(len(tgt)),
    }
    (out_dir / "contexts_meta.json").write_text(json.dumps(meta, indent=2))

    # Pre-committed tripwire, re-expressed for the regridded context: spacing is
    # now regular by construction, so what can still misrepresent the
    # information set is an *unusable* amount of missingness. 5% / 48h are the
    # thresholds; anything above them means the FM is being asked to read a
    # series that is mostly hole, and the run is reported rather than scored.
    ok = meta["missing_fraction"] <= 0.05 and max_run_missing <= 48
    verdict = "OK" if ok else "COMPROMISED — too much missingness, do not score"
    print(
        f"{meta['n_vintages']} vintages, context len "
        f"{meta['context_len_min']}..{meta['context_len_max']} "
        f"(median {meta['context_len_median']}), {meta['n_targets']} targets\n"
        f"raggedness before regridding: max gap {max_gap_h:.0f}h\n"
        f"after regridding: {n_missing_total} NaN of "
        f"{n_present_total + n_missing_total} context points "
        f"({100 * meta['missing_fraction']:.2f}%), longest run "
        f"{max_run_missing}h -> {verdict}\n"
        f"wrote {out_dir}/contexts.parquet, targets.parquet, contexts_meta.json"
    )


# --------------------------------------------------------------------------
# mode: predict  (b650-gpu — torch/chronos/pandas only, no Augur imports)
# --------------------------------------------------------------------------


def mode_predict(args: argparse.Namespace) -> None:
    import torch
    from chronos import BaseChronosPipeline

    out_dir = Path(args.out)
    ctx = pd.read_parquet(out_dir / "contexts.parquet")
    tgt = pd.read_parquet(out_dir / "targets.parquet")
    ctx_meta = json.loads((out_dir / "contexts_meta.json").read_text())
    # When the context is held back to match the incumbent's `shift(1)` feature
    # row, the eval cells are unchanged but each is one step further from the
    # context end — so roll out further and index the same target hours.
    offset = int(ctx_meta.get("context_end_offset_h", 0))
    pred_len = MAX_HORIZON + offset

    pipeline = BaseChronosPipeline.from_pretrained(
        args.model,
        device_map=args.device,
        torch_dtype=torch.float32,
    )
    inner = getattr(pipeline, "model", None)
    # chronos 2.x exposes `chronos_config` as a plain dict on some model classes
    # and as a dataclass on others; read it without caring which.
    raw_cfg = getattr(getattr(inner, "config", None), "chronos_config", None) or {}
    cfg_get = raw_cfg.get if isinstance(raw_cfg, dict) else lambda k: getattr(raw_cfg, k, None)

    t0s = list(ctx["t0"].drop_duplicates())
    series = {t0: g.sort_values("pos")["price"].to_numpy() for t0, g in ctx.groupby("t0")}
    levels = list(QUANTILE_LEVELS)

    records: list[dict] = []
    tgt_by_t0 = {t0: g for t0, g in tgt.groupby("t0")}

    for i in range(0, len(t0s), args.batch_size):
        batch_t0s = t0s[i : i + args.batch_size]
        inputs = [torch.tensor(series[t0], dtype=torch.float32) for t0 in batch_t0s]
        q, _mean = pipeline.predict_quantiles(
            inputs, prediction_length=pred_len, quantile_levels=levels
        )
        q = q.numpy()  # (batch, horizon, n_quantiles), fp32 on cpu

        for b, t0 in enumerate(batch_t0s):
            raw = q[b]  # (72, 3)
            srt = np.sort(raw, axis=1)
            n_ctx = int(len(series[t0]))
            for _, row in tgt_by_t0[t0].iterrows():
                j = int(row["horizon_h"]) - 1 + offset
                records.append(
                    {
                        "variant": FM_VARIANT,
                        "t0": t0,
                        "timestamp_utc": row["timestamp_utc"],
                        "horizon_h": int(row["horizon_h"]),
                        "realized": float(row["realized"]),
                        "p10_raw": float(raw[j, 0]),
                        "p50_raw": float(raw[j, 1]),
                        "p90_raw": float(raw[j, 2]),
                        "p10": float(srt[j, 0]),
                        "p50": float(srt[j, 1]),
                        "p90": float(srt[j, 2]),
                        "n_train": n_ctx,
                    }
                )
        print(f"  {min(i + args.batch_size, len(t0s))}/{len(t0s)} vintages", flush=True)

    preds = pd.DataFrame.from_records(records)
    preds.to_parquet(out_dir / "fm_predictions.parquet")

    n_cross = int((preds["p10_raw"] > preds["p90_raw"]).sum())
    meta = {
        "model": args.model,
        "device": args.device,
        "torch_dtype": "float32",
        "quantile_levels": levels,
        "prediction_length": pred_len,
        "context_end_offset_h": offset,
        "native_prediction_length": cfg_get("prediction_length"),
        "native_context_length": cfg_get("context_length"),
        "native_quantile_levels": cfg_get("quantiles"),
        "batch_size": args.batch_size,
        "n_vintages": len(t0s),
        "n_rows": int(len(preds)),
        "n_quantile_crossings_raw": n_cross,
        "torch_version": torch.__version__,
        "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    }
    (out_dir / "fm_predict_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


# --------------------------------------------------------------------------
# mode: score  (situla — reuses the EXP-018 scoring functions unchanged)
# --------------------------------------------------------------------------


def mode_score(args: argparse.Namespace) -> None:
    from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

    from exp018_stage0_ablation import by_horizon_group, summarize

    out_dir = Path(args.out)
    fm = pd.read_parquet(out_dir / "fm_predictions.parquet")
    inc = pd.read_parquet(args.incumbents)
    inc = inc[inc["variant"].isin([PRIMARY_BASE, SECONDARY_BASE])]

    preds = pd.concat([fm, inc], ignore_index=True)
    variants = [FM_VARIANT, PRIMARY_BASE, SECONDARY_BASE]

    # Same pairing discipline as EXP-018/020: every arm restricted to the
    # (t0, timestamp) pairs all arms share, so pooled metrics and the paired DM
    # compare like with like.
    counts = preds.groupby(["t0", "timestamp_utc"])["variant"].nunique()
    shared = set(counts[counts == len(variants)].index)
    paired = preds[
        [k in shared for k in zip(preds["t0"], preds["timestamp_utc"])]
    ].sort_values(["variant", "t0", "horizon_h"])

    # Realised prices must agree across arms on every shared cell, or the two
    # runs were built off different data and nothing below means anything.
    check = paired.pivot_table(
        index=["t0", "timestamp_utc"], columns="variant", values="realized"
    )
    max_realized_delta = float((check.max(axis=1) - check.min(axis=1)).abs().max())
    if max_realized_delta > 1e-6:
        raise SystemExit(
            f"realised prices disagree across arms (max delta {max_realized_delta}) "
            "— the FM and incumbent runs are not on the same data"
        )

    qs_by_variant = {
        v: per_observation_quantile_score(
            sl["realized"].to_numpy(),
            sl[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
            list(QUANTILE_LEVELS),
        )
        for v, sl in ((v, paired[paired["variant"] == v]) for v in variants)
    }

    summary: dict = {
        "config": {
            "fm_predictions": str(out_dir / "fm_predictions.parquet"),
            "incumbents": str(args.incumbents),
            "window_days": WINDOW_DAYS,
            "max_horizon": MAX_HORIZON,
            "hac_lags": HAC_LAGS,
            "quantiles": list(QUANTILE_LEVELS),
            "cqr_applied": False,
            "primary_base": PRIMARY_BASE,
            "secondary_base": SECONDARY_BASE,
            "n_paired_vintages": int(paired["t0"].nunique()),
            "n_paired_observations": int(len(paired) // len(variants)),
            "max_realized_delta_across_arms": max_realized_delta,
            "purpose": "model-class arm — gates in docs/hypothesis-log.md [2026-08-29]",
        },
        "variants": {},
    }

    for v in variants:
        sl = paired[paired["variant"] == v]
        entry = summarize(sl)
        entry["by_horizon_group"] = by_horizon_group(sl)
        if v == FM_VARIANT:
            for base in (PRIMARY_BASE, SECONDARY_BASE):
                # H1: the FM beats this base.
                dm = diebold_mariano(
                    qs_by_variant[v], qs_by_variant[base], hac_lags=HAC_LAGS
                )
                entry[f"dm_fm_beats_{base}"] = {
                    "base": base,
                    "statistic": float(dm.statistic),
                    "p_one_sided": float(dm.p_value_one_sided),
                    "mean_loss_diff_fm_minus_base": float(dm.mean_diff),
                    "hac_lags": int(dm.hac_lags),
                }
        summary["variants"][v] = entry

    summary["gates"] = gate_report(summary)
    summary["alternative_1_error_decorrelation"] = alternative_1(paired)
    summary["alternative_3_rollout_boundary"] = alternative_3(paired)
    summary["alternative_5_monthly_upper_coverage"] = alternative_5(paired)

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print_table(summary, variants)


def gate_report(summary: dict) -> dict:
    """The four pre-committed gates, plus EXP-021's three-way effect-size rule.

    Gates (docs/hypothesis-log.md [2026-08-29], 1/3/4 copied verbatim from
    EXP-018a; gate 2 is stated in both directions because the Position is
    competitiveness, not superiority):
      1. paired DM on per-observation quantile score, one-sided p < 0.10
      2. >=3% better => superiority; within +-5% with p > 0.10 => parity
         (Position confirmed); >5% worse => Position refuted
      3. lower- and upper-side coverage each not more than 0.02 worse than base
      4. mean Winkler (alpha=0.20) <= 1.05 x base
    """
    out: dict = {}
    t = summary["variants"][FM_VARIANT]
    for label, base_name in (("primary", PRIMARY_BASE), ("secondary", SECONDARY_BASE)):
        b = summary["variants"][base_name]
        dm = t[f"dm_fm_beats_{base_name}"]
        delta_pct = 100.0 * (t["quantile_score"] / b["quantile_score"] - 1.0)

        g1 = dm["p_one_sided"] < 0.10
        g2_superiority = delta_pct <= -3.0
        g3 = (t["coverage_lower"] >= b["coverage_lower"] - 0.02) and (
            t["coverage_upper"] >= b["coverage_upper"] - 0.02
        )
        g4 = t["winkler"] <= 1.05 * b["winkler"]

        if g1 and g2_superiority and g3 and g4:
            verdict = "SUPERIORITY"
        elif abs(delta_pct) <= 5.0 and dm["p_one_sided"] > 0.10:
            verdict = "PARITY (Position confirmed)"
        elif delta_pct > 5.0:
            verdict = "REFUTED (>5% worse)"
        else:
            verdict = "INCONCLUSIVE (no gate band matches)"

        out[label] = {
            "base": base_name,
            "gate_1_dm_p_lt_0.10": g1,
            "gate_2_qs_delta_pct": delta_pct,
            "gate_2_superiority": g2_superiority,
            "gate_3_coverage": g3,
            "gate_4_winkler": g4,
            "dm_p_one_sided": dm["p_one_sided"],
            "verdict": verdict,
        }
    return out


def alternative_1(paired: pd.DataFrame) -> dict:
    """Do the FM's errors decorrelate from the incumbent's? (ensemble signal)

    Signal per the pre-commit: FM loses on skill but paired absolute-error
    Pearson r < 0.8 => the value is ensemble, not replacement.
    """
    piv = paired.pivot_table(
        index=["t0", "timestamp_utc"], columns="variant", values="p50"
    )
    y = paired.pivot_table(
        index=["t0", "timestamp_utc"], columns="variant", values="realized"
    ).iloc[:, 0]
    err = {v: (piv[v] - y).abs() for v in piv.columns}
    signed = {v: (piv[v] - y) for v in piv.columns}

    out: dict = {}
    for base in (PRIMARY_BASE, SECONDARY_BASE):
        r_abs = float(err[FM_VARIANT].corr(err[base]))
        # A 50/50 median blend is the cheapest ensemble that could exist; report
        # its MAE so the signal is actionable rather than merely suggestive.
        blend = (piv[FM_VARIANT] + piv[base]) / 2.0
        out[base] = {
            "pearson_r_abs_errors": r_abs,
            "pearson_r_signed_errors": float(signed[FM_VARIANT].corr(signed[base])),
            "decorrelated_r_lt_0.8": r_abs < 0.8,
            "mae_fm": float(err[FM_VARIANT].mean()),
            "mae_base": float(err[base].mean()),
            "mae_50_50_median_blend": float((blend - y).abs().mean()),
        }
    return out


def alternative_3(paired: pd.DataFrame) -> dict:
    """Is the damage concentrated above Bolt's native 64h prediction_length?

    Signal per the pre-commit: FM competitive at short horizons and collapsing
    only past h=64 => the comparison is contaminated by an implementation limit,
    not a verdict on model class.
    """
    from ml.shadow.metrics import per_observation_quantile_score

    out: dict = {}
    for label, mask in {
        "h1_64_native": paired["horizon_h"] <= 64,
        "h65_72_rollout": paired["horizon_h"] > 64,
    }.items():
        sl = paired[mask]
        entry: dict = {"n_obs_per_arm": int(len(sl) // paired["variant"].nunique())}
        for v in sl["variant"].unique():
            a = sl[sl["variant"] == v]
            qs = per_observation_quantile_score(
                a["realized"].to_numpy(),
                a[["p10_raw", "p50_raw", "p90_raw"]].to_numpy(),
                list(QUANTILE_LEVELS),
            )
            entry[v] = {
                "mae": float((a["p50"] - a["realized"]).abs().mean()),
                "quantile_score": float(qs.mean()),
            }
        base_qs = entry[PRIMARY_BASE]["quantile_score"]
        entry["fm_qs_delta_pct_vs_lean"] = 100.0 * (
            entry[FM_VARIANT]["quantile_score"] / base_qs - 1.0
        )
        out[label] = entry
    return out


def alternative_5(paired: pd.DataFrame) -> dict:
    """Per-month upper-side coverage — is the FM a band source even if not a
    point-forecast replacement? (augur#19)

    Signal per the pre-commit: FM upper-side coverage in Jul/Aug 2026 at least
    0.05 better than the incumbent's.
    """
    p = paired.copy()
    p["month"] = p["timestamp_utc"].dt.to_period("M").astype(str)
    out: dict = {}
    for month, g in p.groupby("month"):
        entry: dict = {}
        for v in g["variant"].unique():
            a = g[g["variant"] == v]
            entry[v] = {
                "coverage_lower": float((a["realized"] >= a["p10"]).mean()),
                "coverage_upper": float((a["realized"] <= a["p90"]).mean()),
                "coverage_band": float(
                    ((a["realized"] >= a["p10"]) & (a["realized"] <= a["p90"])).mean()
                ),
                "mean_price": float(a["realized"].mean()),
            }
        entry["fm_upper_minus_lean_upper"] = (
            entry[FM_VARIANT]["coverage_upper"] - entry[PRIMARY_BASE]["coverage_upper"]
        )
        entry["signal_fm_upper_better_by_0.05"] = entry["fm_upper_minus_lean_upper"] >= 0.05
        out[month] = entry
    return out


def print_table(summary: dict, variants: list[str]) -> None:
    ref = summary["variants"][PRIMARY_BASE]
    print(
        f"\n{'variant':<20}{'MAE':>9}{'QS':>9}{'dQS% vs lean':>14}"
        f"{'cov_lo':>9}{'cov_hi':>9}{'Winkler':>10}{'DM p':>9}"
    )
    for v in variants:
        e = summary["variants"][v]
        dm = e.get(f"dm_fm_beats_{PRIMARY_BASE}")
        p_txt = "—" if dm is None else format(dm["p_one_sided"], ".4f")
        print(
            f"{v:<20}{e['mae']:>9.2f}{e['quantile_score']:>9.2f}"
            f"{100 * (e['quantile_score'] / ref['quantile_score'] - 1):>14.1f}"
            f"{e['coverage_lower']:>9.3f}{e['coverage_upper']:>9.3f}"
            f"{e['winkler']:>10.1f}{p_txt:>9}"
        )
    print()
    for label, g in summary["gates"].items():
        print(
            f"{label:<10} vs {g['base']:<6} QS {g['gate_2_qs_delta_pct']:+.1f}%  "
            f"DM p={g['dm_p_one_sided']:.4f}  "
            f"g1={g['gate_1_dm_p_lt_0.10']} g2={g['gate_2_superiority']} "
            f"g3={g['gate_3_coverage']} g4={g['gate_4_winkler']}  -> {g['verdict']}"
        )
    a3 = summary["alternative_3_rollout_boundary"]
    print(
        f"\nAlt-3 rollout boundary: h1-64 FM {a3['h1_64_native']['fm_qs_delta_pct_vs_lean']:+.1f}% "
        f"vs lean | h65-72 FM {a3['h65_72_rollout']['fm_qs_delta_pct_vs_lean']:+.1f}% vs lean"
    )
    a1 = summary["alternative_1_error_decorrelation"][PRIMARY_BASE]
    print(
        f"Alt-1 decorrelation vs lean: r(|err|)={a1['pearson_r_abs_errors']:.3f} "
        f"(<0.8 => {a1['decorrelated_r_lt_0.8']}) | MAE fm {a1['mae_fm']:.2f} / "
        f"lean {a1['mae_base']:.2f} / 50-50 blend {a1['mae_50_50_median_blend']:.2f}"
    )
    print(f"\nwrote summary.json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)

    c = sub.add_parser("contexts", help="derive t0 grid + price contexts (situla)")
    c.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--out", default="ml/shadow/exp021_foundation")
    c.add_argument(
        "--context-end-offset-h",
        type=int,
        default=0,
        help="end each context this many hours before t0. 0 = everything known "
        "at t0. 1 = matched to the incumbent, whose features are shift(1) and "
        "therefore stop at t0-1h (code-review battery, 2026-08-29).",
    )
    c.set_defaults(func=mode_contexts)

    p = sub.add_parser("predict", help="zero-shot foundation-model inference (GPU box)")
    p.add_argument("--out", default="ml/shadow/exp021_foundation")
    p.add_argument("--model", default="amazon/chronos-bolt-base")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--batch-size", type=int, default=32)
    p.set_defaults(func=mode_predict)

    s = sub.add_parser("score", help="pair against incumbents + run gates (situla)")
    s.add_argument("--out", default="ml/shadow/exp021_foundation")
    s.add_argument(
        "--incumbents", default="ml/shadow/exp020_fundamentals_ctl/predictions.parquet"
    )
    s.set_defaults(func=mode_score)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
