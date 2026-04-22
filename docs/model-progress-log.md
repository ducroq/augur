# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-04-22 — New-feature readiness audit (investigation, no code change)

**Trigger**: With ADR-005 long-history warmup paused, re-opened the question of whether to add new energyDataHub sources as features to the live River ARF: `market_history` (TTF gas + carbon EUA), `generation_mix`, `gas_storage`, `gas_flows`, `ned_production`.

**Method**: Pulled the HAN `energyDataHub/` checkout, counted daily files per source, cross-referenced the fetcher log's last DQ report (2026-03-31), and checked ADR-005's "out of scope" caveat.

**Findings (file-count precheck after pull, all 4 sources now current through 2026-04-21):**

| Source | Days covered | File-count precheck | DQ notes from last log |
|---|---|---|---|
| market_history (TTF+carbon) | 26 (2026-03-27→04-21) | borderline | TTF=26 days, **carbon=1 day** — completeness error (17%) |
| generation_mix | 26 | borderline | passed DQ |
| gas_storage | 91 | pass | value-range errors (24 vals outside [0,100]%) + staleness |
| gas_flows | 92 | pass | passed DQ |
| ned_production | 142 | pass | completeness error (25%) |

**Strategic caveat**: ADR-005 explicitly deferred TTF/cross-border/gas-storage features "until v2 cutover is evaluated". With v2 paused, that guidance is stale and this question is legitimately re-open. The mini-warmup's calibrated-noise surprise suggests low-importance features won't dramatically move MAE either way — Lasso will downweight weak signals.

**Operational gotcha uncovered**: HAN OneDrive checkout had not been pulled since 2026-03-31, creating a 22-day phantom gap that nearly caused a false "collection stopped" alarm. Added gotcha entry and feedback memory to always `git pull` before reasoning about data freshness.

**Recommended next step (not executed)**: Phase-1 scope of **TTF gas + generation_mix only** (both pass DQ, cleanest story). Defer carbon (needs backfill), ned_production and gas_storage (active DQ errors). Before committing to Phase 1, re-check `data_quality_report.json` for the latest DQ status rather than the stale March log.

**Outcome**: No code change; investigation captured here and in auto-memory `project_new_features_rewarmup.md` so the next session inherits scope and blockers.

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
