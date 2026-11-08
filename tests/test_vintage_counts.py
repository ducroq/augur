"""Tests for scripts/vintage_counts.py: what counts as a fully realised vintage."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "vintage_counts", Path(__file__).resolve().parents[1] / "scripts" / "vintage_counts.py")
vc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vc)


def vintage(day: str, hours: int = 72, realized=1.0, **extra) -> list[dict]:
    t0 = datetime.fromisoformat(f"{day}T22:00:00+00:00")
    return [{"eval_day": day, "t0_utc": t0.isoformat(),
             "timestamp_utc": (t0 + timedelta(hours=h + 1)).astimezone(timezone.utc).isoformat(),
             "realized": realized, **extra} for h in range(hours)]


def test_partial_and_unrealised_vintages_do_not_count():
    hist = vintage("2026-11-01") + vintage("2026-11-02", hours=48) + vintage("2026-11-03", realized=None)
    assert list(vc.realised_vintages(hist)) == ["2026-11-01"]


def test_duplicate_rows_keep_the_last_and_do_not_inflate():
    hist = vintage("2026-11-01") + vintage("2026-11-01", realized=None)
    assert vc.realised_vintages(hist) == {}


def test_t0_cutoff_and_room():
    hist = vintage("2026-10-29") + vintage("2026-10-30") + vintage("2026-10-31")
    n, room = vc.count_t0_since(hist, "2026-10-30")
    assert n == 2
    assert room == vc.MAX_HISTORY_DAYS - 2


def test_fm_pairing_needs_live_cqr_and_production_coverage():
    prod = vintage("2026-11-10") + vintage("2026-11-11") + vintage("2026-11-12", hours=24)
    fm = (vintage("2026-11-09", cqr_n_calib_days=3)        # no production pair
          + vintage("2026-11-10", cqr_n_calib_days=2)      # CQR not live
          + vintage("2026-11-11", cqr_n_calib_days=3)      # counts
          + vintage("2026-11-12", cqr_n_calib_days=3))     # production partial
    n, _ = vc.count_fm_paired(fm, prod)
    assert n == 1


def test_empty_history_has_no_room_figure():
    assert vc.count_t0_since([], "2026-10-30") == (0, None)
