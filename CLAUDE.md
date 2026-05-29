# Augur

Energy price forecasting platform for the Netherlands. Combines data from 18+ APIs (via energyDataHub), ML-based week-ahead price predictions, and an interactive dashboard for smart consumption (heat pumps, EV charging, industrial thermal).

- **Stack**: Python 3.12 (ML pipeline), Hugo + Plotly.js (dashboard), River ARF (production — retired as a model 2026-04-28, cron continues driving the dashboard) + LightGBM-Quantile multi-horizon (M4 tested 2026-05-08→05-27 and **parked 2026-05-29 (Path B)**; see `docs/lightgbm-shadow-postmortem.md`)
- **Status**: Production — dashboard live, ML pipeline daily on sadalsuud
- **Repo**: github.com/ducroq/augur
- **agent-ready-projects**: v1.9.0

## Before You Start

| When | Read |
|------|------|
| Working on ML features or training | `ml/features/online_features.py` — feature engineering, `ml/training/warmup.py` — model lifecycle |
| Changing the dashboard or chart rendering | `static/js/modules/` — modular ES6 code |
| Changing deployment or build pipeline | `docs/RUNBOOK.md` — Netlify build, --force flag, webhook flow |
| Making architectural decisions | `docs/decisions/` — ADR index |
| Stuck or debugging something weird | `memory/gotcha-log.md` — problem-fix archive |
| Questioning ML architecture choices | `memory/ml-decisions.md` (week-ahead, River ARF, feature strategy) + `docs/river-arf-retrospective.md` (why ARF is being retired and what replaces it) |
| Working with energyDataHub data formats | `memory/data-formats.md` — schema v2.1, units, timezone conventions |
| Changing ML pipeline, model, or forecast logic | `docs/model-progress-log.md` — add dated entry with rationale, evidence, and outcome |
| Logging or citing an experiment (A/B, warmup, ablation) | `experiments/registry.jsonl` — append one line per experiment; schema in `experiments/README.md` |
| Taking a provisional position to revisit later | `docs/hypothesis-log.md` — Position / Alternative / Method / Revisit trigger / Review-by; surface due items in `/curate` |
| Looking up citations or starting a literature pass | `docs/literature.md` — topic-indexed bibliography; per-topic deep-dives live as separate `docs/*.md` files (e.g. `metric-redesign-literature-review.md`) |
| Ending a session | Run `/curate` — review gotchas, promote patterns, check doc sync |
| Monthly or after major restructuring | Run `/audit-context` — structural health audit |

## Hard Constraints

- Never commit encryption keys or secrets — keys are base64-encoded env vars (`ENCRYPTION_KEY_B64`, `HMAC_KEY_B64`)
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
sadalsuud (daily cron 16:45 CEST = 14:45 UTC)
    ├── git pull energyDataHub
    ├── python -m ml.update              → ARF: learn + generate forecast (production)
    ├── python -m ml.data.consolidate    → rebuild parquet (parsers still useful post-M4)
    ├── (parked 2026-05-29) python -m ml.shadow.update_shadow
    ├── (parked 2026-05-29) python -m ml.shadow.evaluate_shadow
    ├── git push augur                   → triggers Netlify rebuild
    │
    │ Note: augur#12 — orchestration is misordered (augur runs before EDH collector at ~15:20 UTC),
    │       so parquet always trails 24h. Pending fix: systemd migration with After=edh.service.
    │
    ▼
Augur Netlify build
    ├── decrypt_data_cached.py --force   → static/data/*.json (10 files)
    ├── hugo --minify                    → public/
    └── Netlify CDN deploy

Client browser (https://energy.jeroenveen.nl):
    ├── 5 tabs: Prices, Weather, Grid, Market, Model
    ├── loads forecast + augur_forecast.json from /data/
    ├── fetches live Energy Zero API (every 10 min)
    └── renders Plotly.js charts with noise
```

### ML Pipeline (live)
- **Status (2026-05-29)**: ARF cron drives the dashboard; LGBM-Quantile shadow **parked** after M4 Method run on the trailing-14 window 2026-05-14→05-27. Criteria (a) and (b) failed (ratio 1.61 / mean cov 0.696 / 3 days <0.60); (c) passed (peak ratio 0.450). Primary diagnosis: structural long-horizon (h>24) low-price weakness — 72h aggregation forces criterion (a)'s low-price slice into hours LGBM cannot extrapolate to midday solar troughs. Companion live-vs-backtest ratio 1.84 also refuted: freshness skew is material (augur#12). Shadow cron disabled in `scripts/daily_update.sh`, code stays in tree; pre-flight stale check + Healthchecks.io ping also gated off. ARF retired as a model 2026-04-28 but its cron continues feeding the dashboard. Next bet (postmortem §6): **metric redesign before model redesign** — promote pinball-at-p10 / CRPS over MAE on the low-price slice; then prioritise augur#12. See `docs/lightgbm-shadow-postmortem.md` for full diagnosis, `docs/river-arf-retrospective.md` for ARF retirement, `docs/lightgbm-quantile-shadow-plan.md` for the original shadow plan.

**ARF (production)**:
- Model: River ARFRegressor (10 trees), continuous online learning
- Features: Lasso-selected — price lags, rolling stats, wind speed, solar GHI, load forecast
- Target: ENTSO-E NL wholesale day-ahead price (EUR/MWh)
- Consumer forecast: derived from wholesale via auto-computed surcharge (EZ consumer - ENTSO-E × 1.21), fallback chain (recent files → state → default 95 EUR/MWh)
- Forecast: 72h with 80% confidence band, exchange-informed lags
- Confidence bands: EWM error stats (half-life 24h) + volatility scaling from price_rolling_std_6h
- Convergence metric: vs Exchange MAE (tracking daily)
- Forecast archive: timestamped copies in `ml/forecasts/` on sadalsuud
- M3 review fixup A added `error_prices` parallel array + `mae_at_low_price` in state for criterion (a) evaluability

**LightGBM-Quantile shadow (parked 2026-05-29)**:
- Model: 9 LGBMRegressor (3 horizon groups × 3 quantiles, horizon-as-feature stacking)
- Training: rolling 56-day window from `ml/data/training_history.parquet`
- Bands: split-conformal (CQR) with 7-day calibration, target 0.80
- Eval: `ml/shadow/eval_log.jsonl` — frozen at 20 rows (2026-05-08 → 2026-05-27)
- Outcome: M4 Method run 2026-05-29 produced PROMOTE = False on (a)+(b); (c) passed. Path B (park) executed. Code stays in tree; re-enable by uncommenting the block in `scripts/daily_update.sh` + the pre-flight stale check. See `docs/lightgbm-shadow-postmortem.md`.
- Pickle integrity: HMAC-SHA256 sidecar via `ml/shadow/secure_pickle.py`; verify-before-load
- Open: augur#12 (cron→systemd + run-after-EDH for fresh data)

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
| `decrypt_data_cached.py` | Production decryption with caching + --force |
| `utils/secure_data_handler.py` | AES-CBC-256 + HMAC-SHA256 |
| `scripts/netlify_build.sh` | Shared Netlify build script (all contexts) |
| `netlify.toml` | Build pipeline: decrypt → hugo |
| `tests/` | pytest suite for SecureDataHandler + OnlineFeatureBuilder |
| `layouts/index.html` | Dashboard HTML template |
| `static/css/style.css` | Glassmorphism dark theme |
| `experiments/registry.jsonl` | Append-only experiment log (EXP-NNN); schema in `experiments/README.md` |
| `docs/river-arf-retrospective.md` | ARF retirement postmortem with figures and recovered data |
| `docs/lightgbm-quantile-shadow-plan.md` | LGBM shadow replacement plan with milestones + promotion criteria §6 |
| `docs/hypothesis-log.md` | Provisional positions awaiting evidence (M4 hypothesis seeded) |
| `ml/shadow/lightgbm_quantile.py` | `MultiHorizonLightGBMQuantileForecaster` — 9 LGBM models, horizon-as-feature |
| `ml/shadow/secure_pickle.py` | HMAC-SHA256 sidecar; `save_signed_pickle` / `load_verified_pickle` |
| `ml/shadow/update_shadow.py` | Nightly LGBM retrain + 72h predict + CQR widen |
| `ml/shadow/evaluate_shadow.py` | Daily LGBM-vs-ARF metrics, appends to `ml/shadow/eval_log.jsonl` |
| `ml/shadow/eval_log.jsonl` | Append-only eval log per fully-realised eval day (M4 promotion data) |
| `ml/models/shadow/shadow_state.json` | LGBM shadow state: `last_run_utc`, `pending_predictions`, `calibration_history`, CQR stats (NOT under `ml/shadow/`) |
| `ml/shadow/conformal.py` | Split-conformal CQR band correction (Romano/Patterson/Candès 2019) |
| `ml/forecasts/{YYYYMMDD_HHMM}_forecast.json` | Timestamped ARF forecast archives (read by `evaluate_shadow.py`) |

## How to Work Here

```bash
# Install dependencies
pip install -r requirements.txt
npm install

# Set encryption keys (Windows PowerShell)
$env:ENCRYPTION_KEY_B64 = "your_key"
$env:HMAC_KEY_B64 = "your_key"

# Fetch and decrypt data
python decrypt_data_cached.py --force

# Run tests
python -m pytest tests/ -v

# Dev server
hugo server -D
# Visit http://localhost:1313

# Production build
hugo --minify
```
