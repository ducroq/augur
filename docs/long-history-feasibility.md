# Long-History Warmup — Phase 1 Feasibility

**Branch**: `feat/long-history-warmup`
**Date**: 2026-04-19
**Status**: Scouting — no code written, no APIs called at scale. Decides whether to proceed to ADR + build.

## Premise

The live River ARF model has seen ~64 training days (6,183 samples, 15-min resolution since warmup on 2026-03-26). It has never encountered:

- A winter demand peak
- A summer solar saturation window
- Christmas / New Year / Easter
- A spring regime transition
- Multi-week industrial shutdown patterns

Adding more features to a model that has never seen a full seasonal cycle risks overfitting to the current short window. A long historical warmup is the structurally honest fix.

## Tier boundary

**2025-11-04** — the date `collectors/googleweather.py` was added to energyDataHub and the first `weather_forecast_multi_location.json` file appeared. Before this date we have single-location weather; after, we have the full multi-location feature set the live pipeline uses.

Two-tier strategy:

- **Tier 1 (backfill, 2020→2025-11-03)** — reduced feature set drawn from publicly backfillable sources. Purpose: teach the model seasonality, holidays, crisis regimes, multi-year price level shifts.
- **Tier 2 (live, 2025-11-04→now)** — full current feature set from energyDataHub. Purpose: fine-tune on current market microstructure and rich features unavailable historically.

River ARF's ADWIN drift detection absorbs the regime change at the boundary. Features absent in Tier 1 remain null during Tier 1 replay; tree leaves will only split on them once Tier 2 training begins.

## Source-by-source feasibility

### ENTSO-E Transparency Platform — **feasible**

- **Client**: energyDataHub already uses `entsoe-py` (`EntsoePandasClient`). Supports arbitrary start/end date ranges.
- **Coverage**: NL day-ahead prices from ~2015-01-01. Load forecasts and actuals from ~2015. Generation by type (aggregated) reliable from ~2016. Cross-border flows from ~2015.
- **Auth**: Free API key via email to `transparency@entsoe.eu`. ~24-48h turnaround. **Blocker**: existing keys live on a separate Pi collector host (not on sadalsuud or this dev machine). A dedicated key for this initiative is cleanest.
- **Rate limits**: 400 req/min. Pandas client auto-chunks. A 5-year price pull is ~60 chunks ≈ 10 minutes wall clock.
- **Schema stability**: Stable since 2018; pre-2018 some documents have different EIC codes, but the library handles it.

**What's pullable**:
| Field | Granularity | Coverage |
|---|---|---|
| Day-ahead prices (NL, DE, BE) | 60min | 2015-present |
| Actual load (NL) | 15min/60min | 2015-present |
| Day-ahead load forecast (NL) | 60min | 2015-present |
| Actual generation by type (NL) | 60min | 2016-present |
| Day-ahead generation forecast (wind+solar, NL) | 60min | 2018-present |
| Cross-border physical flows (NL↔DE/BE/UK/NO) | 60min | 2015-present |

### Open-Meteo Historical Archive — **feasible, best free source**

- **Endpoint**: `https://archive-api.open-meteo.com/v1/archive`
- **Backend**: ERA5 reanalysis (hourly, 0.25° grid)
- **Coverage**: 1940-01-01 to ~5 days ago
- **Auth**: None. Rate limit 10,000 req/day (free tier). A single call can return multi-year multi-variable series.
- **Caveat**: Returns **actuals**, not as-of-date forecasts. Using actuals as stand-ins for forecast lags during Tier 1 introduces a subtle form of leakage: the model learns with perfect-knowledge weather. Two mitigations:
  - Add noise calibrated to realistic 24-48h forecast error (from Google Weather / Open-Meteo forecast-vs-actual benchmarks, e.g. temperature MAE ~1.5°C at 24h horizon).
  - Accept the leakage as a Tier-1 bias that Tier-2 retraining corrects — the model will over-weight weather features going in, then be rebalanced by the noisier live forecasts.

**What's pullable for our feature set**: temperature_2m, wind_speed_80m, wind_speed_100m, shortwave_radiation (GHI), cloud_cover, precipitation — all available at our grid points (Eindhoven, Gemini wind farm lat/lon, population centers). Extracting 5 years × 6 variables × 5 locations ≈ 1 request returning ~250MB JSON. Pull in monthly chunks to stay safe.

### TTF gas & EUA carbon — **feasible but degraded**

ICE and EEX no longer publish free EOD settlement CSVs for futures. Realistic free options, in order of quality:

1. **yfinance** — front-month TTF (`TTF=F`) and EUA (`CO2.DE` or `KRBN`) daily closes. History back to ~2017. **Best free option for daily granularity**. Used for Tier 1 features `gas_ttf_price_daily`, `carbon_eua_price_daily` (forward-filled to hourly).
2. **Investing.com historical pages** — scrape; brittle.
3. **Alpha Vantage** — the pipeline already has a key. Supports some commodity tickers but TTF/EUA coverage is spotty.
4. **Manual download** — EEX publishes settlement reports; monthly downloads for 5 years is ~60 files, tractable but tedious.

Recommendation: start with yfinance, daily resolution. Gas/carbon only drive price at daily-to-weekly time scale anyway — sub-daily resolution is not needed.

### Calendar features — **feasible, trivial**

- **Library**: `holidays` (pip), covers NL holidays deterministically back centuries. Includes fixed (Koningsdag) and moving (Easter, Ascension, Whit Monday).
- **School breaks**: `workalendar` or a small hand-maintained CSV from Dutch govt publications (~20 rows/year × 5 years = 100 rows).
- **No API calls needed**. Pure compute from date.

**Proposed feature columns**: `is_holiday`, `is_school_break`, `is_bridge_day`, `is_summer_vacation`, `day_of_year_sin`, `day_of_year_cos`, `week_of_year_sin`, `week_of_year_cos`.

## What Tier 1 does **not** include

| Feature | Why excluded | Impact |
|---|---|---|
| Multi-location Google Weather | Starts 2025-11-04 | Tier 1 uses single-location ERA5 actuals + noise |
| NED production breakdown | NL-specific, short history | Generation-by-type from ENTSO-E covers this partially |
| TenneT grid imbalance | Short history, intraday-only use | Not useful for 72h horizon anyway |
| EZ consumer surcharge | Recent API | Tier 1 trains on wholesale only; surcharge is applied at forecast time |
| Gas flows, gas storage | Short history on our side | GIE has longer history; defer to Tier-2 as-is |
| As-of-date forecast lags | Not archived | Tier 1 uses actuals-as-forecasts with noise |

## Scale & storage

- **Rows**: 5 years × 8760 hours × ~1 row = ~44k rows per series. Price series alone: 44k. With 20 feature columns: 44k × 21 = ~900k cells. **Parquet file: ~5-15 MB**. Trivial.
- **Warmup time**: 44k samples through River ARF `learn_one` at ~500 samples/s (observed on sadalsuud) = ~90 seconds. Tier 1 warmup is fast — earlier estimate of hours was overblown.
- **API pulls total**: ENTSO-E ~60 chunks × 15s = 15 min. Open-Meteo ~60 chunks × 2s = 2 min. yfinance ~2 calls, instant. **Total backfill data collection ≈ 20 minutes wall time.**

## Risks

1. **Regime change at 2022 gas crisis**. Prices went from €50 → €500 → €50 over 18 months. River ARF's trees will see this as extreme outliers. Mitigation: winsorize prices beyond 99.5 percentile for training, keep raw prices for inference. Or: accept the noisy trees, ADWIN will prune.
2. **As-of-date weather leakage** (see Open-Meteo section). Core design risk. Can be measured: train two Tier-1 models, one with noiseless actuals, one with calibrated-noise actuals, compare held-out Tier-2-only MAE.
3. **Target definition drift**. Pre-2025 we only had ENTSO-E prices; current pipeline uses consolidated multi-source with ENTSO-E override. Tier 1 target is pure ENTSO-E day-ahead — matches production target after the 2026-04-02 source-cleanup fix. No drift concern.
4. **Time-zone footguns**. ENTSO-E returns CET; Open-Meteo defaults UTC; holidays library uses local date. Unified on UTC-indexed DataFrames before merge. ADR-001 exists for this.
5. **Cross-contamination with current warmup**. The in-repo `ml/data/consolidate.py` is pointed at energyDataHub's short history. Tier 1 consolidation is a new code path — must not accidentally overwrite or interleave with current training data. Solution: separate module `ml/data/consolidate_tier1.py` and a distinct model directory `ml/models/river_v2/`.

## Recommended next steps

1. **Obtain a fresh ENTSO-E API key** (email registration, 1-2 days). Blocker for anything price-related.
2. **Write ADR-005** — design stance: two-tier, tier boundary 2025-11-04, Tier 1 feature set, leakage mitigation, evaluation gate.
3. **Build `ml/data/consolidate_tier1.py`** with one-source-at-a-time testability. Unit tests mock each external API.
4. **Warmup + backtest** on held-out April 2026 slice. Compare `mae_vs_exchange` and spike recall against current model. Go/no-go gate.

## Decision for this phase

**Feasibility: GREEN**. All sources are accessible, the scale is trivial, and the design risks are measurable rather than architectural. The main non-trivial item is a business-level decision (the weather-leakage tradeoff), which belongs in the ADR, not here.

Next: write ADR-005.
