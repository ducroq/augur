"""EXP-041: Chronos-Bolt against the profile rule, the dashboard's incumbent, on live vintages.

Pre-commitment: `docs/experiment-backlog.md` EXP-041 (2026-11-08, pinned in
`scripts/audit_registry.py:PRECOMMIT_REV_BY_ID`). That Method governs, and this
script implements it. Written 2026-11-08, before any qualifying FM vintage
existed. Host: situla, CPU, minutes; reads committed state and git history only.

**No interim read.** Until the population holds 14 vintages, the script reports
the count and exits without computing a gate, a loss or a coverage. Use
`--count-only` for the count alone (`scripts/vintage_counts.py` does).

Operational readings of the Method, fixed here before any data, not edits to it:
- "The daily commit for that `eval_day`": the profile JSON is matched on its
  `metadata.t0`, the Method's binding condition. A vintage's `eval_day` is the
  UTC date of its `t0`, and the run that produces it is dated the day before,
  so the commit is the last `Daily update …` commit whose
  `augur_forecast_profile.json` has `metadata.t0` equal to the vintage's
  `t0_utc`. Manual commits never count.
- Timestamps are compared as instants (parsed to UTC), not as strings.
- "First 14 in date order": ascending `t0_utc`.
- The LightGBM report uses the population vintages that also meet the
  [2026-11-07] pairing: production's `calibration_history` holds the same 72
  unique timestamps, all realised, for the same `eval_day`.

CLI:
    PYTHONPATH=. .venv/bin/python scripts/exp041_fm_vs_profile.py --count-only
    PYTHONPATH=. .venv/bin/python scripts/exp041_fm_vs_profile.py   # the read, once 14 exist
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

N_VINTAGES = 14
HOURS = 72
HAC_LAGS = 71
ALPHA = 0.10
GUARDRAIL = 0.02
PROFILE_PATH = "static/data/augur_forecast_profile.json"
OUT = Path("ml/shadow/exp041_fm_vs_profile/summary.json")


def ts(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def realised_by_day(history: list[dict]) -> dict[str, dict[datetime, dict]]:
    """eval_day -> {instant: row}, last row per key, only fully realised vintages."""
    by: dict[str, dict[datetime, dict]] = {}
    for r in history:
        by.setdefault(r["eval_day"], {})[ts(r["timestamp_utc"])] = r
    return {d: rows for d, rows in by.items()
            if len(rows) == HOURS and all(r.get("realized") is not None for r in rows.values())}


def shipped_profiles(repo: str = ".") -> dict[datetime, dict]:
    """t0 -> the profile JSON from the last `Daily update` commit that shipped it."""
    log = subprocess.run(
        ["git", "-C", repo, "log", "--reverse", "--format=%H%x09%s", "--", PROFILE_PATH],
        capture_output=True, text=True, check=True).stdout
    out: dict[datetime, dict] = {}
    for line in log.splitlines():
        sha, subject = line.split("\t", 1)
        if not subject.startswith("Daily update"):
            continue
        r = subprocess.run(["git", "-C", repo, "show", f"{sha}:{PROFILE_PATH}"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            continue
        doc = json.loads(r.stdout)
        out[ts(doc["metadata"]["t0"])] = doc  # later commits win
    return out


def population(fm_hist: list[dict], profiles: dict[datetime, dict]):
    """(counted vintages, excluded-for-(b) eval_days), each counted vintage as
    (eval_day, t0, fm rows by instant, profile doc). Capped at N_VINTAGES."""
    fm = realised_by_day(fm_hist)
    days = sorted(
        (d for d, rows in fm.items()
         if all((r.get("cqr_n_calib_days") or 0) >= 3 for r in rows.values())),
        key=lambda d: ts(next(iter(fm[d].values()))["t0_utc"]))
    counted, excluded = [], []
    for d in days:
        if len(counted) == N_VINTAGES:
            break
        rows = fm[d]
        t0 = ts(next(iter(rows.values()))["t0_utc"])
        doc = profiles.get(t0)
        ok = doc is not None and all(
            set(map(ts, doc.get(k) or {})) >= set(rows) for k in ("forecast", "forecast_lower", "forecast_upper"))
        (counted if ok else excluded).append((d, t0, rows, doc) if ok else d)
    return counted, excluded


def arrays(vintages, pick):
    """Concatenate per-observation values ordered by t0, then horizon."""
    return np.array([pick(rows[k], doc, k) for _, _, rows, doc in vintages for k in sorted(rows)], dtype=float)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fm-state", default="ml/models/shadow/fm_state.json")
    ap.add_argument("--shadow-state", default="ml/models/shadow/shadow_state.json")
    ap.add_argument("--count-only", action="store_true")
    a = ap.parse_args()

    fm_hist = json.loads(Path(a.fm_state).read_text())["calibration_history"]
    counted, excluded = population(fm_hist, shipped_profiles())
    print(f"EXP-041 population: {len(counted)} of {N_VINTAGES}; "
          f"excluded for no shipped profile: {excluded or 'none'}")
    if a.count_only or len(counted) < N_VINTAGES:
        if not a.count_only:
            print("Fewer than 14 vintages: no read (pre-committed, no interim look).")
        return 0

    from ml.shadow.metrics import diebold_mariano, lower_side_coverage, winkler_interval_score

    def prof(doc, field, k):
        return {ts(t): v for t, v in doc[field].items()}[k]

    y = arrays(counted, lambda r, d, k: r["realized"])
    fm_p50 = arrays(counted, lambda r, d, k: r["p50"])
    fm_lo = arrays(counted, lambda r, d, k: r["p10"])
    fm_hi = arrays(counted, lambda r, d, k: r["p90"])
    pr_p50 = arrays(counted, lambda r, d, k: prof(d, "forecast", k))
    pr_lo = arrays(counted, lambda r, d, k: prof(d, "forecast_lower", k))
    pr_hi = arrays(counted, lambda r, d, k: prof(d, "forecast_upper", k))

    dm = diebold_mariano(np.abs(y - fm_p50), np.abs(y - pr_p50), hac_lags=HAC_LAGS)
    skill_pass = dm.mean_diff < 0 and dm.p_value_one_sided < ALPHA
    cov = {
        "fm_lower": lower_side_coverage(y, fm_lo), "fm_upper": float((y <= fm_hi).mean()),
        "profile_lower": lower_side_coverage(y, pr_lo), "profile_upper": float((y <= pr_hi).mean()),
    }
    blocked = (cov["fm_lower"] < cov["profile_lower"] - GUARDRAIL
               or cov["fm_upper"] < cov["profile_upper"] - GUARDRAIL)

    # Reported, not gated: LightGBM on the vintages that also meet the [2026-11-07] pairing.
    prod = realised_by_day(json.loads(Path(a.shadow_state).read_text())["calibration_history"])
    paired = [v for v in counted if v[0] in prod and set(prod[v[0]]) == set(v[2])]
    lgbm = None
    if paired:
        yl = arrays(paired, lambda r, d, k: r["realized"])
        lg = np.array([prod[dd][k]["p50"] for dd, _, rows, _ in paired for k in sorted(rows)])
        fl = arrays(paired, lambda r, d, k: r["p50"])
        dml = diebold_mariano(np.abs(yl - fl), np.abs(yl - lg), hac_lags=HAC_LAGS)
        lgbm = {"n_vintages": len(paired), "dm_mean_diff": dml.mean_diff,
                "dm_p_one_sided": dml.p_value_one_sided,
                "lgbm_lower": lower_side_coverage(yl, np.array([prod[dd][k]["p10"] for dd, _, rows, _ in paired for k in sorted(rows)])),
                "lgbm_upper": float((yl <= np.array([prod[dd][k]["p90"] for dd, _, rows, _ in paired for k in sorted(rows)])).mean())}

    summary = {
        "experiment": "EXP-041",
        "vintages": [d for d, *_ in counted],
        "excluded_no_shipped_profile": excluded,
        "n_obs": int(len(y)),
        "skill_gate": {"dm_mean_diff": dm.mean_diff, "dm_statistic": dm.statistic,
                       "dm_p_one_sided": dm.p_value_one_sided, "hac_lags": HAC_LAGS,
                       "verdict": "PASS" if skill_pass else "FAIL"},
        "guardrail": {**cov, "verdict": "BLOCK" if blocked else "PASS"},
        "descriptive": {
            "fm_mae": float(np.abs(y - fm_p50).mean()), "profile_mae": float(np.abs(y - pr_p50).mean()),
            "fm_winkler": float(winkler_interval_score(y, fm_lo, fm_hi).mean()),
            "profile_winkler": float(winkler_interval_score(y, pr_lo, pr_hi).mean()),
            "fm_median_width": float(np.median(fm_hi - fm_lo)),
            "profile_median_width": float(np.median(pr_hi - pr_lo)),
            "n_holiday_fallback_hours": {d: doc["metadata"].get("n_holiday_fallback_hours")
                                         for d, _, _, doc in counted},
        },
        "lightgbm_reported_not_gated": lgbm,
        "note": "Swap also needs EXP-021a Stage 1 and the [2026-10-28] product criterion; not computed here.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("skill_gate", "guardrail")}, indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
