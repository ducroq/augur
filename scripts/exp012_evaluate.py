"""EXP-012 — re-evaluate the M4 window using the new probabilistic metrics.

Tests whether the literature-recommended criterion (CRPS / pinball-p10 /
twCRPS / lower-side coverage / DM) tells a different story than the failed
M4 criterion (a) (fixed-threshold MAE-on-slice).

Phase 1 (this script): use the ALREADY-COLLECTED 3-quantile LGBM predictions
from `ml/models/shadow/shadow_state.json:calibration_history`, paired with
ARF point forecasts from `ml/forecasts/*.json`, on the M4 trailing-14 window
(2026-05-14 to 2026-05-27). Reports both the OLD and NEW metrics side by
side, plus DM significance tests.

Caveat (per `docs/metric-redesign-literature-review.md` §7): with only 3
quantiles the CRPS estimator is biased; we report it as "mean quantile
score (3-point estimator)" not as CRPS. Honest aggregate CRPS requires
retraining at 9+ quantiles (potential Phase 2).

Output:
- prints summary to stdout
- writes `docs/exp-012-results.md` with full report
- prints alignment diagnostics if data is sparse
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.shadow.metrics import (
    DMResult,
    diebold_mariano,
    lower_side_coverage,
    mean_quantile_score,
    per_observation_quantile_score,
    pinball_loss,
    point_to_quantile_loss_equivalent,
    twcrps_left_tail,
    winkler_interval_score,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SHADOW_STATE = REPO_ROOT / "ml" / "models" / "shadow" / "shadow_state.json"
ARF_FORECASTS_DIR = REPO_ROOT / "ml" / "forecasts"
EVAL_LOG = REPO_ROOT / "ml" / "shadow" / "eval_log.jsonl"

# Pre-committed M4 trailing-14 window (matches scripts/m4_method_run.py).
WINDOW_START = "2026-05-14"
WINDOW_END = "2026-05-27"

LOW_PRICE_THRESHOLD = 30.0
LGBM_TAUS = np.array([0.10, 0.50, 0.90])  # what we have in calibration_history


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def load_lgbm_predictions() -> pd.DataFrame:
    """LGBM p10/p50/p90 + realized + eval_day from calibration_history."""
    state = json.loads(SHADOW_STATE.read_text())
    hist = state.get("calibration_history", [])
    if not hist:
        raise RuntimeError(f"No calibration_history in {SHADOW_STATE}")
    df = pd.DataFrame(hist)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df["eval_day"] = pd.to_datetime(df["eval_day"]).dt.date.astype(str)
    df = df[(df["eval_day"] >= WINDOW_START) & (df["eval_day"] <= WINDOW_END)].copy()
    # Horizon = hours from eval_day midnight UTC (matches m4_method_run.py def)
    midnight = pd.to_datetime(df["eval_day"]).dt.tz_localize("UTC")
    df["horizon_h"] = (df["timestamp_utc"] - midnight).dt.total_seconds() / 3600.0
    return df.reset_index(drop=True)


def _load_arf_archive(archive_path: Path) -> pd.DataFrame:
    """Parse one ARF forecast archive into (timestamp_utc, point, lower, upper) rows."""
    data = json.loads(archive_path.read_text())
    f = data.get("forecast", {})
    fl = data.get("forecast_lower", {})
    fu = data.get("forecast_upper", {})
    rows = []
    for ts_iso, point in f.items():
        if point is None:
            continue
        ts = pd.Timestamp(ts_iso)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        rows.append(
            {
                "timestamp_utc": ts,
                "arf_point": float(point),
                "arf_lower": float(fl[ts_iso]) if ts_iso in fl else np.nan,
                "arf_upper": float(fu[ts_iso]) if ts_iso in fu else np.nan,
            }
        )
    return pd.DataFrame(rows)


def build_paired() -> pd.DataFrame:
    """LGBM and ARF predictions joined on (eval_day, target timestamp_utc).

    For each LGBM eval_day D, finds the ARF archive that the production
    pipeline (`ml.shadow.evaluate_shadow.find_arf_archive_for_day`) would have
    used — the most recent archive whose run-timestamp precedes eval_day
    midnight UTC. This is typically the archive named `{D-1}_1445_forecast.json`
    (the 14:45 UTC run of the previous day).

    An earlier version of this function joined on `issue_date = filename_date`,
    which paired LGBM `eval_day=D` with `{D}_1445_forecast.json` — an ARF
    forecast issued ~15h after the LGBM cron's t0. The 2026-05-29 code-review
    battery flagged this as a vintage mismatch; corrected to match the
    production pipeline exactly.
    """
    # Import here to avoid circular issues if metrics.py is reused stand-alone.
    from ml.shadow.evaluate_shadow import find_arf_archive_for_day

    lgbm = load_lgbm_predictions()
    eval_days = sorted(lgbm["eval_day"].unique())

    arf_rows = []
    archives_used = {}
    for eval_day in eval_days:
        archive = find_arf_archive_for_day(ARF_FORECASTS_DIR, eval_day)
        if archive is None:
            print(f"  WARN: no ARF archive available for eval_day={eval_day}; skipping")
            continue
        archives_used[eval_day] = archive.name
        arf_df = _load_arf_archive(archive)
        if arf_df.empty:
            continue
        arf_df = arf_df.assign(eval_day=eval_day)
        arf_rows.append(arf_df)

    if not arf_rows:
        return pd.DataFrame()

    arf = pd.concat(arf_rows, ignore_index=True)

    # Diagnostic: print archive-to-eval_day mapping so the join is auditable.
    print("\nARF archive per eval_day (production-pipeline-consistent mapping):")
    for d, name in archives_used.items():
        print(f"  eval_day={d}  ->  {name}")

    paired = pd.merge(
        lgbm,
        arf,
        on=["eval_day", "timestamp_utc"],
        how="inner",
    )
    return paired.sort_values(["eval_day", "timestamp_utc"]).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Old criterion (a) — recomputed for sanity check
# ---------------------------------------------------------------------------


def old_criterion_a(paired: pd.DataFrame) -> dict:
    """MAE on hours where realised < 30 EUR/MWh — the failed M4 criterion."""
    low = paired[paired["realized"] < LOW_PRICE_THRESHOLD]
    if len(low) == 0:
        return {"n_low": 0, "lgbm_mae": None, "arf_mae": None, "ratio": None}
    lgbm_mae = float(np.abs(low["p50"] - low["realized"]).mean())
    arf_mae = float(np.abs(low["arf_point"] - low["realized"]).mean())
    return {
        "n_low": int(len(low)),
        "lgbm_mae": lgbm_mae,
        "arf_mae": arf_mae,
        "ratio": lgbm_mae / arf_mae if arf_mae else None,
    }


# ---------------------------------------------------------------------------
# New metrics
# ---------------------------------------------------------------------------


@dataclass
class NewMetricsResult:
    n: int
    # Aggregate / overall
    lgbm_mqs: float                  # mean quantile score (3-point biased CRPS)
    arf_mae: float                   # CRPS-equivalent for point forecast
    overall_mqs_minus_arf_mae: float # paired direction (negative = LGBM wins)
    dm_overall: DMResult
    # Tail-skill (the structural test)
    twcrps_threshold: float          # the c used
    lgbm_twcrps: float               # mean per-observation twCRPS
    arf_twcrps_equiv: float          # ARF: pinball-at-p_below-threshold equivalent
    dm_twcrps: DMResult
    # Pinball-at-p10
    lgbm_p10_pinball: float
    arf_p10_pinball: float           # using arf_lower as p10
    dm_p10: DMResult
    # Coverage diagnostics
    lgbm_lower_coverage: float       # target 0.90 for 80% interval lower side
    arf_lower_coverage: float
    lgbm_winkler: float
    arf_winkler: float


def compute_new_metrics(paired: pd.DataFrame, threshold: float) -> NewMetricsResult:
    """Apply the literature-recommended metrics to the paired dataframe."""
    y = paired["realized"].to_numpy()
    lgbm_q = np.column_stack(
        [paired["p10"].to_numpy(), paired["p50"].to_numpy(), paired["p90"].to_numpy()]
    )
    arf_point = paired["arf_point"].to_numpy()
    arf_lower = paired["arf_lower"].to_numpy()
    arf_upper = paired["arf_upper"].to_numpy()

    # --- overall skill (MQS vs MAE-as-CRPS-equivalent) ---
    lgbm_mqs_per = per_observation_quantile_score(y, lgbm_q, LGBM_TAUS)
    arf_mae_per = point_to_quantile_loss_equivalent(y, arf_point)
    dm_overall = diebold_mariano(lgbm_mqs_per, arf_mae_per)

    # --- twCRPS at left-tail threshold ---
    # LGBM twCRPS variant: only quantiles below threshold contribute, averaged
    # across all 3 columns. See metrics.py docstring — this is NOT canonical
    # Gneiting-Ranjan twCRPS; it's the per-quantile-decomposition variant.
    lgbm_tw_per = twcrps_left_tail(y, lgbm_q, LGBM_TAUS, threshold)
    # ARF equivalent: treat ARF as a Dirac-mass predictive distribution
    # (Gneiting & Raftery 2007 §4.2: CRPS of a point mass = MAE). For the
    # per-quantile-decomposition variant the parity-correct contribution is
    # `|y - point| * 1{point <= c}` — no additional `/ K` factor (an earlier
    # version divided by len(LGBM_TAUS) ad hoc, which the 2026-05-29 code
    # review flagged as biasing the variant comparison ~3× in ARF's favour).
    arf_tw_per = np.where(arf_point <= threshold, np.abs(y - arf_point), 0.0)
    dm_tw = diebold_mariano(lgbm_tw_per, arf_tw_per)
    # Diagnostic: count zero-weight observations (where neither quantile fell
    # below threshold for LGBM, OR the ARF point didn't). These contribute
    # nothing to the per-obs score and inflate "lower is better" via abstention.
    lgbm_tw_zero = int((lgbm_tw_per == 0).sum())
    arf_tw_zero = int((arf_tw_per == 0).sum())
    print(
        f"\n  twCRPS variant zero-weight obs: LGBM {lgbm_tw_zero}/{len(y)}, "
        f"ARF {arf_tw_zero}/{len(y)}  (high zero count = model abstains from tail)"
    )

    # --- pinball-at-p10 ---
    lgbm_p10_per = pinball_loss(y, lgbm_q[:, 0], 0.10)
    # ARF's lower band ≈ point - 1.282 sigma at 80% → treat as p10 directly.
    arf_p10_per = pinball_loss(y, arf_lower, 0.10)
    dm_p10 = diebold_mariano(lgbm_p10_per, arf_p10_per)

    # --- coverage diagnostics (descriptive) ---
    lgbm_lower_cov = lower_side_coverage(y, lgbm_q[:, 0])
    arf_lower_cov = lower_side_coverage(y, arf_lower)
    lgbm_winkler = float(winkler_interval_score(y, lgbm_q[:, 0], lgbm_q[:, 2], 0.20).mean())
    arf_winkler = float(winkler_interval_score(y, arf_lower, arf_upper, 0.20).mean())

    return NewMetricsResult(
        n=len(y),
        lgbm_mqs=float(lgbm_mqs_per.mean()),
        arf_mae=float(arf_mae_per.mean()),
        overall_mqs_minus_arf_mae=float(lgbm_mqs_per.mean() - arf_mae_per.mean()),
        dm_overall=dm_overall,
        twcrps_threshold=float(threshold),
        lgbm_twcrps=float(lgbm_tw_per.mean()),
        arf_twcrps_equiv=float(arf_tw_per.mean()),
        dm_twcrps=dm_tw,
        lgbm_p10_pinball=float(lgbm_p10_per.mean()),
        arf_p10_pinball=float(arf_p10_per.mean()),
        dm_p10=dm_p10,
        lgbm_lower_coverage=lgbm_lower_cov,
        arf_lower_coverage=arf_lower_cov,
        lgbm_winkler=lgbm_winkler,
        arf_winkler=arf_winkler,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_report(paired: pd.DataFrame, old: dict, new: NewMetricsResult) -> str:
    lines = []
    lines.append("=" * 78)
    lines.append(f"EXP-012  re-evaluation on M4 window  ({WINDOW_START}..{WINDOW_END})")
    lines.append(f"  paired observations: {len(paired)}")
    lines.append(f"  distinct eval days:  {paired['eval_day'].nunique()}")
    lines.append("=" * 78)
    lines.append("")
    lines.append("OLD criterion (a) — MAE on hours with realized < 30 EUR/MWh")
    lines.append(f"  n_low:    {old['n_low']}")
    if old['lgbm_mae'] is not None:
        lines.append(f"  LGBM MAE: {old['lgbm_mae']:.3f}")
        lines.append(f"  ARF MAE:  {old['arf_mae']:.3f}")
        lines.append(f"  ratio (LGBM/ARF): {old['ratio']:.3f}   (M4 threshold <= 0.75)")
        lines.append(f"  VERDICT: {'PASS' if old['ratio'] <= 0.75 else 'FAIL'}")
    lines.append("")
    lines.append("NEW metrics  (paired LGBM vs ARF, Diebold-Mariano one-sided H1: LGBM better)")
    lines.append("")
    lines.append(
        f"  1. Overall skill — mean quantile score (3-point) vs MAE-as-CRPS-equiv"
    )
    lines.append(f"     LGBM MQS:  {new.lgbm_mqs:.3f}")
    lines.append(f"     ARF MAE:   {new.arf_mae:.3f}")
    lines.append(
        f"     DM:        stat={new.dm_overall.statistic:.3f}, "
        f"p(one-sided)={new.dm_overall.p_value_one_sided:.4f}, "
        f"mean diff={new.dm_overall.mean_diff:.3f}"
    )
    lines.append("")
    lines.append(
        f"  2. Tail skill — twCRPS with left-tail weight at threshold={new.twcrps_threshold:.1f}"
    )
    lines.append(f"     LGBM twCRPS:        {new.lgbm_twcrps:.4f}")
    lines.append(f"     ARF twCRPS-equiv:   {new.arf_twcrps_equiv:.4f}")
    lines.append(
        f"     DM:                 stat={new.dm_twcrps.statistic:.3f}, "
        f"p(one-sided)={new.dm_twcrps.p_value_one_sided:.4f}, "
        f"mean diff={new.dm_twcrps.mean_diff:.4f}"
    )
    lines.append("")
    lines.append(f"  3. Pinball-at-p10  (the literal 'did the lower band reach low enough')")
    lines.append(f"     LGBM p10 pinball:  {new.lgbm_p10_pinball:.3f}")
    lines.append(f"     ARF lower pinball: {new.arf_p10_pinball:.3f}  (ARF lower band as p10)")
    lines.append(
        f"     DM:                stat={new.dm_p10.statistic:.3f}, "
        f"p(one-sided)={new.dm_p10.p_value_one_sided:.4f}, "
        f"mean diff={new.dm_p10.mean_diff:.3f}"
    )
    lines.append("")
    lines.append(f"  4. Coverage / interval diagnostics  (descriptive, not a comparison)")
    lines.append(
        f"     LGBM lower-side coverage (target 0.90): {new.lgbm_lower_coverage:.3f}"
    )
    lines.append(
        f"     ARF lower-side coverage  (target 0.90): {new.arf_lower_coverage:.3f}"
    )
    lines.append(f"     LGBM Winkler IS (alpha=0.20):  {new.lgbm_winkler:.3f}")
    lines.append(f"     ARF Winkler IS (alpha=0.20):   {new.arf_winkler:.3f}")
    lines.append("")
    lines.append("=" * 78)
    text = "\n".join(lines)
    print(text)
    return text


def _precommitted_threshold_from_april2026() -> float:
    """Pre-committed twCRPS left-tail threshold = q05 of realised prices in
    April 2026 (the EXP-009 backtest window — a window distinct from the
    EXP-012 evaluation window 2026-05-14..2026-05-27).

    Defensibility: this is computed from a calendar period that precedes the
    evaluation window, so the threshold cannot have been chosen after seeing
    the evaluation outcomes. The earlier version of this script computed q05
    from the evaluation window itself, which broke pre-commitment and was
    flagged by code review.
    """
    import pandas as pd

    df = pd.read_parquet(REPO_ROOT / "ml" / "data" / "training_history.parquet")
    apr = df.loc[
        (df.index >= "2026-04-01") & (df.index < "2026-05-01"), "price_eur_mwh"
    ]
    if len(apr) < 100:
        raise RuntimeError(
            f"Pre-committed threshold needs April 2026 data; got n={len(apr)}. "
            f"Parquet must include April 2026."
        )
    return float(apr.quantile(0.05))


def main():
    paired = build_paired()
    if len(paired) == 0:
        print(f"FATAL: no paired observations in window {WINDOW_START}..{WINDOW_END}")
        print("Check that ml/forecasts/ has ARF archives for these dates and that")
        print("shadow_state.json:calibration_history covers them.")
        sys.exit(2)

    threshold = _precommitted_threshold_from_april2026()
    print(
        f"\nPre-committed twCRPS left-tail threshold: q05(realised, April 2026) "
        f"= {threshold:.2f} EUR/MWh"
    )
    print(
        f"  (computed from a window distinct from the evaluation period "
        f"{WINDOW_START}..{WINDOW_END}; preserves pre-commitment)\n"
    )

    old = old_criterion_a(paired)
    new = compute_new_metrics(paired, threshold=threshold)

    text = print_report(paired, old, new)

    # Per-horizon breakdown
    print()
    print("Per-horizon split (paired observations by horizon_h from eval_day midnight UTC):")
    by_h = paired.copy()
    by_h["h_group"] = pd.cut(
        by_h["horizon_h"], bins=[0, 24, 48, 72, np.inf], labels=["h<=24", "24<h<=48", "48<h<=72", "h>72"]
    )
    by_h["lgbm_p10_pinball"] = pinball_loss(by_h["realized"].to_numpy(), by_h["p10"].to_numpy(), 0.10)
    by_h["arf_p10_pinball"] = pinball_loss(by_h["realized"].to_numpy(), by_h["arf_lower"].to_numpy(), 0.10)
    by_h["lgbm_abs"] = np.abs(by_h["realized"] - by_h["p50"])
    by_h["arf_abs"] = np.abs(by_h["realized"] - by_h["arf_point"])
    summary = by_h.groupby("h_group", observed=False).agg(
        n=("realized", "size"),
        n_low=("realized", lambda s: (s < LOW_PRICE_THRESHOLD).sum()),
        lgbm_p10_pin=("lgbm_p10_pinball", "mean"),
        arf_p10_pin=("arf_p10_pinball", "mean"),
        lgbm_mae=("lgbm_abs", "mean"),
        arf_mae=("arf_abs", "mean"),
    )
    print(summary.to_string())
    return paired, old, new, threshold, summary


if __name__ == "__main__":
    main()
