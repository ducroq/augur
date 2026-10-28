"""Tests for ml/shadow/regret.py — nightly cheap-hour regret per horizon block."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.shadow.regret import (
    BLOCKS,
    read_logged_keys,
    run_regret,
    score_block,
    score_vintage,
)

REPO = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2026-10-01T22:00:00Z")


def _history(hours: int, p50=None, realized=None) -> list[dict]:
    rows = []
    for h in range(1, hours + 1):
        ts = T0 + pd.Timedelta(hours=h)
        rows.append({
            "timestamp_utc": ts.isoformat(),
            "eval_day": T0.strftime("%Y-%m-%d"),
            "t0_utc": T0.isoformat(),
            "p10": 0.0, "p50": float(p50(h) if p50 else h), "p90": 0.0,
            "realized": float(realized(h) if realized else h),
        })
    return rows


def _prices(days: int = 40) -> pd.Series:
    idx = pd.date_range(T0 - pd.Timedelta(days=days), T0, freq="h", tz="UTC")
    return pd.Series(np.arange(len(idx), dtype=float) % 24, index=idx)


def test_score_block_matches_exp037_runner():
    """The copy in ml/ must give exactly what the pre-committed runner gives."""
    spec = importlib.util.spec_from_file_location(
        "exp037", REPO / "scripts" / "exp037_rank_metric.py")
    exp037 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exp037)
    rng = np.random.default_rng(7)
    for _ in range(50):
        pred = rng.normal(80, 30, 24).round(0)   # rounding forces ties
        real = rng.normal(80, 30, 24).round(0)
        a, b = score_block(pred, real), exp037.score_block(pred, real)
        assert a.keys() == b.keys()
        for k in a:
            assert a[k] == pytest.approx(b[k], nan_ok=True)


def test_known_regret():
    realized = np.array([5.0, 1.0, 9.0, 2.0] + [50.0] * 20)
    perfect = score_block(realized, realized)
    assert perfect["regret_k3"] == 0.0
    # Picks slots 4,5,6 (all 50) instead of 1,3,0 (1,2,5): regret = 50 - 8/3.
    wrong = np.array([90.0] * 4 + [1.0, 2.0, 3.0] + [60.0] * 17)
    assert score_block(wrong, realized)["regret_k3"] == pytest.approx(50 - 8 / 3)


def test_partial_block_dropped_not_padded():
    rows = score_vintage(T0.strftime("%Y-%m-%d"), _history(40), None, None)
    assert [r["block"] for r in rows] == ["h1_24"]


def test_full_vintage_three_blocks_baselines_null_without_prices():
    rows = score_vintage(T0.strftime("%Y-%m-%d"), _history(72), None, None)
    assert [r["block"] for r in rows] == [b[0] for b in BLOCKS]
    assert all(r["naive_regret_k6"] is None and r["profile_regret_k6"] is None for r in rows)
    assert all(r["lightgbm_regret_k6"] is not None for r in rows)


def test_carry_scored_when_prices_cover_every_slot():
    rows = score_vintage(T0.strftime("%Y-%m-%d"), _history(72), _prices(), None)
    assert all(r["naive_regret_k6"] is not None for r in rows)
    assert all(r["profile_regret_k6"] is None for r in rows)  # no holiday set


def test_unknown_anchor_skips_vintage():
    hist = _history(72)
    for r in hist:
        del r["t0_utc"]
    hist = hist[3:]  # leading hours withheld: inference refuses to guess
    assert score_vintage(T0.strftime("%Y-%m-%d"), hist, None, None) == []


def test_run_regret_is_idempotent(tmp_path):
    state = tmp_path / "shadow_state.json"
    state.write_text(json.dumps({"calibration_history": _history(72),
                                 "pending_predictions": []}))
    log = tmp_path / "regret_log.jsonl"
    missing = tmp_path / "none.parquet"
    first = run_regret(state, missing, log)
    assert len(first) == 3
    assert run_regret(state, missing, log) == []
    assert read_logged_keys(log) == {(T0.strftime("%Y-%m-%d"), b[0]) for b in BLOCKS}


def test_incomplete_block_logged_once_it_can_no_longer_complete():
    hist = _history(72)
    del hist[30]                       # one h25_48 hour never realises
    later = T0 + pd.Timedelta(hours=48 + 48)
    hist.append({"timestamp_utc": later.isoformat(), "eval_day": "2026-10-05",
                 "t0_utc": "2026-10-04T22:00:00+00:00", "p10": 0.0, "p50": 1.0,
                 "p90": 0.0, "realized": 1.0})
    rows = score_vintage(T0.strftime("%Y-%m-%d"), hist, None, None)
    inc = [r for r in rows if r.get("incomplete")]
    assert [(r["block"], r["n_slots"]) for r in inc] == [("h25_48", 23)]


def test_incomplete_block_not_final_yet_is_not_logged():
    hist = _history(72)
    del hist[30]
    rows = score_vintage(T0.strftime("%Y-%m-%d"), hist, None, None)
    assert not any(r.get("incomplete") for r in rows)


def test_torn_final_line_is_repaired(tmp_path):
    state = tmp_path / "shadow_state.json"
    state.write_text(json.dumps({"calibration_history": _history(72),
                                 "pending_predictions": []}))
    log = tmp_path / "regret_log.jsonl"
    log.write_text('{"date": "2026-01-01", "blo')    # crash mid-write
    run_regret(state, tmp_path / "none.parquet", log)
    lines = log.read_text().splitlines()
    assert len(lines) == 4 and all(json.loads(l) for l in lines[1:])
