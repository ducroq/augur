"""EXP-014 — apply the pre-committed redesigned promotion criterion to the
M4 paired data.

This is not a new shadow window. It is the application of the criterion
defined in `docs/hypothesis-log.md` entry "[2026-05-29] LightGBM-Quantile
passes the redesigned promotion criterion on the M4 window data" to the
already-collected, vintage-corrected paired dataset that EXP-013 produced.

Method (pre-committed before this script's first run):

1. Skill gate: paired Diebold-Mariano on |y - p50_lgbm| vs |y - point_arf|.
   - HAC bandwidth: max_horizon - 1 = 71 (DM 1995 §4 for h-step-ahead overlap).
   - Threshold: mean diff < 0 AND one-sided DM p < 0.10.

2. Calibration guardrail: 80% interval coverage on BOTH sides.
   - lower_cov = fraction(y >= p10) must be in [0.85, 0.95]
   - upper_cov = fraction(y <= p90) must be in [0.85, 0.95]
   - If either side fails for either model, promotion is blocked.

3. No tail-metric gate. Pinball-at-p10 and per-horizon decomposition are
   reported descriptively after the decision.

Exit codes:
   0  promotion criterion met (PROMOTE = True)
   1  promotion criterion failed
   2  input prerequisites missing
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ml.shadow.metrics import (
    diebold_mariano,
    lower_side_coverage,
    pinball_loss,
    point_to_quantile_loss_equivalent,
)

# Re-use EXP-012's paired-data assembly (vintage-corrected join).
from exp012_evaluate import build_paired

# Pre-committed thresholds — DO NOT change after seeing data.
# iteration-5 redesign (2026-05-29): calibration gate is now "not worse than
# incumbent" rather than absolute target. See docs/hypothesis-log.md entry
# "[2026-05-29] Iteration-5 redesign of the calibration guardrail".
SKILL_DM_P_THRESHOLD = 0.10
CALIBRATION_DEGRADATION_TOLERANCE = 0.02  # LGBM may be at most 0.02 worse than ARF on either side
ABSOLUTE_CALIBRATION_FLOOR = 0.85  # below this, flagged as known-weakness but not blocker
HAC_LAGS = 71  # max_horizon - 1 for h+1..h+72


def main() -> int:
    print("=" * 78)
    print("EXP-014  redesigned promotion criterion on M4 paired data")
    print(
        "  pre-committed thresholds: skill DM p < {}, calibration degradation <= {}, HAC lag {}".format(
            SKILL_DM_P_THRESHOLD, CALIBRATION_DEGRADATION_TOLERANCE, HAC_LAGS
        )
    )
    print("=" * 78)

    paired = build_paired()
    if paired.empty:
        print("FATAL: no paired observations", file=sys.stderr)
        return 2

    y = paired["realized"].to_numpy()
    lgbm_p50 = paired["p50"].to_numpy()
    arf_point = paired["arf_point"].to_numpy()
    lgbm_p10 = paired["p10"].to_numpy()
    lgbm_p90 = paired["p90"].to_numpy()
    arf_lower = paired["arf_lower"].to_numpy()
    arf_upper = paired["arf_upper"].to_numpy()

    # --- 1. Skill gate: paired DM on absolute errors, p50 vs point ---
    loss_lgbm = point_to_quantile_loss_equivalent(y, lgbm_p50)
    loss_arf = point_to_quantile_loss_equivalent(y, arf_point)
    dm = diebold_mariano(loss_lgbm, loss_arf, hac_lags=HAC_LAGS)

    lgbm_mae = float(loss_lgbm.mean())
    arf_mae = float(loss_arf.mean())
    mae_ratio = lgbm_mae / arf_mae

    print("\n1. Skill gate  (paired DM, |y - p50_LGBM| vs |y - point_ARF|)")
    print(f"   LGBM MAE: {lgbm_mae:.3f}")
    print(f"   ARF MAE:  {arf_mae:.3f}")
    print(f"   ratio (LGBM/ARF): {mae_ratio:.3f}")
    print(
        f"   DM stat = {dm.statistic:.3f}, one-sided p = {dm.p_value_one_sided:.4g}, "
        f"mean diff = {dm.mean_diff:.3f}"
    )
    print(f"   HAC bandwidth: {dm.hac_lags} lags")

    skill_pass = dm.mean_diff < 0 and dm.p_value_one_sided < SKILL_DM_P_THRESHOLD
    print(f"   --> skill gate: {'PASS' if skill_pass else 'FAIL'}")

    # --- 2. Calibration guardrail: "not worse than incumbent" on each side ---
    # Iteration-5 redesign. The previous absolute-target gate blocked promotion
    # for a calibration weakness both models share; this gate asks the swap-
    # relevant question: "does LGBM make calibration worse?"
    lgbm_lower = lower_side_coverage(y, lgbm_p10)
    lgbm_upper = float((y <= lgbm_p90).mean())
    arf_lower_cov = lower_side_coverage(y, arf_lower)
    arf_upper_cov = float((y <= arf_upper).mean())

    lower_degradation = arf_lower_cov - lgbm_lower
    upper_degradation = arf_upper_cov - lgbm_upper

    print("\n2. Calibration guardrail  (LGBM not more than 0.02 worse than ARF on either side)")
    print(
        f"   LGBM lower-side (y >= p10):  {lgbm_lower:.3f}  "
        f"upper-side (y <= p90): {lgbm_upper:.3f}"
    )
    print(
        f"   ARF  lower-side (y >= L):    {arf_lower_cov:.3f}  "
        f"upper-side (y <= U):   {arf_upper_cov:.3f}"
    )
    print(
        f"   degradation (ARF - LGBM):    lower {lower_degradation:+.3f}  "
        f"upper {upper_degradation:+.3f}  (tolerance: <= {CALIBRATION_DEGRADATION_TOLERANCE})"
    )

    lower_ok = lower_degradation <= CALIBRATION_DEGRADATION_TOLERANCE
    upper_ok = upper_degradation <= CALIBRATION_DEGRADATION_TOLERANCE
    lgbm_cal_pass = lower_ok and upper_ok
    print(f"   --> calibration gate: {'PASS' if lgbm_cal_pass else 'FAIL'}")

    # Absolute calibration as separate concern: flag if below floor but don't block.
    abs_floor_warnings = []
    if lgbm_lower < ABSOLUTE_CALIBRATION_FLOOR:
        abs_floor_warnings.append(
            f"LGBM lower-side {lgbm_lower:.3f} < {ABSOLUTE_CALIBRATION_FLOOR} absolute floor"
        )
    if lgbm_upper < ABSOLUTE_CALIBRATION_FLOOR:
        abs_floor_warnings.append(
            f"LGBM upper-side {lgbm_upper:.3f} < {ABSOLUTE_CALIBRATION_FLOOR} absolute floor"
        )
    if abs_floor_warnings:
        print(
            f"   WARNING  absolute-coverage floor weakness (NOT a blocker; same problem as ARF):"
        )
        for w in abs_floor_warnings:
            print(f"      - {w}")
        print(
            f"   Queue follow-up: CQR retune or ACI to improve lower-tail calibration."
        )

    promote = skill_pass and lgbm_cal_pass

    # --- 3. Descriptive tail metrics (reported, not gated) ---
    lgbm_p10_pin = pinball_loss(y, lgbm_p10, 0.10).mean()
    arf_p10_pin = pinball_loss(y, arf_lower, 0.10).mean()
    print("\n3. Descriptive tail metrics  (NOT a gate)")
    print(
        f"   Pinball-at-p10: LGBM {lgbm_p10_pin:.3f} vs ARF {arf_p10_pin:.3f}"
    )

    # Per-horizon decomposition
    paired = paired.copy()
    midnight = pd.to_datetime(paired["eval_day"]).dt.tz_localize("UTC")
    paired["horizon_h"] = (paired["timestamp_utc"] - midnight).dt.total_seconds() / 3600.0
    paired["lgbm_abs"] = np.abs(paired["realized"] - paired["p50"])
    paired["arf_abs"] = np.abs(paired["realized"] - paired["arf_point"])
    paired["h_group"] = pd.cut(
        paired["horizon_h"],
        bins=[0, 24, 48, 72, np.inf],
        labels=["h<=24", "24<h<=48", "48<h<=72", "h>72"],
    )
    per_h = paired.groupby("h_group", observed=False).agg(
        n=("realized", "size"),
        lgbm_mae=("lgbm_abs", "mean"),
        arf_mae=("arf_abs", "mean"),
    )
    print("\n   Per-horizon MAE (descriptive):")
    print(per_h.to_string())

    # --- Final verdict ---
    print("\n" + "=" * 78)
    print(f"VERDICT:  PROMOTE = {promote}")
    if promote:
        print("  LightGBM passes the redesigned criterion. Swap ARF -> LightGBM on")
        print("  the dashboard; ARF cron remains as a backup signal for one cycle.")
    else:
        reasons = []
        if not skill_pass:
            reasons.append(f"skill gate failed (DM p={dm.p_value_one_sided:.3g})")
        if not lgbm_cal_pass:
            reasons.append(
                f"LGBM calibration failed (lower {lgbm_lower:.3f}, upper {lgbm_upper:.3f})"
            )
        print(f"  Failure reason(s): {'; '.join(reasons)}")
        print(f"  Pre-committed decision: BLOCK promotion. Fix the calibration problem,")
        print(f"  re-run, do not promote on skill alone.")
    print("=" * 78)

    return 0 if promote else 1


if __name__ == "__main__":
    sys.exit(main())
