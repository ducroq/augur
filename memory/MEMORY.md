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

- Dashboard: 5 tabs (Prices, Weather, Grid, Market, Model) on Netlify, served from `static/data/augur_forecast_shadow.json` (price charts) and `static/data/augur_forecast.json` (Model-tab metrics)
<!-- verify: cd /c/local_dev/augur && [ -f static/data/augur_forecast.json ] && [ -f static/data/augur_forecast_shadow.json ] && [ -f layouts/index.html ] && echo PASS || echo FAIL -->
- ML pipeline: **live** — LightGBM-Quantile in production (ADR-006), ARF as backup signal (ADR-004 superseded). Daily cron at 16:45 CEST on sadalsuud runs ARF + parquet consolidate + LightGBM retrain + shadow eval.
<!-- verify: cd /c/local_dev/augur && grep -q "ml.shadow.update_shadow" scripts/daily_update.sh && grep -q "augur_forecast_shadow.json" static/js/dashboard.js && echo PASS || echo FAIL -->
- **LightGBM promotion**: EXP-014 (2026-05-29), redesigned criterion (skill DM p<0.10, calibration not >0.02 worse than ARF). LGBM MAE 28.9 vs ARF MAE 38.4 (25% better, DM p=0.029). One-line revert path: change `static/js/dashboard.js:loadAugurForecast` back to `augur_forecast.json`.
- **ARF retained as backup signal**: cron continues; produces `augur_forecast.json`, the surcharge cache in `ml/models/state.json` (consumed by LightGBM's consumer-pricing step), and the timestamped archives in `ml/forecasts/` used by `evaluate_shadow.py`. Retiring ARF infrastructure deferred until ≥1 rolling-window cycle (~56 days) of clean LightGBM operation.
- **Known weakness in production**: lower-side coverage ~0.81 vs nominal 0.90 target. Same as ARF era; swap doesn't worsen. Next experiment: horizon-conditioned CQR or ACI (Gibbs & Candès 2021).
- ENTSO-E collector recovered ~2026-04-18 after 2026-03-26 outage; guard in `parse_price_file()` remains.
- Test suite: 177 tests passing (SecureDataHandler, OnlineFeatureBuilder, LightGBM forecaster + multi-horizon + secure_pickle + conformal + backtest + update_shadow + evaluate_shadow + slice MAE + archive path + new metrics module).
<!-- verify: cd /c/local_dev/augur && python -m pytest tests/ --collect-only -q 2>&1 | grep -qE "17[5-9] tests" && echo PASS || echo FAIL -->
- Experiment registry: EXP-001..EXP-014 in `experiments/registry.jsonl`. EXP-014 is the production-promotion entry.
<!-- verify: cd /c/local_dev/augur && [ "$(wc -l < experiments/registry.jsonl)" -ge 14 ] && echo PASS || echo FAIL -->
- Docs structure: CLAUDE.md + docs/RUNBOOK.md + docs/decisions/ (ADR-001..007, gap at 005) + docs/articles/ (M4 metric-redesign case study) + docs/river-arf-retrospective.md + docs/lightgbm-quantile-shadow-plan.md + docs/lightgbm-shadow-postmortem.md + docs/exp-012-results.md + docs/metric-redesign-literature-review.md + docs/literature.md + docs/hypothesis-log.md + docs/model-progress-log.md + memory/.
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
- ADR-001: Timezone handling — use `Intl.DateTimeFormat` with Europe/Amsterdam.
- ADR-003: Netlify cache `--force` flag — ensures fresh data on webhook builds.
- ADR-004 superseded by ADR-006 (ARF replaced as model, kept as backup pipeline).
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast (wholesale × VAT + cached ARF surcharge).
- Features (LightGBM): 24 total — price lags (8), rolling mean/std (6), calendar (7), wind/solar/load (3) + horizon-as-feature.
- Noise: client-side `Math.random` ±5%, transparent to users.

## Open Issues

- **augur#12**: migrate sadalsuud orchestration cron → systemd + run augur *after* EDH collector. Currently augur runs at 14:45 UTC, EDH collects at ~15:20 UTC, so parquet always trails 24h. Live LightGBM MAE is 84% above backtest h+1 partly because of this freshness skew. Highest-priority infrastructure ticket.
- **Lower-side coverage** ~0.81 vs 0.90 target. Next experiment after augur#12: horizon-conditioned CQR (separate calibration windows per horizon group) or Adaptive Conformal Inference.
- **Model-tab metric parity**: `update_shadow.py` doesn't yet emit ARF-equivalent metadata (`metrics_history`, `error_history`, `n_training_samples`), so `static/js/modules/model-viz.js` still reads `augur_forecast.json` (ARF backup). Future work to extend the LightGBM metadata schema and update model-viz.js.
- **Publishability backlog** (`docs/hypothesis-log.md` entry, review-by 2026-12-31): ADR-006 + the M4 → EXP-014 arc is publishable with ~2-3 weeks of empirical follow-up (naive baseline, PIT, multi-window robustness, canonical CRPS at 9-19 quantiles, canonical twCRPS integral). Or ~3-4 days of polish for a blog post.
- #2-4: New ML features (NED production, gas/carbon prices, cross-border flows) — deferred indefinitely post-EXP-014 (model class is good, features aren't the bottleneck).
- #5: Backtesting framework from archived forecasts — partly absorbed into `ml/shadow/backtest.py` + `scripts/exp012_evaluate.py`.
- #6-7: Model variants (peak/off-peak, larger ensemble) — see ADR-006 alternatives.
- #8-10: Product expansion (SaaS API, ensemble forecasting, multi-country).
- **agent-ready-projects#12** (framework-level, not augur): calendar-bridge skill candidate — plant `Review by:` dates from hypothesis logs into Google Calendar.

## Resolved this session (2026-05-29)

- ✅ EXP-011: M4 verdict (PROMOTE=False initially, Path B park).
- ✅ EXP-012: metric-redesign validation on existing data — surprise findings.
- ✅ EXP-013: corrections following code-review battery (vintage-join bug; pinball-at-p10 reversed).
- ✅ EXP-014: redesigned-criterion pass + LightGBM promoted to production (Path A swap).
- ✅ Article draft: `docs/articles/m4-metric-redesign-story.md` (five-iteration arc).
- ✅ Literature bibliography: `docs/literature.md`, `docs/metric-redesign-literature-review.md`.
- ✅ ADR-006 and ADR-007 written.
- ✅ Healthchecks.io shadow endpoint deleted (no more alert emails).
- ✅ `tests/test_metrics.py` (19 tests) added.
