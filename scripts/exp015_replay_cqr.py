"""EXP-015 Stage-1 offline replay: per-side CQR vs production symmetric CQR.

Pre-committed method: docs/hypothesis-log.md entry [2026-06-12] EXP-015.
Run AFTER the pre-commit is recorded; the verdict block at the end states the
four IMPLEMENT conditions exactly as pre-committed.

Replays, on `calibration_history` rows that carry raw quantiles
(p10_raw/p50_raw/p90_raw, stored since 2026-05-29):

  incumbent : the stored production bands (p10/p90 — sorted raw quantiles
              widened by the symmetric feedback-loop CQR in update_shadow).
  treatment : per-side split-conformal on raw sorted quantiles —
              q_lo = 0.90-quantile of (q10_sorted - y),
              q_hi = 0.90-quantile of (y - q90_sorted),
              trailing 7-day / min-3-distinct-days calibration window with
              cutoff at vintage-day midnight UTC (mirrors apply_cqr).
              No flooring at zero: a negative q legitimately narrows a side.

Descriptive companions (never gated): horizon-grouped per-side variant,
per-group coverage, width deltas, negative-q frequency.

CLI:
    python scripts/exp015_replay_cqr.py \
        [--state ml/models/shadow/shadow_state.json] \
        [--calib-days 7] [--min-calib-days 3] [--alpha 0.20]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from ml.shadow.metrics import winkler_interval_score  # noqa: E402

DEFAULT_STATE = _REPO_ROOT / "ml" / "models" / "shadow" / "shadow_state.json"
RAW_COLS = ["p10_raw", "p50_raw", "p90_raw"]
HORIZON_GROUPS = [(1, 6, "h1-6"), (7, 24, "h7-24"), (25, 72, "h25-72")]
MIN_EVALUABLE_VINTAGES = 4  # pre-committed precondition


def load_history(state_path: Path) -> pd.DataFrame:
    with open(state_path) as f:
        state = json.load(f)
    df = pd.DataFrame(state["calibration_history"])
    df = df.dropna(subset=["realized"]).copy()
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values(["eval_day", "timestamp_utc"]).reset_index(drop=True)
    # Horizon = rank within vintage. Valid because each vintage's predictions
    # are t0+1h..t0+72h and realisation arrives in timestamp order, so the
    # realised subset is a contiguous prefix.
    df["horizon"] = df.groupby("eval_day").cumcount() + 1
    return df


def add_sorted_raw_bands(df: pd.DataFrame) -> pd.DataFrame:
    """q10s/q50s/q90s = the per-row sorted raw quantile triple.

    This is the same monotonicity-restored base that production widens
    (predict(sort=True)); we re-derive it from the raws so the treatment
    calibrates the raw model output, not the already-widened bands.
    """
    raw = np.sort(df[RAW_COLS].to_numpy(dtype=float), axis=1)
    df = df.copy()
    df["q10s"], df["q50s"], df["q90s"] = raw[:, 0], raw[:, 1], raw[:, 2]
    return df


def finite_sample_quantile(scores: np.ndarray, level: float) -> float:
    """Split-conformal finite-sample quantile: rank ceil((n+1)*level), 1-indexed.

    Clipped to n-1 when the correction exceeds the sample (conservative-down;
    textbook value would be +inf — at our calibration sizes, ~400+ scores,
    the clip never binds for level=0.90).
    """
    n = len(scores)
    rank = int(np.ceil((n + 1) * level)) - 1
    rank = min(max(rank, 0), n - 1)
    return float(np.sort(scores)[rank])


def replay_per_side(
    df_raw: pd.DataFrame,
    calib_days: int,
    min_calib_days: int,
    level: float,
    by_horizon_group: bool = False,
) -> pd.DataFrame:
    """Return evaluated rows with treatment columns lo_t/hi_t (NaN if not evaluable)."""
    out = df_raw.copy()
    out["lo_t"] = np.nan
    out["hi_t"] = np.nan
    out["q_lo"] = np.nan
    out["q_hi"] = np.nan
    ts = out["timestamp_utc"]

    for day in sorted(out["eval_day"].unique()):
        cutoff_end = pd.Timestamp(day, tz="UTC")
        cutoff_start = cutoff_end - pd.Timedelta(days=calib_days)
        calib_mask = (ts >= cutoff_start) & (ts < cutoff_end)
        if ts[calib_mask].dt.date.nunique() < min_calib_days:
            continue
        day_mask = out["eval_day"] == day

        if by_horizon_group:
            for lo_h, hi_h, _name in HORIZON_GROUPS:
                gmask = (out["horizon"] >= lo_h) & (out["horizon"] <= hi_h)
                cm = calib_mask & gmask
                if cm.sum() == 0:
                    continue
                _apply(out, day_mask & gmask, cm, level)
        else:
            _apply(out, day_mask, calib_mask, level)
    return out


def _apply(out: pd.DataFrame, target_mask: pd.Series, calib_mask: pd.Series, level: float) -> None:
    calib = out.loc[calib_mask]
    e_lo = (calib["q10s"] - calib["realized"]).to_numpy()
    e_hi = (calib["realized"] - calib["q90s"]).to_numpy()
    q_lo = finite_sample_quantile(e_lo, level)
    q_hi = finite_sample_quantile(e_hi, level)
    out.loc[target_mask, "lo_t"] = out.loc[target_mask, "q10s"] - q_lo
    out.loc[target_mask, "hi_t"] = out.loc[target_mask, "q90s"] + q_hi
    out.loc[target_mask, "q_lo"] = q_lo
    out.loc[target_mask, "q_hi"] = q_hi


def summarize(y: pd.Series, lo: pd.Series, hi: pd.Series, alpha: float) -> dict:
    return {
        "n": int(len(y)),
        "lower": float((y >= lo).mean()),
        "upper": float((y <= hi).mean()),
        "both": float(((y >= lo) & (y <= hi)).mean()),
        "med_width": float((hi - lo).median()),
        "winkler": float(np.mean(winkler_interval_score(
            y.to_numpy(), lo.to_numpy(), hi.to_numpy(), alpha=alpha))),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="EXP-015 Stage-1 offline CQR replay")
    parser.add_argument("--state", default=str(DEFAULT_STATE))
    parser.add_argument("--calib-days", type=int, default=7)
    parser.add_argument("--min-calib-days", type=int, default=3)
    parser.add_argument("--alpha", type=float, default=0.20)
    args = parser.parse_args()
    per_side_level = 1.0 - args.alpha / 2.0  # 0.90 per side for an 80% interval

    df = load_history(Path(args.state))
    if not set(RAW_COLS).issubset(df.columns):
        sys.exit("calibration_history has no raw quantile columns — nothing to replay.")
    df_raw = add_sorted_raw_bands(df[df[RAW_COLS].notna().all(axis=1)].copy())
    print(f"history: {df['eval_day'].nunique()} vintages, {len(df)} realised rows; "
          f"raw-bearing: {df_raw['eval_day'].nunique()} vintages, {len(df_raw)} rows "
          f"({df_raw['eval_day'].min()} → {df_raw['eval_day'].max()})")

    treated = replay_per_side(df_raw, args.calib_days, args.min_calib_days, per_side_level)
    ev = treated.dropna(subset=["lo_t", "hi_t"]).copy()
    n_vintages = ev["eval_day"].nunique()
    print(f"evaluable: {n_vintages} vintages, {len(ev)} rows "
          f"({sorted(ev['eval_day'].unique())})")
    if n_vintages < MIN_EVALUABLE_VINTAGES:
        sys.exit(f"precondition not met: {n_vintages} < {MIN_EVALUABLE_VINTAGES} evaluable "
                 f"vintages — wait for more raw-bearing days and re-run unchanged.")

    inc = summarize(ev["realized"], ev["p10"], ev["p90"], args.alpha)
    trt = summarize(ev["realized"], ev["lo_t"], ev["hi_t"], args.alpha)
    print("\n== Same-rows comparison (incumbent = stored production bands) ==")
    for name, m in (("incumbent", inc), ("treatment", trt)):
        print(f"{name:10s} lower={m['lower']:.3f} upper={m['upper']:.3f} "
              f"both={m['both']:.3f} med_width={m['med_width']:.1f} winkler={m['winkler']:.1f}")

    print("\n== Per-vintage lower-side (treatment | incumbent) ==")
    for day, sub in ev.groupby("eval_day"):
        t = (sub["realized"] >= sub["lo_t"]).mean()
        i = (sub["realized"] >= sub["p10"]).mean()
        print(f"  {day}  n={len(sub):3d}  treatment={t:.3f}  incumbent={i:.3f}")

    neg_lo = float((ev["q_lo"] < 0).mean())
    neg_hi = float((ev["q_hi"] < 0).mean())
    print(f"\nnegative-q frequency (row-weighted): q_lo {neg_lo:.2f}, q_hi {neg_hi:.2f}")

    # Descriptive companion: horizon-grouped per-side variant + per-group coverage
    grouped = replay_per_side(df_raw, args.calib_days, args.min_calib_days,
                              per_side_level, by_horizon_group=True)
    gev = grouped.dropna(subset=["lo_t", "hi_t"])
    print("\n== Descriptive (never gated): horizon-grouped per-side variant ==")
    for lo_h, hi_h, name in HORIZON_GROUPS:
        sub = gev[(gev["horizon"] >= lo_h) & (gev["horizon"] <= hi_h)]
        subp = ev[(ev["horizon"] >= lo_h) & (ev["horizon"] <= hi_h)]
        if sub.empty or subp.empty:
            continue
        g = summarize(sub["realized"], sub["lo_t"], sub["hi_t"], args.alpha)
        p = summarize(subp["realized"], subp["lo_t"], subp["hi_t"], args.alpha)
        print(f"  {name:7s} grouped lower={g['lower']:.3f} upper={g['upper']:.3f} "
              f"| pooled-treatment lower={p['lower']:.3f} upper={p['upper']:.3f}")

    # Pre-committed verdict block (docs/hypothesis-log.md [2026-06-12] EXP-015 Stage 1)
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
