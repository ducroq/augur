"""Cheap-hour cost regret per horizon block, logged nightly.

The product criterion (`docs/hypothesis-log.md` [2026-10-28]) judges a
forecaster by how well it picks the cheapest hours, per 24-slot horizon block,
against the EXP-036 profile floor. `eval_log.jsonl` cannot carry it: a day is
logged once, as soon as 24 hours are realised, so it only ever sees h1-24 --
the block where the incumbent is BEST. Hours 25-72, where EXP-037 found the
amplitude collapse, were never scored live.

This pass reads `calibration_history` (all 72 horizons once realised, but a
rolling 30-day window), scores every complete block not yet in
`regret_log.jsonl`, and appends one row per (date, block). Running it nightly
keeps blocks from rolling off unscored. To backfill older vintages, point
`--state` at an earlier committed `shadow_state.json`
(`git show <commit>:ml/models/shadow/shadow_state.json`); rows already logged
are skipped, so overlapping states are safe.

Arms, each on the SAME 24 slots:
- ``lightgbm``: the sorted ``p50`` the dashboard ships (EXP-037 scored this
  one; its raw twin ranks the same, diagnostics.json ``sorted_vs_raw``).
- ``naive``: the single-day carry (`naive_source_timestamp`).
- ``profile``: the EXP-036 floor (`naive_profile_prediction`).
A baseline missing any of the 24 slots gets null fields: a ranking over fewer
slots is a different decision, so it is never padded.

A block that is still short of 24 realised slots FINAL_AFTER_H after its last
hour (by the data's own clock, the latest realised hour in the history) will
never complete -- usually a withheld or non-ENTSO-E hour. It is logged once as
``incomplete: true`` with its slot count, so the loss is visible and countable
rather than a silently missing row, and it is not re-scored nightly.

Runs as its own step in `scripts/daily_update.sh`; a non-zero exit becomes an
``[ALARM: regret pass failed]`` marker in the commit subject.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from ml.shadow.evaluate_shadow import (
    DEFAULT_PARQUET,
    DEFAULT_SHADOW_DIR,
    SHADOW_STATE_FILENAME,
    load_holiday_dates,
    load_price_history,
    load_shadow_state,
    naive_profile_prediction,
    naive_source_timestamp,
    t0_for_eval_day,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_REGRET_LOG = _REPO_ROOT / "ml" / "shadow" / "regret_log.jsonl"

# EXP-037's decision geometry. pick/score_block are copied from
# scripts/exp037_rank_metric.py rather than imported (ml/ never imports
# scripts/); tests/test_regret.py pins the two copies to identical output.
KS = (3, 6)
BLOCKS = (("h1_24", 1, 24), ("h25_48", 25, 48), ("h49_72", 49, 72))
SLOTS = 24
ARMS = ("lightgbm", "naive", "profile")
FINAL_AFTER_H = 48


def pick(pred: np.ndarray, k: int) -> np.ndarray:
    """Indices of the k cheapest slots, ties broken by earlier timestamp."""
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
    rp = pd.Series(pred).rank().to_numpy()
    rr = pd.Series(realized).rank().to_numpy()
    out["spearman"] = float(np.corrcoef(rp, rr)[0, 1]) if rp.std() > 0 else np.nan
    return out


def _r(x: float | None, n: int = 4) -> float | None:
    return None if x is None or pd.isna(x) else round(float(x), n)


def score_vintage(
    eval_day: str,
    calibration_history: list[dict],
    price_history: pd.Series | None,
    holiday_dates: set | None,
) -> list[dict]:
    """One row per complete block of one vintage. Empty if the anchor is unknown.

    The anchor comes from `t0_for_eval_day`, which returns None rather than
    guess; without it the horizon of every row is unknown, so no block can be
    assigned and the vintage is skipped, not mis-blocked.
    """
    t0 = t0_for_eval_day(calibration_history, eval_day)
    if t0 is None:
        return []
    clock = max(
        (pd.Timestamp(r["timestamp_utc"]) for r in calibration_history
         if r.get("realized") is not None and r.get("timestamp_utc")),
        default=None,
    )
    rows = [
        r for r in calibration_history
        if r.get("eval_day") == eval_day and r.get("realized") is not None
    ]
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    df = df.sort_values("timestamp_utc").reset_index(drop=True)
    df["horizon_h"] = ((df["timestamp_utc"] - t0).dt.total_seconds() / 3600).round().astype(int)

    prices = price_history.to_dict() if price_history is not None else None
    out: list[dict] = []
    for label, lo, hi in BLOCKS:
        g = df[(df["horizon_h"] >= lo) & (df["horizon_h"] <= hi)]
        if len(g) != SLOTS:
            # Partial: never padded. Logged once it can no longer complete.
            block_end = t0 + pd.Timedelta(hours=hi)
            if clock is not None and clock >= block_end + pd.Timedelta(hours=FINAL_AFTER_H):
                out.append({"date": eval_day, "t0_utc": t0.isoformat(), "block": label,
                            "incomplete": True, "n_slots": int(len(g))})
            continue
        realized = g["realized"].to_numpy(dtype=float)
        preds: dict[str, np.ndarray | None] = {"lightgbm": g["p50"].to_numpy(dtype=float)}
        if prices is not None:
            carry = [prices.get(naive_source_timestamp(ts, t0)) for ts in g["timestamp_utc"]]
            preds["naive"] = None if any(v is None for v in carry) else np.array(carry, float)
            if holiday_dates is not None:
                prof = [naive_profile_prediction(ts, t0, prices, holiday_dates)
                        for ts in g["timestamp_utc"]]
                preds["profile"] = None if any(v is None for v in prof) else np.array(prof, float)

        row = {
            "date": eval_day,
            "t0_utc": t0.isoformat(),
            "block": label,
            "n_slots": SLOTS,
            "mean_price": _r(realized.mean(), 3),
            "realised_amplitude": _r(realized.std(ddof=1), 3),
            "lightgbm_amplitude": _r(preds["lightgbm"].std(ddof=1), 3),
        }
        for arm in ARMS:
            p = preds.get(arm)
            s = score_block(p, realized) if p is not None else {}
            for key in ("regret_k3", "regret_k6", "hit_k6", "spearman"):
                row[f"{arm}_{key}"] = _r(s.get(key))
        out.append(row)
    return out


def read_logged_keys(log_path: Path) -> set[tuple[str, str]]:
    if not log_path.exists():
        return set()
    keys: set[tuple[str, str]] = set()
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed regret_log line: %r", line[:60])
                continue
            keys.add((row.get("date"), row.get("block")))
    return keys


def run_regret(
    state_path: Path = DEFAULT_SHADOW_DIR / SHADOW_STATE_FILENAME,
    parquet_path: Path = DEFAULT_PARQUET,
    log_path: Path = DEFAULT_REGRET_LOG,
) -> list[dict]:
    """Append every newly complete (date, block). Returns the rows appended."""
    history = load_shadow_state(state_path)["calibration_history"]
    logged = read_logged_keys(log_path)
    days = sorted({r["eval_day"] for r in history if r.get("eval_day")})
    pending = [d for d in days if any((d, b[0]) not in logged for b in BLOCKS)]
    if not pending:
        logger.info("No new regret blocks.")
        return []

    price_history = load_price_history(parquet_path)
    holiday_dates = load_holiday_dates(parquet_path)
    appended: list[dict] = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # A crash mid-write leaves a final line with no newline; appending onto it
    # would weld tonight's first row to it and make both unreadable.
    torn = log_path.exists() and log_path.stat().st_size > 0 and \
        log_path.read_bytes()[-1:] != b"\n"
    with open(log_path, "a") as f:
        if torn:
            f.write("\n")
        for day in pending:
            for row in score_vintage(day, history, price_history, holiday_dates):
                if (row["date"], row["block"]) in logged:
                    continue
                f.write(json.dumps(row) + "\n")
                appended.append(row)
    logger.info("Logged %d regret block(s)", len(appended))
    return appended


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", default=str(DEFAULT_SHADOW_DIR / SHADOW_STATE_FILENAME))
    ap.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    ap.add_argument("--regret-log", default=str(DEFAULT_REGRET_LOG))
    args = ap.parse_args()
    run_regret(Path(args.state), Path(args.parquet), Path(args.regret_log))


if __name__ == "__main__":
    main()
