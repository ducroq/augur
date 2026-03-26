# Augur

Energy price forecasting platform for the Netherlands. Combines data from 18+ APIs (via energyDataHub), ML-based week-ahead price predictions, and an interactive dashboard for smart consumption (heat pumps, EV charging, industrial thermal).

- **Stack**: Python 3.12 (ML pipeline), Hugo + Plotly.js (dashboard), XGBoost + River (forecasting)
- **Status**: Restructuring — dashboard production, ML pipeline scaffolded
- **Repo**: github.com/ducroq/augur
- **agent-ready-projects**: v1.2.0

## Before You Start

| When | Read |
|------|------|
| Working on ML features or training | `ml/features/builder.py` — feature engineering, `ml/training/trainer.py` — model lifecycle |
| Changing the dashboard or chart rendering | `static/js/modules/` — use modular JS, NOT legacy `chart.js` |
| Changing deployment or build pipeline | `docs/RUNBOOK.md` — Netlify build, --force flag, webhook flow |
| Making architectural decisions | `docs/decisions/` — ADR index |
| Stuck or debugging something weird | `memory/gotcha-log.md` — problem-fix archive |
| Working with energyDataHub data formats | `memory/data-formats.md` — schema v2.1, units, timezone conventions |
| Ending a session | `memory/gotcha-log.md` — review, promote patterns, retire stale entries |

## Hard Constraints

- Never commit encryption keys or secrets — keys are base64-encoded env vars (`ENCRYPTION_KEY_B64`, `HMAC_KEY_B64`)
- Never modify legacy `chart.js` — all new frontend work goes in `static/js/modules/`
- Never use hardcoded +2h timezone offset — use `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'`
- Never claim tests pass without running them. Never claim a file exists without reading it.
- Always verify HMAC before decryption — data integrity is non-negotiable
- ML models must use temporal train/val/test splits, never random — time series data leaks across random splits
- The `--force` flag in `decrypt_data_cached.py` must remain in the Netlify build command — without it, webhook-triggered builds reuse stale cached data

## Decision Framework

Before completing a task, self-assess:
- **PASS**: Tests pass, constraints respected, code matches project patterns
- **REVIEW**: Touches encryption, build pipeline, data schemas, or ML model architecture — flag for human review
- **FAIL**: Tests fail, constraints violated, or approach contradicts an ADR — stop and discuss

## Architecture

```
energyDataHub (separate repo, 18+ API collectors)
    │ daily 16:00 UTC, encrypted JSON → GitHub Pages
    │
    ▼
sadalsuud (daily cron 16:45 UTC)
    ├── git pull energyDataHub
    ├── python -m ml.update              → learn new prices, generate forecast
    ├── git push augur                   → triggers Netlify rebuild
    │
    ▼
Augur Netlify build
    ├── decrypt_data_cached.py --force   → static/data/*.json (10 files)
    ├── hugo --minify                    → public/
    └── Netlify CDN deploy

Client browser (https://energy.jeroenveen.nl):
    ├── 5 tabs: Prices, Forecast, Grid, Market, Model
    ├── loads forecast + augur_forecast.json from /data/
    ├── fetches live Energy Zero API (every 10 min)
    └── renders Plotly.js charts with noise
```

### ML Pipeline (live)
- **Model**: River ARFRegressor (10 trees), continuous online learning
- **Features**: Lasso-selected — price lags, rolling stats, wind speed, solar GHI, load forecast
- **Target**: ENTSO-E NL wholesale day-ahead price (EUR/MWh)
- **Forecast**: 48h with 80% confidence band, exchange-informed lags
- **Convergence metric**: vs Exchange MAE (tracking daily)
- **Forecast archive**: timestamped copies in `ml/forecasts/` on sadalsuud

## Key Paths

| Path | What it is |
|------|-----------|
| `ml/features/online_features.py` | Shared feature builder for warmup + daily update |
| `ml/data/consolidate.py` | Parses encrypted energyDataHub history into training parquet |
| `ml/training/warmup.py` | One-time historical replay through River ARF |
| `ml/update.py` | Daily entry point: learn + forecast + archive |
| `ml/models/river_model.pkl` | Trained model artifact (committed daily by sadalsuud) |
| `ml/models/state.json` | Model state: timestamps, error history, price buffer |
| `static/js/dashboard.js` | Modular dashboard entry point (preferred) |
| `static/js/modules/` | ES6 modules: api-client, chart-renderer, data-processor, etc. |
| `static/js/chart.js` | Legacy monolith — DO NOT MODIFY, pending deprecation |
| `decrypt_data_cached.py` | Production decryption with caching + --force |
| `utils/secure_data_handler.py` | AES-CBC-256 + HMAC-SHA256 |
| `netlify.toml` | Build pipeline: decrypt → infer → hugo |
| `layouts/index.html` | Dashboard HTML template |
| `static/css/style.css` | Glassmorphism dark theme |

## How to Work Here

```bash
# Install dependencies
pip install cryptography pandas numpy xgboost
npm install

# Set encryption keys (Windows PowerShell)
$env:ENCRYPTION_KEY_B64 = "your_key"
$env:HMAC_KEY_B64 = "your_key"

# Fetch and decrypt data
python decrypt_data_cached.py --force

# Run ML inference (once model trained)
python -m ml.inference

# Dev server
hugo server -D
# Visit http://localhost:1313

# Production build
hugo --minify
```
