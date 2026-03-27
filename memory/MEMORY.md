# Memory

## Topic Files

| File | When to load | Key insight |
|------|-------------|-------------|
| `memory/gotcha-log.md` | Stuck or debugging | Problem-fix archive |
| `memory/data-formats.md` | Working with energyDataHub data | Schema v2.1 structure, units, timezone conventions |
| `memory/ml-decisions.md` | ML architecture choices | Original XGBoost plan (superseded by River ARF) |

## Current State

- Restructured from energyDataDashboard to Augur (2026-03-25)
- Dashboard: 5 tabs (Prices, Forecast, Grid, Market, Model) on Netlify
- ML pipeline: **live** — River ARF on sadalsuud, daily cron at 16:45 UTC
- Forecast: 48h wholesale + consumer (auto-derived surcharge), exchange-informed lags
- Confidence bands: EWM error stats (half-life 24h) + volatility scaling (2026-03-27)
- Consumer forecast: orange dotted line, derived from EZ/ENTSO-E overlap (2026-03-27)
- Key metric: vs Exchange MAE = 16.1 EUR/MWh (tracking convergence)
- energyDataHub: stable, collecting daily, ~220 days of history
- energyDataHub issues #5, #6, #7 all resolved (gas TTF, NED, generation mix)

## Key File Paths

| Path | Why it matters |
|------|---------------|
| `ml/features/online_features.py` | Shared feature builder for warmup + daily update |
| `ml/data/consolidate.py` | Parses 220 days of encrypted energyDataHub history |
| `ml/training/warmup.py` | Replays history through River ARF (one-time) |
| `ml/update.py` | Daily entry point: learn + forecast + archive |
| `ml/models/river_model.pkl` | Trained model (committed daily by sadalsuud) |
| `ml/models/state.json` | Model state: last timestamp, error history, price buffer |
| `static/data/augur_forecast.json` | Dashboard forecast output with confidence bands |
| `decrypt_data_cached.py` | Decrypts 10 data files from energyDataHub |
| `scripts/daily_update.sh` | Cron script on sadalsuud |

## Active Decisions

- ADR-001: Timezone handling — use `Intl.DateTimeFormat` with Europe/Amsterdam
- ADR-003: Netlify cache --force flag — ensures fresh data on webhook builds
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast
- Model: River ARF (10 trees), not XGBoost — continuous learning over batch
- Features: selected by Lasso at multiple horizons (1h/6h/24h/48h)
- Dropped temperature (no signal per Lasso), using one NL location per data type
- Exchange prices fed as lag features for first ~29h of forecast
- Noise: client-side Math.random ±5%, transparent to users

## Open Issues

- energyDataHub #5, #6, #7: All resolved (gas TTF, NED, generation mix now collecting)
- Augur #2-4: New features (NED, gas, flows), #5: Backtesting, #6-7: Model variants
- Planned ~2026-04-17: Re-warmup with new features (TTF gas, gen mix, gas storage, NED production)
