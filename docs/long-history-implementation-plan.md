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

- **Weather-noise σ calibration**: benchmark against archived `*_wind_forecast.json` / `*_solar_forecast.json` files on sadalsuud (they go back to 2025-09-28) to measure actual forecast-vs-archived-truth error at relevant horizons. Informs noise budget before Phase A starts.
- **ENTSO-E retry-strategy specifics**: exponential backoff with max retries? Circuit breaker? The existing `energydatahub/collectors/base.py` has `RetryConfig` + `CircuitBreakerConfig` — reuse or write fresh?
- **Feature importance re-run target date**: at end of Phase A, before or after Phase B? Before = risk of re-warmup loop if feature set changes; after = delay cutover. Recommend: after Phase B evaluation confirms v2 is worth deploying, then re-run Lasso on the extended data to check whether next iteration should touch features.
