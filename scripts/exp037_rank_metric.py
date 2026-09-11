#!/usr/bin/env python3
"""EXP-037: does the model pick the cheap hours, even where it misses the level?

Why this exists
---------------
augur#29 measures MAE. Augur does not exist to state prices -- it exists so a
heat pump, an EV or an industrial thermal load runs during the cheap hours.
That is a RANKING problem within a day, and it is invariant to exactly the
error the incumbent is known to make: a forecast biased 20 EUR/MWh low for a
whole day has a terrible MAE and a perfect ranking.

`docs/hypothesis-log.md` [2026-09-06] names this as Alternative 3 and instructs
that it be run *before acting* on whichever verdict bucket lands. The method is
pre-committed in `docs/experiment-backlog.md` (EXP-037, 2026-09-11) and pinned
by `scripts/audit_registry.py`.

What it measures
----------------
COST REGRET, in EUR/MWh. Within a 24-slot decision block, each forecaster ranks
the hours by its own p50 and picks the cheapest k. Regret is the mean REALISED
price over the hours it picked, minus the mean realised price over the k truly
cheapest hours. Zero is perfect foresight, it can never be negative, and it is
denominated in the unit the user actually pays. It is the metric, not a proxy
for one.

Hit rate and Spearman rho are reported because they are interpretable, but they
decide nothing: missing the third-cheapest hour by 0.1 EUR/MWh is a hit-rate
miss and not a loss.

The baseline is imported from EXP-035 rather than reimplemented, so the carry is
bit-identical to the one augur#29's floor is measured against.

Usage
-----
    python scripts/exp037_rank_metric.py
    python scripts/exp037_rank_metric.py --out ml/shadow/exp037_rank_metric
"""

from __future__ import annotations

import argparse
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

# The observation here is a BLOCK, not an hour. Blocks from anchors more than
# three days apart share no realised hours, so the 71 used elsewhere in this
# project (max_horizon - 1, for hourly series) would be far too wide.
# Pre-committed at 3 before the series was seen.
HAC_LAGS = 3
KS = (3, 6)
BLOCKS = (("h1_24", 1, 24), ("h25_48", 25, 48), ("h49_72", 49, 72))
SLOTS = 24
MATERIALITY_EUR_MWH = 1.0   # G2


def block_label(h: int) -> str:
    for lab, lo, hi in BLOCKS:
        if lo <= h <= hi:
            return lab
    return ""


def pick(pred: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k cheapest slots, ties broken by earlier timestamp.

    Rows arrive sorted by timestamp, so a STABLE sort breaks ties that way for
    every arm identically -- np.argsort's default quicksort would not.
    """
    return np.argsort(pred, kind="stable")[:k]


def score_block(pred: np.ndarray, realized: np.ndarray) -> dict:
    """Regret, hit rate and rank correlation for one 24-slot decision."""
    out = {}
    for k in KS:
        chosen = pick(pred, k)
        oracle = pick(realized, k)
        out[f"regret_k{k}"] = float(realized[chosen].mean()
                                    - realized[oracle].mean())
        out[f"hit_k{k}"] = len(set(chosen.tolist()) & set(oracle.tolist())) / k
    # Spearman = Pearson on ranks; avoids a scipy dependency.
    rp = pd.Series(pred).rank().to_numpy()
    rr = pd.Series(realized).rank().to_numpy()
    out["spearman"] = float(np.corrcoef(rp, rr)[0, 1]) if rp.std() > 0 else np.nan
    return out


def blocks_for(df: pd.DataFrame, pred_col: str) -> pd.DataFrame:
    """One scored row per (t0, block) for a single arm."""
    d = df.copy()
    d["block"] = d["horizon_h"].map(block_label)
    d = d[d["block"] != ""]
    d = d.dropna(subset=[pred_col, "realized"])
    d = d.sort_values(["t0", "block", "timestamp_utc"])

    rows = []
    for (t0, blk), g in d.groupby(["t0", "block"], sort=False):
        if len(g) != SLOTS:
            continue          # partial block: dropped, never padded
        r = score_block(g[pred_col].to_numpy(), g["realized"].to_numpy())
        r.update(t0=t0, block=blk, mean_price=float(g["realized"].mean()))
        rows.append(r)
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="EXP-037 rank / cost-regret metric")
    ap.add_argument("--out", default=str(REPO / "ml" / "shadow" / "exp037_rank_metric"))
    args = ap.parse_args()

    price = pd.read_parquet(CONTEXTS).set_index(["t0", "timestamp_utc"])["price"]
    lgbm = add_naive(pd.read_parquet(LGBM_PREDS), price)
    fm = add_naive(pd.read_parquet(FM_PREDS), price)

    arms = {f"lgbm_{v}": d for v, d in lgbm.groupby("variant")}
    arms.update({f"fm_{v}": d for v, d in fm.groupby("variant")})

    # The carry is scored from any one arm's rows: `naive` is a property of
    # (t0, timestamp), identical across arms by construction.
    any_arm = next(iter(arms.values()))
    scored = {"naive": blocks_for(any_arm, "naive")}
    for name, d in arms.items():
        scored[name] = blocks_for(d, "p50")

    # G-hygiene: every arm scored on the identical surviving block set.
    common = None
    for s in scored.values():
        keys = set(zip(s["t0"], s["block"]))
        common = keys if common is None else (common & keys)
    for name, s in scored.items():
        mask = [(t, b) in common for t, b in zip(s["t0"], s["block"])]
        scored[name] = s[mask].sort_values(["t0", "block"]).reset_index(drop=True)

    base = scored["naive"]
    summary = {
        "precommit": "docs/experiment-backlog.md EXP-037 (2026-09-11), pinned 2e96bb9",
        "baseline": "single-day carry, 24*ceil(h/24), from the EXP-035 context tape",
        "hac_lags": HAC_LAGS,
        "materiality_eur_mwh": MATERIALITY_EUR_MWH,
        "n_blocks": int(len(base)),
        "n_vintages": int(base["t0"].nunique()),
        "window": [str(base["t0"].min()), str(base["t0"].max())],
        "naive": {}, "arms": {}, "monthly": {},
    }

    for lab, _, _ in BLOCKS:
        m = base["block"] == lab
        summary["naive"][lab] = {
            "n": int(m.sum()),
            **{f"regret_k{k}": round(float(base.loc[m, f"regret_k{k}"].mean()), 4)
               for k in KS},
            **{f"hit_k{k}": round(float(base.loc[m, f"hit_k{k}"].mean()), 4)
               for k in KS},
            "spearman": round(float(base.loc[m, "spearman"].mean()), 4),
        }
    summary["naive"]["pooled"] = {
        **{f"regret_k{k}": round(float(base[f"regret_k{k}"].mean()), 4) for k in KS},
        "spearman": round(float(base["spearman"].mean()), 4),
    }

    for name, s in sorted(scored.items()):
        if name == "naive":
            continue
        row: dict = {}
        for lab, _, _ in BLOCKS:
            m = s["block"] == lab
            row[lab] = {
                **{f"regret_k{k}": round(float(s.loc[m, f"regret_k{k}"].mean()), 4)
                   for k in KS},
                **{f"advantage_k{k}": round(
                    float(base.loc[m.to_numpy(), f"regret_k{k}"].mean()
                          - s.loc[m, f"regret_k{k}"].mean()), 4) for k in KS},
                **{f"hit_k{k}": round(float(s.loc[m, f"hit_k{k}"].mean()), 4)
                   for k in KS},
                "spearman": round(float(s.loc[m, "spearman"].mean()), 4),
            }
        for k in KS:
            adv = float(base[f"regret_k{k}"].mean() - s[f"regret_k{k}"].mean())
            dm = diebold_mariano(s[f"regret_k{k}"].to_numpy(),
                                 base[f"regret_k{k}"].to_numpy(),
                                 hac_lags=HAC_LAGS)
            row[f"pooled_k{k}"] = {
                "regret": round(float(s[f"regret_k{k}"].mean()), 4),
                "naive_regret": round(float(base[f"regret_k{k}"].mean()), 4),
                "advantage": round(adv, 4),
                "dm_statistic": round(float(dm.statistic), 4),
                "dm_p_one_sided": round(float(dm.p_value_one_sided), 6),
            }
        row["pooled_spearman"] = round(float(s["spearman"].mean()), 4)
        row["naive_pooled_spearman"] = round(float(base["spearman"].mean()), 4)
        summary["arms"][name] = row

        mo = s.assign(month=s["t0"].dt.tz_convert("UTC").dt.strftime("%Y-%m"))
        bm = base.assign(month=base["t0"].dt.tz_convert("UTC").dt.strftime("%Y-%m"))
        summary["monthly"][name] = {
            m: {
                "mean_price": round(float(g["mean_price"].mean()), 2),
                "regret_k6": round(float(g["regret_k6"].mean()), 3),
                "naive_regret_k6": round(float(bm.loc[bm["month"] == m, "regret_k6"].mean()), 3),
                "advantage_k6": round(
                    float(bm.loc[bm["month"] == m, "regret_k6"].mean()
                          - g["regret_k6"].mean()), 3),
            }
            for m, g in mo.groupby("month")
        }

    # --- pre-committed gates, evaluated mechanically -----------------------
    full = summary["arms"].get("lgbm_full", {})
    per_block_adv = [full[lab]["advantage_k6"] for lab, _, _ in BLOCKS]
    g1 = all(a > 0 for a in per_block_adv) and \
        full["pooled_k6"]["dm_p_one_sided"] < 0.10
    g2 = full["pooled_k6"]["advantage"] > MATERIALITY_EUR_MWH
    g3 = sum(1 for a in per_block_adv if a <= 0) >= 2
    summary["gates"] = {
        "G1_ranks_better_all_blocks_k6": bool(g1),
        "G1_per_block_advantage_k6": [round(a, 4) for a in per_block_adv],
        "G1_pooled_dm_p": full["pooled_k6"]["dm_p_one_sided"],
        "G2_material": bool(g2),
        "G2_pooled_advantage_eur_mwh": full["pooled_k6"]["advantage"],
        "G3_refuted": bool(g3),
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    print(f"blocks={summary['n_blocks']}  vintages={summary['n_vintages']}  "
          f"window={summary['window'][0][:10]}..{summary['window'][1][:10]}\n")
    print("cost regret at k=6, EUR/MWh (lower is better; 0 = perfect foresight)")
    print(f"{'arm':<24} {'h1-24':>8} {'h25-48':>8} {'h49-72':>8} "
          f"{'pooled':>8} {'vs carry':>9} {'DM p':>9} {'rho':>7}")
    n = summary["naive"]
    print(f"{'carry (baseline)':<24} {n['h1_24']['regret_k6']:>8.3f} "
          f"{n['h25_48']['regret_k6']:>8.3f} {n['h49_72']['regret_k6']:>8.3f} "
          f"{n['pooled']['regret_k6']:>8.3f} {'-':>9} {'-':>9} "
          f"{n['pooled']['spearman']:>7.3f}")
    for name, r in sorted(summary["arms"].items(),
                          key=lambda kv: -kv[1]["pooled_k6"]["advantage"]):
        print(f"{name:<24} {r['h1_24']['regret_k6']:>8.3f} "
              f"{r['h25_48']['regret_k6']:>8.3f} {r['h49_72']['regret_k6']:>8.3f} "
              f"{r['pooled_k6']['regret']:>8.3f} "
              f"{r['pooled_k6']['advantage']:>+9.3f} "
              f"{r['pooled_k6']['dm_p_one_sided']:>9.5f} "
              f"{r['pooled_spearman']:>7.3f}")
    print("\ngates (pre-committed 2026-09-11):")
    for k, v in summary["gates"].items():
        print(f"  {k:<34} {v}")
    print(f"\nWritten to {out_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
