# ADR-005: Long-History Warmup

**Status**: Proposed
**Date**: 2026-04-19
**Context**: The live River ARF model has seen ~64 days of training data and has never encountered winter demand, summer solar saturation, Christmas/New Year, Easter, or regime transitions. Forecast accuracy (`mae_vs_exchange` ~17 EUR/MWh) is ~2× academic benchmarks. Before investing in ensembles or new features, give the model multi-year seasonal coverage.

Informed by `docs/long-history-feasibility.md` (Phase 1 scouting, branch `feat/long-history-warmup`, commit `f3a2987`).

## Decision

Build a **single-tier** historical warmup that replays 5+ years of hourly data through the existing River ARF model using the **current feature set unchanged**. Warmup artifact goes to `ml/models/river_v2/river_model.pkl`, parallel to the live `ml/models/river_model.pkl`. After a held-out backtest gate, cut over by moving artifacts; the daily cron is untouched during development.

Data sources (all free, measured reachable):
- **ENTSO-E Transparency API** (requires api_key) — NL day-ahead prices (target), actual load, day-ahead load forecast, day-ahead wind+solar generation forecast, historical coverage back to Jan 2015.
- **Open-Meteo archive** (no auth) — hourly wind_speed_100m at offshore grid point near Gemini wind farm, shortwave_radiation at Eindhoven. ERA5 actuals, 1940-present.
- **yfinance `TTF=F`** (no auth) — front-month TTF gas daily close, forward-filled to hourly. ~2017-present.
- **`holidays` library** (no auth, offline) — NL national holidays and cyclical calendar features.

EUA carbon price is **omitted** from Tier 1 (no free yfinance ticker found; EEX/Sandbag scraping deferred).

## Context

Phase 1 scouting upended the original two-tier design. An audit of `ml/update.py:93-95` and `ml/features/online_features.py:149-151` showed Augur's feature vector is price lags + rolling stats + calendar + `wind_speed_80m`, `solar_ghi`, `load_forecast`. Temperature is extracted from multi-location weather but dropped by Lasso feature selection (per `memory/ml-decisions.md`). The 2025-11-04 introduction of Google Weather multi-location data did **not** change Augur's input vector. The tiering hypothesis was wrong.

This simplifies the architecture substantially: no tier boundary, no regime-change reconciliation, no feature-namespace overlap concerns. One chronological replay with one model, one feature builder.

## Rationale

- **Single-tier is justified by the feature audit.** No benefit to splitting training.
- **Warmup is cheap.** Measured River ARF throughput is 322 samples/s on sadalsuud; a 5-year hourly warmup (~44k samples) is ~2.3 minutes wall. Data collection is ~10 minutes. End-to-end run is under 15 minutes.
- **Parallel model directory is safe.** `ml/models/river_v2/` is isolated from the daily cron. Cutover is a rename + commit, easily reverted.
- **Uses the existing feature builder unchanged.** `OnlineFeatureBuilder` in `ml/features/online_features.py` is authoritative for both warmup and daily update (per ADR-004). No new feature code for the historical warmup — the consolidation module produces the same-shape rows the builder already consumes.
- **Failure surface is small.** If the backtest fails, we throw away `river_v2/` and lose nothing.

## Consequences

- **New module**: `ml/data/consolidate_historical.py` (separate from current `consolidate.py` so the daily pipeline is unaffected).
- **New warmup script**: `ml/training/warmup_historical.py`. Replays chronologically; at end, writes `ml/models/river_v2/river_model.pkl` and a `river_v2/warmup_summary.json` with training statistics. Does **not** populate `state.json` `error_history` / `metrics_history` — those are daily-cron artifacts with 500/365 bounded length; a 44k-sample warmup would flood them.
- **New evaluation harness**: `ml/evaluation/backtest.py`. Walks forward over a held-out slice (default: April 2026), produces MAE, MAPE, horizon-segmented MAE, spike recall (forecast within 30% when actual > 150 EUR/MWh).
- **Key management**: ENTSO-E API key and any Alpha Vantage key are read from `C:\Users\scbry\HAN\HAN H2 LAB IPKW - Projects - WebBasedControl\01. Software\energyDataHub\secrets.ini` on the dev machine. For CI / sadalsuud runs the same keys must be available via a local `.env` (gitignored). **No secrets committed.**
- **ENTSO-E robustness**: every call wrapped in retry with exponential backoff (observed 503 rate ~20% in scouting). Token must be redacted from any exception logging — `entsoe-py` passes the token in the URL and stock exception messages include it.
- **Weather-forecast leakage**: Open-Meteo archive returns ERA5 **actuals**, not as-of-date forecasts. The live pipeline uses as-of-date forecasts. To approximate this during warmup, calibrated noise is added to backfilled wind/solar:
  - Horizon-dependent, drawn from `N(0, σ(h))` per sample
  - Initial σ budget (to be benchmarked against live pipeline): wind 1.5 m/s at 24h, 3.0 m/s at 72h; solar GHI ~15% RMSE at 24h.
  - This is a source of bias — acknowledge and measure, don't pretend it's absent.
- **2022 gas-crisis regime**: prices went ~€50 → peaks ~€700 → ~€50 over 18 months. Initial stance: **let ARF+ADWIN handle it**, do not winsorize prior to measurement. If the 2022-2023 backtest slice is catastrophic, revisit with winsorization or a reset-at-crisis option.
- **Git history impact**: a new ~5-10 MB parquet artifact in `ml/data/` is generated once. Gitignore it; regenerate on demand.

## Evaluation Gate (cutover criteria)

Merge `feat/long-history-warmup` to `main` only if, on the April 2026 held-out slice:

1. `mae_vs_exchange` improves by **≥2 EUR/MWh** vs the current baseline (~17), **and**
2. Spike recall (predicted price within 30% on hours with actual > 150 EUR/MWh) does not regress, **and**
3. No horizon segment (1-6h / 6-24h / 24-48h / 48-72h) regresses by more than 20% in MAE.

If the gate fails, the branch stays live for iteration — the main branch and live model are unaffected.

## Rollback

- **During development**: the live cron runs on `main`. Nothing on `feat/long-history-warmup` touches it.
- **After cutover**: archive the pre-cutover model as `ml/models/river_v1_baseline.pkl` (committed to main). If v2 underperforms in production, restore by moving `river_v1_baseline.pkl` → `river_model.pkl` in a single commit. A rollback runbook entry goes in `docs/RUNBOOK.md` at cutover.

## Alternatives Considered

- **Two-tier with 2025-11-04 boundary** (the original proposal). Rejected: feature audit showed no actual feature-set change at that date. Adds complexity without benefit.
- **Keep short history, add explicit seasonal features**. Cheap, but can't cover regimes the model has never seen. Suitable as a complementary step, not a replacement for historical data.
- **Retrain from scratch with a different model (XGBoost, LightGBM)**. Out of scope for this ADR — the question here is "does more history help our current model." ADR-004 chose River; revisiting model choice is a separate ADR, tracked as augur#9 ensemble.
- **Winsorize training prices beyond p99.5 to tame the 2022 crisis**. Deferred: treat as a potential follow-up if the initial backtest shows crisis-period damage.

## Open questions (not blocking ADR acceptance)

- Benchmark weather-noise σ against the live pipeline's forecast-vs-actual history (need a parallel study on archived `*_wind_forecast.json` vs Open-Meteo archive for the same dates).
- Whether to include historical gas-storage (GIE) levels or cross-border flows in the feature set. Deferred to a follow-up ADR if v2 merges but accuracy plateaus.
- Whether to eventually backfill EUA carbon from EEX settlement archive. Deferred.
