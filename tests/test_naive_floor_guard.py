"""Tests for the seasonal-naive floor reader in scripts/daily_update.sh.

The reader turns `lightgbm_skill_vs_naive` from a field nobody looks at into
the nightly signal for augur#29. It has to separate three different things that
all look like "no number tonight":

  * a LOSS          — the model is below the floor. A result, rides as NOTE.
  * an UNSCORED row — the row landed carrying no naive field at all, so the
                      instrument broke. A fault, rides as ALARM.
  * a DEGENERATE row (added 2026-09-11) — scored, but on too few paired hours
                      to weigh. Neither: reported, counted nowhere.

The third category exists because of the 2026-09-09 row. The baseline pairs
whatever hours it can find, and after the 2026-09-08..10 vintage damage that
was ONE hour, at horizon 25, scoring +0.762 — a single draw of a variable whose
daily MAE ranges over tens of EUR/MWh, standing as a full day beside 24-hour
rows, at a moment when only three scored rows existed at all. The verdict's
reading rule already refuses to average across spans, but the >=21 trigger that
admits the verdict counted rows, so a row could be counted in and then read out.

The block is executed as the shell really runs it, extracted from the script,
so a restructure fails here loudly instead of leaving these tests green against
code that no longer exists.
"""
import json
import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "daily_update.sh"

# From the floor's default through the last variable it sets.
BLOCK = re.compile(
    r'^MIN_NAIVE_HOURS=.*?^NAIVE_ELIGIBLE=[^\n]*\n', re.S | re.M)


def guard_source():
    m = BLOCK.search(SCRIPT.read_text())
    assert m, ("could not extract the naive-floor block from daily_update.sh — "
               "it was restructured; update this test rather than deleting it")
    block = m.group(0)
    # `assert m` only catches deletion. A reorder that moved NAIVE_ELIGIBLE=
    # above its siblings would still match, and quietly extract a shorter span
    # whose missing counters then read as empty rather than as a broken test.
    for var in ("NAIVE_N", "NAIVE_LOSSES", "NAIVE_UNSCORED",
                "NAIVE_DEGENERATE", "NAIVE_ELIGIBLE"):
        assert f"\n{var}=" in block, (
            f"{var} is not inside the extracted block — the guard was "
            "reordered and this test is now measuring the wrong span")
    return block


def run_guard(tmp_path, rows, min_hours=None):
    """Run the real block against a synthetic eval_log and read its counters."""
    log = tmp_path / "ml" / "shadow"
    log.mkdir(parents=True, exist_ok=True)
    (log / "eval_log.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows))
    env_line = f'MIN_NAIVE_HOURS={min_hours}\n' if min_hours is not None else ''
    script = (
        f'set -u\nAUGUR_DIR="{tmp_path}"\n{env_line}{guard_source()}'
        'echo "RESULT $NAIVE_N $NAIVE_LOSSES $NAIVE_UNSCORED '
        '$NAIVE_DEGENERATE $NAIVE_ELIGIBLE"\n')
    out = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    line = [l for l in out.stdout.splitlines() if l.startswith("RESULT")]
    assert line, f"guard produced no result: {out.stdout!r} {out.stderr!r}"
    n, losses, unscored, degen, eligible = map(int, line[-1].split()[1:])
    return dict(n=n, losses=losses, unscored=unscored,
                degenerate=degen, eligible=eligible)


def scored(date, skill, hours=24):
    return {"date": date, "lightgbm_mae": 30.0, "n_naive_hours": hours,
            "naive_mae": 30.0, "lightgbm_skill_vs_naive": skill}


def unscored_row(date):
    """An eval row from after the field existed that carries no score."""
    return {"date": date, "lightgbm_mae": 30.0, "n_naive_hours": 0,
            "naive_mae": None, "lightgbm_skill_vs_naive": None}


def legacy(date):
    """A pre-2026-09-06 row: the fields do not exist at all."""
    return {"date": date, "lightgbm_mae": 30.0, "arf_mae": 40.0}


class TestDegenerateRows:
    def test_thin_row_is_excluded_from_the_window(self, tmp_path):
        r = run_guard(tmp_path, [
            scored("2026-09-06", 0.3424),
            scored("2026-09-07", -0.0383),
            scored("2026-09-09", 0.762, hours=1),
        ])
        assert r["n"] == 2, "the 1-hour row must not count as a scored day"
        assert r["degenerate"] == 1
        assert r["losses"] == 1

    def test_thin_row_is_excluded_from_the_verdict_trigger(self, tmp_path):
        """The >=21 count and the window must agree on the population."""
        r = run_guard(tmp_path, [
            scored(f"2026-08-{d:02d}", 0.1) for d in range(1, 21)
        ] + [scored("2026-08-21", 0.9, hours=2)])
        assert r["eligible"] == 20, "a thin row must not tip the trigger to 21"

    def test_thin_row_is_not_a_fault(self, tmp_path):
        """It is scored — the instrument worked. It must not reach the ALARM."""
        r = run_guard(tmp_path, [scored("2026-09-09", 0.762, hours=1)])
        assert r["unscored"] == 0
        assert r["degenerate"] == 1

    def test_thin_row_does_not_reset_an_unscored_run(self, tmp_path):
        r = run_guard(tmp_path, [
            unscored_row("2026-09-06"),
            scored("2026-09-07", 0.5, hours=1),
            unscored_row("2026-09-08"),
        ])
        assert r["unscored"] == 2, "a thin row is neither a fault nor a reset"

    def test_floor_is_configurable(self, tmp_path):
        rows = [scored("2026-09-09", 0.5, hours=12)]
        assert run_guard(tmp_path, rows)["n"] == 1, "12 hours clears the default"
        assert run_guard(tmp_path, rows, min_hours=18)["degenerate"] == 1

    def test_a_float_hour_count_is_still_measured(self, tmp_path):
        """json numbers are not always ints, and a float must not slip the floor."""
        r = run_guard(tmp_path, [
            {"date": "2026-09-09", "n_naive_hours": 1.0,
             "lightgbm_skill_vs_naive": 0.762},
        ])
        assert r["degenerate"] == 1 and r["n"] == 0

    def test_missing_hour_count_is_kept_not_dropped(self, tmp_path):
        """An older scored row without n_naive_hours must still count.

        The floor may only exclude rows it can actually measure; treating an
        absent count as zero would silently void history.
        """
        r = run_guard(tmp_path, [
            {"date": "2026-09-06", "lightgbm_skill_vs_naive": 0.2},
        ])
        assert r["n"] == 1 and r["degenerate"] == 0


class TestUnchangedBehaviour:
    def test_full_rows_count_normally(self, tmp_path):
        r = run_guard(tmp_path, [scored(f"2026-09-{d:02d}", -0.1)
                                 for d in range(1, 8)])
        assert r == dict(n=7, losses=7, unscored=0, degenerate=0, eligible=7)

    def test_window_is_the_last_seven(self, tmp_path):
        r = run_guard(tmp_path, [scored(f"2026-09-{d:02d}", 0.5)
                                 for d in range(1, 6)]
                      + [scored(f"2026-09-{d:02d}", -0.5)
                         for d in range(6, 11)])
        assert r["n"] == 7 and r["losses"] == 5
        assert r["eligible"] == 10, "the trigger counts the whole log"

    def test_legacy_rows_reset_the_unscored_run(self, tmp_path):
        r = run_guard(tmp_path, [unscored_row("2026-09-06"), legacy("2026-09-07")])
        assert r["unscored"] == 0

    def test_unscored_rows_are_counted(self, tmp_path):
        r = run_guard(tmp_path, [unscored_row(f"2026-09-{d:02d}")
                                 for d in range(6, 9)])
        assert r["unscored"] == 3

    def test_missing_log_yields_zeroes_not_a_crash(self, tmp_path):
        r = run_guard(tmp_path, [])
        assert r == dict(n=0, losses=0, unscored=0, degenerate=0, eligible=0)
