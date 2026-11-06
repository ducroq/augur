#!/usr/bin/env python3
"""Replay CQR on unwidened scores against the bands production delivered.

Pre-commitment: docs/hypothesis-log.md [2026-11-06]. Guardrail: lower-side and
upper-side coverage each no more than 0.02 below delivered. Winkler and width
are descriptive only (ADR-007). Host: situla, CPU, seconds per run.

calibration_history is capped at 30 days, so the record is rebuilt from every
committed ml/models/shadow/shadow_state.json. q for an eval day uses only rows
with target timestamps before that day. Realised prices that arrived late are
used as if on time, which moved q on 8 of 129 days and coverage by under 0.001.

Coverage is pooled over rows, not a mean of daily values. Numbers quoted in the
docs are at --rev acb1a5b, the last committed state when this was written.

    .venv/bin/python scripts/replay_cqr_unwidened.py --rev acb1a5b
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.shadow.conformal import DEFAULT_CALIB_DAYS, apply_cqr  # noqa: E402
from ml.shadow.metrics import winkler_interval_score  # noqa: E402

STATE = "ml/models/shadow/shadow_state.json"
SINCE = "2026-05-29"  # *_raw fields exist from here


def load_history(rev: str) -> pd.DataFrame:
    commits = subprocess.check_output(
        ["git", "log", f"--since={SINCE}", "--reverse", "--format=%h", rev, "--", STATE],
        text=True,
    ).split()
    rows = {}
    for commit in commits:
        shown = subprocess.run(
            ["git", "show", f"{commit}:{STATE}"], capture_output=True, text=True
        )
        if shown.returncode:
            continue
        for row in json.loads(shown.stdout).get("calibration_history", []):
            rows[(row["timestamp_utc"], row["eval_day"])] = row
    df = pd.DataFrame(rows.values())
    return df.dropna(subset=["p10_raw", "p50_raw", "p90_raw", "realized"])


def score(y, lo, hi) -> dict:
    return {
        "band": float(((y >= lo) & (y <= hi)).mean()),
        "lower": float((y >= lo).mean()),
        "upper": float((y <= hi).mean()),
        "median_width": float(np.median(hi - lo)),
        "winkler": float(winkler_interval_score(y, lo, hi, alpha=0.20).mean()),
    }


def report(label: str, delivered: pd.DataFrame, replay: pd.DataFrame) -> dict:
    a = score(
        delivered["realized"].to_numpy(),
        delivered["p10"].to_numpy(),
        delivered["p90"].to_numpy(),
    )
    b = score(
        replay["realized"].to_numpy(),
        replay["p10_cqr"].to_numpy(),
        replay["p90_cqr"].to_numpy(),
    )
    print(f"\n{label}: {delivered.eval_day.nunique()} eval days, {len(delivered)} rows")
    print(pd.DataFrame({"delivered": a, "replay": b}).round(3).to_string())
    return {"delivered": a, "replay": b}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rev", default="HEAD", help="last revision to read state from")
    rev = parser.parse_args().rev
    df = load_history(rev)
    raw = df[["p10_raw", "p50_raw", "p90_raw"]]
    unwidened = df.assign(p10=raw.min(axis=1), p90=raw.max(axis=1))
    out = apply_cqr(unwidened, calib_days=DEFAULT_CALIB_DAYS, target_coverage=0.80)
    days = sorted(df["eval_day"].unique())[DEFAULT_CALIB_DAYS:]
    keep_df, keep_out = df[df.eval_day.isin(days)], out[out.eval_day.isin(days)]
    print(f"rev {rev}, {days[0]}..{days[-1]}")

    result = report("all", keep_df, keep_out)
    for label, start in (("since anchor shift", "2026-09-13"), ("November", "2026-11-01")):
        report(label, keep_df[keep_df.eval_day >= start], keep_out[keep_out.eval_day >= start])

    q_fix = keep_out.groupby("eval_day")["cqr_q"].first()
    q_old = (unwidened["p10"] - df["p10"]).groupby(df["eval_day"]).mean().loc[q_fix.index]
    print(f"\nmean q {q_old.mean():.1f} -> {q_fix.mean():.1f}")
    print(f"days with q < 1: {(q_old < 1).sum()} -> {(q_fix < 1).sum()}")

    # True by construction: the replay's q is never below the q delivered, so the
    # bands nest. See the 2026-11-06 note in the hypothesis-log entry.
    ok = all(
        result["replay"][side] >= result["delivered"][side] - 0.02
        for side in ("lower", "upper")
    )
    print("GUARDRAIL", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
