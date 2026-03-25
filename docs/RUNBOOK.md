# Runbook

## Principles

- **Forecast accuracy > dashboard polish** — the ML pipeline is the core value; the dashboard is the delivery mechanism
- **Continuous learning > batch perfection** — ship a working model, improve daily with online learning
- **Temporal splits only** — never random train/test splits on time series; always split by date
- **energyDataHub is upstream, not ours** — don't modify its data formats; adapt to them

## Local Development

### Prerequisites

- Python 3.11+ with pip
- [Hugo](https://gohugo.io/) v0.124.0+
- Node.js 16+ (for npm scripts)
- Encryption keys from energyDataHub (ENCRYPTION_KEY_B64, HMAC_KEY_B64)

### Setup

```bash
git clone https://github.com/ducroq/augur.git
cd augur
npm install
pip install cryptography pandas numpy xgboost river
```

### Running

```bash
# Set keys (PowerShell)
$env:ENCRYPTION_KEY_B64 = "your_key"
$env:HMAC_KEY_B64 = "your_key"

# Decrypt data
python decrypt_data_cached.py --force

# ML inference (when model exists)
python -m ml.inference

# Dashboard
hugo server -D
```

## Deployment

### Build Pipeline (Netlify)

The `netlify.toml` build command runs sequentially:
1. `pip install cryptography` — Python deps
2. `python decrypt_data_cached.py --force` — fetch + decrypt from energyDataHub
3. `python -m ml.inference` — generate augur_forecast.json (when model ready)
4. `hugo --minify` — build static site

### Pre-deploy checklist

- [ ] Encryption keys set in Netlify environment variables
- [ ] energyDataHub publishing to GitHub Pages
- [ ] `--force` flag present in build command (critical — see ADR-003)
- [ ] ML model artifact exists in `ml/models/` if inference step enabled

### Post-deploy verification

- Dashboard loads at deployed URL
- Chart renders with current day's data
- Energy Zero live data refreshes (check browser console)
- Forecast data timestamp is recent (< 24 hours)

### Webhook Flow

1. energyDataHub GitHub Action runs daily at 16:00 UTC
2. Collects, encrypts, publishes to GitHub Pages
3. Triggers Netlify rebuild via `NETLIFY_BUILD_HOOK` secret
4. Netlify decrypts fresh data, runs inference, builds, deploys

## Adding a New Data Feature (ML)

1. Identify the data source in energyDataHub's published JSON files
2. Add extraction logic in `ml/features/builder.py`
3. Ensure timestamp alignment with existing features (hourly resolution)
4. Handle unit conversion if needed (see `memory/data-formats.md`)
5. Retrain model and evaluate impact on forecast accuracy
6. Update `memory/data-formats.md` if the source has quirks

## Adding a New Data Source to Dashboard

1. Add collector in energyDataHub (separate repo)
2. Update `ml/features/builder.py` to use the new source as features
3. If client-side visualization needed, update `static/js/modules/data-processor.js`
4. Add to constants in `static/js/modules/constants.js`

## Common Problems

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Dashboard shows old data | energyDataHub Action didn't run or webhook didn't trigger | Check Action logs, verify NETLIFY_BUILD_HOOK secret |
| Build fails with decryption error | Missing or wrong encryption keys | Check Netlify env vars match energyDataHub keys |
| Chart renders but no live data | Energy Zero API down or CORS issue | Check browser console; API tries yesterday if today fails |
| ML inference outputs empty forecast | Model not trained yet | Train with `python -m ml.training.trainer` first |
| Timezone appears wrong in winter | Legacy chart.js hardcodes +2h | Use modular dashboard.js which handles DST correctly |

## Documentation Practices

| Type of change | Update |
|---------------|--------|
| New constraint or principle | `CLAUDE.md` |
| Operational process change | This file (`docs/RUNBOOK.md`) |
| Hit a weird bug | `memory/gotcha-log.md` |
| Chose between approaches | New ADR in `docs/decisions/` |
| Learned something about data formats | `memory/data-formats.md` |
| ML architecture decision | `memory/ml-decisions.md` |
