# Augur

Energy price forecasting platform for the Netherlands. Combines data from 18+ APIs with online machine learning to forecast electricity prices 48 hours ahead.

**Live dashboard**: https://energy.jeroenveen.nl/

```
energyDataHub (18+ APIs)          Augur ML Pipeline              Dashboard
┌──────────────────────┐    ┌─────────────────────────┐    ┌──────────────────┐
│ ENTSO-E, EnergyZero  │    │ Feature engineering      │    │ Hugo + Plotly.js │
│ EPEX, TenneT, NED    │───>│ River ARF (online)       │───>│ 5-tab dashboard  │
│ Weather, Grid, Gas   │    │ Daily learn + forecast   │    │ Netlify CDN      │
└──────────────────────┘    └─────────────────────────┘    └──────────────────┘
```

## Features

- **48-hour price forecast** with confidence bands, updated daily
- **Wholesale + consumer pricing**: auto-derived surcharge from EZ/ENTSO-E overlap
- **Live data**: Energy Zero real-time prices refresh every 10 minutes
- **Continuous learning**: River ARFRegressor improves daily as new prices arrive
- **5 dashboard tabs**: Prices, Weather, Grid, Market, Model
- **Secure pipeline**: AES-CBC-256 encryption with HMAC-SHA256 verification

## Quick Start

```bash
git clone https://github.com/ducroq/augur.git
cd augur
pip install -r requirements.txt
npm install

# Set encryption keys
export ENCRYPTION_KEY_B64="your_key"
export HMAC_KEY_B64="your_key"

# Fetch and decrypt data
python decrypt_data_cached.py --force

# Run tests
python -m pytest tests/ -v

# Start dashboard
hugo server -D
# Visit http://localhost:1313
```

## Project Structure

```
augur/
├── ml/                          # ML forecasting pipeline
│   ├── features/online_features.py  # Shared feature builder
│   ├── training/warmup.py       # Historical replay through River ARF
│   ├── data/consolidate.py      # energyDataHub → training parquet
│   ├── update.py                # Daily entry point: learn + forecast
│   └── models/                  # Trained model + state
├── layouts/                     # Hugo templates
├── static/
│   ├── js/modules/              # Modular ES6 dashboard
│   ├── css/style.css            # Dark theme
│   └── data/                    # Decrypted data + forecast JSON
├── tests/                       # pytest suite
├── utils/                       # Encryption, helpers
├── docs/                        # Runbook + ADRs
├── memory/                      # Gotcha log + topic files
├── scripts/                     # Build + cron scripts
├── decrypt_data_cached.py       # Production decryption
├── netlify.toml                 # Build pipeline
└── CLAUDE.md                    # Agent context (agent-ready-projects v1.3.2)
```

## Related Projects

- **[energyDataHub](https://github.com/ducroq/energydatahub)** — Data collection backend (18+ API collectors)

## License

MIT
