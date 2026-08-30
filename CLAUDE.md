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
- **Fundamentals refuted (EXP-020, 2026-08-29 — evidence only, nothing deployed)**: the counter-bet to the above — that the exogenous trio is inert because it is the wrong *shape* (not the merit-order quantity; no fuel-cost level anchor) — was pre-committed and tested. **Refuted on both bases.** `residual_load_mw` is a tie with the lean set (DM p=0.648 on 195 vintages, p=0.899 on the 263-vintage control), plain `load_forecast` likewise (p=0.851), and **TTF gas actively degrades** (+3.2% QS, p=0.991). Primary gate `lean+fundamentals` vs `lean` fails on skill and effect size; confirmatory `full+fundamentals` vs `full` fails identically. The gas result is the informative half and corrects the hypothesis's own mechanism: this model class does not *lack* a level anchor, it **rejects added level columns** — the second independent confirmation of EXP-019's split-search-dilution reading, now generalised from internal (`price_rolling_mean_168h`) to exogenous (gas) provenance. Not a regime artifact (worse in 5 of 7 months, Jul +16.7%, no rescue in August). **Standing conclusion: at a 56-day window this model gains nothing from added exogenous columns and loses from added level columns — the next lever is window length or model class, not features** (→ augur#15, foundation models). The four parquet columns stay (additive-only, free); `FEATURE_COLUMNS` is untouched.
- **Model class is the live lever (EXP-021, 2026-08-29 — evidence only, nothing deployed)**: the half of EXP-020's standing conclusion that survived was tested the same day. **`amazon/chronos-bolt-base` run zero-shot — no features, no exogenous, no calendar, no NL-specific training, no nightly retrain, only the 56-day price series — beats the lean LightGBM by 20.3% quantile score and 16% MAE** (DM p<0.0001), and beats today's 24-feature production set by 26.0%, on the same 260-vintage window with exact `(t0, timestamp)` pairing. The pre-commit predicted *parity*; all four gates pass as superiority against both bases. **The calibration half may matter more than the skill half**: the FM's *raw* band coverage is 0.811 against the 0.80 target **with no conformal layer**, where the incumbent sits at 0.611 — and its upper-side coverage beats lean in 8 of 9 months, with the largest gaps in exactly the months that opened augur#19 (Jul +0.232, Aug +0.174). The 64→72h autoregressive rollout, pre-registered as the likeliest contaminant, runs the other way: the FM's edge *grows* with horizon (−19.9% h1-64, −22.8% h65-72). Six-check code-review battery clean, and it found a real defect the pre-commit missed (`build_features` is `shift(1)`, so the incumbent's feature row stops at t0−1h; the reported arm is matched to that, costing 0.8pp of 21). Contamination is impossible, not merely unlikely — weights frozen 2025-11-21, window opens 2025-12-05. **Nothing shipped**: per the pre-committed decision rule, superiority triggers fresh-vintage confirmation (**EXP-021a**, ≈2026-09-09, after EXP-018a) → operational feasibility on sadalsuud (CPU latency, tail risk) → live shadow → only then an ADR-006 amendment. Runner `scripts/exp021_foundation_zeroshot.py`, compute on `b650-gpu`.
- **Why it wins — mechanism measured, not assumed (EXP-022, 2026-08-29, exploratory diagnostic, `parked`)**: a context ladder settles it. Chronos with a **7-day** context still beats LightGBM trained on **56 days** by 12.5% QS (p<0.0001), so **~12 of the 20.3 points are pretrained prior and only ~8 are context volume** (the latter being a critique of our 14-number feature vector, not of gradient boosting). **Band coverage is flat across the ladder — 0.811/0.804/0.813/0.823 at 56d/28d/14d/7d — so the calibration win is *pure* pretrained prior**, which is also why the pinball gain is largest at p10 (26.3%) and smallest at p50 (16.3%): tail quantiles are what a 1344-row nightly refit can least afford. Bands are better *shaped*, not wider (lean needs 2.0x inflation to reach 0.811, ending 1.7x wider; at matched width it gets 0.682). The win is routine, not extremal: FM takes 75% of vintages, median per-vintage MAE 19.89 vs 26.62, but **p95 is a tie** (48.55 vs 48.39). **This corrects EXP-021's own stated mechanism**: the level-drift story carried since EXP-018/019/020 does *not* explain it — mean signed error is +0.34 (FM) vs −0.52 (lean), and lean's worst month is June, not August. Runner `scripts/exp022_context_ladder.py`.
- **CORRECTION to the calibration claim above (EXP-025, 2026-08-29 overnight)**: the "0.611 vs 0.811" framing **overstates the FM's calibration advantage and must not be requoted**. 0.611 is the incumbent's *pre-conformal* band coverage, and production does not ship a pre-conformal band — it wraps CQR. Measured: **lean + production CQR reaches 0.788** against the FM's 0.811. The honest live gap is **0.023, not 0.200**. What survives is an *efficiency* edge: the FM reaches 0.811 at median band width 73.4 where CQR needs 89.2 for 0.788 (Winkler 119.8 vs 148.9). Transplanting the FM's spread onto the incumbent's median was tested and **refuted** (0.733, below its 0.76 gate). Discharges EXP-021a Alternative 4. Also: a median blend at w=0.80 toward the FM beats the FM alone (−1.4% QS, p=0.0042), unlike EXP-021's unoptimised 50/50 — in-sample weight, unconfirmed. Runner `scripts/exp025_band_transplant.py`.
- **Window length is a real lever (EXP-023, 2026-08-29 overnight — evidence only, nothing deployed)**: the lever EXP-020 named. Sweeping 28/56/84/112/168d on the lean set, **112 days beats production's 56 by 3.0% QS (DM p<0.0001) with better coverage on both sides and better Winkler — all four pre-committed gates pass**. The curve is an inverted U (28d +5.2%, 84d −1.4%, 112d −3.0%, 168d −2.5%), so a genuine interior optimum exists. Two honest limits: the Position's stronger 5% claim is *not* met, and its mechanism is *not* supported (the gain is near-uniform across quantiles, not tail-concentrated). Parked, not shipped — best-of-five on the discovery window is the selection bias EXP-018a exists to guard against, and the confound control (fix the vintage set so the 168d rung is available throughout) left only **95 vintages, all 2026-05-19..2026-08-21** — three months, May–August, squarely the rising-price stretch (corrected 2026-08-30: earlier records said "Mar–Aug"; the feature frame starts 2025-12-02, not the parquet's 2025-09-28, because `load_frame_ext` drops rows on the EXP-020 fundamentals columns). Runner `scripts/exp023_window_sweep.py`. **Demoted 2026-08-30 by EXP-023a Stage A (EXP-032)**: on 56 vintages the discovery sweep never scored (`t0 ∈ [2026-03-24, 2026-05-18]`), 112d is **1.4% *worse*** than 56d (DM p=0.894) — the sign flipped against a discovery estimate of −3.0%, and 56d wins coverage on both sides and Winkler. Alternative 1 (regime artifact) fires: the gain looks specific to the May–Aug rising-price stretch. Stage A is a *quasi*-holdout (the data existed when 112 was chosen) so EXP-023 is not formally refuted, but this is no longer a cheap win — Stage B on ≥45 fresh vintages (≈2026-10-09) is now the test that decides it.
- **Exogenous data is not useless — it was unusable by LightGBM (EXP-028/029, 2026-08-29 overnight — evidence only, nothing deployed)**: EXP-020's refutation of exogenous held for *one model class*, with a LightGBM-specific mechanism. **`amazon/chronos-2`, which takes covariates at inference time with no retraining, gains 8.3% QS from the same columns (DM p=0.0051, MAE 23.10→21.14)** — Augur's first positive exogenous result. Gate 3 fails (coverage cost on both sides), so it is a skill-and-sharpness-for-calibration trade, not a free win; `parked`. Caveats that matter: chronos-2 **univariate** already beats bolt-base by 5.5% on this subset, so part of the headline is the newer model; and **chronos-2's weights were modified 2026-06-05, inside the evaluation window**, so unlike bolt-base contamination is not excluded by construction — all arms restricted to `t0 > 2026-06-05`, and the internally valid comparison is covariate-vs-univariate. Gas is unhelpful even here (fourth strike against added level columns). **EXP-029's cheap residual pre-screen said don't bother and was wrong** — it would have vetoed this; only its own pre-registered Alternative 3 kept the arm alive. Runners `scripts/exp028_chronos2_covariates.py`, `scripts/exp029_residual_screen.py`.
- **The context advantage is NOT recoverable inside LightGBM (EXP-024, 2026-08-30)**: EXP-022 attributed ~8pp of the FM's edge to context volume — the incumbent predicts 72 horizons from a single ~14-number feature row. Widening that row **fails**: +1.6% QS worse at 33 features, **+2.5% worse at 37** (DM p=1.0000). The dimensionality-**matched** control is the payoff — at identical width (37 vs 37), raw lags cost +2.5% but derived/smoothed columns cost **+12.2%** and additionally break coverage and Winkler. So **count and kind both matter** (~2.5pp from width, a further ~9.7pp from making them derived). Consequence: the bottleneck is the model class's ability to consume a long context, not the feature row's width — which removes the cheapest alternative to the model-class reading. Fourth independent confirmation of the EXP-019/020 dilution mechanism, and the first to isolate it from dimensionality. Runner `scripts/exp024_lag_richness.py`.
- **Do not fine-tune (EXP-027, 2026-08-30)**: fine-tuning `chronos-bolt-base` on NL history degrades **both** halves monotonically — MAE 26.75→31.85 (+19.0%) and band coverage **0.825→0.394** (−0.431), with median band width collapsing 85.5→33.9. The predicted *mechanism* (a narrow single-series spread prior overwriting the broad pretrained one) is confirmed emphatically; the predicted *dissociation* is not, because point skill was not bought in exchange. Only **3578 points** exist before the cutoff. Verified as overfitting, not divergence (train loss −45% while held-out MAE +19%); even 250 steps already destroys calibration. **Zero-shot is the deployment mode**; EXP-021's Alternative 4 is closed. Scope limit: this is *naive* fine-tuning — no LR schedule, no early stopping, no recipe search. Runner `scripts/exp027_finetune_dissociation.py`.
- **The pretrained prior is cheap (EXP-026, 2026-08-29 overnight)**: `chronos-bolt-tiny` retains **93.5%** of base's advantage (mini 97.1%, small 98.3%), band coverage flat across the ladder. The "205M-parameter model in the nightly path" objection largely dissolves. **Latency half completed by proxy (EXP-030, 2026-08-30)**: one 1343-point/72h forecast on 4 pinned threads takes **tiny 0.03s / mini 0.06s / small 0.13s / base 0.52s** — ~19× headroom on EXP-026's 10s gate and ~115× on Stage 2's 60s gate. Latency is a non-issue and deployment cost is dominated by the torch dependency footprint, not inference time. **Now measured on the real host (EXP-033, 2026-08-30)**: on sadalsuud itself — tiny 0.11s, mini 0.22s, small 0.46s, **base 1.16s** median (max 1.17s), in an *isolated* venv that never touched production's. That is **~52× headroom** on Stage 2's 60s gate and ~8.6× on EXP-026's 10s one. The proxy understated the real host by 2.2×, inside the 3–5× band predicted, so it was a valid lower bound. **EXP-021a Stage 2's latency gate is discharged**; its other half (per-vintage MAE tail risk, p95 ratio ≤1.5) and the venv-footprint question remain open.

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
| `ml/shadow/update_shadow.py` | Nightly LGBM retrain + 72h predict + CQR widen + consumer-pricing fields via `read_arf_surcharge` |
| `ml/shadow/evaluate_shadow.py` | Daily LGBM-vs-ARF metrics, appends to `ml/shadow/eval_log.jsonl` |
| `ml/shadow/eval_log.jsonl` | Append-only eval log per realised eval day |
| `ml/shadow/secure_pickle.py` | HMAC-SHA256 sidecar; `save_signed_pickle` / `load_verified_pickle` |
| `ml/shadow/metrics.py` | Reusable metrics module — pinball, mean_quantile_score, twcrps_left_tail, lower_side_coverage, winkler_interval_score, diebold_mariano (manual Newey-West HAC) |
| `ml/models/shadow/shadow_model.pkl` | Trained LGBM artifact (HMAC-signed; **gitignored** — regenerated nightly on sadalsuud from the rolling window, never committed) |
| `ml/models/shadow/shadow_state.json` | `last_run_utc`, `pending_predictions`, `calibration_history` (with `p10_raw`/`p50_raw`/`p90_raw`), CQR stats |
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
| `scripts/wait_for_edh.sh` | systemd `ExecStartPre` gate — polls EDH `data_quality_report.json:timestamp` for today's date **and a publish hour ≥ `MIN_PUBLISH_HOUR_UTC=12`** (2026-08-28: the date alone let an EDH overnight catch-up publish release the run 90s before the real one, costing a vintage; the NL day-ahead auction clears ~12:00 CET, so a pre-noon-UTC stamp can't hold today's prices). Max wait 4h, then proceeds with stale data so the run isn't fail-closed — the t0-advance alarm now marks it. |
| `scripts/systemd/{augur-daily.service,augur-daily.timer,README.md}` | Canonical systemd unit files; deploy via `sudo cp` to `/etc/systemd/system/`. |
| `netlify.toml` | Build pipeline: decrypt → hugo |

**Process + experiments**:
| Path | What it is |
|------|-----------|
| `experiments/registry.jsonl` | Append-only experiment log (EXP-001..EXP-033, gap at EXP-017 which was never run); schema in `experiments/README.md` |
| `docs/decisions/006-lightgbm-quantile-production-architecture.md` | ADR-006 — what the production system does |
| `docs/decisions/007-model-promotion-method.md` | ADR-007 — how we decide what to change |
| `docs/decisions/004-river-online-learning-architecture.md` | ADR-004 — superseded by ADR-006 |
| `docs/hypothesis-log.md` | Provisional positions awaiting evidence; iteration-4/5 EXP-014 entries resolved 2026-05-29 |
| `docs/experiment-backlog.md` | Five designed-but-unrun experiments (EXP-023..027), each an ADR-007 pre-commit with gates fixed 2026-08-29; all run on the existing 260-vintage window and consume no fresh vintages |
| `docs/articles/m4-metric-redesign-story.md` | Case-study article — five-iteration arc from M4 park to EXP-014 promotion (~4960 words) |
| `docs/literature.md` | Topic-indexed bibliography |
| `docs/metric-redesign-literature-review.md` | Focused EPF metric review (input to EXP-012) |
| `docs/exp-012-results.md` | EXP-012 + EXP-013 corrections report |
| `docs/lightgbm-shadow-postmortem.md` | M4 Path B postmortem (historical; superseded by EXP-014 swap) |
| `docs/lightgbm-quantile-shadow-plan.md` | Original shadow plan (historical) |
| `docs/river-arf-retrospective.md` | ARF retirement narrative + closing addendum on the EXP-014 promotion |
| `docs/model-progress-log.md` | Dated narrative log of ML pipeline changes |
| `tests/` | pytest suite — 222 tests (SecureDataHandler, OnlineFeatureBuilder, LGBM forecaster + multi-horizon + secure_pickle + conformal + backtest + update_shadow + evaluate_shadow + slice MAE + archive path + metrics module + **consolidate parsers (test_consolidate.py, 18 tests, 2026-06-10)** + **t0-advance guard (TestClassifyT0Advance, 7 tests, 2026-08-28)** + **EXP-020 fundamentals parsers (20 tests, 2026-08-29)**) |
| `scripts/m4_method_run.py` | M4 verdict runner (historical — pre-EXP-014) |
| `scripts/exp012_evaluate.py` | EXP-012/013 paired-data evaluation (vintage-corrected) |
| `scripts/exp014_evaluate_promotion.py` | EXP-014 promotion-criterion runner |
| `scripts/exp015_replay_cqr.py` | EXP-015 offline replay — per-side CQR vs production bands on `calibration_history` raws |
| `scripts/exp016_replay_aci.py` | EXP-016 offline replay — per-side ACI (Gibbs-Candès) with α trace + γ sensitivity |
| `scripts/exp018_stage0_ablation.py` | EXP-018 per-feature-group ablation — production-shaped walk-forward, `--variants`/`--reuse-predictions`; **also the EXP-018a Stage-1 runner** |
| `scripts/exp019_stationary_ablation.py` | EXP-019 anchor-relative spread variants (imports the EXP-018 harness) |
| `docs/experiment-results.md` | **Generated** readable digest of all experiments — summary table + per-experiment sections |
| `scripts/render_results.py` | Renders the digest from the registry; `--check` fails if stale |
| `scripts/audit_registry.py` | Registry auditor — 5 checks incl. number-traceability and pre-commit immutability |
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
