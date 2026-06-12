"""EXP-016 Stage-1 offline replay: per-side ACI vs production symmetric CQR.

Pre-committed method: docs/hypothesis-log.md entry [2026-06-12] EXP-016.
Run AFTER the pre-commit is recorded; the verdict block states the four
IMPLEMENT conditions exactly as pre-committed (identical to EXP-015's).

Treatment = Adaptive Conformal Inference (Gibbs & Candes 2021) layered on
EXP-015's per-side nonconformity scores:

  - per-side adaptive miscoverage state alpha_lo / alpha_hi, init 0.10
  - one batched update per vintage day V over the not-yet-consumed hours
    with ts < V-day midnight UTC, scored against the band assigned when
    their own vintage was predicted:
        alpha <- clip(alpha + gamma * (0.10 - err_rate), 0.005, 0.5)
  - band for vintage V: finite-sample quantile of trailing-7d per-side
    scores at level (1 - alpha_side); sparse calibration -> q = 0 (raw
    bands), alpha still updates; no flooring of q at zero
  - gamma = 0.10 primary; 0.05 / 0.20 reported descriptively, never gated

CLI:
    python scripts/exp016_replay_aci.py \
        [--state ml/models/shadow/shadow_state.json] \
        [--calib-days 7] [--min-calib-days 3] [--alpha 0.20] [--gamma 0.10]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from scripts.exp015_replay_cqr import (  # noqa: E402
    DEFAULT_STATE,
    MIN_EVALUABLE_VINTAGES,
    RAW_COLS,
    add_sorted_raw_bands,
    finite_sample_quantile,
    load_history,
    summarize,
)

ALPHA_INIT = 0.10
ALPHA_CLIP = (0.005, 0.5)
DESCRIPTIVE_GAMMAS = [0.05, 0.20]


def replay_aci(
    df_raw: pd.DataFrame,
    calib_days: int,
    min_calib_days: int,
    alpha_target: float,
    gamma: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (rows with lo_t/hi_t/evaluable columns, per-day alpha trace)."""
    out = df_raw.copy().reset_index(drop=True)
    out["lo_t"] = np.nan
    out["hi_t"] = np.nan
    out["evaluable"] = False
    ts = out["timestamp_utc"]

    alpha_lo = alpha_hi = ALPHA_INIT
    prev_cutoff: pd.Timestamp | None = None
    trace_rows = []

    for day in sorted(out["eval_day"].unique()):
        cutoff = pd.Timestamp(day, tz="UTC")

        # ACI update: consume hours realised before this vintage's cutoff,
        # scored against the bands their own vintage was assigned.
        upd_mask = out["lo_t"].notna() & (ts < cutoff)
        if prev_cutoff is not None:
            upd_mask &= ts >= prev_cutoff
        n_upd = int(upd_mask.sum())
        if n_upd > 0:
            sub = out.loc[upd_mask]
            err_lo = float((sub["realized"] < sub["lo_t"]).mean())
            err_hi = float((sub["realized"] > sub["hi_t"]).mean())
            alpha_lo = float(np.clip(alpha_lo + gamma * (alpha_target - err_lo), *ALPHA_CLIP))
            alpha_hi = float(np.clip(alpha_hi + gamma * (alpha_target - err_hi), *ALPHA_CLIP))
        prev_cutoff = cutoff

        # Band assignment for this vintage at the adapted levels.
        calib_mask = (ts >= cutoff - pd.Timedelta(days=calib_days)) & (ts < cutoff)
        n_calib_days = ts[calib_mask].dt.date.nunique()
        day_mask = out["eval_day"] == day
        if n_calib_days >= min_calib_days:
            calib = out.loc[calib_mask]
            e_lo = (calib["q10s"] - calib["realized"]).to_numpy()
            e_hi = (calib["realized"] - calib["q90s"]).to_numpy()
            q_lo = finite_sample_quantile(e_lo, 1.0 - alpha_lo)
            q_hi = finite_sample_quantile(e_hi, 1.0 - alpha_hi)
            out.loc[day_mask, "evaluable"] = True
        else:
            q_lo = q_hi = 0.0  # raw bands during warm-up; alpha still updates
        out.loc[day_mask, "lo_t"] = out.loc[day_mask, "q10s"] - q_lo
        out.loc[day_mask, "hi_t"] = out.loc[day_mask, "q90s"] + q_hi

        trace_rows.append({
            "day": day, "n_upd": n_upd,
            "alpha_lo": round(alpha_lo, 4), "alpha_hi": round(alpha_hi, 4),
            "q_lo": round(q_lo, 2), "q_hi": round(q_hi, 2),
        })

    return out, pd.DataFrame(trace_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-016 Stage-1 offline ACI replay")
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--calib-days", type=int, default=7)
    parser.add_argument("--min-calib-days", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.20)
    parser.add_argument("--gamma", type=float, default=0.10)
    args = parser.parse_args()
    alpha_target_side = args.alpha / 2.0  # 0.10 per side for an 80% interval

    df = load_history(Path(args.state))
    if not set(RAW_COLS).issubset(df.columns):
        sys.exit("calibration_history has no raw quantile columns — nothing to replay.")
    df_raw = add_sorted_raw_bands(df[df[RAW_COLS].notna().all(axis=1)].copy())
    print(f"raw-bearing: {df_raw['eval_day'].nunique()} vintages, {len(df_raw)} rows "
          f"({df_raw['eval_day'].min()} → {df_raw['eval_day'].max()})")

    treated, trace = replay_aci(
        df_raw, args.calib_days, args.min_calib_days, alpha_target_side, args.gamma
    )
    ev = treated[treated["evaluable"]].copy()
    n_vintages = ev["eval_day"].nunique()
    print(f"evaluable: {n_vintages} vintages, {len(ev)} rows")
    if n_vintages < MIN_EVALUABLE_VINTAGES:
        sys.exit(f"precondition not met: {n_vintages} < {MIN_EVALUABLE_VINTAGES} evaluable "
                 f"vintages — wait for more raw-bearing days and re-run unchanged.")

    inc = summarize(ev["realized"], ev["p10"], ev["p90"], args.alpha)
    trt = summarize(ev["realized"], ev["lo_t"], ev["hi_t"], args.alpha)
    print(f"\n== Same-rows comparison (gamma={args.gamma}) ==")
    for name, m in (("incumbent", inc), ("treatment", trt)):
        print(f"{name:10s} lower={m['lower']:.3f} upper={m['upper']:.3f} "
              f"both={m['both']:.3f} med_width={m['med_width']:.1f} winkler={m['winkler']:.1f}")

    print("\n== Per-vintage lower-side (treatment | incumbent) ==")
    per_vintage_err = []
    for day, sub in ev.groupby("eval_day"):
        t = (sub["realized"] >= sub["lo_t"]).mean()
        i = (sub["realized"] >= sub["p10"]).mean()
        per_vintage_err.append(1.0 - t)
        print(f"  {day}  n={len(sub):3d}  treatment={t:.3f}  incumbent={i:.3f}")

    print("\n== ACI state trace ==")
    print(trace.to_string(index=False))

    # Descriptive: oscillation check (lag-1 autocorr of per-vintage lower err)
    if len(per_vintage_err) >= 3:
        e = np.asarray(per_vintage_err)
        ac1 = float(np.corrcoef(e[:-1], e[1:])[0, 1]) if np.std(e) > 0 else float("nan")
        print(f"\nlag-1 autocorr of per-vintage lower err (oscillation check): {ac1:.2f}")

    # Descriptive: gamma sensitivity (never gated)
    print("\n== Descriptive (never gated): gamma sensitivity ==")
    for g in DESCRIPTIVE_GAMMAS:
        t_g, _ = replay_aci(df_raw, args.calib_days, args.min_calib_days,
                            alpha_target_side, g)
        ev_g = t_g[t_g["evaluable"]]
        m = summarize(ev_g["realized"], ev_g["lo_t"], ev_g["hi_t"], args.alpha)
        print(f"  gamma={g:.2f}  lower={m['lower']:.3f} upper={m['upper']:.3f} "
              f"med_width={m['med_width']:.1f} winkler={m['winkler']:.1f}")

    # Pre-committed verdict block (docs/hypothesis-log.md [2026-06-12] EXP-016 Stage 1)
    c1 = trt["lower"] >= inc["lower"] + 0.03
    c2 = trt["lower"] >= 0.86
    c3 = 0.85 <= trt["upper"] <= 0.97
    c4 = trt["winkler"] <= 1.05 * inc["winkler"]
    print("\n== Pre-committed Stage-1 verdict ==")
    print(f"1. lower >= incumbent+0.03 : {trt['lower']:.3f} vs {inc['lower'] + 0.03:.3f}  "
          f"{'PASS' if c1 else 'FAIL'}")
    print(f"2. lower >= 0.86           : {trt['lower']:.3f}  {'PASS' if c2 else 'FAIL'}")
    print(f"3. upper in [0.85, 0.97]   : {trt['upper']:.3f}  {'PASS' if c3 else 'FAIL'}")
    print(f"4. winkler <= 1.05x        : {trt['winkler']:.1f} vs {1.05 * inc['winkler']:.1f}  "
          f"{'PASS' if c4 else 'FAIL'}")
    print(f"\nIMPLEMENT = {c1 and c2 and c3 and c4}")


if __name__ == "__main__":
    main()
