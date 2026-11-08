"""Count the vintages each open hypothesis-log trigger waits on.

`docs/hypothesis-log.md` used to carry hand counts in its `## Open` trigger table,
and they drifted: the 2026-11-06 count of "7 clean vintages" was eval-log days
(h1-24 only), while the Methods need fully realised 72-hour vintages, which
numbered 6. This prints the counts from committed state instead. It counts
vintages only and never computes a gate, so running it is not an interim read.

Print-only, with no committed render and no `--check`: the state changes every
night, so a committed render would be stale by the next daily commit.

Definitions (each from its entry's Method):
- fully realised: 72 unique `timestamp_utc` with a non-null `realized`, after
  keeping the last row per (`eval_day`, `timestamp_utc`). `eval_day` labels the
  vintage, one per `t0`.
- [2026-08-29] EXP-021a Stage 1: fully realised, `t0` >= 2026-10-30 (after
  EXP-038's window, which ends at `t0` 2026-10-28). Target 14.
- [2026-11-06] CQR live check: fully realised, `t0` >= 2026-11-06 22:00 UTC, the
  first run after the fix (4854b4e). Target 28.
- EXP-041 (the FM gate since 2026-11-08; also the [2026-10-28] product
  criterion's trigger): `scripts/exp041_fm_vs_profile.py:population`, imported
  so the definition lives in one place. FM vintages with live CQR, fully
  realised, with a shipped profile forecast on the same t0. Target 14.
- [2026-11-07] pairing with production, still printed: the population that
  entry defined, now used only for EXP-041's reported LightGBM comparison.

`calibration_history` keeps the 30 newest vintage days (`MAX_HISTORY_DAYS`).
The "room" column is how many more vintage days the history can add before the
oldest counted vintage drops out; at 0, read it before the next nightly run.

CLI:
    .venv/bin/python scripts/vintage_counts.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MAX_HISTORY_DAYS = 30  # mirrors ml/shadow/update_shadow.py
HOURS = 72


def realised_vintages(history: list[dict]) -> dict[str, dict[str, dict]]:
    """eval_day -> {timestamp_utc: row} for vintages with all 72 hours realised."""
    by_day: dict[str, dict[str, dict]] = {}
    for row in history:  # last row per key wins
        by_day.setdefault(row["eval_day"], {})[row["timestamp_utc"]] = row
    return {
        day: rows for day, rows in by_day.items()
        if len(rows) == HOURS and all(r.get("realized") is not None for r in rows.values())
    }


def room(history: list[dict], oldest_day: str | None) -> int | None:
    if oldest_day is None:
        return None
    days = {r["eval_day"] for r in history}
    return MAX_HISTORY_DAYS - sum(d >= oldest_day for d in days)


def count_t0_since(history: list[dict], t0_min: str) -> tuple[int, int | None]:
    full = realised_vintages(history)
    days = sorted(d for d, rows in full.items()
                  if next(iter(rows.values()))["t0_utc"] >= t0_min)
    return len(days), room(history, days[0] if days else None)


def count_fm_paired(fm_history: list[dict], prod_history: list[dict]) -> tuple[int, int | None]:
    fm, prod = realised_vintages(fm_history), realised_vintages(prod_history)
    days = sorted(
        d for d, rows in fm.items()
        if d in prod and set(rows) == set(prod[d])
        and all((r.get("cqr_n_calib_days") or 0) >= 3 for r in rows.values())
    )
    return len(days), room(fm_history, days[0] if days else None)


def count_exp041(fm_history: list[dict]) -> tuple[int, int | None, list[str]]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "exp041", Path(__file__).resolve().parent / "exp041_fm_vs_profile.py")
    exp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp)
    counted, excluded = exp.population(fm_history, exp.shipped_profiles())
    return len(counted), room(fm_history, counted[0][0] if counted else None), excluded


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--shadow-state", default="ml/models/shadow/shadow_state.json")
    ap.add_argument("--fm-state", default="ml/models/shadow/fm_state.json")
    ap.add_argument("--eval-log", default="ml/shadow/eval_log.jsonl")
    a = ap.parse_args()

    shadow = json.loads(Path(a.shadow_state).read_text())
    prod = shadow["calibration_history"]
    fm_path = Path(a.fm_state)
    fm = json.loads(fm_path.read_text())["calibration_history"] if fm_path.exists() else []
    eval_days = sorted({json.loads(l)["date"] for l in Path(a.eval_log).read_text().splitlines()
                        if l.strip()})

    rows = [
        ("[2026-08-29] EXP-021a Stage 1", *count_t0_since(prod, "2026-10-30"), 14),
        ("[2026-11-06] CQR live check", *count_t0_since(prod, "2026-11-06T22:00"), 28),
        ("[2026-11-07] FM paired with LightGBM (reported only)", *count_fm_paired(fm, prod), 14),
    ]
    n41, room41, excluded41 = count_exp041(fm)
    rows.insert(2, ("EXP-041 FM vs profile + [2026-10-28]", n41, room41, 14))
    print(f"State as of shadow run {shadow.get('last_run_utc', '?')}, last t0 {shadow.get('last_t0', '?')}")
    print(f"eval_log: {len(eval_days)} days ({eval_days[0] if eval_days else '-'} .. "
          f"{eval_days[-1] if eval_days else '-'}), h1-24 only, not vintages")
    print()
    print("| Entry | Fully realised vintages | Room in history |")
    print("|---|---|---|")
    for name, n, rm, target in rows:
        flag = " (read before the next run)" if rm == 0 else ""
        print(f"| {name} | {n} of {target} | {'-' if rm is None else rm}{flag} |")
    if excluded41:
        print(f"\nEXP-041 vintages excluded for no shipped profile forecast: {', '.join(excluded41)}")


if __name__ == "__main__":
    main()
