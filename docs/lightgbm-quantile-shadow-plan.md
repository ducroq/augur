# LightGBM-Quantile Shadow Plan (prospective EXP-009)

**Status**: planning. No code yet. Will register as `EXP-009` in `experiments/registry.jsonl` once shadow validation actually starts.

**Context**: ARF retired in `EXP-008` (see `docs/river-arf-retrospective.md`). This document defines the replacement we will validate in shadow before any production swap.

## 1. Hypothesis

A LightGBM regressor trained per-quantile (P10/P50/P90) with pinball loss, retrained nightly on a rolling 4-week window, will outperform River ARF on negative-price hours by enough to justify replacement, without regressing on evening peaks. The structural argument: LightGBM's leaf values are unbounded, and pinball loss directly learns quantile boundaries — both are absent in ARF as deployed.

## 2. Model spec

- **Library**: `lightgbm` (PyPI). Python 3.12 wheel available.
- **Architecture**: three independent regressors, one per target quantile.
  - `LGBMRegressor(objective='quantile', alpha=0.10)` → forecast_lower
  - `LGBMRegressor(objective='quantile', alpha=0.50)` → forecast_mean (median)
  - `LGBMRegressor(objective='quantile', alpha=0.90)` → forecast_upper
- **Hyperparameters (initial, conservative)**:
  - `n_estimators=300`, `learning_rate=0.05`, `num_leaves=31`, `min_child_samples=20`
  - No early stopping in v1 (rolling 4-week window is small enough that variance dominates).
- **Multi-horizon strategy**: one model trio per horizon group. Three groups initially: `h+1..h+6` (momentum), `h+6..h+24` (intraday weather), `h+24..h+72` (weather + calendar). Avoids 72 separate models while still letting error structure differ by horizon.
  - Total: 3 horizon groups × 3 quantiles = **9 models**, retrained nightly.

**Why not multi-quantile single model**: LightGBM's quantile loss only supports one alpha per fit. Catboost has multi-quantile but adds a dependency. Three independent fits is simplest.

**Why not neural (N-BEATS, TFT)**: heavier infra, longer iteration loop, no clear win at this corpus size (~6k rows). Keep on the table for v2 if LightGBM stalls.

## 3. Feature set

Start with ARF's existing feature set (same `OnlineFeatureBuilder`, no rewrite) so any difference is attributable to the model, not the features:

- price lags: 1, 2, 3, 6, 12, 24, 48, 168 h
- rolling stats: mean/std over 6 h, 24 h, 168 h
- calendar: hour, hour_sin/cos, dow_sin/cos, is_weekend, month_sin
- exogenous: wind_speed_80m, solar_ghi, load_forecast

**One additive feature** (cheap, addresses ARF's blind spot on regime onset):

- `renewable_pressure = solar_ghi × C_solar + wind_speed_80m³ × C_wind − load_forecast`
  - `C_solar`, `C_wind` are static capacity scalars (calibrated once from the parquet by regressing solar_ghi/wind on actual generation, if available; else order-of-magnitude defaults).
  - This is forecast-side data, no leakage. It captures "today there will be more renewable supply than load can absorb" — the regime-onset signal that the parked Phase 1 gen-mix lag24h could not provide.

**Held back for now**: TTF gas, gen-mix lag24h (parked Phase 1 features). Add only if v1 shadow underperforms — keeps the A/B clean.

## 4. Data window & retraining

- **Training window**: rolling **28 days** of hourly samples (~672 rows).
  - Rationale: long enough for LightGBM to find interactions, short enough to track regime shifts.
- **Retraining cadence**: nightly, immediately after the existing `python -m ml.update` step in `scripts/daily_update.sh` on sadalsuud.
- **Bootstrap**: re-consolidate `ml/data/training_history.parquet` from energyDataHub up through yesterday before first shadow run, so the model starts with the full ~7-month corpus including the 04-21+ negative-price regime. The current parquet (4272 rows, 2025-09-28 → 2026-03-28) is winter-only and inadequate.
- **Train/eval split**: walk-forward only — no random splits, never. (Same constraint as ARF, restated for clarity.)

## 5. Shadow infrastructure

- **Code location**: new `ml/shadow/` package — `lightgbm_quantile.py` (model wrapper), `update_shadow.py` (nightly retrain + predict), `evaluate_shadow.py` (metrics).
- **Artifacts**: `ml/models/lightgbm_q{10,50,90}_h{1,6,24}.pkl` (9 pickles) + `ml/models/shadow_state.json` (rolling metrics, error history).
- **Output**: separate forecast file `static/data/augur_forecast_shadow.json`, NOT consumed by the dashboard. Same schema as `augur_forecast.json` so downstream consumers can swap by config flag later.
- **Cron**: extend `scripts/daily_update.sh` to run shadow update after the ARF update. ARF prediction continues to drive the dashboard during shadow phase.
- **Eval log**: append-only `ml/shadow/eval_log.jsonl` — one row per nightly evaluation: date, n_overlap_hours, lightgbm_mae, arf_mae, lightgbm_mae_at_low_price, arf_mae_at_low_price, lightgbm_band_coverage_p80, peak_hour_mae_delta.

## 6. Promotion criteria

All three must hold across a contiguous **14-day** shadow window:

| Criterion | Threshold |
|---|---|
| (a) MAE on hours where realised < 30 EUR/MWh | LightGBM beats ARF by ≥ 25% (relative) |
| (b) P10/P90 band empirical coverage | Within [75%, 85%] (target 80%) |
| (c) MAE on weekday evening peak (16–19 UTC) | LightGBM no more than +10% worse than ARF |

Only when all three hold for 14 consecutive days do we promote. Anything weaker is parked, not promoted. Asymmetric promotion bar is intentional — replacing a live system needs a stronger case than introducing a new one.

## 7. Risks & open questions

- **Cold start**: first ~28 days of nightly retraining will see thin training data on negative-price hours unless the bootstrap parquet is reconsolidated to include April 2026. Mitigation: do that consolidation first.
- **Per-quantile crossing**: independent quantile fits can produce P10 > P50 in extrapolation. Mitigation: post-hoc sort `[P10, P50, P90]` per timestamp, or use isotonic post-processing. Document whichever is chosen.
- **Multi-horizon edge cases**: predictions at h+5 (last hour of group 1) and h+6 (first of group 2) may show step-discontinuities. Mitigation: light overlap blending in the boundary hour, or just verify it visually and tolerate small jumps.
- **Computational budget**: 9 models × 672 samples × 300 estimators ≈ a few seconds per nightly retrain on sadalsuud. Should be fine; verify before shipping.
- **Open question — feature pipeline reuse**: `OnlineFeatureBuilder` produces a flat dict for River. LightGBM wants a DataFrame. Adapter needed; trivial.
- **Open question — drift detection**: LightGBM has no built-in drift detector. Rely on rolling-window retraining + the eval log as the drift signal. Acceptable for v1.

## 8. Milestones

| Step | Status | Effort | Output |
|---|---|---|---|
| 0. Reconsolidate parquet through 2026-04-28 | ✅ done 2026-04-28 (local) | 1 h | `training_history.parquet` rebuilt to 5,039 rows; April captured (100 negative-price hours, min −413 EUR/MWh, 0% April NaN). Parquet is gitignored — sadalsuud regenerates separately. |
| 1. `ml/shadow/lightgbm_quantile.py` model wrapper | ✅ done 2026-04-28 (commit `cb5d2f2` on `feat/lightgbm-shadow`) | 2 h | 18 unit tests pass; full repo suite 35/35. `lightgbm>=4.0` added to `requirements.txt` on the same branch. |
| 2. Backtest harness over April 2026 holdout | pending | 2 h | first comparison numbers vs ARF on the regime-shift period |
| 3. Nightly shadow update wired into cron | pending | 2 h | shadow forecast file appearing daily on origin/main |
| 4. 14-day shadow window | pending | 14 d | eval log populated |
| 5. Promotion decision + EXP-009 register or park | pending | — | `experiments/registry.jsonl` updated either way |

Total active work before the 14-day waiting period: roughly one focused day. The waiting period dominates.

## What this plan deliberately does *not* do

- Doesn't change `ml/update.py` ARF behaviour during shadow phase. ARF continues to drive the dashboard until promotion.
- Doesn't add or remove features beyond `renewable_pressure`. Feature engineering is a separate experiment.
- Doesn't ship a dashboard toggle for users to choose forecasts. Single-truth dashboard until promotion.
- Doesn't auto-promote on the 14-day mark — promotion is a manual decision after reading the eval log.

## References

- `docs/river-arf-retrospective.md` — why ARF is being replaced
- `experiments/registry.jsonl` — EXP-001 → EXP-008 (the ARF lifecycle); this becomes EXP-009 after milestone 5
- `ml/features/online_features.py` — feature builder reused as-is
- `ml/data/training_history.parquet` — parquet to be re-consolidated as milestone 0
