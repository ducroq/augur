"""Tests for scripts/exp041_fm_vs_profile.py on synthetic vintages only.

Real FM vintages are never read here: EXP-041 forbids an interim look.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

spec = importlib.util.spec_from_file_location(
    "exp041", Path(__file__).resolve().parents[1] / "scripts" / "exp041_fm_vs_profile.py")
exp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exp)

BASE = datetime(2026, 11, 10, 22, tzinfo=timezone.utc)


def vintage(i, cqr=3, hours=72, noise=0.0, rng=None):
    t0 = BASE + timedelta(days=i)
    day = t0.date().isoformat()
    rows, fc, lo, hi = [], {}, {}, {}
    for h in range(hours):
        t = t0 + timedelta(hours=h + 1)
        y = 100 + 30 * np.sin(h / 24 * 2 * np.pi)
        e = rng.normal(0, 10) if rng is not None else 0.0
        rows.append({"eval_day": day, "t0_utc": t0.isoformat(), "timestamp_utc": t.isoformat(),
                     "realized": y + e, "p50": y + noise, "p10": y - 20, "p90": y + 20,
                     "cqr_n_calib_days": cqr})
        # The profile ships "+01:00"-style strings in other files; use Z-free UTC here.
        fc[t.isoformat()], lo[t.isoformat()], hi[t.isoformat()] = y + 5, y - 15, y + 15
    doc = {"metadata": {"t0": t0.isoformat(), "n_holiday_fallback_hours": 0},
           "forecast": fc, "forecast_lower": lo, "forecast_upper": hi}
    return rows, t0, doc


def test_population_conditions_and_exclusions():
    fm, profiles = [], {}
    for i in range(4):
        rows, t0, doc = vintage(i, cqr=2 if i == 0 else 3, hours=48 if i == 1 else 72)
        fm += rows
        if i != 3:
            profiles[t0] = doc
    counted, excluded = exp.population(fm, profiles)
    assert [d for d, *_ in counted] == ["2026-11-12"]   # 0: CQR cold, 1: partial
    assert excluded == ["2026-11-13"]                    # 3: no shipped profile


def test_population_caps_at_fourteen_in_t0_order():
    fm, profiles = [], {}
    for i in reversed(range(16)):
        rows, t0, doc = vintage(i)
        fm += rows
        profiles[t0] = doc
    counted, _ = exp.population(fm, profiles)
    assert len(counted) == 14 and counted[0][0] == "2026-11-10" and counted[-1][0] == "2026-11-23"


def test_read_runs_end_to_end_on_synthetic_state(tmp_path, monkeypatch):
    rng = np.random.default_rng(0)
    fm, profiles = [], {}
    for i in range(14):
        rows, t0, doc = vintage(i, rng=rng)
        fm += rows
        profiles[t0] = doc
    (tmp_path / "fm.json").write_text(json.dumps({"calibration_history": fm}))
    (tmp_path / "prod.json").write_text(json.dumps({"calibration_history": fm}))
    monkeypatch.setattr(exp, "shipped_profiles", lambda repo=".": profiles)
    monkeypatch.setattr(exp, "OUT", tmp_path / "summary.json")
    monkeypatch.setattr(sys, "argv", ["x", "--fm-state", str(tmp_path / "fm.json"),
                                      "--shadow-state", str(tmp_path / "prod.json")])
    assert exp.main() == 0
    s = json.loads((tmp_path / "summary.json").read_text())
    assert s["n_obs"] == 14 * 72
    assert s["skill_gate"]["verdict"] == "PASS"       # FM p50 exact, profile off by 5
    assert s["guardrail"]["fm_lower"] >= s["guardrail"]["profile_lower"]
    assert s["lightgbm_reported_not_gated"]["n_vintages"] == 14
