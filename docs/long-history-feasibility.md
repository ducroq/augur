# Long-History Warmup — Phase 1 Feasibility

**Branch**: `feat/long-history-warmup`
**Date**: 2026-04-19
**Status**: Scouting complete with measured probes. Decision pending ADR-005.

## Premise

The live River ARF model has seen ~64 days of training data (6,183 samples since warmup on 2026-03-26). It has never encountered a winter demand peak, summer solar saturation, Christmas/New Year, Easter, a spring regime transition, or multi-week industrial shutdown patterns. Adding more features before the model has seen a full seasonal cycle risks overfitting to the current short window.

## Surprise finding — tier boundary may not be needed

The original plan assumed a boundary at **2025-11-04** (day `collectors/googleweather.py` was added to energyDataHub and first `weather_forecast_multi_location.json` appeared). On audit:

- `ml/update.py:93-95` reads `weather_forecast_multi_location.json` and calls `parse_weather_file(...)` → extracts **only NL temperature**.
- `ml/features/online_features.py:149-151` does **not** use temperature. Per `memory/ml-pipeline.md`: "Dropped: temperature (no signal per Lasso)."
- Augur's actual exogenous features are `wind_speed_80m` (from `wind_forecast.json`), `solar_ghi` (from `solar_forecast.json`), `load_forecast` (from `load_forecast.json`). All three sources predate the 2025-11-04 boundary and are fully backfillable from their original suppliers (ENTSO-E for load, Open-Meteo for wind/solar).

**Implication**: single-tier long warmup using the current feature set is viable. No tier boundary, no regime-change handling, no leakage comparison study. The design simplifies significantly.

The open question is whether wind/solar **forecast** data (not actuals) is obtainable historically. Open-Meteo archive returns ERA5 actuals — same leakage concern as before — but this is one decision about feature construction, not a two-tier architecture.

## Measured probe results

All probes executed 2026-04-19 against live APIs.

### Probe 1: ENTSO-E Transparency — **working**

| Query | Period | Result | Wall |
|---|---|---|---|
| NL day-ahead prices | Jan 2015 week | 169 rows | 0.5s |
| NL actual load | Jan 2018 week | 672 rows (15-min) | 0.7s |
| NL wind+solar day-ahead forecast | Jan 2019 week | 672 rows, cols `Solar, Wind Offshore, Wind Onshore` | 1.5s |
| NL generation by type | Jan 2019 week | 672 rows, multi-index cols (Biomass, Fossil Gas, Hard Coal, ...) | 3.2s |
| NL day-ahead prices | Jan 2020 week | transient 503 | — |

- **API key**: pulled from `C:\Users\scbry\HAN\HAN H2 LAB IPKW - Projects - WebBasedControl\01. Software\energyDataHub\secrets.ini` → `[api_keys].entsoe`. Works without modification to `entsoe-py` pandas client.
- **2015 boundary confirmed**: earliest probed week (Jan 5-12, 2015) returns data.
- **503 errors are transient**: one of five calls hit a 503 Service Unavailable. Must wrap every call in retry logic (exponential backoff). Not a blocker.
- **Security note**: the ENTSO-E library encodes the API token in the query URL (`securityToken=...`). 503 errors echo the URL back — any logs or tracebacks that capture these responses will leak the key. Production code must redact.
- **Call sizes**: a week of hourly data is one API call ≈ 1-3s. A 5-year pull is ~260 weekly calls ≈ 10-15 minutes wall time with retries.

### Probe 2: Open-Meteo archive — **best-in-class free source**

| Query | Result | Wall |
|---|---|---|
| Eindhoven (51.44, 5.47), Jan 2020 week, 4 vars | 168 rows | 0.5s |
| Offshore point (54.0, 5.97) near Gemini wind farm, Jan 2020 week | 168 rows, wind_speed_100m available | 0.1s |
| **Eindhoven 5 years (2020-2024), 2 vars, single call** | **43,848 rows** | **0.5s** |

- No API key, no rate-limit hit during scouting.
- Single-call multi-year pulls work — the earlier plan to chunk monthly is unnecessary. A full 5-year pull for our 3-5 grid points × 5-6 variables is a handful of requests, ~5 seconds total wall time.
- Returns **actuals** (ERA5 reanalysis), not as-of-date forecasts. See leakage note below.

### Probe 3: Gas / carbon — **mixed**

| Source | Series | Result |
|---|---|---|
| yfinance `TTF=F` (Natural Gas Dutch TTF) | 6 months | ✓ 124 daily rows |
| yfinance `EUA=F`, `CO2.DE`, `CARBON.L`, `FEUA.L` | any | ✗ all 0 rows (delisted / wrong tickers) |
| Alpha Vantage `NATURAL_GAS` endpoint | monthly history | ✓ 351 rows (but this is Henry Hub US, not TTF EU) |

- **TTF front-month via yfinance works**. Key already in the pipeline config (not needed — no auth on yfinance).
- **EUA carbon has no free yfinance ticker**. Options: Sandbag/Ember public CSV (annual), EEX manual downloads, scrape Investing.com, or **omit EUA from Tier 1** (TTF alone carries most of the cross-commodity price signal pre-2022; independent EUA signal matters mainly in the 2022-2023 crisis).
- **Recommendation**: start with TTF only. Revisit EUA if backtests show 2022-2023 performance is weak.

### Probe 4: Augur feature audit — **already covered above**

The critical finding: Augur's features do not depend on the multi-location weather introduction. Tier boundary is structural hypothesis that didn't survive contact with the code.

### Probe 5: River ARF throughput — **measured on sadalsuud**

- **322 samples/s** (`learn_one + predict_one`, 30 synthetic features, 10-tree ARF Regressor with StandardScaler pipeline).
- 5-year hourly warmup (~44k samples): **~2.3 minutes** wall.
- 3-year 15-minute warmup (~105k samples): **~5.5 minutes** wall.
- My earlier "~500 samples/s / 90 seconds" estimate was optimistic by ~1.5×. Conclusion unchanged: warmup time is trivial.

## Revised proposal — single-tier long warmup

Since the tier boundary doesn't load-bear, the proposal collapses to:

1. **Historical data module** `ml/data/consolidate_historical.py` (separate from the current `consolidate.py`) pulls from authoritative sources:
   - ENTSO-E: day-ahead prices (target), load actuals, load forecast, wind+solar day-ahead forecast
   - Open-Meteo archive: `wind_speed_100m` at offshore point, `shortwave_radiation` at Eindhoven (with calibrated noise to approximate forecast error)
   - yfinance: TTF front-month daily, forward-filled to hourly
   - `holidays`: NL calendar features
2. **Feature builder** uses the same `online_features.py` as production — no Tier 1/Tier 2 split.
3. **Warmup script** `ml/training/warmup_historical.py` replays chronologically through River ARF → produces `ml/models/river_v2/river_model.pkl`.
4. **Backtest** on a held-out slice of 2026 data (e.g., April only) compares `mae_vs_exchange` between current model and v2.

Time to first measurable backtest number: ~1-2 days of code plus 5-10 minutes of data collection and training.

## Design risks (reduced from prior version)

1. **Weather-forecast leakage** — still relevant. ERA5 actuals used as wind/solar "forecast" lags during warmup give the model perfect-knowledge weather. Mitigation: apply calibrated noise per horizon. A realistic budget (from published weather-forecast-skill studies):
   - temperature MAE: ~1.0°C at 24h, ~2.0°C at 72h, ~3.5°C at 168h
   - wind MAE: ~1.5 m/s at 24h, ~3.0 m/s at 72h
   - Actual benchmark against our live pipeline is TBD — but this is feature engineering, not architecture.
2. **2022 gas crisis regime**. Prices went from ~€50 → peaks of ~€700 → back to ~€50 over 18 months. River ARF with ADWIN may handle this, or may get destabilized. Mitigations under consideration: winsorize training prices beyond p99.5; reset model at crisis boundaries; or simply let it run and measure.
3. **Target definition**: production target is ENTSO-E day-ahead (post the 2026-04-02 source-cleanup fix). Historical target is also ENTSO-E day-ahead. No drift concern — clean match.
4. **State file bloat**. `ml/models/state.json` has bounded `error_history` (500) and `metrics_history` (365). A 44k-sample warmup overflows both. Solution: reset both to empty at the end of warmup; `warmup_historical` does not populate these (they're daily-cron-only). No code change needed in `update.py` beyond using `river_v2/` paths.
5. **503 retry & key redaction**. ENTSO-E API has transient 503s and leaks tokens in error URLs. Backfill script must retry with exponential backoff and redact query strings from any logged exceptions.

## Decision — GREEN

- All three external sources (ENTSO-E, Open-Meteo, yfinance TTF) reachable and verified.
- Scale is trivial (~10 min data pull, ~3-6 min warmup).
- Tier-boundary complexity was unnecessary — single long warmup suffices.
- Remaining risks are feature-engineering tradeoffs (weather noise, EUA omission) and code hygiene (retry + key redaction), not architecture.

## Next step

Write **ADR-005** — design stance for a single-tier long warmup, feature set, weather-leakage mitigation, evaluation gate, rollback plan. Then code.
