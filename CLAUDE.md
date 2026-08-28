# Augur

Energy price forecasting platform for the Netherlands. Combines data from 18+ APIs (via energyDataHub), ML-based week-ahead price predictions, and an interactive dashboard for smart consumption (heat pumps, EV charging, industrial thermal).

- **Stack**: Python 3.12 (ML pipeline), Hugo + Plotly.js (dashboard), **LightGBM-Quantile multi-horizon (production — promoted EXP-014 2026-05-29 after a five-iteration metric-redesign arc)** + River ARF (kept running as backup signal for one rolling-window cycle; retired as a model 2026-04-28 but its cron output still feeds the Model tab metrics)
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
sadalsuud (systemd timer: 16:30 UTC start + wait_for_edh.sh gate, fires after EDH publishes)
    ├── git pull energyDataHub + Augur
    ├── python -m ml.update              → ARF: learn + generate forecast (backup signal)
    ├── python -m ml.data.consolidate    → rebuild parquet for LGBM training
    ├── python -m ml.shadow.update_shadow → LGBM: retrain on 56-day window, predict 72h (production)
    ├── python -m ml.shadow.evaluate_shadow → eval log row vs ARF (continued)
    ├── git push augur                   → triggers Netlify rebuild
    │
    │ Schedule: system-level systemd unit at /etc/systemd/system/augur-daily.timer fires at
    │           16:30 UTC. ExecStartPre=scripts/wait_for_edh.sh polls EDH's
    │           data_quality_report.json:timestamp until today's date appears (max wait 4h),
    │           so the run always sees fresh exogenous data. Migrated from `45 16 * * *` cron
    │           on 2026-06-08/09 (augur#12).
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
- **Status (2026-05-29 — post EXP-014 promotion)**: LightGBM-Quantile drives the dashboard via `static/data/augur_forecast_shadow.json` (loaded by `static/js/dashboard.js:loadAugurForecast`). ARF cron continues as a backup signal — `static/data/augur_forecast.json` still updates daily and is read by `static/js/modules/model-viz.js` for the Model-tab metric widgets. The shadow now generates consumer-pricing fields too (`update_shadow.py:read_arf_surcharge` reads the cached surcharge from ARF's state.json and applies the same VAT+surcharge transform). To revert: change the path in `dashboard.js:loadAugurForecast` back to `augur_forecast.json`.
- **Why the swap**: five iterations of criterion redesign converged on a single-criterion-plus-guardrail design (skill: paired DM on |y−p50_LGBM| vs |y−point_ARF|, HAC bandwidth 71, p<0.10; calibration: LGBM not >0.02 worse than ARF on either side). Applied to the M4 paired data: LGBM MAE 28.9 vs ARF MAE 38.4 (25% better, DM p=0.029); LGBM lower-side coverage 0.811 vs ARF 0.824 (within tolerance); LGBM upper-side 0.870 vs ARF 0.621 (LGBM materially better). PROMOTE = True. See `docs/articles/m4-metric-redesign-story.md` for the full arc, `docs/hypothesis-log.md` for the pre-committed criteria, `experiments/registry.jsonl` EXP-008..EXP-014.
- **Known weakness — calibration (augur#19), reframed 2026-08-25**: the P80 band is under-covering and **the deficit has moved to the upper side**. Measured from `shadow_state.json:calibration_history` (NOT `eval_log.jsonl` — eval rows mix 24/48/72h vintages and have permanent holes at 2026-06-08/06-10 from the EDH v2.2 break and at 2026-08-25 from the t0-stall incident): Jul 2026 lower 0.865 / upper 0.841 / band 0.706; **Aug 2026 lower 0.887 / upper 0.774 / band 0.660** (target 0.80). The lower side has essentially healed since the 0.834 figure that opened the issue through 2026-06-11. Most likely driver: August's mean price of 128 EUR/MWh is the highest in the parquet, and a trailing-56-day model under-reaches an upward level shift.
- **Calibration-layer arc resolved 2026-06-12**: EXP-015 (per-side CQR, `parked`) fixes the side asymmetry; EXP-016 (per-side ACI, `parked`) fixes post-shift days but hits a γ-independent ~0.85 ceiling from first-shift-day misses and trips the Winkler guardrail. Their conclusion — the gap lives in the raw quantiles → EXP-017 (9-quantile training) next — **is now stale on its premise**: EXP-015/016 diagnosed a high-biased `q10_raw`, and the live breach is the opposite side. Re-derive after the feature set settles. See `docs/hypothesis-log.md` and `experiments/registry.jsonl` EXP-015/016.
- **Feature-set finding (EXP-018/EXP-019, 2026-08-25 — evidence only, nothing deployed)**: a production-shaped ablation over 263 vintages found the 24-feature set carries dead weight. Dropping the six rolling stats buys −6.0% MAE / −7.8% quantile score *and* lifts lower-side coverage (DM p<0.0001); calendar is the only group clearly earning its place (+7.3% MAE when dropped); wind/solar/load are inert (±0.4% each). Best variant is a **15-feature lean set** (−6.5% MAE / −8.1% QS). EXP-019 refuted the stationary-reparameterisation alternative (anchor-relative spreads tie plain deletion) but showed re-adding `price_rolling_mean_168h` alone costs most of the gain. Because this is a best-of-eight selection on one window, it ships only through the pre-committed **EXP-018a** gates on fresh vintages (`t0 ≥ 2026-08-25`, ≈2026-09-09) in `docs/hypothesis-log.md`.

**ARF (backup signal, retired-as-model 2026-04-28, kept-running 2026-05-29 — see ADR-006 / ADR-004 superseded)**:
- Model: River ARFRegressor (10 trees), continuous online learning
- Features: Lasso-selected — price lags, rolling stats, wind speed, solar GHI, load forecast
- Target: ENTSO-E NL wholesale day-ahead price (EUR/MWh)
- Consumer forecast: derived from wholesale via auto-computed surcharge (EZ consumer - ENTSO-E × 1.21), fallback chain (recent files → state → default 95 EUR/MWh) — *the cached surcharge is also consumed by LightGBM's consumer-pricing step via `update_shadow.py:read_arf_surcharge`*
- Forecast: 72h with 80% confidence band, exchange-informed lags (now in `augur_forecast.json` only consumed by Model-tab metric widgets, not dashboard price charts)
- Forecast archive: timestamped copies in `ml/forecasts/` on sadalsuud (still used by `evaluate_shadow.py` for daily comparison)
- Retirement reasoning + structural ceiling: `docs/river-arf-retrospective.md` (including post-promotion closing addendum)

- **Pipeline reliability (2026-08-28)**: t0 is data-derived (`parquet.index.max()`), so a stale parquet used to stall it — overwriting a vintage — and a catching-up parquet used to skip one, permanently. Both now alarm in the daily commit subject via `classify_t0_advance`, and `wait_for_edh.sh` requires the EDH report to be stamped ≥12:00 UTC so an overnight catch-up publish can't release the run early. Residual risk is upstream: EDH published on only 31 of 35 days over 2026-07-25..08-28 (ducroq/energyDataHub#50). Known permanent `eval_log.jsonl` holes: 2026-06-08, 2026-06-10, 2026-08-25. Position + 14-run review in `docs/hypothesis-log.md` [2026-08-28].

**LightGBM-Quantile (production from 2026-05-29)**:
- Model: 9 LGBMRegressor (3 horizon groups × 3 quantiles p10/p50/p90, horizon-as-feature stacking)
- Training: rolling 56-day window from `ml/data/training_history.parquet` (regenerated nightly by `ml.data.consolidate`)
- Bands: split-conformal (CQR) with 7-day calibration, target 0.80 — produces `lightgbm_band_coverage_p80` per day
- Consumer pricing: `update_shadow.py:read_arf_surcharge` reads cached `consumer_surcharge.value_eur_mwh` from ARF's `ml/models/state.json`; consumer = wholesale × VAT × surcharge applied to forecast/upper/lower bands (mirrors `ml/update.py:generate_consumer_forecast`).
- Output: `static/data/augur_forecast_shadow.json` (loaded by dashboard.js)
- Eval: `ml/shadow/eval_log.jsonl` continues to log per-day metrics
- Promotion criterion (now resolved): see `docs/hypothesis-log.md` iteration-5 entry and `scripts/exp014_evaluate_promotion.py`
- Pickle integrity: HMAC-SHA256 sidecar via `ml/shadow/secure_pickle.py`; verify-before-load
- Calibration_history schema: `p10/p50/p90` are sorted-CQR-widened; `p10_raw/p50_raw/p90_raw` are the raw tau-quantile model outputs (added 2026-05-29 after EXP-013 code review caught sort-then-pinball bias).
- Open: **augur#19** (calibration — now an *upper-side* / band-width gap, see the reframed weakness bullet above; EXP-017's premise stale), **augur#28 / EXP-018a** (feature reduction — awaiting fresh vintages ≈2026-09-09), **augur#14** (gap *detection* shipped 2026-08-28; automated backfill still undecided — a reconstructed vintage built from fresher exogenous would not be comparable with the live ones beside it), **augur#25** (event-driven EDH trigger — the 2026-08-24 90-second race is the concrete case for it). Closed 2026-08-26: augur#12 (cron→systemd, timer verified enabled+active), augur#26 (ARF back to 72h — `f49a1c8` maxlen 200→800 confirmed in `static/data/augur_forecast.json`), augur#27 (lockfile committed `affa443`; stale `# Cron:` comment removed).

## Key Paths

| Path | What it is |
|------|-----------|
**Production model pipeline (LightGBM-Quantile, ADR-006)**:
| Path | What it is |
|------|-----------|
| `ml/shadow/lightgbm_quantile.py` | `MultiHorizonLightGBMQuantileForecaster` — 9 LGBM models, horizon-as-feature; `predict(sort=False)` returns raw tau quantiles |
| `ml/shadow/features_pandas.py` | 24-feature builder for LGBM (price lags, rolling stats, calendar, exogenous, horizon) |
| `ml/shadow/conformal.py` | Split-conformal CQR band correction (Romano/Patterson/Candès 2019) |
| `ml/shadow/update_shadow.py` | Nightly LGBM retrain + 72h predict + CQR widen + consumer-pricing fields via `read_arf_surcharge` |
| `ml/shadow/evaluate_shadow.py` | Daily LGBM-vs-ARF metrics, appends to `ml/shadow/eval_log.jsonl` |
| `ml/shadow/eval_log.jsonl` | Append-only eval log per realised eval day |
| `ml/shadow/secure_pickle.py` | HMAC-SHA256 sidecar; `save_signed_pickle` / `load_verified_pickle` |
| `ml/shadow/metrics.py` | Reusable metrics module — pinball, mean_quantile_score, twcrps_left_tail, lower_side_coverage, winkler_interval_score, diebold_mariano (manual Newey-West HAC) |
| `ml/models/shadow/shadow_model.pkl` | Trained LGBM artifact (HMAC-signed; **gitignored** — regenerated nightly on sadalsuud from the rolling window, never committed) |
| `ml/models/shadow/shadow_state.json` | `last_run_utc`, `pending_predictions`, `calibration_history` (with `p10_raw`/`p50_raw`/`p90_raw`), CQR stats |
| `static/data/augur_forecast_shadow.json` | Production forecast file consumed by `dashboard.js` |
| `ml/data/consolidate.py` | Parses encrypted energyDataHub history into training parquet |
| `ml/data/training_history.parquet` | Rolling 56-day training data (gitignored; regenerated nightly) |

**ARF backup pipeline (kept running, ADR-004 superseded)**:
| Path | What it is |
|------|-----------|
| `ml/update.py` | ARF daily entry point — produces `augur_forecast.json` + cached surcharge in `state.json` |
| `ml/features/online_features.py` | ARF's streaming feature builder |
| `ml/training/warmup.py` | One-time historical replay (used only when bootstrapping ARF) |
| `ml/models/river_model.pkl` | ARF model artifact |
| `ml/models/state.json` | ARF state — *the surcharge cache here is consumed by LightGBM's consumer-pricing step* |
| `ml/forecasts/{YYYYMMDD_HHMM}_forecast.json` | Timestamped ARF forecast archives (still used by `evaluate_shadow.py`) |
| `static/data/augur_forecast.json` | ARF forecast file; consumed only by `static/js/modules/model-viz.js` for Model-tab metrics |

**Dashboard + delivery**:
| Path | What it is |
|------|-----------|
| `static/js/dashboard.js` | Dashboard entry; `loadAugurForecast` fetches `augur_forecast_shadow.json` (the swap point — change here to revert) |
| `static/js/modules/` | ES6 modules: api-client, chart-renderer, data-processor (uses `consumer_forecast`), model-viz (reads ARF metrics), etc. |
| `layouts/index.html` | Dashboard HTML template (5 tabs: Prices, Weather, Grid, Market, Model) |
| `static/css/style.css` | Glassmorphism dark theme |
| `decrypt_data_cached.py` | Production decryption with caching + `--force` (ADR-003) |
| `utils/secure_data_handler.py` | AES-CBC-256 + HMAC-SHA256 |
| `scripts/netlify_build.sh` | Shared Netlify build script |
| `scripts/daily_update.sh` | Sadalsuud daily job — ARF backup + parquet consolidate + LGBM retrain + shadow eval + commit + push. Triggered by `scripts/systemd/augur-daily.timer` (deployed to `/etc/systemd/system/`), gated by `scripts/wait_for_edh.sh` polling EDH freshness. **ARF runs NON-FATAL (`set +e`) since 2026-07-03** — a backup-signal failure can no longer abort the production LightGBM push; its rc shows as `ARF OK`/`ARF FAIL rc=N` in the commit subject. Pre-flight alarms (all surface in the commit subject): `SHADOW_PRE_AGE_H >36h` (stale state), `DEP_PROBE_OK=0` (**lightgbm/pandas** import broken — river deliberately excluded 2026-07-03 so a broken backup-only dep can't skip production), and a non-blocking pytest smoke gate (`SMOKE_OK`, writes `logs/smoke.log`). Three post-run output guards: ARF forecast <24h and no new eval row >2 days (2026-06-12, augur#14), and **t0 not advancing exactly one calendar day** (2026-08-28) — `[ALARM: t0 stale <date>]` when a stale parquet makes the run overwrite yesterday's vintage, `[ALARM: t0 jumped Nd]` when a day is skipped and becomes permanently unevaluable. |
| `scripts/wait_for_edh.sh` | systemd `ExecStartPre` gate — polls EDH `data_quality_report.json:timestamp` for today's date **and a publish hour ≥ `MIN_PUBLISH_HOUR_UTC=12`** (2026-08-28: the date alone let an EDH overnight catch-up publish release the run 90s before the real one, costing a vintage; the NL day-ahead auction clears ~12:00 CET, so a pre-noon-UTC stamp can't hold today's prices). Max wait 4h, then proceeds with stale data so the run isn't fail-closed — the t0-advance alarm now marks it. |
| `scripts/systemd/{augur-daily.service,augur-daily.timer,README.md}` | Canonical systemd unit files; deploy via `sudo cp` to `/etc/systemd/system/`. |
| `netlify.toml` | Build pipeline: decrypt → hugo |

**Process + experiments**:
| Path | What it is |
|------|-----------|
| `experiments/registry.jsonl` | Append-only experiment log (EXP-001..EXP-019, gap at EXP-017 which was never run); schema in `experiments/README.md` |
| `docs/decisions/006-lightgbm-quantile-production-architecture.md` | ADR-006 — what the production system does |
| `docs/decisions/007-model-promotion-method.md` | ADR-007 — how we decide what to change |
| `docs/decisions/004-river-online-learning-architecture.md` | ADR-004 — superseded by ADR-006 |
| `docs/hypothesis-log.md` | Provisional positions awaiting evidence; iteration-4/5 EXP-014 entries resolved 2026-05-29 |
| `docs/articles/m4-metric-redesign-story.md` | Case-study article — five-iteration arc from M4 park to EXP-014 promotion (~4960 words) |
| `docs/literature.md` | Topic-indexed bibliography |
| `docs/metric-redesign-literature-review.md` | Focused EPF metric review (input to EXP-012) |
| `docs/exp-012-results.md` | EXP-012 + EXP-013 corrections report |
| `docs/lightgbm-shadow-postmortem.md` | M4 Path B postmortem (historical; superseded by EXP-014 swap) |
| `docs/lightgbm-quantile-shadow-plan.md` | Original shadow plan (historical) |
| `docs/river-arf-retrospective.md` | ARF retirement narrative + closing addendum on the EXP-014 promotion |
| `docs/model-progress-log.md` | Dated narrative log of ML pipeline changes |
| `tests/` | pytest suite — 202 tests (SecureDataHandler, OnlineFeatureBuilder, LGBM forecaster + multi-horizon + secure_pickle + conformal + backtest + update_shadow + evaluate_shadow + slice MAE + archive path + metrics module + **consolidate parsers (test_consolidate.py, 18 tests, 2026-06-10)** + **t0-advance guard (TestClassifyT0Advance, 7 tests, 2026-08-28)**) |
| `scripts/m4_method_run.py` | M4 verdict runner (historical — pre-EXP-014) |
| `scripts/exp012_evaluate.py` | EXP-012/013 paired-data evaluation (vintage-corrected) |
| `scripts/exp014_evaluate_promotion.py` | EXP-014 promotion-criterion runner |
| `scripts/exp015_replay_cqr.py` | EXP-015 offline replay — per-side CQR vs production bands on `calibration_history` raws |
| `scripts/exp016_replay_aci.py` | EXP-016 offline replay — per-side ACI (Gibbs-Candès) with α trace + γ sensitivity |
| `scripts/exp018_stage0_ablation.py` | EXP-018 per-feature-group ablation — production-shaped walk-forward, `--variants`/`--reuse-predictions`; **also the EXP-018a Stage-1 runner** |
| `scripts/exp019_stationary_ablation.py` | EXP-019 anchor-relative spread variants (imports the EXP-018 harness) |
| `ml/shadow/exp018_stage0*/summary.json`, `ml/shadow/exp019_stationary/summary.json` | Sweep records (per-hour `predictions.parquet` dumps are gitignored, regenerable) |

## How to Work Here

```bash
# Install dependencies — reproducible venv from the pinned lockfile
scripts/bootstrap_venv.sh --dev     # creates ./.venv from requirements.lock; --dev adds pytest
source .venv/bin/activate
npm install

# Set encryption keys (bash; or use a .env file the daily job sources)
export ENCRYPTION_KEY_B64="your_key"
export HMAC_KEY_B64="your_key"

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
