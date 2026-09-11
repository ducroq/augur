#!/usr/bin/env python3
"""EXP-037 post-hoc diagnostics — NOT pre-committed, and not a gate.

Written after EXP-037's pre-committed gates were read (G3 fired: the incumbent
is WORSE than the carry on cost regret). These answer "why", and check the one
way the headline could be an artifact of which column was scored. Kept in a
separate file so the pre-committed runner and its numbers stay untouched.

(a) FORECAST AMPLITUDE. Cost regret is invariant to level but not to shape. If
    a forecast flattens toward the conditional mean, its ranking degrades
    toward arbitrary while its MAE IMPROVES -- hedging is what minimising
    expected absolute error buys you. Measured as the mean within-block
    standard deviation of each forecast, against the realised series.

(b) SORTED vs RAW p50. `update_shadow.py:357` ships the row-sorted `p50` to the
    dashboard, which is what EXP-037 scored, and sorting can move it a long way
    (max |p50 - p50_raw| is ~50 EUR/MWh on this window). If the RAW tau=0.50
    output ranks materially better, that is a free product fix and not a model
    change, so it has to be checked before the finding is acted on.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from ml.shadow.metrics import diebold_mariano  # noqa: E402
from exp035_naive_floor import CONTEXTS, FM_PREDS, LGBM_PREDS, add_naive  # noqa: E402
from exp037_rank_metric import BLOCKS, HAC_LAGS, blocks_for  # noqa: E402

OUT = REPO / "ml" / "shadow" / "exp037_rank_metric" / "diagnostics.json"


def amplitude(df: pd.DataFrame, col: str) -> dict:
    out = {}
    for lab, lo, hi in BLOCKS:
        s = df[(df["horizon_h"] >= lo) & (df["horizon_h"] <= hi)]
        out[lab] = round(float(s.groupby("t0")[col].std().mean()), 3)
    return out


def main() -> None:
    price = pd.read_parquet(CONTEXTS).set_index(["t0", "timestamp_utc"])["price"]
    lgbm = add_naive(pd.read_parquet(LGBM_PREDS), price)
    fm = add_naive(pd.read_parquet(FM_PREDS), price)
    full = lgbm[lgbm["variant"] == "full"]

    diag = {
        "note": "post-hoc, not pre-committed; mechanism + one artifact check",
        "amplitude_eur_mwh": {
            "realised": amplitude(full, "realized"),
            "carry": amplitude(full, "naive"),
            "lgbm_full_p50": amplitude(full, "p50"),
            "lgbm_full_p50_raw": amplitude(full, "p50_raw"),
            "chronos_p50": amplitude(fm, "p50"),
        },
    }

    # (b) sorted vs raw, scored identically to the pre-committed runner.
    scored = {
        "carry": blocks_for(full, "naive"),
        "p50": blocks_for(full, "p50"),
        "p50_raw": blocks_for(full, "p50_raw"),
    }
    common = None
    for s in scored.values():
        keys = set(zip(s["t0"], s["block"]))
        common = keys if common is None else (common & keys)
    for k, s in scored.items():
        m = [(t, b) in common for t, b in zip(s["t0"], s["block"])]
        scored[k] = s[m].sort_values(["t0", "block"]).reset_index(drop=True)

    base = scored["carry"]
    diag["sorted_vs_raw"] = {"n_blocks": int(len(base))}
    for k, s in scored.items():
        row = {lab: round(float(s.loc[s["block"] == lab, "regret_k6"].mean()), 4)
               for lab, _, _ in BLOCKS}
        row["pooled"] = round(float(s["regret_k6"].mean()), 4)
        row["spearman"] = round(float(s["spearman"].mean()), 4)
        if k != "carry":
            dm = diebold_mariano(s["regret_k6"].to_numpy(),
                                 base["regret_k6"].to_numpy(), hac_lags=HAC_LAGS)
            row["advantage_vs_carry"] = round(
                float(base["regret_k6"].mean() - s["regret_k6"].mean()), 4)
            row["dm_p_one_sided"] = round(float(dm.p_value_one_sided), 6)
        diag["sorted_vs_raw"][k] = row

    OUT.write_text(json.dumps(diag, indent=2))

    a = diag["amplitude_eur_mwh"]
    print("(a) within-block forecast spread, EUR/MWh — shape, not level")
    print(f"{'series':<22}" + "".join(f"{lab:>9}" for lab, _, _ in BLOCKS))
    for k, v in a.items():
        print(f"{k:<22}" + "".join(f"{v[lab]:>9.2f}" for lab, _, _ in BLOCKS))
    print("\n(b) does the dashboard ship the worse column? regret k=6, EUR/MWh")
    sv = diag["sorted_vs_raw"]
    print(f"{'column':<22}" + "".join(f"{lab:>9}" for lab, _, _ in BLOCKS)
          + f"{'pooled':>9}{'vs carry':>10}{'rho':>7}")
    for k in ("carry", "p50", "p50_raw"):
        r = sv[k]
        adv = f"{r['advantage_vs_carry']:>+10.3f}" if "advantage_vs_carry" in r else f"{'-':>10}"
        print(f"{k:<22}" + "".join(f"{r[lab]:>9.3f}" for lab, _, _ in BLOCKS)
              + f"{r['pooled']:>9.3f}{adv}{r['spearman']:>7.3f}")
    print(f"\nWritten to {OUT}")


if __name__ == "__main__":
    main()
