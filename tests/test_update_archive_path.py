"""Test for the ARF forecast archive path fix.

Surfaced by the EXP-009 M3 review battery: ``write_forecast_json`` was
computing ``archive_dir = output_dir.parent / "ml" / "forecasts"`` which
resolved to ``augur_dir/static/ml/forecasts`` — not where CLAUDE.md and
``evaluate_shadow.py`` expect the archive (``augur_dir/ml/forecasts``).
"""

from __future__ import annotations

from pathlib import Path

from ml.update import write_forecast_json


def test_archive_lives_under_augur_root_not_under_static(tmp_path):
    augur_dir = tmp_path / "augur"
    output_dir = augur_dir / "static" / "data"
    output_dir.mkdir(parents=True)

    forecast = {"2026-04-30T01:00:00+00:00": 50.0}
    state = {
        "n_samples": 100,
        "metrics": {},
        "metrics_history": [],
        "error_history": [],
        "error_hours": [],
    }
    write_forecast_json(forecast, forecast, forecast, state, output_dir)

    expected = augur_dir / "ml" / "forecasts"
    wrong = augur_dir / "static" / "ml" / "forecasts"

    archives = list(expected.glob("*_forecast.json"))
    assert len(archives) == 1, f"expected one archive in {expected}, got {archives}"
    assert not wrong.exists(), f"archive should NOT land in {wrong}"
