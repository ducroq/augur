# Long-History Warmup — Implementation Plan

**Companion to**: `docs/decisions/005-long-history-warmup.md`
**Branch**: `feat/long-history-warmup`
**Status**: Draft — revised as decisions are made

This doc carries the mechanics. ADR-005 is the architectural decision; everything here can evolve without re-ratifying the ADR.

## 1. Execution environment

**Warmup runs on sadalsuud.**

- River ARF is installed in sadalsuud's venv; not on the Windows dev box.
- Production feature builder lives there — same code path for warmup and daily update, per ADR-004.
- Same network proximity to ENTSO-E (EU-hosted) for better API latency.
- Secrets: copy ENTSO-E key into `~/local_dev/augur/.env.local-history` (gitignored) on sadalsuud. Source from the HAN SharePoint `secrets.ini` via a one-time manual transfer. Never committed.

**Windows dev box is used for:**
- Writing and unit-testing `consolidate_historical.py` against mocked APIs
- yfinance / Open-Meteo experimentation (no-auth sources)
- Reviewing diffs before push

**Pi collector** (referenced by energyDataHub's `run_script.sh` `/home/pi/energyDataHub/`) is untouched. This project does not interact with that pipeline.

## 2. Resolution handling

Production target: 15-minute ENTSO-E wholesale day-ahead.
ENTSO-E API returns hourly day-ahead prices only.
**Strategy**: forward-fill each hourly price across its four 15-minute slots. Explicit persistence within the hour. Known bias; acknowledged in ADR-005.

Other signals at their natural resolution:
- Load actuals: 15-min from ENTSO-E
- Load forecast (day-ahead): hourly → forward-fill
- Wind+solar day-ahead forecast: hourly → forward-fill
- Open-Meteo ERA5 wind/solar: hourly → forward-fill
- TTF gas: daily → forward-fill across the day

All rows merged on a 15-minute UTC timestamp grid.

## 3. Concurrency with daily cron

The daily cron fires at 16:45 UTC and writes `ml/models/river_model.pkl`, `ml/models/state.json`, `static/data/augur_forecast.json`, then git-commits and pushes.

Warmup writes **only** to `ml/models/river_v2/`. No contention with v1 paths.

Shadow-mode daily runs (after warmup, during evaluation):
- Add a shadow step to `scripts/daily_update.sh`: after the normal update, run a lightweight `ml.update_shadow` that predicts and learns with v2. Writes to `ml/models/river_v2/state.json`.
- If shadow step fails, production update is already complete — shadow failure cannot corrupt production.
- File lock on `ml/models/river_v2/river_model.pkl` (flock) so a long warmup run can't collide with shadow-mode daily updates. Warmup takes the lock; daily shadow retries for 2 minutes then skips with a WARN.

## 4. Price buffer seeding at handoff

`state.json` has a 200-entry `price_buffer` that the feature builder reads for lag features on the first daily update after warmup.

After warmup, **pull the most recent 200 real 15-min ENTSO-E prices** (i.e., the last ~50 hours of today) and seed the v2 `state.json.price_buffer` with those. Do **not** use the warmup's end-of-history (which is 2026-04-whatever depending on when we run it) — because the daily cron will learn today's prices next, and lags need to reach back into today's actuals.

Effectively: warmup trains on 2020-01-01 to ~T-2 days; price_buffer is seeded from ENTSO-E's most recent prices; daily cron resumes from T with proper lags.

## 5. state.json history arrays

`error_history` (500-entry bounded) and `metrics_history` (365-entry bounded) are populated only by the daily cron (`update_model`). Warmup does not write them.

**Dashboard impact**: the Model tab (`static/js/modules/model-viz.js`) reads these from `augur_forecast.json.metadata`. Post-cutover, the dashboard shows empty history for v2 until the daily cron accumulates a few days.

**Mitigation options** (decide before cutover):
- **a**: accept the gap. Dashboard shows history rebuilding daily after cutover.
- **b**: seed `metrics_history` with an optional summary entry like `{"date": "warmup", "update_mae": <backtest_mae>, "n_samples": 44000}`. Requires `model-viz.js` to handle non-date entries.
- **c**: compute per-day MAE during warmup (walk-forward, last 365 days) and populate `metrics_history` with real daily entries. Most honest but adds ~10 lines of warmup code.

Recommend **c**.

## 6. Model artifact size and git

Current `river_model.pkl` is 771 KB (10 trees, ~6k samples).

Expected size with 6 years × 15-min × 10 trees: tree depth grows roughly log(N), but ARF does internal pruning. Realistic estimate: **3-15 MB**. Above the informal git threshold (~5 MB) but not huge.

**Decision**: keep committing `river_model.pkl` directly (no git-lfs). If sizes exceed 20 MB post-warmup, revisit with git-lfs. The daily cron already pushes the pickle every day; adding git-lfs mid-flight would break the existing workflow.

During development, the `river_v2/river_model.pkl` is **not** committed until cutover. Gitignore pattern:
```
ml/models/river_v2/*.pkl
ml/models/river_v2/state.json
```

## 7. Branch sync cadence

`main` receives one "Daily model update" commit per day from sadalsuud's cron. `feat/long-history-warmup` must not drift.

**Rule**: rebase `feat/long-history-warmup` onto `main` at the start of every working session, at minimum every 3 days. If conflicts occur (they shouldn't — cron only touches `ml/models/`, `static/data/`; branch only touches `docs/`, `ml/data/consolidate_historical.py`, `ml/training/warmup_historical.py`, `ml/evaluation/backtest.py`), resolve in favor of `main` for any `ml/models/*` path.

## 8. Test plan

### 8.1 Unit tests (Windows dev box)
- `tests/test_consolidate_historical.py` — mock all three external APIs, verify:
  - Correct merging onto 15-min UTC grid
  - Forward-fill behavior for hourly → 15-min
  - Missing-data handling (ENTSO-E gaps, Open-Meteo gaps)
  - Output schema matches `OnlineFeatureBuilder` input expectations
- `tests/test_entsoe_retry.py` — mock 503 responses, verify retry with backoff and token redaction in exception messages
- `tests/test_backtest_harness.py` — synthetic forecast + actual pairs, verify MAE / MAPE / spike-recall / horizon-segmented MAE computation

### 8.2 Integration tests (sadalsuud)
- `tests/test_warmup_replay.py` — run `warmup_historical` on a small fixture (e.g., one month of recorded data in test fixtures), verify produced model can predict on a known sample and match expected output within tolerance
- Verify river_v2 `state.json` structure matches v1 so `ml.update` can consume it interchangeably

### 8.3 Regression checks
- Run current `pytest tests/` on the branch before any new code — all existing tests must still pass.
- After implementation, full pytest plus new tests must be green before merge.

## 9. Phased rollout

### Phase A — Build and measure (in branch)
1. Implement `consolidate_historical.py` + unit tests
2. Implement `warmup_historical.py` + unit tests
3. Run warmup on sadalsuud → produces `river_v2/river_model.pkl`
4. Implement `backtest.py` → evaluate v2 against April 2026 held-out
5. Report: all three gate criteria numeric results

### Phase B — Shadow mode (on main, behind flag)
Only if Phase A passes the evaluation gate:
6. Merge branch to main
7. Add shadow-mode step to `scripts/daily_update.sh` — runs v2 alongside v1, logs predictions, no dashboard impact
8. Run shadow mode for **14 calendar days**
9. Compare daily v2 vs v1 predictions against same-day actuals; produce a rolling shadow-mode report (`logs/shadow_mode_compare.log`)

### Phase C — Cutover
Only if shadow-mode report shows v2 continues to beat v1 on live data:
10. Rename `ml/models/river_model.pkl` → `ml/models/river_v1_baseline.pkl` (committed, for rollback)
11. Rename `ml/models/river_v2/river_model.pkl` → `ml/models/river_model.pkl`
12. Update `ml/models/state.json` from v2 state; archive v1 state
13. Remove shadow-mode step from `scripts/daily_update.sh`
14. Add rollback procedure to `docs/RUNBOOK.md`

### Rollback (post-cutover)
If v2 underperforms in production over any 7-day window after cutover:
- Restore `river_v1_baseline.pkl` → `river_model.pkl` in a single commit
- Document the failure mode in `memory/gotcha-log.md`
- `feat/long-history-warmup` branch reopened for iteration

## 10. Dependencies

Add to `requirements.txt`:
```
entsoe-py==0.6.12      # pin after scouting confirmed 2015 coverage
yfinance==0.2.40
holidays==0.50
```

(Exact versions pin at implementation time based on what's installed during scouting.)

## 11. Operational runbook additions

At cutover, update `docs/RUNBOOK.md`:
- How to rerun warmup (if needed for feature additions)
- How to roll back from v2 → v1
- Shadow-mode comparison report location
- ENTSO-E key rotation procedure

## 12. Timeline (rough)

- Phase A (build + backtest): 2-3 working days
- Phase B (shadow mode): 14 calendar days minimum
- Phase C (cutover): 1 day

Total: ~3 weeks wall clock, ~4 days of actual engineering effort.

## 13. Open questions (pre-implementation)

- **ENTSO-E retry-strategy specifics**: exponential backoff with max retries? Circuit breaker? The existing `energydatahub/collectors/base.py` has `RetryConfig` + `CircuitBreakerConfig` — reuse or write fresh?
- **Feature importance re-run target date**: at end of Phase A, before or after Phase B? Before = risk of re-warmup loop if feature set changes; after = delay cutover. Recommend: after Phase B evaluation confirms v2 is worth deploying, then re-run Lasso on the extended data to check whether next iteration should touch features.

## 14. Accepted decisions from risk review (2026-04-19)

Three decisions were made after the FMEA:

1. **Pre-flight approach**: run the two design-affecting studies (target-diff, weather-noise) before Phase A begins; do the remaining 8 hygiene items in parallel with Phase A tasks that touch them. Rationale: the studies can reshape the plan; the hygiene items are cheap and don't inform architecture.
2. **Weather-leakage mitigation**: accept calibrated noise as the production mitigation, **and add a leakage probe to Phase A**: during warmup, train **two** v2 models side-by-side — one with ERA5 + calibrated noise (production candidate), one with ERA5 as-is (perfect-knowledge ceiling). Compare backtest metrics. Gap-analysis outcomes:
   - Gap small → noise isn't doing enough; shadow mode won't catch; revisit before cutover.
   - Gap large → calibration is working; shadow mode remains the final check.
   - Perfect-knowledge model loses to current baseline → project premise is wrong; stop.
3. **Time reserve**: budget +20% wall time across phases for unknown-unknowns. Phase A: 3 → 3.5-4 days. Phase B shadow: 14 → up to 18 days.

## 15. Pre-flight studies (running now)

### 15.1 Target-definition diff study

Pull 1 month of production training target (what the live model actually learned) and 1 month of ENTSO-E hourly forward-filled to 15-min. Compare.

Accept criteria: `mean |diff| < 0.5 EUR/MWh` AND `p95 |diff| < 2.0 EUR/MWh`. If fails, warmup must use consolidated target (more complex build) or accept the documented bias.

### 15.2 Weather-noise calibration study

For archived `*_wind_forecast.json` and `*_solar_forecast.json` files on sadalsuud (2025-12-01 onward, 59-60 files), extract forecasts at h+24, h+48, h+72 and compare against Open-Meteo archive actuals for the same timestamps. Report σ per horizon, which becomes the Phase A noise budget.

## 16. Study findings (2026-04-19)

### 16.1 Target-diff — passes cleanly

- Compared production `parse_price_file` output for 14 days (2026-04-04 to 2026-04-19, 1440 rows of 15-min data) against raw ENTSO-E day-ahead prices for the same period, forward-filled to 15-min.
- **Mean |diff| = 0.000 EUR/MWh, p95 = 0.000, max = 0.000**. All 1440 timestamps exact zeros.
- Production target is literally ENTSO-E; the multi-source merge in `parse_price_file` has no measurable effect when ENTSO-E is present (which is the norm post-2026-04-02 fix).
- **Target-definition drift risk (FMEA row 2) effectively retired.** No systematic divergence to correct for.

### 16.2 ENTSO-E resolution transition — 2025-10-01

Unexpected finding during the study: ENTSO-E NL day-ahead prices transitioned from hourly to native 15-minute resolution on **2025-10-01** (EU 15-minute MTU rollout).

- Pre-2025-10-01: hourly prices
- Post-2025-10-01: 15-min prices

Implication for warmup: two resolution regimes must be handled. Pre-transition data gets **forward-filled** to 15-min (each hourly price spans its following four 15-min slots). Post-transition is used as-is. No architectural change to ADR-005; a note in `consolidate_historical.py`.

### 16.3 Weather-noise calibration

Methodology: forecast-vs-proxy-actual. For each target timestamp, the short-lead forecast (within 4h of publish) acts as proxy actual; long-lead forecasts at h+24/48/72/168 are compared against it.

**Results** (59-60 archived files, 155-178 samples per horizon):

| Horizon | Wind σ (m/s) | Solar σ (W/m²) |
|---|---|---|
| h+24h | 1.82 | 29.5 |
| h+48h | 2.30 | 27.5 |
| h+72h | 2.35 | 34.4 |
| h+168h | 6.16 | — (insufficient data) |

**Caveats**:
- Underestimates true forecast error (short-lead proxy has its own residual error).
- Solar σ mixes day and night; night-hours (GHI=0) drag the mean down. For Phase A, split solar noise by daytime/nighttime, or apply noise only to nonzero GHI values.
- Only 60 days of forecast history; may not reflect seasonal variation (summer clear skies vs winter stratus).

**Phase A noise budget** (starting point, refine in shadow mode):
- Wind: `σ_wind(h) = 1.8 + 0.007·h` m/s (interpolated between measured points)
- Solar: `σ_solar(h) = 30 + 0.06·h` W/m², applied only when `baseline_ghi > 0`
- Beyond h+72 (where data thins), extrapolate cautiously or use persistence-model fallback

### 16.4 Overall status

Both design-affecting studies completed. No architectural changes required to ADR-005. Two small additions:

1. Historical warmup must forward-fill ENTSO-E pre-2025-10-01 hourly data to 15-min.
2. Weather noise is split by horizon per the budget above; solar noise is GHI-gated.

Pre-flight checklist: **items 2 and 3 complete**. Remaining items are hygiene (ENTSO-E key, `.env`, `.gitattributes`, disk check, pip dry-run, user sign-off) and can proceed alongside Phase A.
