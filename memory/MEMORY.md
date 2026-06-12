# Memory

<!-- Loaded every session. Keep lean — index only, deep knowledge in topic files.
     END-OF-SESSION: review gotcha-log, promote patterns, retire stale entries. -->

## Topic Files

| File | When to load | Key insight |
|------|-------------|-------------|
| `memory/gotcha-log.md` | Stuck or debugging | Problem-fix archive |
| `memory/data-formats.md` | Working with energyDataHub data | Schema v2.1 structure, units, timezone conventions |
| `memory/ml-decisions.md` | ML architecture choices | Historical XGBoost plan + River ARF era; superseded by ADR-006 |

## Current State

- Dashboard: 5 tabs (Prices, Weather, Grid, Market, Model) on Netlify, served from `static/data/augur_forecast_shadow.json` (price charts) and `static/data/augur_forecast.json` (Model-tab metrics). **Chart time-axis convention is now enforced at a single rendering boundary** — `utcToLocalNaiveISO()` in `static/js/modules/chart-renderer.js` normalises every timestamp to browser-local naive ISO at `renderChart()`/`getCurrentTimeLineShape()`/`getChartLayout()`. ADR-008 documented this convention; commit `fc24676` (2026-06-06) is its actual implementation. Data layer keeps using `new Date(ts)` for sorting/filtering.
- Weather tab: two-dropdown UI parity. Both "Temperature & Wind (10-day)" and "Cloud Cover & Humidity" each show a `<select>` (synced — changing one mirrors the other before re-render). Distinct aria-labels per chart. Commits `656e917` + `fa28450`.
- **EDH v2.2 envelope shim, both sides** (`4a557c8` JS 2026-06-07; `e11487b` Python 2026-06-10): EDH commit `3dfc7fb` (2026-06-07 12:43 CEST) wrapped `energy_price_forecast.json` + `wind_forecast.json` under `{metadata, data: {...}}` to match the other 14 strategic feeds. The dashboard JS got a defensive `obj.data ?? obj` shim in `4a557c8` (data-processor.js:117, tab-charts.js:64-79, dashboard.js:264). The Python parsers ALSO needed the equivalent shim — the 4a557c8 commit message asserted "Python migrated transparently via `_migrate_2_1_to_2_2`" but `load_json_file` in `ml/data/consolidate.py` never invokes schema_registry, so parsers silently returned empty Series for every v2.2 file until `e11487b` added `_unwrap_v22_envelope` at three sites (`parse_price_file`, `_parse_single_source`, `parse_wind_file`). Pattern updated in gotcha-log Promoted table + user-memory `feedback_edh_schema_consumer_audit.md` to reflect: NEITHER side auto-migrates; audit JS + Python parsers + any direct `json.load`/`fetch` of EDH files on every schema bump.
<!-- verify: cd /c/local_dev/augur && [ -f static/data/augur_forecast.json ] && [ -f static/data/augur_forecast_shadow.json ] && [ -f layouts/index.html ] && grep -q "utcToLocalNaiveISO" static/js/modules/chart-renderer.js && grep -q "weather-location-cloud" static/js/dashboard.js && grep -q "energyData.data ?? energyData" static/js/modules/data-processor.js && grep -q "_unwrap_v22_envelope" ml/data/consolidate.py && echo PASS || echo FAIL -->
- ML pipeline: **live** — LightGBM-Quantile in production (ADR-006), ARF as backup signal (ADR-004 superseded). Daily system-level systemd timer on sadalsuud (fires 16:30 UTC + `wait_for_edh.sh` ExecStartPre gate, post-augur#12) runs ARF + parquet consolidate + LightGBM retrain + shadow eval.
<!-- verify: cd /c/local_dev/augur && grep -q "ml.shadow.update_shadow" scripts/daily_update.sh && grep -q "augur_forecast_shadow.json" static/js/dashboard.js && echo PASS || echo FAIL -->
- **LightGBM promotion**: EXP-014 (2026-05-29), redesigned criterion (skill DM p<0.10, calibration not >0.02 worse than ARF). LGBM MAE 28.9 vs ARF MAE 38.4 (25% better, DM p=0.029). One-line revert path: change `static/js/dashboard.js:loadAugurForecast` back to `augur_forecast.json`.
- **ARF retained as backup signal**: still runs daily inside `daily_update.sh` (now systemd-triggered post-augur#12, not cron); produces `augur_forecast.json`, the surcharge cache in `ml/models/state.json` (consumed by LightGBM's consumer-pricing step), and the timestamped archives in `ml/forecasts/` used by `evaluate_shadow.py`. Retiring ARF infrastructure deferred until ≥1 rolling-window cycle (~56 days) of clean LightGBM operation.
- **Known weakness in production**: lower-side coverage 0.834 over 30 vintages / 2112 realised hours through 2026-06-11 (vs nominal 0.90), measured from `calibration_history` — **not** `eval_log.jsonl`, whose rows mix 24/48/72h vintages and have permanent holes at 06-08/06-10. Tracked as **augur#19**. **EXP-015 + EXP-016 both run and resolved 2026-06-12** (offline replays, both `parked`, criteria pre-committed per ADR-007): per-side CQR fixes the side asymmetry (+0.048 at +2.5% Winkler), ACI on top fixes post-shift days (0.852), but a γ-independent ceiling ~0.85 remains from first-shift-day misses (06-02/06-03) that no calibration layer can reach. Conclusion: the gap lives in the raw quantiles (q10_raw biased high entering regime shifts) → **EXP-017 (9-quantile training) carries the arc**; needs a walk-forward backtest over a window including 06-01..06-03 + fresh pre-commit. Replay scripts: `scripts/exp015_replay_cqr.py`, `scripts/exp016_replay_aci.py`. Bonus finding: production `compute_cqr_q` conformalizes already-widened bands (feedback loop), not raw quantiles.
- ENTSO-E collector recovered ~2026-04-18 after 2026-03-26 outage; guard in `parse_price_file()` remains.
- Test suite: 195 tests passing (177 prior + 18 new in `test_consolidate.py` for EDH v2.1/v2.2 parser shapes, units, timezone normalisation, isinstance guards — added 2026-06-10 as code-review followup to the v2.2 fix).
<!-- verify: cd /c/local_dev/augur && python -m pytest tests/ --collect-only -q 2>&1 | grep -qE "19[0-9] tests" && echo PASS || echo FAIL -->
- Experiment registry: EXP-001..EXP-016 in `experiments/registry.jsonl`. EXP-014 is the production-promotion entry; EXP-015/016 are the parked calibration-layer replays (2026-06-12).
<!-- verify: cd /c/local_dev/augur && [ "$(wc -l < experiments/registry.jsonl)" -ge 16 ] && echo PASS || echo FAIL -->
- Daily-pipeline output guards (2026-06-12, `1c33daa`): two post-run checks in `daily_update.sh` alarm in the commit subject when the ARF forecast spans <24h or no eval row lands for >2 days — closes the "rc=0 but empty output" blindspot from the EDH v2.2 incident. **ARF forecasts currently 48h (not 72h)** — v2.2 files only span today+tomorrow; tracked as **augur#26**, alarm deliberately doesn't fire on it.
<!-- verify: cd /c/local_dev/augur && grep -q "ARF_FC_HOURS" scripts/daily_update.sh && grep -q "EVAL_LAG_DAYS" scripts/daily_update.sh && echo PASS || echo FAIL -->
- Docs structure: CLAUDE.md + docs/RUNBOOK.md + docs/decisions/ (ADR-001..008, gap at 005; ADR-001 superseded by ADR-008 on 2026-06-03) + docs/articles/ (M4 metric-redesign case study) + docs/river-arf-retrospective.md + docs/lightgbm-quantile-shadow-plan.md + docs/lightgbm-shadow-postmortem.md + docs/exp-012-results.md + docs/metric-redesign-literature-review.md + docs/literature.md + docs/hypothesis-log.md + docs/model-progress-log.md + memory/.
- agent-ready-projects: v1.9.0 (hypothesis-log + literature-index patterns inform v1.10+ framework candidates).

## Recently Promoted

- **The model-promotion method** (ADR-007): pre-commit → test-on-existing-data → article-review battery → code-review battery. Each layer catches a different class of error. Promoted from the five-iteration M4 → EXP-014 arc (2026-05-29).
- **Code-review battery surfaces what article-review can't**: vintage-mismatched data joins, sort-then-pinball quantile bias, HAC-bandwidth underestimation, non-canonical metric implementations. Always fire a code-level battery before drawing conclusions from a numerical script. Promoted 2026-05-29 from EXP-013.
- **Don't condition evaluation slices on the realised outcome** (forecaster's dilemma, Lerch et al. 2017). MAE-on-y-extreme rewards constant-mean predictors and biases comparisons. Use threshold-weighted scoring (with the threshold pre-committed from a *prior* window) instead. Promoted from M4 verdict 2026-05-29.
- **Newey-West HAC bandwidth = max_horizon − 1, not `n^(1/3)`**, when paired loss differentials come from h-step-ahead overlapping forecasts. Promoted 2026-05-29 from EXP-013 code review.
- If EWM variance looks wrong → check that `ewm_mean` (signed) is used, not `ewm_abs` — promoted from code review 2026-03-28.
- If exchange prices corrupt lag buffer → ensure they're only pushed once (pre-loop), not also in forecast loop — promoted from code review 2026-03-28.
- If adding a Python dep that ships in cron → install it manually in sadalsuud's venv first; the cron does NOT run `pip install -r requirements.txt`. Caught 2026-04-30 by manual dry-run of M3 shadow pipeline (lightgbm not installed). Alternative: extend `daily_update.sh` to install deps idempotently.
- If fixing a bad path in code → also handle git state of files that lived at the bad path. M3 fixup A redirected ARF archives from `static/ml/forecasts/` to `ml/forecasts/`; the existing tracked files at the old location showed up as deletions on sadalsuud's working tree, requiring `git restore` before the branch switch could proceed. Rule: a path-fix commit should either keep the old files (they continue to be tracked, just become frozen historical) or include their `git rm` in the same commit.

## Active Decisions

- **ADR-006**: LightGBM-Quantile + CQR is the production forecasting architecture (2026-05-29). Multi-horizon stacking, 56-day rolling window, retrain-from-scratch nightly.
- **ADR-007**: Promotion method — single skill criterion + one-sided calibration guardrail, pre-committed in hypothesis-log, with article-level + code-level review batteries before action.
- **ADR-008** (2026-06-03, fully implemented 2026-06-06 in `fc24676`): Chart data carries real UTC ISO strings; **rendering layer normalises to browser-local naive** at a single boundary (`utcToLocalNaiveISO()` in `chart-renderer.js`). Supersedes ADR-001 (the `convertUTCToAmsterdam` mutation pattern caused EZ↔Augur misalignment, augur#16). The original ADR-008 claim "Plotly renders UTC strings in browser-local" was *wrong*; `fc24676` is the actual fix. CLAUDE.md hard constraint still stands: use `Intl.DateTimeFormat` for any wall-clock display; never bake offsets into stored timestamps.
- ADR-003: Netlify cache `--force` flag — ensures fresh data on webhook builds.
- ADR-004 superseded by ADR-006 (ARF replaced as model, kept as backup pipeline).
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast (wholesale × VAT + cached ARF surcharge).
- Features (LightGBM): 24 total — price lags (8), rolling mean/std (6), calendar (7), wind/solar/load (3) + horizon-as-feature.
- Noise: client-side `Math.random` ±5%, transparent to users.

## Open Issues

- **augur#12** (Phase 1 deployed 2026-06-08, Phase 2 deployed 2026-06-09 — 1-week observation window 2026-06-09..2026-06-15): systemd user-timer `augur-daily.timer` at 16:30 UTC + `ExecStartPre=wait_for_edh.sh` polling EDH's `data_quality_report.json:timestamp` until today's date appears (max-wait 4h, exits 0 on timeout — `daily_update.sh`'s pre-flight `SHADOW_PRE_AGE_H >36h` ALARM surfaces stale-state failures in the next day's commit; missing daily commit on origin/main is the external alive signal). Empirically EDH publishes 16:23-20:13 UTC (14-day sample, **not** the 15:20 UTC the old MEMORY claimed). Artifacts canonical at `scripts/wait_for_edh.sh` + `scripts/systemd/{augur-daily.service,augur-daily.timer,README.md}`; deployed as **system-level units** at `/etc/systemd/system/` (re-deployed 2026-06-09 — initial Phase 1 deployment was user-level, migrated to system-level same-day to eliminate the `loginctl enable-linger` dependency; service runs as `User=jeroen` so SSH-key / venv / .env access is preserved). **First (user-level) timer fire was clean** (Mon 2026-06-08 18:31:44 CEST, `status=0/SUCCESS`, wait_for_edh detected EDH-timestamp 2026-06-08T09:04:05Z; commit `98ce3b8` landed 16:32 UTC, **after** the cron's 14:45 UTC commit `09f7c15`). Cron line was commented 2026-06-09 with marker `# Migrated to systemd augur-daily.timer 2026-06-08 (augur#12). Restore if broken.`, then **deleted entirely on 2026-06-10** (start of session — sadalsuud crontab is now empty; backup remains at `/tmp/crontab.backup`). System-level timer has fired cleanly Mon 2026-06-08, Tue 2026-06-09, and twice on Wed 2026-06-10 (one auto + one manual via `sudo systemctl start augur-daily.service` during the v2.2 fix). Rollback path (if ever needed): `ssh sadalsuud "crontab /tmp/crontab.backup"` + `sudo systemctl disable --now augur-daily.timer`.
<!-- verify: ssh sadalsuud "systemctl is-enabled augur-daily.timer && systemctl is-active augur-daily.timer" 2>/dev/null | grep -q "enabled" && echo PASS || echo FAIL -->
- **augur#19** (filed 2026-06-03): lower-side calibration umbrella. **EXP-015 (per-side CQR) + EXP-016 (per-side ACI) both run and parked 2026-06-12** — see Current State known-weakness bullet for the arc conclusion. **Next: EXP-017 (9-quantile training)** — a model-training change, needs walk-forward backtest (no stored 9-tau history to replay) + fresh ADR-007 pre-commit; both parked layers are candidates to re-add on top of better raws. **2026-06-05 comment** adds a forward pointer for Phase-1-for-LGBM (TTF + genmix features) as EXP-018 candidate behind the calibration arc.
- **augur#26** (filed 2026-06-12, root cause corrected same day): ARF 48h truncation was a **buffer-sizing bug, fixed in `f49a1c8`** — `OnlineFeatureBuilder.price_history` deque(maxlen=200) was sized for hourly data (~8 days); EDH v2.2's 15-min resolution shrank it to ~50h and generate_forecast's ~100 future quarter-point pushes evicted history to ~24h, failing the required `lag_24h` for the first ~21 forecast hours (the "5 hours with exchange lags" anomaly was the tell). maxlen now 800; buffer refills ~96/day — **verify a ≥72h `Generated NN-hour forecast` line on the 06-13/06-14 runs, then close #26**. The v2.2 file-window narrowing (today+tomorrow vs ~8 days) is real but secondary (long-horizon exogenous quality, not truncation) — filed EDH-side as **energydatahub#33**.
- **augur#22** (filed 2026-06-05): EXP-018 candidate — HDD/CDD as long-horizon demand features. Open-Meteo demand_weather data already collected (population centers + HDD/CDD pre-computed). Hypothesis: HDD/CDD adds signal at h+25..h+72 horizon group where ENTSO-E load forecast is structurally absent. Pre-commit criterion: paired DM at h+25..h+72 p<0.10 + calibration not >0.02 worse at long horizons + no regression at h+1..h+24. Hard dep on augur#12, soft dep on EXP-015.
- **augur#23** (filed 2026-06-06): inter-source price-chart lag investigation. After `fc24676` time-axis fix the residual lags between EZ/EPEX/ENTSO-E are smaller but still visible. Investigation tracked: all four sources publish identical `+02:00` ISO convention (ruled out as a timezone-parsing issue). Most likely causes: 15-min ENTSO-E vs hourly EPEX granularity, per-source filtering in `data-processor.js`, genuine publication-cadence differences. Low priority — likely partly genuine.
- **augur#24** (filed 2026-06-07): dashboard silent-empty-state UX hardening — 5 findings from review battery (zero-trace guard on Prices chart RPN 288, defensive shim on remaining processors RPN 252 hypothetical, DataLoader silent-null→notification RPN 210, empty-`<select>` placeholder RPN 168, `lastUpdate` `new Date()` fallback lies RPN 120). No FAIL; all in the same silent-failure category that the `4a557c8` fix patched defensively but didn't generalize. Recommend tackling #1/#3/#4/#5 (real pre-existing modes); skip #2 (hypothetical future schema bump).
- **EDH-side follow-ups** — filed 2026-06-12 as **energydatahub#34** (elspot: today-only fetch + probable ENTSO-E redundancy since the Feb 2026 pynordpool migration) and **energydatahub#33** (v2.2 load/price file window narrowed to today+tomorrow; also stale `resolution: hourly` metadata on 15-min data). If #34 resolves by retiring elspot, drop it from `static/js/modules/constants.js` DATA_SOURCES.forecast.
- **augur#18** (filed 2026-06-03): verify EnergyZero endpoint really returns all-in consumer pricing as the constants.js comment claims; clarify wholesale vs consumer comparator labelling on the dashboard.
- **augur#15** (filed 2026-06-03): foundation-model spike — Chronos / TabPFN-TS as offline baselines or ensemble members. Won't fix the calibration gap.
- **augur#14**: gap-detection + automated backfill for missed daily runs. **2026-06-12 comment** documents the concrete incident (three "ARF OK | eval rc=0" commits while ARF published empty forecasts; eval vintages 06-08/06-10 permanently unevaluable); the two `daily_update.sh` post-run guards (`1c33daa`) cover the alarm half — automated backfill remains open.
- **Model-tab metric parity**: `update_shadow.py` doesn't yet emit ARF-equivalent metadata (`metrics_history`, `error_history`, `n_training_samples`), so `static/js/modules/model-viz.js` still reads `augur_forecast.json` (ARF backup). Future work to extend the LightGBM metadata schema and update model-viz.js.
- **Publishability backlog** (`docs/hypothesis-log.md` entry, review-by 2026-12-31): ADR-006 + the M4 → EXP-014 arc is publishable with ~2-3 weeks of empirical follow-up (naive baseline, PIT, multi-window robustness, canonical CRPS at 9-19 quantiles, canonical twCRPS integral). Or ~3-4 days of polish for a blog post.
- **Deferred ML features**: augur#2 (NED production), #3 (gas/carbon prices — parsers banked on `feat/new-features-ttf-genmix`, data precondition verified met 2026-06-05), #4 (cross-border flows), **#22 (HDD/CDD as long-horizon demand features — added 2026-06-06)**. Re-scoped 2026-06-05/06: Phase-1-for-LGBM (TTF + NL genmix) and HDD/CDD are queued behind augur#19 EXP-015..017 — calibration first to avoid conflating effects. ARF-era `warmup_p1`/`backtest_p1` tooling is stale; new work would port parsers into `ml/shadow/features_pandas.py`.

## Upstream data sources (energydatahub side)

Production weather/solar/AQ collectors that augur consumes (or could consume) via the GH Pages → Netlify decrypt path. Owned by the energydatahub repo, not by augur.

- **`weather_forecast_multi_location.json`** (consumed by augur dashboard Weather tab): Open-Meteo since 2026-06-05 (was Google Weather; collector swap in energydatahub `df1bdb8`/`6e9433e`). 6 strategic CWE+DK locations (Hamburg/Munich/Arnhem/IJmuiden/Brussels/Esbjerg), 10-day forecast, 17 fields incl. WMO `condition` text via energydatahub `WMO_CODE_MAP`.
- **`demand_weather_forecast.json`** (NOT yet consumed; tracked at augur#20 for dashboard wire-up + augur#22 for model-feature wire-up): Open-Meteo at 11 NL/DE/BE population centers, 7-day forecast, includes pre-computed HDD/CDD.
- **`weather_forecast_buurt.json`** (NOT consumed by augur; FyE B1 input): Open-Meteo at Elsweide + Elderveld centroids (computed from CBS Wijken en Buurten polygons), 16-day forecast, full enriched field set.
- **`solar_forecast_buurt.json`** + **`air_quality_buurt.json`** (NOT consumed by augur; FyE B1 inputs): Open-Meteo solar irradiance + Luchtmeetnet (RIVM) NO2/PM10/PM25/O3/AQI at the same buurt centroids.
- **Workflow defensive gate**: `energydatahub/.github/workflows/collect-data.yml` now exits 1 when `data_quality_report.json:overall_status == "critical"`. Prevents the silent-failure pattern that masked GoogleWeatherCollector returning `API_KEY_INVALID` for ~7 months (Nov 2025 → Jun 2026).
- **Storage migration**: energydatahub repo uses git as time-series archive (intentional). Tracked at energydatahub#9 — runway ~17 months until hits GitHub's 1 GB soft limit.
- **Product expansion**: augur#8 (SaaS API), #9 (ensemble forecasting — overlaps with #15), #10 (multi-country). Strategic / long-horizon.
- **agent-ready-projects#12** (framework-level, not augur): calendar-bridge skill candidate — plant `Review by:` dates from hypothesis logs into Google Calendar.

## Closed 2026-06-03

- ✅ augur#16 — dashboard timezone-mutation bug (ADR-001 superseded by ADR-008; convertUTCToAmsterdam removed). Commit `5ae82b4`.
- ✅ augur#17 — dashboard wholesale lower-band clamp at 0 (hid LGBM's negative-price predictions; same pattern as deprecated ARF clamp). Commit `07fb9a4`.
- ✅ augur#5 — backtesting framework substantially completed in a different shape during EXP-009..014.
- ✅ augur#6 — peak/off-peak model variants speculative + obsolete (LGBM already does horizon stacking).
- ✅ augur#7 — ARF ensemble / Prophet baseline stale (ARF retired; Prophet overlaps with #15).
- ✅ augur#11 — cron→systemd standalone superseded by broader augur#12.

## Closed 2026-06-12

- ✅ **Missing eval-row forensics** — vintages 06-08/06-10 explained (EDH v2.2 → stale parquet → t0 froze/jumped; permanent, unrecoverable); 06-09 `arf_mae: null` explained (empty ARF archive, no lookup fallback). Incident on augur#14.
- ✅ **Post-run output guards in `daily_update.sh`** (`1c33daa`) — ARF forecast <24h + eval row stale >2d alarm in commit subject. Pattern promoted: "rc=0 is not output quality".
- ✅ **EXP-015 (per-side CQR replay)** — parked; pre-commit `bcc3e78`, resolution `b40db95`. Fixes side asymmetry; can't reach regime days. Baseline redirect: horizon-conditioning refuted (deficit flat across groups).
- ✅ **EXP-016 (per-side ACI replay)** — parked; pre-commit `440b0b6`, resolution `d21b179`. Fixes post-shift days; γ-independent ~0.85 ceiling from first-shift days; Winkler guardrail tripped. Arc conclusion: gap is in the raw quantiles → EXP-017 next.
- ✅ **augur#26 filed** — ARF 48h truncation (EDH v2.2 file-window narrowing), live degradation, EDH-side fix preferred.

## Closed 2026-06-10

- ✅ **EDH v2.2 envelope wrap Python parser fix** — `e11487b` adds `_unwrap_v22_envelope` shim to `ml/data/consolidate.py`. Parquet recovered from being pinned at 2026-06-07 21:00Z; full 72h dashboard forecast restored. Eval log backfilled for 2026-06-07 (LGBM MAE 30.6 vs ARF 39.5) and 2026-06-09 (LGBM 19.9, ARF empty). 2026-06-08 has a permanent eval-log gap (no LGBM prediction set was made for that target date during the outage). Code-review battery returned REVIEW with 4 non-blocking findings (parser test gap is biggest); filed for separate follow-up.
- ✅ **augur#12 cron-comment cleanup** — sadalsuud crontab now empty; systemd timer is the sole trigger. Backup at `/tmp/crontab.backup`.
- ✅ **sadalsuud `.venv/` untracked** — `d20992a` adds `.venv/`+`venv/` to `.gitignore`; `967b653` runs `git rm -r --cached .venv/` (7921 files untracked). Next daily commit (`576a65c`) was clean — only 6 data/state files instead of swept-up venv noise.
- ✅ **sadalsuud lightgbm reinstall** — install was silently corrupted at 15:50 UTC today (root cause unknown — directory existed but contained no `__init__.py`); `pip install --force-reinstall lightgbm` recovered. Gotcha logged for potential pre-flight hardening.

## Closed 2026-06-09

- ✅ Healthchecks.io shadow endpoint removed from `scripts/daily_update.sh` (curl ping block deleted) and sadalsuud `.env` (`HEALTHCHECKS_SHADOW_URL` line removed). Comments in `scripts/wait_for_edh.sh` + `scripts/systemd/README.md` reworded — the alarm path is now: pre-flight `SHADOW_PRE_AGE_H >36h` ALARM in `daily_update.sh` surfaces stale state in the next commit message, and absence of a daily commit on origin/main is the external alive signal. Orphaned hc-ping UUID `e7771ae1-…1cc58bab0992` left dangling on healthchecks.io (owning account unknown; check will go silent/down on its own since no pings are sent).

## Resolved 2026-05-29

- ✅ EXP-011: M4 verdict (PROMOTE=False initially, Path B park).
- ✅ EXP-012: metric-redesign validation on existing data — surprise findings.
- ✅ EXP-013: corrections following code-review battery (vintage-join bug; pinball-at-p10 reversed).
- ✅ EXP-014: redesigned-criterion pass + LightGBM promoted to production (Path A swap).
- ✅ Article draft: `docs/articles/m4-metric-redesign-story.md` (five-iteration arc).
- ✅ Literature bibliography: `docs/literature.md`, `docs/metric-redesign-literature-review.md`.
- ✅ ADR-006 and ADR-007 written.
- ✅ `tests/test_metrics.py` (19 tests) added.
