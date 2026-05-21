"""M4 promotion-method runner (pre-staged 2026-05-21 for the 2026-05-23 session).

Runs the pre-committed Method from `docs/hypothesis-log.md` against the most
recent 14 contiguous rows of `ml/shadow/eval_log.jsonl` and prints a copy-
pasteable verdict block.

Also computes the supplementary horizon-decomposed (a) low-price MAE per the
2026-05-18 mid-window preview caveat: criterion (a) is dominated by long-
horizon hours where LGBM is structurally weakest, so we report h<=24 vs h>24
splits derived from `shadow_state.json:calibration_history` without modifying
the eval_log schema. This is reported alongside the Method result, not in
place of it — Method is not loosened mid-window (framework: don't loosen
Method when the answer arrives).

Usage:
    python scripts/m4_method_run.py
    python scripts/m4_method_run.py --eval-log path/to/eval_log.jsonl \\
                                    --shadow-state path/to/shadow_state.json

Exit codes:
    0 — script ran, verdict printed (regardless of pass/fail)
    2 — input prerequisites missing (file not found, <14 rows, gap)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVAL_LOG = REPO_ROOT / "ml" / "shadow" / "eval_log.jsonl"
DEFAULT_SHADOW_STATE = REPO_ROOT / "ml" / "models" / "shadow" / "shadow_state.json"

LOW_PRICE_EUR_MWH = 30.0
N_WINDOW_DAYS = 14


def _die(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def load_rows(path: Path) -> list[dict]:
    if not path.is_file():
        _die(f"ERR: eval_log not found at {path}")
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) < N_WINDOW_DAYS:
        _die(
            f"ERR: need {N_WINDOW_DAYS} rows, got {len(rows)}. "
            f"Latest date: {rows[-1]['date'] if rows else 'n/a'}"
        )
    return rows[-N_WINDOW_DAYS:]


def check_contiguity(rows: list[dict]) -> None:
    dates = [datetime.strptime(r["date"], "%Y-%m-%d").date() for r in rows]
    for prev, nxt in zip(dates, dates[1:]):
        if (nxt - prev).days != 1:
            _die(f"ERR: non-contiguous rows {prev} -> {nxt}")


def run_method(rows: list[dict]) -> dict:
    """Pre-committed Method from docs/hypothesis-log.md."""
    # (a) Slice MAE win on hours where realised < 30 EUR/MWh
    lgbm_low = [r["lightgbm_mae_at_low_price"] for r in rows if r["lightgbm_mae_at_low_price"] is not None]
    arf_low = [r["arf_mae_at_low_price"] for r in rows if r["arf_mae_at_low_price"] is not None]
    lgbm_low_mean = float(np.mean(lgbm_low)) if lgbm_low else None
    arf_low_mean = float(np.mean(arf_low)) if arf_low else None
    if lgbm_low_mean is not None and arf_low_mean is not None and arf_low_mean != 0.0:
        ratio_a = lgbm_low_mean / arf_low_mean
    else:
        ratio_a = None
    n_low = sum(r["n_low_price_hours"] for r in rows)

    # (b) P10/P90 coverage — both guards
    covs = [r["lightgbm_band_coverage_p80"] for r in rows]
    mean_cov = float(np.mean(covs))
    n_low_cov_days = sum(1 for c in covs if c < 0.60)

    # (c) Weekday-evening-peak (16-19 UTC) MAE ratio.
    # Explicit None/zero checks mirror the (a) guard; truthy filter would
    # silently drop legitimate zero-MAE days (implausible in EUR/MWh but
    # consistent guards are safer than asymmetric ones).
    peak_ratios = [
        r["lightgbm_peak_hour_mae"] / r["arf_peak_hour_mae"]
        for r in rows
        if r["arf_peak_hour_mae"] is not None
        and r["lightgbm_peak_hour_mae"] is not None
        and r["arf_peak_hour_mae"] != 0.0
    ]
    mean_peak_ratio = float(np.mean(peak_ratios)) if peak_ratios else None

    # Overall MAE (informational)
    overall_lgbm = float(np.mean([r["lightgbm_mae"] for r in rows]))
    overall_arf = float(np.mean([r["arf_mae"] for r in rows if r["arf_mae"] is not None]))

    # Decision
    pass_a = ratio_a is not None and ratio_a <= 0.75 and n_low >= 50
    pass_b = 0.75 <= mean_cov <= 0.85 and n_low_cov_days < 3
    pass_c = mean_peak_ratio is not None and mean_peak_ratio <= 1.10
    promote = pass_a and pass_b and pass_c

    return {
        "ratio_a": ratio_a,
        "lgbm_low_mae": lgbm_low_mean,
        "arf_low_mae": arf_low_mean,
        "n_low": n_low,
        "mean_cov": mean_cov,
        "n_low_cov_days": n_low_cov_days,
        "mean_peak_ratio": mean_peak_ratio,
        "overall_lgbm_mae": overall_lgbm,
        "overall_arf_mae": overall_arf,
        "overall_ratio": overall_lgbm / overall_arf if overall_arf else None,
        "pass_a": pass_a,
        "pass_b": pass_b,
        "pass_c": pass_c,
        "promote": promote,
    }


def horizon_decomposed_a(state_path: Path, first_date: str, last_date: str) -> dict | None:
    """Supplementary: criterion (a) split by horizon group (h<=24 vs h>24).

    Per the 2026-05-18 mid-window preview, criterion (a) low-price MAE is
    dominated by long-horizon hours. Derive horizon from (timestamp_utc -
    midnight_of_eval_day_utc), filter to realised < 30 EUR/MWh, report
    mean |p50 - realized| in each bucket.

    Returns None if shadow_state missing or no data in window.
    """
    if not state_path.is_file():
        return None
    state = json.loads(state_path.read_text())
    history = state.get("calibration_history", [])
    if not history:
        return None

    lo, hi = [], []
    for entry in history:
        if not (first_date <= entry["eval_day"] <= last_date):
            continue
        if entry["realized"] >= LOW_PRICE_EUR_MWH:
            continue
        ts = datetime.fromisoformat(entry["timestamp_utc"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        eval_day_midnight = datetime.strptime(entry["eval_day"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        horizon_h = (ts - eval_day_midnight).total_seconds() / 3600.0
        err = abs(entry["p50"] - entry["realized"])
        (lo if horizon_h <= 24 else hi).append(err)

    return {
        "n_low_h_le_24": len(lo),
        "n_low_h_gt_24": len(hi),
        "lgbm_p50_mae_h_le_24": float(np.mean(lo)) if lo else None,
        "lgbm_p50_mae_h_gt_24": float(np.mean(hi)) if hi else None,
        "lgbm_p50_medae_h_le_24": float(np.median(lo)) if lo else None,
        "lgbm_p50_medae_h_gt_24": float(np.median(hi)) if hi else None,
    }


def fmt(x, suffix=""):
    if x is None:
        return "n/a"
    return f"{x:.3f}{suffix}"


def print_verdict(rows: list[dict], m: dict, h: dict | None) -> None:
    first, last = rows[0]["date"], rows[-1]["date"]
    print()
    print("=" * 72)
    print(f"M4 METHOD RUN  —  window: {first}  ..  {last}  ({len(rows)} contiguous rows)")
    print("=" * 72)
    print()
    print("Criterion (a)  low-price MAE win  (threshold: ratio <= 0.75 AND n_low >= 50)")
    print(f"  lightgbm_mae_at_low_price (mean):  {fmt(m['lgbm_low_mae'])} EUR/MWh")
    print(f"  arf_mae_at_low_price      (mean):  {fmt(m['arf_low_mae'])} EUR/MWh")
    print(f"  ratio_a = lgbm / arf:              {fmt(m['ratio_a'])}    (guard only)")
    print(f"  n_low_price_hours (sum):           {m['n_low']:<6}            (guard only)")
    print(f"  --> criterion (a) overall:         {'PASS' if m['pass_a'] else 'FAIL'}")
    print()
    print("Criterion (b)  P80 band coverage  (threshold: mean in [0.75, 0.85] AND <3 days <0.60)")
    print(f"  mean coverage:                     {fmt(m['mean_cov'])}    (guard only)")
    print(f"  days with coverage < 0.60:         {m['n_low_cov_days']:<6}            (guard only)")
    print(f"  --> criterion (b) overall:         {'PASS' if m['pass_b'] else 'FAIL'}")
    print()
    print("Criterion (c)  weekday-peak MAE ratio  (threshold: <= 1.10)")
    print(f"  mean peak ratio (lgbm/arf):        {fmt(m['mean_peak_ratio'])}    (guard only)")
    print(f"  --> criterion (c) overall:         {'PASS' if m['pass_c'] else 'FAIL'}")
    print()
    print("Informational  (not promotion criteria)")
    print(f"  overall MAE  lgbm / arf:           {fmt(m['overall_lgbm_mae'])} / {fmt(m['overall_arf_mae'])}  (ratio {fmt(m['overall_ratio'])})")
    print()
    if h is not None:
        print("Supplementary — horizon-decomposed (a)  (2026-05-18 caveat, not part of Method)")
        print(f"  h <= 24:  n={h['n_low_h_le_24']:<5}  LGBM |p50 - realized|  mean = {fmt(h['lgbm_p50_mae_h_le_24'])}  median = {fmt(h['lgbm_p50_medae_h_le_24'])}")
        print(f"  h  > 24:  n={h['n_low_h_gt_24']:<5}  LGBM |p50 - realized|  mean = {fmt(h['lgbm_p50_mae_h_gt_24'])}  median = {fmt(h['lgbm_p50_medae_h_gt_24'])}")
        print("  (mean/median gap large => spike-driven; mean/median similar => structural)")
        print()
    print("=" * 72)
    print(f"VERDICT:  PROMOTE = {m['promote']}")
    if m["promote"]:
        print("  Path A in augur#13 (promote LightGBM-Quantile to production).")
    else:
        print("  Path A is OFF — read failure-mode signals (hypothesis-log Alternatives) ")
        print("  to choose between Path B (park) and Path C (extend window).")
    print("=" * 72)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eval-log", type=Path, default=DEFAULT_EVAL_LOG)
    ap.add_argument("--shadow-state", type=Path, default=DEFAULT_SHADOW_STATE)
    args = ap.parse_args()

    rows = load_rows(args.eval_log)
    check_contiguity(rows)
    method = run_method(rows)
    horizon = horizon_decomposed_a(args.shadow_state, rows[0]["date"], rows[-1]["date"])
    print_verdict(rows, method, horizon)


if __name__ == "__main__":
    main()
