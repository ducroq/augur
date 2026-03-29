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
- Forecast: 48h wholesale + consumer (auto-derived surcharge ~110.85 EUR/MWh)
- Re-warmup completed 2026-03-28 on full backfilled dataset (4,192 rows, MAE 13.80)
- Legacy `chart.js` deleted — all frontend is modular ES6 in `static/js/modules/`
- Test suite added: 17 tests (SecureDataHandler + OnlineFeatureBuilder)
- energyDataHub: stable, ENTSO-E backfill completed, ~220 days of history
- Major code health sweep completed 2026-03-28 (20 issues fixed across ML, security, frontend)
- Repo cleanup 2026-03-28: removed 33 stale docs/archive files, rewrote README
- Docs structure: CLAUDE.md + docs/RUNBOOK.md + docs/decisions/ + memory/ (agent-ready-projects v1.3.4)
- `/curate` skill installed at `.claude/skills/curate/SKILL.md`

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
| `scripts/netlify_build.sh` | Shared Netlify build script (all contexts) |
| `scripts/daily_update.sh` | Cron script on sadalsuud |
| `tests/` | pytest suite: SecureDataHandler + OnlineFeatureBuilder |

## Recently Promoted

- If EWM variance looks wrong → check that `ewm_mean` (signed) is used, not `ewm_abs` — promoted from code review 2026-03-28
- If exchange prices corrupt lag buffer → ensure they're only pushed once (pre-loop), not also in forecast loop — promoted from code review 2026-03-28

## Active Decisions

- ADR-001: Timezone handling — use `Intl.DateTimeFormat` with Europe/Amsterdam
- ADR-003: Netlify cache --force flag — ensures fresh data on webhook builds
- ADR-004: River ARF online learning over XGBoost batch — continuous learning, no retraining
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast
- Features: selected by Lasso at multiple horizons (1h/6h/24h/48h)
- Dropped temperature (no signal per Lasso), using one NL location per data type
- Exchange prices fed as lag features for first ~29h of forecast
- Noise: client-side Math.random ±5%, transparent to users

## Open Issues

- Augur #2-4: New features (NED, gas, flows), #5: Backtesting, #6-7: Model variants
- Planned ~2026-04-17: Re-warmup with new features (TTF gas, gen mix, gas storage, NED production)
