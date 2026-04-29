# Memory

<!-- Loaded every session. Keep lean — index only, deep knowledge in topic files.
     END-OF-SESSION: review gotcha-log, promote patterns, retire stale entries. -->

## Topic Files

| File | When to load | Key insight |
|------|-------------|-------------|
| `memory/gotcha-log.md` | Stuck or debugging | Problem-fix archive |
| `memory/data-formats.md` | Working with energyDataHub data | Schema v2.1 structure, units, timezone conventions |
| `memory/ml-decisions.md` | ML architecture choices | Original XGBoost plan (superseded by River ARF — see ADR-004) |

## Current State

- Dashboard: 5 tabs (Prices, Weather, Grid, Market, Model) on Netlify
- ML pipeline: **live** — River ARF on sadalsuud, daily cron at 16:45 UTC
- ARF retired 2026-04-28 (EXP-008) — structural ceiling on negative-price prediction; cron continues running until shadow validation completes
- LightGBM-Quantile shadow plan documented (`docs/lightgbm-quantile-shadow-plan.md`); EXP-009 milestones 0+1 complete locally on `feat/lightgbm-shadow` (cb5d2f2); milestones 2-5 pending
- ENTSO-E collector recovered ~2026-04-18 after 03-26 outage; guard in `parse_price_file()` remains
- Forecast: 72h wholesale + consumer (auto-derived surcharge ~110.85 EUR/MWh)
- Re-warmup completed 2026-03-28 on full backfilled dataset (4,192 rows, MAE 13.80)
- Test suite: 35 tests passing (SecureDataHandler + OnlineFeatureBuilder + LightGBMQuantileForecaster on `feat/lightgbm-shadow`)
- Experiment registry: EXP-001..EXP-008 back-filled in `experiments/registry.jsonl`; EXP-009 prospective
- Docs structure: CLAUDE.md + docs/RUNBOOK.md + docs/decisions/ + docs/river-arf-retrospective.md + memory/
- agent-ready-projects: v1.9.0

## Recently Promoted

- If EWM variance looks wrong → check that `ewm_mean` (signed) is used, not `ewm_abs` — promoted from code review 2026-03-28
- If exchange prices corrupt lag buffer → ensure they're only pushed once (pre-loop), not also in forecast loop — promoted from code review 2026-03-28

## Active Decisions

- ADR-001: Timezone handling — use `Intl.DateTimeFormat` with Europe/Amsterdam
- ADR-003: Netlify cache --force flag — ensures fresh data on webhook builds
- ADR-004: River ARF online learning over XGBoost batch — superseded 2026-04-28 by EXP-008/EXP-009 (LightGBM-Quantile shadow plan)
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast
- Features: selected by Lasso at multiple horizons (1h/6h/24h/48h)
- Dropped temperature (no signal per Lasso), using one NL location per data type
- Exchange prices fed as lag features for first ~29h of forecast
- Noise: client-side Math.random ±5%, transparent to users

## Open Issues

- EXP-009: LightGBM-Quantile shadow validation — milestones 2-5 (backtest harness, cron wiring, 14-day shadow window, promotion decision). Plan: `docs/lightgbm-quantile-shadow-plan.md`.
- EXP-007 (parked, `feat/new-features-ttf-genmix`): Phase 1 TTF + genmix gave −1.28 EUR/MWh MAE, below the ≥2 gate. Revisit when ~60 days of genmix history accumulates (late May 2026) or in a harder holdout.
- #2-4: New ML features (NED production, gas/carbon prices, cross-border flows)
- #5: Backtesting framework from archived forecasts
- #6-7: Model variants (peak/off-peak, larger ARF ensemble or Prophet)
- #8-10: Product expansion (SaaS API, ensemble forecasting, multi-country)
