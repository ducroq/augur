"""Nightly live shadow of Chronos-Bolt: EXP-021a Stage 3.

CLI:
    python -m ml.shadow.update_fm

Pre-commitment: `docs/hypothesis-log.md` [2026-08-29] Stage 3 and [2026-10-28]
(product criterion). The shadow runs for 14 evaluable vintages, written to its
own files, and the dashboard doesn't read them. The forecast JSON is committed,
so Hugo serves it at /data/ like its siblings.

Why each choice is what it is:

- **t0 is production's**, read from `shadow_state.json:last_t0`, so every FM
  vintage pairs one-to-one with a LightGBM vintage. This step therefore runs
  after `update_shadow`, and only reads that state.
- **The context ends at t0 - 1h.** `features_pandas` shifts every price feature
  by one row, so the production row at t0 knows prices up to t0 - 1h. Handing
  the FM the t0 price would give it an hour the incumbent lacks. The offset,
  length and rollout are those EXP-038 and EXP-039 measured (context 1343,
  prediction length 73); the next-but-one bullet is the one difference.
- **Holes stay NaN on an hourly grid.** Bolt reads its context as regularly
  spaced, so a compressed array would shift every hour of day across the hole
  (EXP-021 addendum 2026-08-29).
- **Price rows only.** EXP-038's context also dropped rows with exogenous NaNs,
  to match the incumbent's training rows. The FM reads no exogenous column, so
  a live hole there is not a reason to discard a real price. It can leave the
  FM a few more prices than the incumbent's row set.
- **Weights are pinned and loaded from the local cache.** An upstream revision
  must not change the arm during its 14 vintages. `daily_update.sh` sets
  `HF_HUB_OFFLINE=1`.
- **CQR is production's**, on this arm's own history. The first vintages run at
  q=0 until `MIN_CALIB_DAYS` days have realised. Each row records its vintage's
  `cqr_q` and `cqr_n_calib_days`, because the Stage 3 criterion counts only
  vintages whose CQR was live. `p50`, and so regret, is unaffected.

Torch is imported only inside `load_bolt_forecaster`, so the tests run without it.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import pandas as pd

from ml.shadow.conformal import DEFAULT_CALIB_DAYS, DEFAULT_TARGET_COVERAGE
from ml.shadow.update_shadow import (
    DEFAULT_PARQUET,
    DEFAULT_SHADOW_DIR,
    HORIZONS,
    MAX_HISTORY_DAYS,
    MIN_WINDOW_DENSITY,
    SHADOW_STATE_FILENAME,
    VAT_RATE,
    WINDOW_DAYS,
    _normalize_parquet_index,
    backfill_realized,
    compute_cqr_q,
    format_consumer_dicts,
    format_forecast_dicts,
    load_shadow_state,
    read_arf_surcharge,
    save_shadow_state,
    trim_to_recent_days,
    widen_with_cqr,
    write_forecast_json,
)

logger = logging.getLogger(__name__)

MODEL_ID = "amazon/chronos-bolt-base"
MODEL_REVISION = "5d9f166d69f47aef3401367a7b842e78fe97b121"
QUANTILE_LEVELS = (0.10, 0.50, 0.90)
CONTEXT_END_OFFSET_H = 1
TORCH_THREADS = 4  # what EXP-039 measured on sadalsuud

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_FORECAST_OUT = _REPO_ROOT / "static" / "data" / "augur_forecast_fm.json"
FM_STATE_FILENAME = "fm_state.json"

# context, prediction_length -> (prediction_length, 3) quantiles, tau-ordered.
Forecaster = Callable[[np.ndarray, int], np.ndarray]


def load_bolt_forecaster() -> Forecaster:
    """Load the pinned model on CPU and return its forecast function."""
    import torch
    from chronos import BaseChronosPipeline

    torch.set_num_threads(TORCH_THREADS)
    pipeline = BaseChronosPipeline.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        device_map="cpu",
        torch_dtype=torch.float32,
    )

    def forecast(context: np.ndarray, prediction_length: int) -> np.ndarray:
        quantiles, _mean = pipeline.predict_quantiles(
            [torch.tensor(context, dtype=torch.float32)],
            prediction_length=prediction_length,
            quantile_levels=list(QUANTILE_LEVELS),
        )
        return quantiles[0].numpy()

    return forecast


def build_context(
    parquet: pd.DataFrame, t0: pd.Timestamp, window_days: int = WINDOW_DAYS
) -> pd.Series:
    """Hourly price context ending at t0 - CONTEXT_END_OFFSET_H, holes as NaN."""
    ctx_end = t0 - pd.Timedelta(hours=CONTEXT_END_OFFSET_H)
    prices = parquet["price_eur_mwh"].dropna()
    window = prices[(prices.index > t0 - pd.Timedelta(days=window_days))
                    & (prices.index <= ctx_end)]
    if len(window) <= max(HORIZONS):
        raise ValueError(f"too few prices in the context ending {ctx_end}: {len(window)}")
    expected = window_days * 24 - CONTEXT_END_OFFSET_H
    if len(window) < MIN_WINDOW_DENSITY * expected:
        logger.warning("Context is sparse: %d of %d hours", len(window), expected)
    return window.reindex(pd.date_range(window.index.min(), ctx_end, freq="h"))


def predict_72h_fm(
    forecast_fn: Forecaster,
    context: pd.Series,
    t0: pd.Timestamp,
    horizons: Sequence[int] = HORIZONS,
) -> pd.DataFrame:
    """Same columns as `update_shadow.predict_72h`, one row per horizon.

    The rollout starts one step behind t0, so horizon h sits at index
    h - 1 + CONTEXT_END_OFFSET_H.
    """
    horizons_list = list(horizons)
    length = max(horizons_list) + CONTEXT_END_OFFSET_H
    raw = np.asarray(forecast_fn(context.to_numpy(dtype=float), length), dtype=float)
    if raw.shape != (length, len(QUANTILE_LEVELS)):
        raise ValueError(f"forecast shape {raw.shape}, expected {(length, len(QUANTILE_LEVELS))}")
    raw = raw[[h - 1 + CONTEXT_END_OFFSET_H for h in horizons_list]]
    if not np.isfinite(raw).all():
        raise ValueError(f"non-finite forecast for t0={t0}")
    ordered = np.sort(raw, axis=1)
    return pd.DataFrame(
        {
            "timestamp_utc": [t0 + pd.Timedelta(hours=h) for h in horizons_list],
            "p10": ordered[:, 0],
            "p50": ordered[:, 1],
            "p90": ordered[:, 2],
            "p10_raw": raw[:, 0],
            "p50_raw": raw[:, 1],
            "p90_raw": raw[:, 2],
        }
    )


def run_fm_update(
    parquet_path: Path = DEFAULT_PARQUET,
    shadow_dir: Path = DEFAULT_SHADOW_DIR,
    forecast_out: Path = DEFAULT_FORECAST_OUT,
    forecast_fn: Forecaster | None = None,
) -> dict:
    """Run one FM shadow cycle on production's t0. Returns the updated state."""
    parquet = _normalize_parquet_index(pd.read_parquet(parquet_path))
    last_t0 = load_shadow_state(shadow_dir / SHADOW_STATE_FILENAME).get("last_t0")
    if last_t0 is None:
        raise ValueError("production shadow state has no last_t0; run update_shadow first")
    t0 = pd.Timestamp(last_t0)
    today = t0.strftime("%Y-%m-%d")

    state_path = shadow_dir / FM_STATE_FILENAME
    state = load_shadow_state(state_path)

    realized_rows, still_pending = backfill_realized(state["pending_predictions"], parquet)
    # Keyed like pending below. A t0 that repeats while prices advance realises
    # the same (hour, vintage) twice, and a doubled row would corrupt the CQR
    # window and read as a 48-slot block in regret.py.
    calibrated = {
        (r["timestamp_utc"], r["eval_day"]): r
        for r in list(state["calibration_history"]) + realized_rows
    }
    state["calibration_history"] = trim_to_recent_days(
        list(calibrated.values()), MAX_HISTORY_DAYS
    )
    q, n_calib_days = compute_cqr_q(state["calibration_history"], today)
    logger.info("FM CQR q=%.3f from %d calibration day(s)", q, n_calib_days)

    context = build_context(parquet, t0)
    preds = predict_72h_fm(forecast_fn or load_bolt_forecaster(), context, t0)
    preds = widen_with_cqr(preds, q)

    # Same row shape as production, so regret.py and compute_cqr_q read both.
    new_pending = [
        {
            "timestamp_utc": pd.Timestamp(row["timestamp_utc"]).isoformat(),
            "eval_day": today,
            "t0_utc": t0.isoformat(),
            "p10": float(row["p10_cqr"]),
            "p50": float(row["p50"]),
            "p90": float(row["p90_cqr"]),
            "p10_raw": float(row["p10_raw"]),
            "p50_raw": float(row["p50_raw"]),
            "p90_raw": float(row["p90_raw"]),
            # Per vintage, because the Stage 3 criterion counts only vintages
            # whose own CQR was live (hypothesis-log [2026-11-07]).
            "cqr_q": round(q, 4),
            "cqr_n_calib_days": n_calib_days,
        }
        for _, row in preds.iterrows()
    ]
    # Last entry per key wins, so a rerun on the same t0 replaces what is pending.
    deduped = {(r["timestamp_utc"], r["eval_day"]): r for r in still_pending + new_pending}
    state["pending_predictions"] = trim_to_recent_days(list(deduped.values()), MAX_HISTORY_DAYS)

    forecast, upper, lower = format_forecast_dicts(preds)
    surcharge = read_arf_surcharge()
    consumer, consumer_upper, consumer_lower = format_consumer_dicts(
        forecast, upper, lower, surcharge
    )
    n_context = int(context.notna().sum())
    write_forecast_json(
        forecast_out,
        forecast,
        upper,
        lower,
        {
            "model": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "t0": t0.isoformat(),
            "window_days": WINDOW_DAYS,
            "context_end_offset_h": CONTEXT_END_OFFSET_H,
            "n_context": n_context,
            "n_context_missing": int(context.isna().sum()),
            "cqr_q": round(q, 4),
            "cqr_calib_days_used": n_calib_days,
            "cqr_calib_window_days": DEFAULT_CALIB_DAYS,
            "cqr_target_coverage": DEFAULT_TARGET_COVERAGE,
            "consumer_surcharge_eur_mwh": round(surcharge, 2),
            "consumer_vat_rate": VAT_RATE,
        },
        consumer=consumer,
        consumer_upper=consumer_upper,
        consumer_lower=consumer_lower,
    )

    state["last_run_utc"] = datetime.now(timezone.utc).isoformat()
    state["last_t0"] = t0.isoformat()
    state["last_cqr_q"] = round(q, 4)
    state["last_cqr_n_calib_days"] = n_calib_days
    state["n_context"] = n_context
    save_shadow_state(state, state_path)
    logger.info("Wrote FM shadow for t0=%s to %s", t0, forecast_out)
    return state


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--parquet", default=str(DEFAULT_PARQUET))
    parser.add_argument("--shadow-dir", default=str(DEFAULT_SHADOW_DIR))
    parser.add_argument("--forecast-out", default=str(DEFAULT_FORECAST_OUT))
    args = parser.parse_args()
    run_fm_update(Path(args.parquet), Path(args.shadow_dir), Path(args.forecast_out))


if __name__ == "__main__":
    main()
