# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-04-23 — Phase 1 new-feature A/B: TTF gas + NL genmix lag24h (parked)

**Trigger**: Follow-up to the 2026-04-22 readiness audit. Implemented the recommended Phase 1 scope (TTF gas + NL generation mix) end-to-end on branch `feat/new-features-ttf-genmix` and ran a baseline-vs-Phase-1 backtest.

**Feature set added** (all via `ml/data/consolidate.py` → `ml/features/online_features.py`):
- `gas_ttf_eur_mwh` — daily yfinance TTF close, anchored to next-day 00:00 UTC (leakage-safe), 72h ffill through weekends
- `gen_nl_fossil_gas_mw_lag24h` — NL fossil-gas actual at H-24h (marginal price-setter)
- `gen_nl_wind_total_mw_lag24h` — onshore + offshore wind actual at H-24h
- `gen_nl_solar_mw_lag24h` — NL solar actual at H-24h
- `gen_nl_renewable_share_lag24h` — (wind+solar+hydro) / total at H-24h

**Design note — actual→+24h shift instead of forecast**: energyDataHub's `entsoe_genmix_collector` runs over `yesterday→today`, so the file contains only `_actual` fields (no `_forecast`). Using same-hour actuals as features for same-hour price would be leakage; shifting +24h models "yesterday's same-hour realized mix", which is legitimately available at inference time for a day-ahead price forecast.

**A/B harness** (new files): `ml/training/warmup_p1.py` (+ `--baseline` flag) and `ml/evaluation/backtest_p1.py`, both writing to `ml/models/river_p1/` or `ml/models/river_baseline/` so the production model at `ml/models/river_model.pkl` is untouched. Same parquet, same split timestamps, identical River ARF hyperparameters (n=10, seed=42).

**Experiment**:

| | |
|---|---|
| Training | 2026-03-27 → 2026-04-17 UTC, 480 rows (24 skipped for missing lags) |
| Holdout | 2026-04-17 → 2026-04-23 UTC, 166 rows |

**Results (holdout backtest)**:

| Metric | Baseline | Phase 1 | Δ |
|---|---|---|---|
| MAE  | 15.15 | 13.87 | **−1.28** EUR/MWh |
| MAPE | 139.2% | 131.0% | −8.2 pp |
| RMSE | 20.12 | 18.51 | −1.61 |
| Spike recall (n=4) | 1.0 | 1.0 | — |

**Verdict — park, don't merge.** Phase 1 features move MAE, MAPE, and RMSE all in the right direction but the MAE improvement of 1.28 EUR/MWh is below the ADR-005 decision gate of ≥2 EUR/MWh. Also: holdout baseline MAE (15.15) is notably lower than the training-window rolling MAE (~20), suggesting the April holdout is an "easy" period — the 1.28 gap could easily be noise at n=166.

**Operational findings worth banking**:
- HAN OneDrive checkout had drifted 4 commits + 3 merge bubbles; now reset to `origin/main` with `pull.ff=only` to fail loudly on future drift.
- TTF lives inside `market_history.gas_ttf.data` as a date-keyed dict; the parent `market_history` DQ error is specifically about the carbon sub-field, not TTF.
- Effective genmix coverage is only ~26 days (file count in HAN), so Phase 1 is data-limited. Re-run makes sense once ~2 months of history has accumulated.

**Status**: banked on `feat/new-features-ttf-genmix`. Revisit when ≥60 days of genmix history is available or if Phase 1.5 (DE/BE mix) is scoped.

---

## 2026-04-14 — Forecast collapse: model outputs flat mean

**Trigger**: Noticed the live forecast on the dashboard barely moves — temporal price swings are suppressed. The model outputs what looks like an average price estimate regardless of time of day.

**Evidence**:

| Metric | Value |
|--------|-------|
| Actual price range (buffer, 200 pts) | -2.09 to 213.31 EUR/MWh (range 215) |
| 72h forecast range | 108.94 to 133.08 EUR/MWh (range 24) |
| Forecast std dev | 5.12 EUR/MWh |
| Range compression | ~89% — nearly flat output |

Daily `update_mae` has been running 25-36 EUR/MWh since April 3, roughly 2-3x the warmup-era MAE.

### Root cause 1: Recursive forecast loop (architectural)

`generate_forecast()` in `ml/update.py:258-298` predicts hour-by-hour and **feeds each prediction back as a lag feature for the next hour**. Combined with MSE-based tree splits (River ARF default), predictions regress toward the mean at every step. Over 72 hours this compounds into a flat line around ~119 EUR/MWh.

The exchange day-ahead prices (~24h horizon) partially mask this — the first day of forecast has real lags and looks reasonable. But beyond the exchange horizon, every lag is a stale prediction, and the forecast collapses.

### Root cause 2: Frozen aggregate metrics (bug)

`update_model()` in `ml/update.py:191-195` writes the metrics history but copies `mae` and `last_week_mae` from existing state instead of recalculating them:

```python
"mae": round(state["metrics"].get("mae", mae), 2),        # frozen at 13.8 since warmup
"last_week_mae": round(state["metrics"].get("last_week_mae", mae), 2),  # frozen at 21.12
```

These have been stuck at warmup values (13.8 / 21.12) since April 2, while real daily errors were 25-39. The degradation was invisible in the dashboard metrics.

### Possible remedies (under consideration)

1. **Direct multi-horizon models** — Train separate models for h+1, h+6, h+24 etc., each predicting directly from current known features. No recursive lag feeding, no mean collapse.
2. **Exchange price anchoring** — Beyond the exchange horizon, anchor lags to last known exchange price rather than recursive predictions.
3. **Loss function change** — ARFRegressor uses variance reduction (MSE). A MAE/quantile objective would reduce mean-reversion bias, but River ARF doesn't expose this easily.
4. **Fix the frozen metrics** — Recalculate `mae` and `last_week_mae` from `error_history` each update so degradation is visible immediately.

### Context

- Model was rolled back to pre-contamination checkpoint on April 2 (commit `27b9876`) after ENTSO-E collector outage caused 5 days of training on wrong price series (Energy Zero consumer prices instead of wholesale).
- Model has been retraining daily since then (5703 samples as of April 13), but the recursive forecast architecture means even a healthy model will produce flat multi-day predictions.
- Model pickle shrank from 1.75 MB to 616 KB at some point — may indicate tree pruning or state loss.

---

## 2026-04-14 — Fix: variance-preserving recursion + metrics bug

**Changes** (`ml/update.py`):

1. **Fixed frozen metrics bug** — `mae` and `last_week_mae` were copied from stale warmup values on every update instead of being recalculated. Now recomputed from `error_history` (last 500 errors for MAE, last 168 for weekly MAE) on each daily run.

2. **Historical rolling stats override** — Added `_historical_rolling_stats(fb)` helper that computes typical price mean/std by hour-of-day from the real price buffer. During recursive forecasting (beyond exchange horizon), `price_rolling_mean_6h` and `price_rolling_std_6h` are overridden with these historical values instead of being computed from artificial predictions. Prevents the rolling stats from collapsing to near-zero variance.

3. **Calibrated noise injection** — When feeding a prediction back as a lag for the next forecast hour, noise drawn from `N(0, ewm_std)` is added. `ewm_std` is the model's own exponentially-weighted error standard deviation (already computed for confidence bands). This prevents correlated lag sequences from converging to the mean. RNG seeded per-hour for reproducibility.

**Rationale**: The model was trained on real data with natural price variance. Recursive predictions created an out-of-distribution input pattern (smooth, correlated lags and collapsed rolling stats). These fixes restore realistic variance in the feature space without changing the model itself.

**What was NOT changed**: Model training path (warmup + learn_one), feature builder, exchange-horizon forecasts (first ~24h still use real lags), model artifact.

**Expected outcome**: Wider forecast range beyond exchange horizon. Actual improvement measurable after next daily update on sadalsuud.

---
