# ML Architecture Decisions

> **STATUS (2026-05-29): historical — superseded by ADR-006.** This file
> captures the original Phase 1 / Phase 2 reasoning (XGBoost → River ARF)
> and the week-ahead horizon thinking from project setup. The production
> system is now LightGBM-Quantile with a 72-hour horizon (see
> `docs/decisions/006-lightgbm-quantile-production-architecture.md`).
> ADR-004 (River) is superseded; ADR-006 (LGBM) is current. ARF still
> runs as a backup signal but no longer drives the dashboard. Keep this
> file as historical record; don't extend it without a "still applies"
> cross-check.

## Why Week-Ahead (168h) Horizon

Day-ahead is academic standard, but week-ahead enables actual scheduling decisions:
- Heat pumps: pre-heat during price valleys, coast through peaks
- EV charging: schedule across cheapest overnight windows over the coming week
- Industrial thermal: plan buffer tank heating around multi-day price patterns

energyDataHub already collects 10-day weather and 7-day solar/wind forecasts to support this horizon.

## Why XGBoost First (Phase 1)

- Fast training, no GPU required
- Strong baseline for tabular time-series features
- Easy feature importance analysis to validate feature engineering
- Academic benchmarks show ~9% MAE for day-ahead energy prices
- Can train on ~160 days of data (growing daily)

## Why River for Online Learning (Phase 2)

- `predict_one()` then `learn_one()` — natural fit for daily data arrival
- ARFRegressor (Adaptive Random Forest) handles concept drift
- No need to retrain from scratch — model improves incrementally
- Built-in ADWIN drift detection for Phase 3

## Why Not Wait for More Data

~160 days is enough for an initial XGBoost. Key insight: start learning now, improve continuously. Online learning means the model gets better every day without manual intervention. Waiting for "enough" data is a trap — there's always more to collect.

## Feature Strategy

Price lags capture temporal patterns:
- t-1, t-2, t-3: recent momentum
- t-24: daily pattern
- t-168: weekly seasonality (critical for week-ahead)

Rolling statistics (6h, 12h, 24h, 48h, 168h windows) capture volatility and trends.
Calendar features use cyclical sin/cos encoding for hour and day-of-week.
