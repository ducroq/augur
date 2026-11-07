"""Tests for ml/shadow/update_fm.py: the Chronos-Bolt live shadow (EXP-021a Stage 3).

The model is replaced by a stub, so these run without torch. The real model is
exercised by the rehearsal recorded in docs/model-progress-log.md.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.shadow.regret import run_regret
from ml.shadow.update_fm import (
    CONTEXT_END_OFFSET_H,
    FM_STATE_FILENAME,
    build_context,
    predict_72h_fm,
    run_fm_update,
)
from ml.shadow.update_shadow import HORIZONS, SHADOW_STATE_FILENAME

REPO = Path(__file__).resolve().parents[1]
T0 = pd.Timestamp("2026-10-20T22:00:00Z")


def _parquet(end: pd.Timestamp = T0, days: int = 70) -> pd.DataFrame:
    idx = pd.date_range(end - pd.Timedelta(days=days), end, freq="h", tz="UTC")
    return pd.DataFrame(
        {"price_eur_mwh": 80 + 30 * np.sin(np.arange(len(idx)) * 2 * np.pi / 24),
         "price_is_entsoe": 1.0},
        index=idx,
    )


def _stub(context: np.ndarray, length: int) -> np.ndarray:
    """p50 at index i is 100 + i, so a horizon's rollout index is readable."""
    mid = 100.0 + np.arange(length)
    return np.column_stack([mid - 10, mid, mid + 10])


def _setup(tmp_path: Path, t0: pd.Timestamp = T0, parquet: pd.DataFrame | None = None):
    path = tmp_path / "history.parquet"
    (_parquet(t0) if parquet is None else parquet).to_parquet(path)
    (tmp_path / SHADOW_STATE_FILENAME).write_text(json.dumps({"last_t0": t0.isoformat()}))
    return path, tmp_path / "fm.json"


def test_context_stops_one_hour_before_t0_at_the_measured_length():
    context = build_context(_parquet(), T0)
    assert context.index[-1] == T0 - pd.Timedelta(hours=1)
    assert len(context) == 1343  # EXP-039 a_latency.context_len


def test_context_never_reads_past_t0():
    parquet = _parquet(T0 + pd.Timedelta(hours=48))
    assert build_context(parquet, T0).index.max() < T0


def test_holes_stay_on_the_grid_as_nan():
    parquet = _parquet()
    hole = parquet.index[-100:-90]
    parquet.loc[hole, "price_eur_mwh"] = np.nan
    context = build_context(parquet, T0)
    assert len(context) == 1343
    assert context.isna().sum() == 10
    assert context.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all()


def test_too_short_context_raises():
    with pytest.raises(ValueError, match="too few prices"):
        build_context(_parquet(days=2), T0)


def test_horizon_one_skips_the_hour_the_context_held_back():
    preds = predict_72h_fm(_stub, build_context(_parquet(), T0), T0)
    assert len(preds) == 72
    assert preds["timestamp_utc"].iloc[0] == T0 + pd.Timedelta(hours=1)
    assert preds["p50"].iloc[0] == 100.0 + CONTEXT_END_OFFSET_H
    assert preds["p50"].iloc[-1] == 100.0 + 71 + CONTEXT_END_OFFSET_H


def test_crossed_quantiles_are_sorted_and_raw_is_preserved():
    def crossed(context, length):
        return _stub(context, length)[:, ::-1]

    preds = predict_72h_fm(crossed, build_context(_parquet(), T0), T0)
    assert (preds["p10"] <= preds["p90"]).all()
    assert (preds["p10_raw"] > preds["p90_raw"]).all()


def test_non_finite_forecast_writes_nothing(tmp_path):
    def broken(context, length):
        out = _stub(context, length)
        out[5, 1] = np.nan
        return out

    parquet, out = _setup(tmp_path)
    with pytest.raises(ValueError, match="non-finite"):
        run_fm_update(parquet, tmp_path, out, forecast_fn=broken)
    assert not out.exists()
    assert not (tmp_path / FM_STATE_FILENAME).exists()


def test_wrong_shape_raises():
    with pytest.raises(ValueError, match="forecast shape"):
        predict_72h_fm(lambda c, n: np.zeros((n - 1, 3)), build_context(_parquet(), T0), T0)


def test_run_uses_production_t0_and_leaves_its_state_alone(tmp_path):
    parquet, out = _setup(tmp_path)
    before = (tmp_path / SHADOW_STATE_FILENAME).read_bytes()
    state = run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)
    assert state["last_t0"] == T0.isoformat()
    assert {r["t0_utc"] for r in state["pending_predictions"]} == {T0.isoformat()}
    assert len(state["pending_predictions"]) == len(HORIZONS)
    assert (tmp_path / SHADOW_STATE_FILENAME).read_bytes() == before


def test_missing_production_t0_raises(tmp_path):
    parquet, out = _setup(tmp_path)
    (tmp_path / SHADOW_STATE_FILENAME).write_text(json.dumps({"last_t0": None}))
    with pytest.raises(ValueError, match="last_t0"):
        run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)


def test_forecast_file_has_the_production_schema(tmp_path):
    parquet, out = _setup(tmp_path)
    run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)
    payload = json.loads(out.read_text())
    production = json.loads((REPO / "static/data/augur_forecast_shadow.json").read_text())
    assert set(payload) == set(production)
    assert len(payload["forecast"]) == 72
    assert payload["metadata"]["t0"] == T0.isoformat()
    assert payload["metadata"]["cqr_q"] == 0.0  # cold start


def test_rerun_on_the_same_t0_replaces_the_vintage(tmp_path):
    parquet, out = _setup(tmp_path)
    run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)
    state = run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)
    assert len(state["pending_predictions"]) == len(HORIZONS)


def test_repeated_t0_with_advancing_prices_keeps_each_hour_once(tmp_path):
    """A held-back t0 realises the same vintage again on later nights."""
    log = tmp_path / "fm_regret.jsonl"
    for night in range(5):
        path, out = _setup(tmp_path, T0, _parquet(T0 + pd.Timedelta(days=night)))
        state = run_fm_update(path, tmp_path, out, forecast_fn=_stub)
    history = state["calibration_history"]
    keys = [(r["timestamp_utc"], r["eval_day"]) for r in history]
    assert keys and len(keys) == len(set(keys))
    rows = run_regret(tmp_path / FM_STATE_FILENAME, path, log, model_arm="fm")
    assert [r["block"] for r in rows] == ["h1_24", "h25_48", "h49_72"]
    assert not any(r.get("incomplete") for r in rows)


def test_vintages_realise_calibrate_and_feed_regret(tmp_path):
    """Six nights: q leaves 0 on the arm's own raw scores, and regret reads it."""
    log = tmp_path / "fm_regret.jsonl"
    state = None
    for night in range(6):
        t0 = T0 + pd.Timedelta(days=night)
        # Prices reach the anchor, so the vintages before it have realised.
        parquet, out = _setup(tmp_path, t0)
        state = run_fm_update(parquet, tmp_path, out, forecast_fn=_stub)

    assert state["calibration_history"]
    assert state["last_cqr_q"] > 0
    assert state["last_cqr_n_calib_days"] >= 3
    last = [r for r in state["pending_predictions"] if r["t0_utc"] == state["last_t0"]]
    assert last[0]["cqr_n_calib_days"] == state["last_cqr_n_calib_days"]
    first = min(state["calibration_history"], key=lambda r: r["t0_utc"])
    assert first["cqr_q"] == 0.0 and first["cqr_n_calib_days"] == 0
    assert last[0]["p10"] == pytest.approx(last[0]["p10_raw"] - state["last_cqr_q"])

    rows = run_regret(tmp_path / FM_STATE_FILENAME, parquet, log, model_arm="fm")
    assert rows
    complete = [r for r in rows if not r.get("incomplete")]
    assert complete and all(r["fm_regret_k6"] is not None for r in complete)
    assert all("lightgbm_regret_k6" not in r for r in complete)
    assert all(r["naive_regret_k6"] is not None for r in complete)


def test_daily_job_can_stage_every_fm_artifact():
    """An ignored path makes `git add` fail, and under `set -e` that kills the
    commit that carries production's forecast."""
    paths = ["static/data/augur_forecast_fm.json", "ml/models/shadow/fm_state.json",
             "ml/shadow/fm_regret_log.jsonl"]
    script = (REPO / "scripts/daily_update.sh").read_text()
    for path in paths:
        ignored = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO)
        assert ignored.returncode == 1, f"{path} is gitignored"
        assert f"git add {path}" in script


def test_fm_step_cannot_take_the_daily_job_down():
    script = (REPO / "scripts/daily_update.sh").read_text()
    block = script[script.index("set +e\n\n# Parquet consolidate"):
                   script.index("# --- end shadow block")]
    assert "timeout" in block and "python -m ml.shadow.update_fm" in block
    assert "HF_HUB_OFFLINE=1" in block
    assert "${FM_MARKER}" in script


def test_torch_stays_out_of_what_netlify_may_install():
    """Netlify may install the root requirements.txt (augur#35)."""
    loose = (REPO / "requirements.txt").read_text().lower()
    assert "torch" not in loose and "chronos" not in loose
