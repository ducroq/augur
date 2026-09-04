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
| **Starting a session — orient first** | `memory/MEMORY.md` — the memory index: current state, standing findings, open bets, deferred items. It is *not* auto-loaded; read it before reconstructing state from the deeper registers. Kept fresh at `/curate`. |
| Stuck or debugging something weird | `memory/gotcha-log.md` — problem-fix archive |
| Questioning ML architecture choices | `memory/ml-decisions.md` (week-ahead, River ARF, feature strategy) + `docs/river-arf-retrospective.md` (why ARF is being retired and what replaces it) |
| Working with energyDataHub data formats | `memory/data-formats.md` — schema v2.1, units, timezone conventions |
| Changing ML pipeline, model, or forecast logic | `docs/model-progress-log.md` — add dated entry with rationale, evidence, and outcome |
| **Before proposing model work** | `docs/experiment-results.md` **Decision state** section — what is closed (do not re-run), what is live, what is standing evidence. Derived from the registry, so it cannot drift. Then `memory/MEMORY.md` → *Standing conclusions* for the judgement layer |
| **Reading experiment results** | `docs/experiment-results.md` — every experiment's hypothesis, outcome, full metrics and caveats in one readable page. **Generated** from `experiments/registry.jsonl` by `scripts/render_results.py`; never hand-edit, regenerate after appending |
| **Verifying the experiment record** | `scripts/audit_registry.py` — schema, id order, artifact existence, number traceability, and sha256 proof that no pre-committed Method was edited after its result landed. Exits non-zero on failure; run it at `/curate` |
| Logging or citing an experiment (A/B, warmup, ablation) | `experiments/registry.jsonl` — append one line per experiment; schema in `experiments/README.md` |
| **Picking up the next experiment** | `docs/experiment-backlog.md` — designed, pre-committed, not yet run; ordered by decision value per unit cost. EXP-025 (transplanted calibration prior) is cheapest and most actionable |
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
    │           data_quality_report.json for a CONTENT contract (rewritten 2026-09-01):
    │           report newer than last consumed AND entsoe >= median points of recent
    │           publishes. Deadline 03:00 UTC, then proceeds anyway (never fail-closed).
    │           Migrated from `45 16 * * *` cron on 2026-06-08/09 (augur#12).
    │
    │ Alerting (2026-08-30/31): three layers, each blind to the others' cases.
    │           OnFailure=augur-alert@ -> alert_failure.sh   when the UNIT DIES
    │           augur-heartbeat.timer 06:00 UTC              when NO COMMIT lands in >30h,
    │                                                        the timer is off, or commits are unpushed
    │           ...same heartbeat greps the commit SUBJECT   for soft failures that exit 0:
    │                                                        [ALARM: ...], ARF FAIL, rc=N, rc=skip
    │           Channel: FluxusSource secrets.ini Gmail via notify_email.py. No new service.
    │           Blind spot by design: it runs ON sadalsuud, so it cannot report sadalsuud down.
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
- **Model work 2026-08-25..30 — 13 experiments (EXP-018..EXP-033), nothing shipped, no production path touched.** The full record is **`docs/experiment-results.md`**, generated from `experiments/registry.jsonl` and opening with a *Decision state* section (closed / live / standing evidence). Read that before proposing model work. Settled:
  - **Feature engineering is closed at this window.** Added exogenous buys nothing; added *level* columns cost — four independent confirmations (EXP-019 rolling mean, EXP-020 gas, EXP-024 matched-count derived, EXP-029 residual regression).
  - **A zero-shot foundation model beats the incumbent by 20.3% QS / 16% MAE with no features at all** (EXP-021, DM p<0.0001). EXP-022 splits it ~12pp pretrained prior / ~8pp context; EXP-024 shows the context half is not recoverable inside LightGBM — the bottleneck is model class.
  - **Zero-shot is the deployment mode.** Fine-tuning degrades both halves (EXP-027). Size and latency are non-constraints (EXP-026/030/033: tiny keeps 93.5%; base runs 1.16s on sadalsuud, ~52× headroom).
  - **Exogenous is not useless — it was unusable *by LightGBM*.** Chronos-2 gains 8.3% QS from the same columns with no retraining (EXP-028); fails its coverage gate, `parked`.
  - **Two numbers not to requote:** the FM's calibration edge is **0.811 vs lean+CQR 0.788**, not vs the pre-conformal 0.611 (EXP-025); and EXP-021's stated level-drift mechanism was wrong — it is a pretrained prior plus a feature-row bottleneck (EXP-022).
- **Live decisions, all gated on fresh vintages** (triggers in `docs/hypothesis-log.md`): **EXP-018a** ≈09-09 has first claim and decides `lean` vs `full`; then **EXP-021a** ≈09-09, **EXP-028a** ≈09-23, **EXP-023a Stage B** ≈10-09 (112d window demoted — Stage A found it 1.4% *worse* on unscored vintages).
- **Record integrity is checkable:** `scripts/audit_registry.py` (schema, id order, artifacts, number-traceability, sha256 proof no pre-committed Method was edited after its result) and `scripts/render_results.py --check`; both exit non-zero.

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
- Open: **augur#19** (calibration — now an *upper-side* / band-width gap, see the reframed weakness bullet above; EXP-017's premise stale; EXP-020 confirmed fundamentals do not fix it), **augur#28 / EXP-018a** (feature reduction — awaiting fresh vintages ≈2026-09-09), **augur#15 / EXP-021a** (foundation models — **first arm run 2026-08-29 and it won decisively**: Chronos-Bolt zero-shot −20.3% QS vs lean, raw band coverage 0.811 vs 0.611, nothing shipped pending EXP-021a's fresh-vintage + feasibility + shadow stages), **augur#14** (gap *detection* shipped 2026-08-28; automated backfill still undecided — a reconstructed vintage built from fresher exogenous would not be comparable with the live ones beside it), **augur#25** (event-driven EDH trigger — the 2026-08-24 90-second race is the concrete case for it). Closed 2026-08-29: augur#3 (gas/carbon as features — EXP-020 tested TTF and it degrades). Closed 2026-08-26: augur#12 (cron→systemd, timer verified enabled+active), augur#26 (ARF back to 72h — `f49a1c8` maxlen 200→800 confirmed in `static/data/augur_forecast.json`), augur#27 (lockfile committed `affa443`; stale `# Cron:` comment removed).

## Key Paths

| Path | What it is |
|------|-----------|
**Production model pipeline (LightGBM-Quantile, ADR-006)**:
| Path | What it is |
|------|-----------|
| `ml/shadow/lightgbm_quantile.py` | `MultiHorizonLightGBMQuantileForecaster` — 9 LGBM models, horizon-as-feature; `predict(sort=False)` returns raw tau quantiles |
| `ml/shadow/features_pandas.py` | 24-feature builder for LGBM (price lags, rolling stats, calendar, exogenous, horizon) |
| `ml/shadow/conformal.py` | Split-conformal CQR band correction (Romano/Patterson/Candès 2019) |
| `ml/shadow/update_shadow.py` | Nightly LGBM retrain + 72h predict + CQR widen + consumer-pricing fields via `read_arf_surcharge`. **t0 comes from `latest_feasible_t0` (2026-08-31), not `price.index.max()`** — EDH's feeds do not share a horizon (load halved to 24h while price stayed 48h on 08-30 and crashed the run), so the anchor is the last timestamp with a *complete* feature row and the alarm names the short feed. |
| `ml/shadow/evaluate_shadow.py` | Daily LGBM-vs-ARF metrics, appends to `ml/shadow/eval_log.jsonl` |
| `ml/shadow/eval_log.jsonl` | Append-only eval log per realised eval day |
| `ml/shadow/secure_pickle.py` | HMAC-SHA256 sidecar; `save_signed_pickle` / `load_verified_pickle` |
| `ml/shadow/metrics.py` | Reusable metrics module — pinball, mean_quantile_score, twcrps_left_tail, lower_side_coverage, winkler_interval_score, diebold_mariano (manual Newey-West HAC) |
| `ml/models/shadow/shadow_model.pkl` | Trained LGBM artifact (HMAC-signed; **gitignored** — regenerated nightly on sadalsuud from the rolling window, never committed) |
| `ml/models/shadow/shadow_state.json` | `last_run_utc`, `pending_predictions`, `calibration_history` (with `p10_raw`/`p50_raw`/`p90_raw`), CQR stats, and **`t0_held_back_hours`/`t0_short_feeds`** (2026-08-31) — read by `daily_update.sh` to emit `[ALARM: t0 held back Nh — <feeds> short]`, because a held-back anchor still exits 0 with a clean `shadow rc=0` while the forecast is degraded |
| `static/data/augur_forecast_shadow.json` | Production forecast file consumed by `dashboard.js` |
| `ml/data/consolidate.py` | Parses encrypted energyDataHub history into training parquet |
| `ml/data/training_history.parquet` | Training history (gitignored; regenerated nightly). Nine columns since 2026-08-29: the five the model uses (`price_eur_mwh`, `wind_speed_80m`, `solar_ghi`, `temperature`, `load_forecast`) plus four EXP-020 fundamentals (`wind_gen_forecast_mw`, `solar_gen_forecast_mw`, `gas_ttf_eur_mwh`, `is_holiday_nl`) that are **collected but not in `FEATURE_COLUMNS`** — EXP-020 refuted them; they stay because they are additive-only and free. |

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
| `scripts/wait_for_edh.sh` | systemd `ExecStartPre` gate. **Readiness is a CONTENT contract, not a clock window (rewritten 2026-09-01, `7d0066d`)**: the EDH report must be strictly newer than the last consumed (`logs/.edh_gate_state`) **and** the primary dataset `entsoe` must carry at least the **median point count of the last N publishes** (`median_points`, fallback 192) — so an upstream resolution change is absorbed in a few days instead of reading as short forever. A short *secondary* feed (`load_forecast`) alarms but deliberately does **not** block. Polls to a 03:00 UTC deadline, then proceeds anyway: never fail-closed, and the t0-advance alarm marks it. The old `MIN_PUBLISH_HOUR_UTC=12` floor is **gone** — GitHub defers EDH's cron unpredictably (observed 00:18–21:14 UTC), so a clock floor shut the gate on good publishes. Earned its place 2026-09-04 by refusing a 06:53 UTC recovery publish whose `entsoe` held same-day prices only (96 vs 192), the day-ahead auction not having cleared. ⚠️ It asserts span on `entsoe`/`load_forecast` only and examines no other feed — `wind_speed_80m`/`solar_ghi` feeds are unchecked; see the gotcha-log Promoted table [2026-09-04]. |
| `scripts/systemd/` | Canonical unit files; deploy via `sudo cp` to `/etc/systemd/system/` (install + rollback in its README). `augur-daily.{service,timer}` plus, since 2026-08-30, `augur-alert@.service` (OnFailure template, runs as `jeroen`), `augur-daily.service.d/alert.conf` (the `OnFailure=` drop-in — a drop-in, not an edit, so it detaches without touching the ExecStartPre ordering), and `augur-heartbeat.{service,timer}`. |
| `scripts/alert_failure.sh` | `OnFailure=` handler for `augur-daily.service`. Covers the **hard** case only: a unit that dies before committing, which emits nothing because every in-script ALARM rides in the commit subject. Logs to `logs/alerts.log`, emails via `notify_email.py`, 3h burst guard armed only after a confirmed send. Always exits 0 — it runs inside systemd's failure handling. |
| `scripts/heartbeat_check.sh` | Daily 06:00 UTC liveness check (`augur-heartbeat.timer`). Covers what `OnFailure=` structurally **cannot**: `daily_update.sh` ends with `git diff --cached --quiet && echo "No changes to commit" || {commit; push;}`, so a run producing nothing exits 0 and the unit *succeeds*; likewise a disabled timer or a down box. Alarms on no `Daily update` commit in >30h, timer not enabled/active, or unpushed commits. Exits 0 when it *sends* an alert (its own `OnFailure=` is reserved for a broken watchman). Blind spot, by design: it runs on sadalsuud, so it cannot report sadalsuud being down — that needs an off-host dead-man's switch, i.e. a new service, declined 2026-07-17. |
| `scripts/notify_email.py` | Shared alert sender, stdlib only. Reads `[email_credentials]` from FluxusSource's gitignored `secrets.ini` on sadalsuud — the same channel `nexusmind-alert@.service` uses; no new notification service. Missing/incomplete creds degrade to log-only and still exit 0. `AUGUR_NOTIFY_SECRETS` overrides the path so a dev-box dry-run can't send a real email. |
| `netlify.toml` | Build pipeline: decrypt → hugo |

**Process + experiments**:
| Path | What it is |
|------|-----------|
| `experiments/registry.jsonl` | Append-only experiment log (EXP-001..EXP-033, gap at EXP-017 which was never run); schema in `experiments/README.md` |
| `docs/decisions/006-lightgbm-quantile-production-architecture.md` | ADR-006 — what the production system does |
| `docs/decisions/007-model-promotion-method.md` | ADR-007 — how we decide what to change |
| `docs/decisions/004-river-online-learning-architecture.md` | ADR-004 — superseded by ADR-006 |
| `docs/hypothesis-log.md` | Provisional positions awaiting evidence; iteration-4/5 EXP-014 entries resolved 2026-05-29 |
| `docs/experiment-backlog.md` | ADR-007 pre-commits. The 2026-08-29 batch (EXP-023..029) is **all run**; the one open entry is **EXP-034** (fragility-conditioned bands, added 2026-08-31, queued after EXP-018a Stage 1). All run on the existing window and consume no fresh vintages |
| `docs/articles/m4-metric-redesign-story.md` | Case-study article — five-iteration arc from M4 park to EXP-014 promotion (~4960 words) |
| `docs/literature.md` | Topic-indexed bibliography |
| `docs/metric-redesign-literature-review.md` | Focused EPF metric review (input to EXP-012) |
| `docs/exp-012-results.md` | EXP-012 + EXP-013 corrections report |
| `docs/lightgbm-shadow-postmortem.md` | M4 Path B postmortem (historical; superseded by EXP-014 swap) |
| `docs/lightgbm-quantile-shadow-plan.md` | Original shadow plan (historical) |
| `docs/river-arf-retrospective.md` | ARF retirement narrative + closing addendum on the EXP-014 promotion |
| `docs/model-progress-log.md` | Dated narrative log of ML pipeline changes |
| `tests/` | pytest suite — **285 tests** (recorded as 243 until 2026-09-04, when a `/curate` verify probe caught the drift) (SecureDataHandler, OnlineFeatureBuilder, LGBM forecaster + multi-horizon + secure_pickle + conformal + backtest + update_shadow + evaluate_shadow + slice MAE + archive path + metrics module + **consolidate parsers (test_consolidate.py, 18 tests, 2026-06-10)** + **t0-advance guard (TestClassifyT0Advance, 7 tests, 2026-08-28)** + **EXP-020 fundamentals parsers (20 tests, 2026-08-29)** + **alert-channel credential layer + exit contract (test_notify_email.py, 12 tests, 2026-08-30)** + **feasible-t0 selection + hold-back state (TestLatestFeasibleT0 + TestHoldBackReachesState, 9 tests, 2026-08-31)**) |
| `scripts/m4_method_run.py` | M4 verdict runner (historical — pre-EXP-014) |
| `scripts/exp012_evaluate.py` | EXP-012/013 paired-data evaluation (vintage-corrected) |
| `scripts/exp014_evaluate_promotion.py` | EXP-014 promotion-criterion runner |
| `scripts/exp015_replay_cqr.py` | EXP-015 offline replay — per-side CQR vs production bands on `calibration_history` raws |
| `scripts/exp016_replay_aci.py` | EXP-016 offline replay — per-side ACI (Gibbs-Candès) with α trace + γ sensitivity |
| `scripts/exp018_stage0_ablation.py` | EXP-018 per-feature-group ablation — production-shaped walk-forward, `--variants`/`--reuse-predictions`; **also the EXP-018a Stage-1 runner** |
| `scripts/exp019_stationary_ablation.py` | EXP-019 anchor-relative spread variants (imports the EXP-018 harness) |
| `docs/experiment-results.md` | **Generated** readable digest of all experiments — summary table + per-experiment sections |
| `scripts/render_results.py` | Renders the digest from the registry; `--check` fails if stale |
| `scripts/audit_registry.py` | Registry auditor — 5 checks incl. number-traceability and pre-commit immutability. Check 5 resolves each backlog entry to **its own** pre-commit revision via `PRECOMMIT_REV_BY_ID` (2026-08-31); pinning all entries to one global revision made adding a new pre-commitment fail forever against an empty baseline |
| `scripts/posthoc_diagnostics.py` | Regenerates registry numbers originally computed ad-hoc (EXP-022/025 diagnostics.json) |
| `scripts/exp024_lag_richness.py` | EXP-024 lag richness + the dimensionality-matched derived control |
| `scripts/exp027_finetune_dissociation.py` | EXP-027 fine-tuning trajectory (train ≤2026-02-28, eval t0 ≥2026-03-01) |
| `scripts/exp026_cpu_latency.py` | EXP-026 part (b) CPU-latency **proxy** on jwasys — explicitly a lower bound, does not discharge EXP-021a Stage 2 |
| `scripts/exp023_window_sweep.py` | EXP-023 window sweep — `--windows`, vintage set fixed to the longest rung's availability |
| `scripts/exp025_band_transplant.py` | EXP-025 band transplant + weighted blends + the production-CQR comparator |
| `scripts/exp028_chronos2_covariates.py` | EXP-028 chronos-2 with past/future covariates (contamination-restricted to t0 > 2026-06-05) |
| `scripts/exp029_residual_screen.py` | EXP-029 residual pre-screen — REJECTED as a gate; kept as a level-column diagnostic |
| `scripts/exp022_context_ladder.py` | EXP-022 mechanism diagnostic — truncates EXP-021's contexts to 7/14/28d rungs and re-scores, separating pretrained prior from context volume |
| `scripts/exp021_foundation_zeroshot.py` | EXP-021 foundation-model arm — three modes (`contexts` on situla / `predict` on `b650-gpu` / `score` on situla) so the GPU box needs no Augur checkout and scoring stays bit-identical to EXP-018/019/020; `--context-end-offset-h 1` is the information-matched arm |
| `scripts/exp020_fundamentals_ablation.py` | EXP-020 fundamentals arms (residual load / TTF gas / holiday) — imports the EXP-018 harness; `load_frame_ext` keeps the parquet fundamentals columns, per-arm DM bases, mechanical gate report |
| `ml/shadow/exp018_stage0*/summary.json`, `ml/shadow/exp019_stationary/summary.json`, `ml/shadow/exp020_fundamentals{,_ctl}/summary.json`, `ml/shadow/exp021_foundation{,_aligned}/summary.json`, `ml/shadow/exp022_context_ladder/summary.json` | Sweep records (per-hour `predictions.parquet` / FM context dumps are gitignored, regenerable) |

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
