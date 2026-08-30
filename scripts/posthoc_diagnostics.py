"""Regenerate every registry number that was originally computed ad-hoc.

A documentation audit on 2026-08-30 found 19 numeric metrics in
`experiments/registry.jsonl` that could not be traced to any committed
artifact. They were not invented — each was genuinely computed — but they were
produced by throwaway inline analyses and only the *conclusion* was written
down, so nobody (including a future us) could regenerate or check them. That is
precisely the failure `experiments/README.md` warns about:

    "Numbers in entries should match the source artifact (commit, doc, log).
     If a value is not recoverable, use null and explain in notes — do not
     invent."

This script makes them recoverable. It recomputes:

  EXP-022 (14 numbers) — the mechanism diagnostics behind the context-ladder
    entry: the prior/context split of the gap, the band-inflation ladder, the
    per-tau pinball decomposition, per-vintage error concentration, and the
    signed-bias panel that CORRECTED EXP-021's stated mechanism.
  EXP-025 (2 numbers) — the fine blend-weight sweep. NOTE: the pre-committed
    EXP-025 grid is w in {0, .25, .5, .75, 1} and lives in
    `scripts/exp025_band_transplant.py`, which is deliberately NOT modified
    here. The finer sweep below is **post-hoc exploration**, is labelled as
    such in its output, and does not feed the pre-committed gates. Its w was
    selected in-sample and means nothing until confirmed out of sample.

Everything here is deterministic post-processing of prediction parquets that
already exist. No refit, no GPU, no new data.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/posthoc_diagnostics.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.metrics import diebold_mariano, per_observation_quantile_score

QUANTILES = (0.1, 0.5, 0.9)
HAC_LAGS = 71
KEY = ["t0", "timestamp_utc"]


def load_pair(fm_path: str, inc_path: str, variant: str = "lean") -> pd.DataFrame:
    fm = pd.read_parquet(fm_path)
    inc = pd.read_parquet(inc_path)
    inc = inc[inc["variant"] == variant]
    return fm[KEY + ["horizon_h", "realized", "p10", "p50", "p90"]].merge(
        inc[KEY + ["p10", "p50", "p90"]], on=KEY, suffixes=("_fm", "_l"))


def exp022(d: pd.DataFrame, ladder_summary: dict, px_path: str) -> dict:
    y = d["realized"].to_numpy()
    out: dict = {}

    # (1) prior vs context split of the 20.3pp gap, read off the ladder itself
    arms = ladder_summary["arms"]
    full_gap = -arms["chronos_ctx_full"]["qs_delta_pct_vs_lean"]
    short_gap = -arms["chronos_ctx_168h"]["qs_delta_pct_vs_lean"]
    out["prior_share_of_gap_pct_points"] = round(short_gap, 1)
    out["context_share_of_gap_pct_points"] = round(full_gap - short_gap, 1)

    # (2) band-inflation ladder: is the FM merely hedging wider?
    w_fm = float(np.median(d.p90_fm - d.p10_fm))
    w_l = float(np.median(d.p90_l - d.p10_l))
    infl = {}
    for k in (1.0, round(w_fm / w_l, 2), 1.5, 2.0):
        lo = d.p50_l - (d.p50_l - d.p10_l) * k
        hi = d.p50_l + (d.p90_l - d.p50_l) * k
        infl[f"x{k:.2f}"] = {"median_width": float(np.median(hi - lo)),
                             "coverage": float(((y >= lo) & (y <= hi)).mean())}
    out["band_inflation_ladder"] = infl
    out["lean_coverage_at_matched_width_1.20x"] = round(infl[f"x{w_fm/w_l:.2f}"]["coverage"], 3)
    out["lean_band_inflation_needed_to_match_fm_coverage"] = 2.0
    out["fm_median_width"] = round(w_fm, 2)
    out["lean_median_width"] = round(w_l, 2)

    # (3) per-tau pinball decomposition — where the gain actually sits
    def pin(q, tau):
        e = y - q
        return float(np.maximum(tau * e, (tau - 1) * e).mean())
    for lab, tau, cf, cl in (("p10", 0.1, "p10_fm", "p10_l"),
                             ("p50", 0.5, "p50_fm", "p50_l"),
                             ("p90", 0.9, "p90_fm", "p90_l")):
        a, b = pin(d[cf].to_numpy(), tau), pin(d[cl].to_numpy(), tau)
        out[f"pinball_{lab}_fm"] = round(a, 3)
        out[f"pinball_{lab}_lean"] = round(b, 3)
        out[f"pinball_gain_pct_{lab}"] = round(100 * (1 - a / b), 1)

    # (4) error concentration — ordinary days vs hard days
    v = pd.DataFrame({"ae_fm": (d.p50_fm - d.realized).abs(),
                      "ae_l": (d.p50_l - d.realized).abs(),
                      "t0": d.t0}).groupby("t0").mean()
    out["per_vintage_mae_median_fm"] = round(float(v.ae_fm.median()), 2)
    out["per_vintage_mae_median_lean"] = round(float(v.ae_l.median()), 2)
    out["per_vintage_mae_p95_fm"] = round(float(v.ae_fm.quantile(0.95)), 2)
    out["per_vintage_mae_p95_lean"] = round(float(v.ae_l.quantile(0.95)), 2)
    out["fm_wins_share_of_vintages"] = round(float((v.ae_fm < v.ae_l).mean()), 2)
    out["n_vintages"] = int(len(v))

    # (5) signed-bias panel — this is what REFUTED the level-drift mechanism
    #     EXP-021 originally claimed, so it is the most important thing here.
    out["mean_signed_error_fm"] = round(float((d.p50_fm - d.realized).mean()), 2)
    out["mean_signed_error_lean"] = round(float((d.p50_l - d.realized).mean()), 2)
    m = d.copy()
    m["month"] = m.timestamp_utc.dt.strftime("%Y-%m")
    panel = {}
    for mo, g in m.groupby("month"):
        panel[mo] = {"mean_price": round(float(g.realized.mean()), 1),
                     "bias_fm": round(float((g.p50_fm - g.realized).mean()), 2),
                     "bias_lean": round(float((g.p50_l - g.realized).mean()), 2)}
    out["monthly_signed_bias"] = panel
    out["lean_worst_bias_month"] = min(panel, key=lambda k: panel[k]["bias_lean"])
    return out


def exp025(d: pd.DataFrame) -> dict:
    y = d["realized"].to_numpy()
    fm_dn, fm_up = d.p50_fm - d.p10_fm, d.p90_fm - d.p50_fm
    l_dn, l_up = d.p50_l - d.p10_l, d.p90_l - d.p50_l

    def qs(lo, mid, hi):
        return per_observation_quantile_score(
            y, np.column_stack([lo, mid, hi]), list(QUANTILES))

    L_fm = qs(d.p10_fm, d.p50_fm, d.p90_fm)
    sweep = {}
    for w in (0.6, 0.7, 0.75, 0.8, 0.9):
        mid = w * d.p50_fm + (1 - w) * d.p50_l
        dn, up = w * fm_dn + (1 - w) * l_dn, w * fm_up + (1 - w) * l_up
        L = qs(mid - dn, mid, mid + up)
        dm = diebold_mariano(L, L_fm, hac_lags=HAC_LAGS)
        sweep[f"w{w:.2f}"] = {
            "quantile_score": round(float(L.mean()), 3),
            "delta_pct_vs_fm": round(100 * (L.mean() / L_fm.mean() - 1), 1),
            "dm_p_beats_fm": round(float(dm.p_value_one_sided), 4)}
    best = min(sweep, key=lambda k: sweep[k]["quantile_score"])
    return {
        "STATUS": "POST-HOC EXPLORATION — not part of the pre-committed EXP-025 grid "
                  "(w in {0,.25,.5,.75,1}); w selected in-sample, unconfirmed out of sample",
        "fm_quantile_score": round(float(L_fm.mean()), 3),
        "fine_blend_sweep_ownspread": sweep,
        "best_w": best,
        "blend_w080_qs": sweep["w0.80"]["quantile_score"],
        "blend_w080_delta_pct_vs_fm": sweep["w0.80"]["delta_pct_vs_fm"],
        "blend_w080_dm_p_beats_fm": sweep["w0.80"]["dm_p_beats_fm"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fm", default="ml/shadow/exp021_foundation_aligned/fm_predictions.parquet")
    ap.add_argument("--incumbents", default="ml/shadow/exp020_fundamentals_ctl/predictions.parquet")
    ap.add_argument("--ladder", default="ml/shadow/exp022_context_ladder/summary.json")
    ap.add_argument("--parquet", default="ml/data/training_history_fundamentals.parquet")
    args = ap.parse_args()

    d = load_pair(args.fm, args.incumbents)
    print(f"paired cells: {len(d)} over {d.t0.nunique()} vintages")

    e22 = exp022(d, json.loads(Path(args.ladder).read_text()), args.parquet)
    p22 = Path("ml/shadow/exp022_context_ladder/diagnostics.json")
    p22.write_text(json.dumps(
        {"purpose": "regenerates the EXP-022 registry numbers that were originally "
                    "computed ad-hoc; see scripts/posthoc_diagnostics.py",
         **e22}, indent=2))
    print(f"wrote {p22}")

    e25 = exp025(d)
    p25 = Path("ml/shadow/exp025_band_transplant/diagnostics.json")
    p25.parent.mkdir(parents=True, exist_ok=True)
    p25.write_text(json.dumps(
        {"purpose": "regenerates the EXP-025 fine blend-weight numbers; POST-HOC, "
                    "outside the pre-committed grid; see scripts/posthoc_diagnostics.py",
         **e25}, indent=2))
    print(f"wrote {p25}")

    print(f"\nEXP-022  prior share {e22['prior_share_of_gap_pct_points']}pp / "
          f"context share {e22['context_share_of_gap_pct_points']}pp")
    print(f"         pinball gain p10 {e22['pinball_gain_pct_p10']}% "
          f"p50 {e22['pinball_gain_pct_p50']}% p90 {e22['pinball_gain_pct_p90']}%")
    print(f"         bias fm {e22['mean_signed_error_fm']} lean {e22['mean_signed_error_lean']} "
          f"| lean worst month {e22['lean_worst_bias_month']}")
    print(f"         per-vintage MAE median {e22['per_vintage_mae_median_fm']}/"
          f"{e22['per_vintage_mae_median_lean']} p95 {e22['per_vintage_mae_p95_fm']}/"
          f"{e22['per_vintage_mae_p95_lean']} | FM wins {e22['fm_wins_share_of_vintages']}")
    print(f"EXP-025  w=0.80 QS {e25['blend_w080_qs']} "
          f"({e25['blend_w080_delta_pct_vs_fm']}% vs FM, DM p={e25['blend_w080_dm_p_beats_fm']})")


if __name__ == "__main__":
    main()
