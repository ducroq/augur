# Augur

Energy price forecasting platform for the Netherlands. Week-ahead predictions for smart energy consumption — heat pumps, EV charging, and industrial thermal processes.

## What It Does

Augur combines data from 18+ energy market APIs with machine learning to forecast electricity prices up to one week ahead. The interactive dashboard helps users optimize energy-intensive activities around predicted price valleys.

```
energyDataHub (18+ APIs)          Augur ML Pipeline              Dashboard
┌──────────────────────┐    ┌─────────────────────────┐    ┌──────────────────┐
│ ENTSO-E, EnergyZero  │    │ Feature engineering      │    │ Hugo + Plotly.js │
│ EPEX, Elspot, TenneT │───>│ XGBoost week-ahead      │───>│ Interactive chart │
│ Weather, Grid, Gas   │    │ Online learning (River)  │    │ Netlify CDN      │
└──────────────────────┘    └─────────────────────────┘    └──────────────────┘
```

## Features

- **Week-ahead price forecasts** (168 hours) targeting scheduling decisions
- **Multi-source price comparison**: ENTSO-E, Energy Zero, EPEX SPOT, Nord Pool Elspot
- **Live data**: Energy Zero real-time prices refresh every 10 minutes
- **Continuous learning**: Model improves daily as new price data arrives
- **Interactive charts**: Zoom, pan, hover — powered by Plotly.js
- **Secure data pipeline**: AES-CBC encryption with HMAC verification

## Quick Start

### Prerequisites
- [Hugo](https://gohugo.io/) v0.124.0+
- Python 3.11+ with `pip`
- Encryption keys from [energyDataHub](https://github.com/ducroq/energydatahub)

### Setup
```bash
git clone https://github.com/ducroq/augur.git
cd augur
npm install
pip install cryptography pandas numpy xgboost
```

### Run Locally
```bash
# Set encryption keys
export ENCRYPTION_KEY_B64="your_key"
export HMAC_KEY_B64="your_key"

# Fetch and decrypt data
python decrypt_data_cached.py --force

# Start dashboard
hugo server -D
# Visit http://localhost:1313
```

## Architecture

### Data Collection (energyDataHub)
External repo collecting from 18+ APIs daily at 16:00 UTC:
- **Prices**: ENTSO-E, EnergyZero, EPEX, Elspot, TenneT (hourly/15-min)
- **Renewables**: Wind generation, offshore wind, solar irradiance forecasts
- **Weather**: 10-day forecasts for 6 strategic + 11 population center locations
- **Grid**: Cross-border flows, load forecasts, nuclear availability
- **Market**: Gas/carbon prices, gas storage levels

### ML Pipeline (`ml/`)
- **Features** (`ml/features/builder.py`): Price lags, rolling statistics, cyclical calendar encoding, weather, grid, and market features
- **Training** (`ml/training/trainer.py`): XGBoost batch training (Phase 1), River online learning (Phase 2)
- **Inference** (`ml/inference.py`): Runs at build time, outputs `augur_forecast.json`

### Dashboard
- Hugo static site with Plotly.js charts
- Deployed on Netlify, auto-rebuilds on new data
- Modular ES6 JavaScript architecture (`static/js/modules/`)

## ML Roadmap

| Phase | What | Status |
|-------|------|--------|
| 1 | XGBoost batch baseline on accumulated data | Next |
| 2 | River online learning with daily updates | Planned |
| 3 | Drift detection (ADWIN + Page-Hinkley) | Planned |
| 4 | Model performance monitoring | Planned |

## Project Structure

```
augur/
├── ml/                          # ML forecasting pipeline
│   ├── features/builder.py     # Feature engineering
│   ├── training/trainer.py     # Model training lifecycle
│   ├── models/                  # Trained artifacts (gitignored)
│   └── inference.py             # Build-time inference
├── layouts/                     # Hugo templates
├── static/
│   ├── js/modules/              # Modular dashboard JS
│   ├── css/style.css            # Glassmorphism dark theme
│   └── data/                    # Generated forecast data
├── utils/                       # Python shared utilities
├── docs/                        # Architecture docs & ADRs
├── decrypt_data_cached.py       # Production decryption
├── hugo.toml                    # Hugo config
├── netlify.toml                 # Netlify build pipeline
└── package.json
```

## Live Dashboard

**https://energy.jeroenveen.nl/** — Hosted on Netlify, auto-deploys from this repo.

## Related Projects

- **[energyDataHub](https://github.com/ducroq/energydatahub)** — Data collection backend (18+ API collectors)

## License

MIT
