"""EXP-025 — is the foundation model's calibration prior separable from its point forecast?

Pre-committed in `docs/experiment-backlog.md` (commit `4024420`, 2026-08-29),
promoted to `docs/hypothesis-log.md` on the run date. EXP-022 showed Chronos's
band advantage is a *pure pretrained prior*: coverage is flat at 0.811 / 0.804 /
0.813 / 0.823 across 56d / 28d / 14d / 7d contexts, so it does not depend on
information at all. If the spread prior is genuinely independent of the point
forecast, it should be transplantable — Chronos's *spread* wrapped around the
incumbent's *median*.

That matters operationally: it is the concrete form of the fallback EXP-021a
Stage 2 already contemplates. A pass gives augur#19 a fix needing no production
torch dependency — the FM runs offline, its spread is cached, the nightly path
stays LightGBM.

Arms (all on the same paired cells, no refit, no GPU):

    lean            incumbent, as-is                                (base)
    fm              Chronos-Bolt, as-is                             (reference)
    A_lean_fmspread incumbent median + FM spread                    PRIMARY
    B_fm_leanspread FM median + incumbent spread                    control
    C_blend_w*      weighted median blend x {own spread, FM spread}
    D_lean_cqr      incumbent + production CQR                      Alternative 3

Spread is transplanted as *asymmetric* half-widths (`p50-p10`, `p90-p50`) so the
skew of the source band is preserved rather than symmetrised.

Note on arm D: production's `compute_cqr_q` conformalises already-widened bands
(a feedback loop, standing finding in `memory/MEMORY.md`). This harness has no
widened bands to feed back, so arm D applies CQR once to the raw quantiles —
the *charitable* reading of production CQR. If even that does not reach the
transplant's coverage, Alternative 3 is refuted more strongly than a faithful
replication would refute it.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp025_band_transplant.py \
        --fm ml/shadow/exp021_foundation_aligned/fm_predictions.parquet \
        --incumbents ml/shadow/exp020_fundamentals_ctl/predictions.parquet \
        --out ml/shadow/exp025_band_transplant
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.conformal import apply_cqr
from ml.shadow.metrics import (
    diebold_mariano,
    per_observation_quantile_score,
    winkler_interval_score,
)

QUANTILES = (0.1, 0.5, 0.9)
HAC_LAGS = 71
BLEND_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)


def score_arm(y: np.ndarray, lo: np.ndarray, mid: np.ndarray, hi: np.ndarray) -> dict:
    q = np.column_stack([lo, mid, hi])
    qs = per_observation_quantile_score(y, q, list(QUANTILES))
    return {
        "mae": float(np.abs(mid - y).mean()),
        "quantile_score": float(qs.mean()),
        "coverage_lower": float((y >= lo).mean()),
        "coverage_upper": float((y <= hi).mean()),
        "coverage_band": float(((y >= lo) & (y <= hi)).mean()),
        "band_width_median": float(np.median(hi - lo)),
        "winkler": float(winkler_interval_score(y, lo, hi, alpha=0.20).mean()),
        "_loss": qs,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fm", default="ml/shadow/exp021_foundation_aligned/fm_predictions.parquet")
    ap.add_argument("--incumbents", default="ml/shadow/exp020_fundamentals_ctl/predictions.parquet")
    ap.add_argument("--out", default="ml/shadow/exp025_band_transplant")
    args = ap.parse_args()

    key = ["t0", "timestamp_utc"]
    fm = pd.read_parquet(args.fm)
    inc = pd.read_parquet(args.incumbents)
    lean = inc[inc["variant"] == "lean"]

    d = fm[key + ["horizon_h", "realized", "p10", "p50", "p90"]].merge(
        lean[key + ["p10", "p50", "p90"]], on=key, suffixes=("_fm", "_l")
    )
    if len(d) == 0:
        raise SystemExit("no paired cells — check the two prediction files")
    y = d["realized"].to_numpy()

    # Asymmetric half-widths, preserving each source's own skew.
    fm_dn, fm_up = d.p50_fm - d.p10_fm, d.p90_fm - d.p50_fm
    l_dn, l_up = d.p50_l - d.p10_l, d.p90_l - d.p50_l

    arms: dict[str, tuple] = {
        "lean": (d.p10_l, d.p50_l, d.p90_l),
        "fm": (d.p10_fm, d.p50_fm, d.p90_fm),
        "A_lean_fmspread": (d.p50_l - fm_dn, d.p50_l, d.p50_l + fm_up),
        "B_fm_leanspread": (d.p50_fm - l_dn, d.p50_fm, d.p50_fm + l_up),
    }
    for w in BLEND_WEIGHTS:
        mid = w * d.p50_fm + (1 - w) * d.p50_l
        arms[f"C_blend_w{w:.2f}_fmspread"] = (mid - fm_dn, mid, mid + fm_up)
        arms[f"C_blend_w{w:.2f}_ownspread"] = (mid - (w * fm_dn + (1 - w) * l_dn),
                                               mid,
                                               mid + (w * fm_up + (1 - w) * l_up))

    # Arm D — production CQR on the incumbent's raw quantiles. eval_day is the
    # vintage day, so calibration only ever sees strictly prior vintages.
    cq = d[key + ["realized"]].copy()
    cq["p10"], cq["p50"], cq["p90"] = d.p10_l, d.p50_l, d.p90_l
    cq["eval_day"] = pd.to_datetime(cq["t0"]).dt.strftime("%Y-%m-%d")
    cq = apply_cqr(cq).sort_values(key).reset_index(drop=True)
    dd = d.sort_values(key).reset_index(drop=True)
    assert (cq["timestamp_utc"].to_numpy() == dd["timestamp_utc"].to_numpy()).all()
    arms["D_lean_cqr"] = (cq.p10_cqr, cq.p50, cq.p90_cqr)
    y_d = dd["realized"].to_numpy()

    scored = {}
    for name, (lo, mid, hi) in arms.items():
        yy = y_d if name == "D_lean_cqr" else y
        scored[name] = score_arm(yy, np.asarray(lo), np.asarray(mid), np.asarray(hi))

    base, ref_fm = scored["lean"]["_loss"], scored["fm"]["_loss"]
    for name, e in scored.items():
        if name != "lean":
            dm = diebold_mariano(e["_loss"], base, hac_lags=HAC_LAGS)
            e["dm_beats_lean_p"] = float(dm.p_value_one_sided)
        e["qs_delta_pct_vs_lean"] = 100 * (e["quantile_score"] / scored["lean"]["quantile_score"] - 1)
        e["qs_delta_pct_vs_fm"] = 100 * (e["quantile_score"] / scored["fm"]["quantile_score"] - 1)
        e["coverage_side_gap"] = abs(e["coverage_lower"] - e["coverage_upper"])

    A, F, L = scored["A_lean_fmspread"], scored["fm"], scored["lean"]
    gates = {
        "gate_1_band_coverage_ge_0.76": A["coverage_band"] >= 0.76,
        "gate_2_side_gap_le_0.08": A["coverage_side_gap"] <= 0.08,
        "gate_3_qs_within_3pct_of_fm": A["qs_delta_pct_vs_fm"] <= 3.0,
        "gate_4_winkler_le_incumbent": A["winkler"] <= L["winkler"],
        "observed": {k: A[k] for k in
                     ("coverage_band", "coverage_side_gap", "qs_delta_pct_vs_fm", "winkler")},
        "incumbent_winkler": L["winkler"],
    }
    gates["ALL_PASS"] = all(v for k, v in gates.items() if k.startswith("gate_"))
    alt3 = {
        "cqr_band_coverage": scored["D_lean_cqr"]["coverage_band"],
        "transplant_band_coverage": A["coverage_band"],
        "cqr_reaches_transplant": scored["D_lean_cqr"]["coverage_band"] >= A["coverage_band"] - 0.02,
    }
    best_blend = min((k for k in scored if k.startswith("C_blend")),
                     key=lambda k: scored[k]["quantile_score"])
    alt2 = {"best_blend_arm": best_blend,
            "best_blend_qs": scored[best_blend]["quantile_score"],
            "beats_fm_alone": scored[best_blend]["quantile_score"] < F["quantile_score"]}

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    summary = {
        "config": {"fm": args.fm, "incumbents": args.incumbents, "hac_lags": HAC_LAGS,
                   "quantiles": list(QUANTILES), "n_paired_observations": int(len(d)),
                   "n_paired_vintages": int(d["t0"].nunique()),
                   "cqr_note": "applied once to raw quantiles — charitable vs production's widened-band feedback loop"},
        "arms": {k: {kk: vv for kk, vv in v.items() if kk != "_loss"} for k, v in scored.items()},
        "gates_primary_arm_A": gates,
        "alternative_2_weighted_blend": alt2,
        "alternative_3_cqr_comparator": alt3,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2))

    print(f"\n{'arm':<28}{'MAE':>8}{'QS':>8}{'dQS%vL':>9}{'cov_lo':>8}{'cov_hi':>8}{'band':>7}{'width':>8}{'Wink':>8}")
    for k, e in scored.items():
        print(f"{k:<28}{e['mae']:>8.2f}{e['quantile_score']:>8.2f}{e['qs_delta_pct_vs_lean']:>9.1f}"
              f"{e['coverage_lower']:>8.3f}{e['coverage_upper']:>8.3f}{e['coverage_band']:>7.3f}"
              f"{e['band_width_median']:>8.1f}{e['winkler']:>8.1f}")
    print("\nGATES (arm A = incumbent median + FM spread):")
    for k, v in gates.items():
        if k.startswith("gate_"): print(f"  {k:<34} {v}")
    print(f"  {'ALL_PASS':<34} {gates['ALL_PASS']}")
    print(f"\nAlt-2 best blend: {alt2['best_blend_arm']} QS {alt2['best_blend_qs']:.2f} "
          f"(beats FM alone: {alt2['beats_fm_alone']})")
    print(f"Alt-3 CQR comparator: lean+CQR band coverage {alt3['cqr_band_coverage']:.3f} vs "
          f"transplant {alt3['transplant_band_coverage']:.3f} -> CQR reaches it: {alt3['cqr_reaches_transplant']}")
    print(f"\nwrote {out/'summary.json'}")


if __name__ == "__main__":
    main()
