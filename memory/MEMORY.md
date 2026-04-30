# Memory

<!-- Loaded every session. Keep lean — index only, deep knowledge in topic files.
     END-OF-SESSION: review gotcha-log, promote patterns, retire stale entries. -->

## Topic Files

| File | When to load | Key insight |
|------|-------------|-------------|
| `memory/gotcha-log.md` | Stuck or debugging | Problem-fix archive |
| `memory/data-formats.md` | Working with energyDataHub data | Schema v2.1 structure, units, timezone conventions |
| `memory/ml-decisions.md` | ML architecture choices | Original XGBoost plan (superseded by River ARF — see ADR-004) |

## Current State

- Dashboard: 5 tabs (Prices, Weather, Grid, Market, Model) on Netlify
<!-- verify: cd /c/local_dev/augur && [ -f static/data/augur_forecast.json ] && [ -f layouts/index.html ] && echo PASS || echo FAIL -->
- ML pipeline: **live** — River ARF on sadalsuud, daily cron at 16:45 CEST (14:45 UTC); LightGBM-Quantile shadow runs alongside ARF after M3 merged 2026-04-30
<!-- verify: cd /c/local_dev/augur && [ -f scripts/daily_update.sh ] && grep -q "ml.shadow.update_shadow" scripts/daily_update.sh && echo PASS || echo FAIL -->
- ARF retired 2026-04-28 (EXP-008) — structural ceiling on negative-price prediction; cron continues running until LGBM shadow promotion (M5)
- **LightGBM-Quantile shadow M0-M3 done, merged to main 2026-04-30** (`84a1af4`/`f77aa5d`). 9 LGBM models (3 horizon groups x 3 quantiles), 56-day rolling window, CQR(7d, 0.80) bands. Deployed and dry-run-validated on sadalsuud. M4 = 14-day shadow window, first eval row writes 2026-05-01 cron.
<!-- verify: cd /c/local_dev/augur && git log --oneline main | grep -q "Merge feat/lightgbm-shadow" && [ -f ml/shadow/update_shadow.py ] && [ -f ml/shadow/evaluate_shadow.py ] && echo PASS || echo FAIL -->
- M4 promotion-decision hypothesis pinned in `docs/hypothesis-log.md` with falsification criteria pre-committed
- ENTSO-E collector recovered ~2026-04-18 after 03-26 outage; guard in `parse_price_file()` remains
<!-- verify: cd /c/local_dev/augur && grep -q "energy_zero" ml/data/consolidate.py && echo "guard-comment-not-machine-checked, manual" || echo FAIL -->
- Forecast: 72h wholesale + consumer (auto-derived surcharge ~110.85 EUR/MWh)
- Re-warmup completed 2026-03-28 on full backfilled dataset (4,192 rows, MAE 13.80) — historical
- Test suite: 158 tests passing (SecureDataHandler, OnlineFeatureBuilder, LightGBMQuantileForecaster, MultiHorizon, secure_pickle, conformal, backtest, update_shadow, evaluate_shadow, slice MAE, archive path)
<!-- verify: cd /c/local_dev/augur && python -m pytest tests/ --collect-only -q 2>&1 | tail -1 | grep -q "158 tests" && echo PASS || echo FAIL -->
- Experiment registry: EXP-001..EXP-010 in `experiments/registry.jsonl`; EXP-009/010 cover the LGBM backtest + CQR validation
<!-- verify: cd /c/local_dev/augur && [ "$(wc -l < experiments/registry.jsonl)" -ge 10 ] && echo PASS || echo FAIL -->
- Docs structure: CLAUDE.md + docs/RUNBOOK.md + docs/decisions/ + docs/river-arf-retrospective.md + docs/lightgbm-quantile-shadow-plan.md + docs/hypothesis-log.md + memory/
- agent-ready-projects: v1.9.0 (v1.10.0 candidate published 2026-04-30 — hypothesis log promoted to framework)
- **Open augur issue #12**: migrate sadalsuud orchestration to systemd + run augur AFTER EDH collector so parquet sees fresh prices

## Recently Promoted

- If EWM variance looks wrong → check that `ewm_mean` (signed) is used, not `ewm_abs` — promoted from code review 2026-03-28
- If exchange prices corrupt lag buffer → ensure they're only pushed once (pre-loop), not also in forecast loop — promoted from code review 2026-03-28
- If adding a Python dep that ships in cron → install it manually in sadalsuud's venv first; the cron does NOT run `pip install -r requirements.txt`. Caught 2026-04-30 by manual dry-run of M3 shadow pipeline (lightgbm not installed). Alternative: extend `daily_update.sh` to install deps idempotently.
- If fixing a bad path in code → also handle git state of files that lived at the bad path. M3 fixup A redirected ARF archives from `static/ml/forecasts/` to `ml/forecasts/`; the existing tracked files at the old location showed up as deletions on sadalsuud's working tree, requiring `git restore` before the branch switch could proceed. Rule: a path-fix commit should either keep the old files (they continue to be tracked, just become frozen historical) or include their `git rm` in the same commit.

## Active Decisions

- ADR-001: Timezone handling — use `Intl.DateTimeFormat` with Europe/Amsterdam
- ADR-003: Netlify cache --force flag — ensures fresh data on webhook builds
- ADR-004: River ARF online learning over XGBoost batch — superseded 2026-04-28 by EXP-008/EXP-009 (LightGBM-Quantile shadow plan)
- Target: ENTSO-E NL wholesale day-ahead price + derived consumer forecast
- Features: selected by Lasso at multiple horizons (1h/6h/24h/48h)
- Dropped temperature (no signal per Lasso), using one NL location per data type
- Exchange prices fed as lag features for first ~29h of forecast
- Noise: client-side Math.random ±5%, transparent to users

## Open Issues

- **EXP-009 M4**: 14-day shadow window collection on sadalsuud. First eval_log row writes 2026-05-01 cron. Calendar trigger 2026-05-22 alongside M5 triage. Promotion decision blocks on M4. See `docs/hypothesis-log.md` for the pre-committed Method.
- **#13 augur**: M5 follow-through — three resolution paths (promote / park / extend) once M4 hypothesis resolves. Conditional implementation work: dashboard config-flag swap, ARF cron retirement, archive. Detailed checklists per path in the issue.
- **#12 augur**: migrate sadalsuud orchestration cron→systemd + run augur AFTER EDH collector. Currently augur runs at 14:45 UTC, EDH collects at ~15:20 UTC, so parquet always trails by 24h. Ideally land before M5 (path A) so promote-to-production isn't on top of broken orchestration.
- **Deferred caveats from M3 review** (documented in `memory/arf-retired.md` auto-memory, surface here for repo readers):
  - Exogenous freshness skew: `consolidate.py` overwrites parquet rows with later forecast vintages — backtest sees fresher exogenous than live cron will get. Live MAE will be 0–20% worse than backtest +46% delta suggested. Hypothesis 2 in hypothesis log tests this empirically.
  - Bimodal P80 coverage: regime-shift days hold 46–50% even with CQR; M2.5 found aggregate 77.5% over 14 days. Hypothesis adds a "fewer than 3 of 14 days below 0.60" guard for criterion (b).
- **EXP-007 reframed → candidate EXP-011** (parked, `feat/new-features-ttf-genmix`): Phase 1 TTF + genmix gave −1.28 EUR/MWh MAE against ARF, below the ≥2 gate. **Baseline shifted post-EXP-008 ARF retirement** — original framing no longer applies (ARF tooling `warmup_p1`/`backtest_p1` doesn't extend to LGBM). New framing: add TTF + genmix lag24h to LGBM-Q via `ml/shadow/features_pandas.py`, re-run via `ml/shadow/backtest.py`, gate at ≥1 EUR/MWh improvement vs LGBM-without-features (lower than ADR-005's ≥2 because stacking on stronger baseline). Conditional on M5 path A. Calendar trigger 2026-05-22 alongside M5 triage. Parsers in `ml/data/consolidate.py` on the parked branch are reusable; the rest is rewrite. See `~/.claude/projects/C--local-dev-augur/memory/project_new_features_rewarmup.md` (auto-memory) for full reframing.
- #2-4: New ML features (NED production, gas/carbon prices, cross-border flows)
- #5: Backtesting framework from archived forecasts
- #6-7: Model variants (peak/off-peak, larger ARF ensemble or Prophet)
- #8-10: Product expansion (SaaS API, ensemble forecasting, multi-country)
- **agent-ready-projects#12** (framework-level, not augur): calendar-bridge skill candidate for v1.11+ — plant `Review by:` dates from hypothesis logs into Google Calendar. Filed 2026-04-30 from this session's transcription friction.
