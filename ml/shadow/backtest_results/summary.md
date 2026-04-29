# EXP-009 Milestone 2 — Backtest Summary

**Date**: 2026-04-29
**Branch**: `feat/lightgbm-shadow`
**Eval window**: 2026-04-01 → 2026-04-28 inclusive (28 days, 672 hourly predictions)
**Comparison window vs ARF**: 2026-04-14 → 2026-04-28 (14 days; ARF metrics were frozen until the 04-14 forecast-fix commit)

## Setup

- **Model**: `LightGBMQuantileForecaster` (P10/P50/P90, default hyperparams from `LGBMHyperparams`).
- **Training window**: rolling 28 days ending at each evaluation day's 00:00 UTC.
- **Eval mode**: single-horizon, **perfect-lag** — features at hour t use the realized price at t-1, mirroring River ARF's `update_mae` measurement. Iterated 72-hour-ahead behaviour is a different question and is deferred to milestone 3.
- **Features**: 24-column ARF parity set (`features_pandas.FEATURE_COLUMNS`). `renewable_pressure` not yet included — held for an A/B once shadow numbers are stable.
- **Data**: `ml/data/training_history.parquet` (5,039 rows, 2025-09-28 → 2026-04-29 UTC).

## Headline numbers

| Metric | Value |
|---|---|
| Hours predicted | 672 |
| Eval days | 28 |
| **MAE (overall)** | **12.83 EUR/MWh** |
| MAE on hours where realized < 30 EUR/MWh (n=136) | 26.47 |
| MAE on weekday evening peak 16-19 UTC (n=80) | 13.26 |
| **P80 band empirical coverage** | **56.3 %** |
| Mean P80 band width | 25.6 EUR/MWh |

## LightGBM vs ARF (14-day apples-to-apples window)

| | ARF `update_mae` | LightGBM `mae` |
|---|---|---|
| **Mean** | **21.95** | **13.21** |
| Median | 16.07 | 7.27 |
| Worst day (04-26) | 69.05 | 60.72 |
| Best day | 9.18 (04-17) | 5.59 (04-18) |

- **LightGBM wins 14/14 days.** Mean improvement: **46%** (range +12% to +70%).
- The two regime-shift extreme days (04-25, 04-26 — min realized -190 and -413 EUR/MWh) still produce the largest absolute LightGBM errors, but improvement vs ARF holds even there (+21% and +12%).
- The post-regime-shift recovery on 04-27/04-28 is dramatic for LightGBM (12.3 / 8.7 MAE) while ARF stayed near 28-29 — its trees are still anchored on pre-shift leaves.

Per-day detail in `comparison.csv`.

## Promotion criteria — preliminary read

Plan (`docs/lightgbm-quantile-shadow-plan.md` §6) requires all three over a contiguous 14-day shadow window. This milestone-2 backtest is not the formal shadow window, but a directional check:

| Criterion | Threshold | Backtest reading | Verdict |
|---|---|---|---|
| (a) MAE on realized < 30 EUR/MWh, ≥25% better than ARF | LGBM MAE = 26.47 here; ARF slice MAE not directly recoverable from `metrics_history.csv` | LGBM beats ARF on every day in the comparison window, including all the days dominated by sub-30 EUR/MWh hours, so the slice criterion is **almost certainly met** but cannot be rigorously stated until milestone 3 emits ARF's per-slice MAE alongside LGBM's. | **Likely PASS, formally TBD** |
| (b) P10/P90 empirical coverage in [75%, 85%] | 56.3 % | **FAIL.** Bands are too narrow. | **FAIL** |
| (c) Evening peak (Mon-Fri 16-19 UTC) MAE ≤ +10% of ARF | LGBM peak = 13.26; ARF peak-only not in `metrics_history.csv` | Overall ARF mean update_mae over the window was 21.95 → LGBM peak (13.26) is well under that, so unless ARF's peak is unusually low this is comfortably **PASS**. | **Likely PASS, formally TBD** |

**Net**: model quality is materially ahead of ARF on next-hour prediction; the calibration of the uncertainty bands is the open issue.

## What's worth flagging

1. **Bands are miscalibrated under-coverage.** 56% empirical coverage when targeting 80% suggests the rolling 28-day window often does not contain enough variance to teach P10/P90 the true tail width — particularly on regime-shift weeks. Possible mitigations to evaluate in milestone 3:
   - Lengthen the training window (8 weeks?) at the cost of slower regime adaptation.
   - Apply a post-hoc conformal correction (offset bands by recent realized residual quantiles).
   - Train P10/P90 on a longer window than P50 (asymmetric windowing).
   The plan's risk section calls out per-quantile crossing as the band concern; under-coverage is the more urgent finding.

2. **Two extreme days dominate the low-price-slice MAE.** Of the 26.47 MAE on hours where realized < 30, the 04-25/04-26 hours alone account for the bulk. Without those two days, low-slice MAE is in the single digits.

3. **`renewable_pressure` not tested yet.** Plan calls for it as the one additive feature on top of ARF parity. Whether it improves on these numbers is the natural milestone 2.5 ablation before wiring nightly cron.

4. **No iterated-horizon testing yet.** This backtest measures next-hour quality. The deployed shadow forecasts 72 hours ahead — error compounds beyond h+1 once forecast lags feed themselves. That is what the multi-horizon group design (plan §2) addresses; needs validation in milestone 3.

5. **Walk-forward correctness is tested.** `tests/test_backtest.py::test_eval_window_uses_only_past_data_for_training` confirms training cuts off at day_start and the first-hour prediction does not change when eval-day prices are perturbed. No leakage.

## Files

- `predictions.parquet` — 672 rows, [timestamp_utc, eval_day, realized, p10, p50, p90, n_train].
- `per_day_metrics.csv` — daily LightGBM MAE.
- `comparison.csv` — LightGBM vs ARF over the 14-day honest window.
- `summary.json` — machine-readable copy of the headline numbers.
- `compare_arf.py` — repro script for the comparison.

## Decision

**Proceed to milestone 3** (nightly shadow update wired into cron). Open work to fold in along the way:

- Address the band-coverage gap before the 14-day shadow eval starts, otherwise criterion (b) will fail by construction.
- Compute ARF's per-slice MAE alongside LightGBM's so promotion criteria (a) and (c) are formally evaluable rather than directional.
- Consider running a `renewable_pressure` ablation on this same backtest harness before the cron wiring.
