# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-05-08 — M4 collection delayed 8 days by silent CLI failure; observability hardening shipped

**Trigger**: Day-7 sanity check on `ml/shadow/eval_log.jsonl` ahead of the M4 promotion vote (~2026-05-22 expected). File didn't exist; `shadow_state.json:last_run_utc` was frozen at 2026-04-30; calibration_history empty.

**Root cause**: `scripts/daily_update.sh:63` invoked `python -m ml.shadow.update_shadow --augur-dir $AUGUR_DIR`, but `update_shadow.py`'s argparse only defines `--parquet/--shadow-dir/--forecast-out`. argparse exited rc=2 every night from 2026-05-01 to 2026-05-07. Failure was hidden by three concurrent factors: shadow block runs under `set +e` (correct, ARF must not be blocked), git step uses `[ -f ... ] && git add` (correct, must tolerate missing files), and the commit message was hardcoded as "ARF + LGBM-shadow" regardless of which steps actually ran. See `memory/gotcha-log.md` top entry for the silent-failure mechanism in full.

**Impact on M4**: 7 nights of shadow-step failures = zero eval rows logged. M4 14-day window cron-effective start slipped from 2026-04-30 → **2026-05-08**. First real eval row expected 2026-05-09; promotion review **2026-05-29** (per updated `docs/hypothesis-log.md`).

**Fixes shipped (5 commits, all on main)**:
- `d620b45` — drop the rejected flag (the actual bug)
- `8c217a6` — docstring CLIs corrected, pre-flight heartbeat on `last_run_utc` (alarms if >36h), dynamic commit message reflecting `SHADOW_UPDATE_RC`/`SHADOW_EVAL_RC`/staleness, env-gated Healthchecks.io ping at end of script
- `0225fe1` — heartbeat alarms on missing/malformed state too (was only stale)
- `c135b4a` — `umask 027` + self-heal `chmod 640` on cron log file (security-auditor MEDIUM finding)

**Live wiring on sadalsuud (2026-05-08)**: `HEALTHCHECKS_SHADOW_URL` appended to `~/local_dev/augur/.env`; first ping registered (HC dashboard green); cron log mode hardened to 640. HC alerts within 25h of any shadow silence going forward.

**Bootstrap state cleanup**: A manual rehearsal of `update_shadow.py` produced a structurally-anomalous eval row (72h forced into one `eval_day=2026-04-30`, ARF archive coverage matched only 40 of 72 LGBM hours). Row was deleted from `eval_log.jsonl` and the 72 corresponding entries purged from `shadow_state.json:calibration_history`; `last_cqr_q` and `last_cqr_n_calib_days` reset to 0. Method snippet in hypothesis-log starts cleanly from real nightly data.

**Verdict**: Pipeline back online. Observability now solid for the silent-failure mode that bit. Open follow-ups (deferred): CI smoke test on `daily_update.sh`, CLI harmonization across the two shadow scripts, `update_shadow.py` pending-dedup logic (see gotcha-log "appends to pending_predictions without dedup" entry). M4 collection in progress.

---

## 2026-04-29 — LightGBM-Quantile shadow: backtest + band fix (EXP-009, EXP-010)

**Trigger**: Plan milestone 2 (`docs/lightgbm-quantile-shadow-plan.md`) — first comparison numbers vs ARF on the regime-shift period.

**What ran**: Walk-forward backtest harness (`ml/shadow/backtest.py`, `ml/shadow/features_pandas.py`) over 2026-04-01 → 2026-04-28, fitting `LightGBMQuantileForecaster` on a rolling 28-day window per evaluation day, predicting the next 24 hours with realised lag inputs. Single-horizon, perfect-lag — apples-to-apples with River ARF's `update_mae`. 24-column ARF parity feature set; `renewable_pressure` not yet included.

**Result vs ARF (apples-to-apples h+1 window 2026-04-14 → 04-28)**: 15 calendar days, ARF cron skipped 04-22 so 14 days are merge-evaluable. All MAE numbers below are h+1 perfect-lag (next-hour given realised lag inputs) — apples-to-apples with ARF's `update_mae`. Iterated 72h behaviour is a separate question and is deferred to milestone 3.

| | LightGBM | ARF (`update_mae`) |
|---|---|---|
| Mean MAE h+1 | **13.21** | **21.95** |
| Wins | **14 / 14 evaluable days** | — |
| Mean improvement | **+46 %** | — |
| Worst day (04-26, min realised −413 EUR/MWh) | 60.72 | 69.05 |
| Recovery 04-27/-28 | 12.25 / 8.67 | 27.79 / 28.96 |

LightGBM beats ARF on every evaluable day of the comparison window, including the regime-shift extreme days; the recovery on 04-27/-28 is the cleanest signal that the new architecture handles the regime that broke ARF. (LightGBM also has predictions for 04-22 with MAE 8.17, but ARF skipped that date so it's not in the merged comparison.)

**Issue surfaced — band miscalibration**: Raw P80 empirical coverage was 56.3 %, well below the [75 %, 85 %] target in plan §6 (b). Diagnostic (`ml/shadow/backtest_results/diagnose_bands.py`) showed the miss is **chronic** (24 / 28 days under target, 0 over) and **bilateral** (25 % below P10, 19 % above P90), correlated negatively with realised volatility. Pinball-loss minimization on small finite samples gives systematically narrow quantile estimates.

**Fix — split-conformal correction (EXP-010)**: `ml/shadow/conformal.py` adds CQR (Romano, Patterson, Candès 2019) with a 7-day rolling calibration window. 2x2 matrix `{28d, 56d} × {raw, CQR}` showed both CQR variants land in target (28d: 0.768, 56d: 0.765); 56d marginally improves point predictions (MAE 12.20 vs 12.83, evening peak 11.42 vs 13.26) without extra infrastructure. Per-day coverage is bimodal (over-cover calm, under-cover volatile) but the 14-day aggregate is stably 0.775 — and the 14-day aggregate is what plan §6 actually measures.

**Decision — final design for milestone 3**: `window_days=56` + CQR(7-day calibration, target 0.80). Plan §6 readings:

- (a) MAE on realised < 30 EUR/MWh ≥ 25 % better than ARF — **Likely PASS**, formally TBD (ARF slice MAE not in `metrics_history.csv`; milestone 3 cron will log it alongside).
- (b) P80 empirical coverage in [75 %, 85 %] — **PASS** (0.775 over the 14-day window).
- (c) Weekday evening peak (16-19 UTC) MAE ≤ +10 % of ARF — **PASS** (11.42 vs ARF 21.95 mean).

**Open items for milestone 3** (gathered from this work + a review battery on 2026-04-29):

- **HMAC-sign pickle artifacts before sadalsuud writes one.** `LightGBMQuantileForecaster.load` uses `pickle.load` with no integrity check; reuse existing `HMAC_KEY_B64` infrastructure (precedent: `utils/secure_data_handler.py`). Security MEDIUM, prereq for any cron landing.
- **ARF slice-MAE logging in cron** so promotion criterion (a) becomes formally evaluable rather than "Likely PASS, formally TBD".
- **`renewable_pressure` ablation** on the 56d_cqr backtest harness before the 14-day shadow window starts.
- **Per-day coverage caveat for criterion (b)**. Aggregate P80 = 0.775 passes [75%, 85%], but 04-25 / 04-26 (the regime-shift days) sit at ~0.46 / ~0.50 even with CQR. Show per-day alongside aggregate in any promotion doc; consider ACI (Gibbs & Candès 2021) if per-day stability becomes a criterion.
- **Always state h+1 qualifier with MAE headlines** until iterated multi-horizon validation lands.
- Code nits worth folding in along the way: warning instead of silent skip on short training windows in `backtest.py:73`; `pd.to_datetime(..., utc=True)` in `compute_metrics`; build prediction DataFrames from `X_eval.index` instead of positional `zip`.

**Branch**: `feat/lightgbm-shadow`. ARF cron continues to drive the dashboard.

**Artifacts**:
- `ml/shadow/backtest_results/summary.md` — milestone 2 detailed summary
- `ml/shadow/backtest_results/milestone_2_5_summary.md` — milestone 2.5 detailed summary
- `ml/shadow/backtest_results/predictions.parquet`, `predictions_28d.parquet`, `predictions_56d.parquet` — full per-hour predictions
- `ml/shadow/backtest_results/comparison.csv`, `matrix_summary.csv`, `band_diagnostic.csv`, `matrix_per_day.csv`
- `experiments/registry.jsonl` — EXP-009 (backtest), EXP-010 (CQR)

---

## 2026-04-28 — River ARF retired (end-of-run)

**Trigger**: Live `mae` climbed from 12.16 (04-21) to 35.58 (04-28) — roughly 3× the post-warmup baseline. Forecast forensics on the 04-25 → 04-28 archives localised the failure to the 09–13 UTC solar trough where the model overpredicts by 55–80 EUR/MWh while realised prices crash to −20 to −30 EUR/MWh.

**Decision**: Retire `River ARFRegressor`. The failure is structural, not tunable: tree ensembles predict the mean of leaf-bound training samples, so leaves never trained on negative prices cannot output negative values. Compounded by `ml/update.py:337` clamping the lower confidence band at 0, the entire prediction-plus-uncertainty channel is incompatible with a regime that now produces ~20% negative quarter-hourly prices.

**Replacement direction**: LightGBM with quantile (pinball) loss, retrained nightly on a rolling window. Shadow-mode validation alongside ARF for ≥2 weeks before promotion. Plan to be drafted separately.

**Artifacts**:
- `docs/river-arf-retrospective.md` — neutral postmortem with 5 figures (trajectory, peak-day forecast vs actual, hour-of-day bias, negative-price prevalence, distribution shift).
- `docs/figures/arf-retrospective/data/` — 35-row daily metrics CSV, 25-row metrics_history CSV, 4 forecast archives, MANIFEST.
- `experiments/registry.jsonl` — EXP-008 records the retirement decision; EXP-001 → EXP-007 back-fill the full ARF lifecycle for future citation.

**Status**: ARF cron continues to run (do not remove infrastructure prematurely); replacement to land in a future EXP-009 entry.

---

## 2026-04-14 — Forecast collapse: model outputs flat mean

**Trigger**: Noticed the live forecast on the dashboard barely moves — temporal price swings are suppressed. The model outputs what looks like an average price estimate regardless of time of day.

**Evidence**:

| Metric | Value |
|--------|-------|
| Actual price range (buffer, 200 pts) | -2.09 to 213.31 EUR/MWh (range 215) |
| 72h forecast range | 108.94 to 133.08 EUR/MWh (range 24) |
| Forecast std dev | 5.12 EUR/MWh |
| Range compression | ~89% — nearly flat output |

Daily `update_mae` has been running 25-36 EUR/MWh since April 3, roughly 2-3x the warmup-era MAE.

### Root cause 1: Recursive forecast loop (architectural)

`generate_forecast()` in `ml/update.py:258-298` predicts hour-by-hour and **feeds each prediction back as a lag feature for the next hour**. Combined with MSE-based tree splits (River ARF default), predictions regress toward the mean at every step. Over 72 hours this compounds into a flat line around ~119 EUR/MWh.

The exchange day-ahead prices (~24h horizon) partially mask this — the first day of forecast has real lags and looks reasonable. But beyond the exchange horizon, every lag is a stale prediction, and the forecast collapses.

### Root cause 2: Frozen aggregate metrics (bug)

`update_model()` in `ml/update.py:191-195` writes the metrics history but copies `mae` and `last_week_mae` from existing state instead of recalculating them:

```python
"mae": round(state["metrics"].get("mae", mae), 2),        # frozen at 13.8 since warmup
"last_week_mae": round(state["metrics"].get("last_week_mae", mae), 2),  # frozen at 21.12
```

These have been stuck at warmup values (13.8 / 21.12) since April 2, while real daily errors were 25-39. The degradation was invisible in the dashboard metrics.

### Possible remedies (under consideration)

1. **Direct multi-horizon models** — Train separate models for h+1, h+6, h+24 etc., each predicting directly from current known features. No recursive lag feeding, no mean collapse.
2. **Exchange price anchoring** — Beyond the exchange horizon, anchor lags to last known exchange price rather than recursive predictions.
3. **Loss function change** — ARFRegressor uses variance reduction (MSE). A MAE/quantile objective would reduce mean-reversion bias, but River ARF doesn't expose this easily.
4. **Fix the frozen metrics** — Recalculate `mae` and `last_week_mae` from `error_history` each update so degradation is visible immediately.

### Context

- Model was rolled back to pre-contamination checkpoint on April 2 (commit `27b9876`) after ENTSO-E collector outage caused 5 days of training on wrong price series (Energy Zero consumer prices instead of wholesale).
- Model has been retraining daily since then (5703 samples as of April 13), but the recursive forecast architecture means even a healthy model will produce flat multi-day predictions.
- Model pickle shrank from 1.75 MB to 616 KB at some point — may indicate tree pruning or state loss.

---

## 2026-04-14 — Fix: variance-preserving recursion + metrics bug

**Changes** (`ml/update.py`):

1. **Fixed frozen metrics bug** — `mae` and `last_week_mae` were copied from stale warmup values on every update instead of being recalculated. Now recomputed from `error_history` (last 500 errors for MAE, last 168 for weekly MAE) on each daily run.

2. **Historical rolling stats override** — Added `_historical_rolling_stats(fb)` helper that computes typical price mean/std by hour-of-day from the real price buffer. During recursive forecasting (beyond exchange horizon), `price_rolling_mean_6h` and `price_rolling_std_6h` are overridden with these historical values instead of being computed from artificial predictions. Prevents the rolling stats from collapsing to near-zero variance.

3. **Calibrated noise injection** — When feeding a prediction back as a lag for the next forecast hour, noise drawn from `N(0, ewm_std)` is added. `ewm_std` is the model's own exponentially-weighted error standard deviation (already computed for confidence bands). This prevents correlated lag sequences from converging to the mean. RNG seeded per-hour for reproducibility.

**Rationale**: The model was trained on real data with natural price variance. Recursive predictions created an out-of-distribution input pattern (smooth, correlated lags and collapsed rolling stats). These fixes restore realistic variance in the feature space without changing the model itself.

**What was NOT changed**: Model training path (warmup + learn_one), feature builder, exchange-horizon forecasts (first ~24h still use real lags), model artifact.

**Expected outcome**: Wider forecast range beyond exchange horizon. Actual improvement measurable after next daily update on sadalsuud.

---

## 2026-04-30 — EXP-009 milestone 3: LightGBM-Quantile shadow pipeline shipped + deployed

**Changes** (merge `84a1af4`/`f77aa5d` to `main`, 14 commits — 6 step + 3 review-fixup A/B/C + 2 prereq + 1 dry-run-fix D + 1 hypothesis-log seed):

1. **`ml/shadow/lightgbm_quantile.py`** — `MultiHorizonLightGBMQuantileForecaster`: 9 LGBM models (3 horizon groups × 3 quantiles), direct multi-horizon via `horizon_h` as a stacked feature. No recursive lag substitution → no variance-collapse pathology. Default groups `(1,6), (7,24), (25,72)`.

2. **`ml/shadow/secure_pickle.py`** — HMAC-SHA256 sidecar (`*.pkl.hmac`) sign/verify. Used by `MultiHorizonLightGBMQuantileForecaster.save/load` so deserialization never runs on an unverified file. Closes the unsigned-pickle RCE risk before sadalsuud writes its first artifact.

3. **`ml/update.py`** — added `error_prices` parallel array + `mae_at_low_price` (slice-MAE on realised < 30 EUR/MWh) so promotion criterion (a) is formally evaluable from ARF state.json. Backward-compatible with legacy state.json (only tail-aligned window contributes).

4. **`ml/shadow/update_shadow.py`** — nightly retrain + predict orchestration. Backfills realised prices into `pending_predictions` from prior runs, computes CQR q (7-day calibration, target 0.80), trains on rolling 56-day window, predicts 72 horizons, widens bands by q. Writes signed pickle + `shadow_state.json` + `static/data/augur_forecast_shadow.json` (NOT consumed by dashboard during shadow phase per plan §5).

5. **`ml/shadow/evaluate_shadow.py`** — daily LightGBM-vs-ARF metrics logger. Cross-references shadow predictions against ARF archives at `ml/forecasts/{YYYYMMDD_HHMM}_forecast.json`, writes one JSON line per fully-realised eval day to `ml/shadow/eval_log.jsonl`. Schema includes `n_low_price_hours`, `lightgbm_peak_hour_mae`, `arf_peak_hour_mae` so all three plan §6 criteria are evaluable directly from the log.

6. **`scripts/daily_update.sh`** — extended with the shadow block under `set +e` so shadow failures don't block the ARF commit. Re-consolidates parquet from energyDataHub each run. Best-effort-adds shadow artifacts (`shadow_state.json`, `augur_forecast_shadow.json`, `eval_log.jsonl`); `shadow_model.pkl` + sidecar are gitignored (regenerated nightly from rolling window).

7. **Path-fix in `ml/update.py:540`** — ARF forecast archive_dir was `output_dir.parent / ml / forecasts` (resolved to `static/ml/forecasts`); now `output_dir.parent.parent / ml / forecasts`. Without this, eval_log.jsonl could never populate `arf_*` fields. Sadalsuud archive history migrated 2026-04-30.

8. **`docs/hypothesis-log.md`** — adopted from ovr.news pattern, M4 promotion-decision hypothesis seeded with falsification criteria pre-committed (concrete numbers, failure-mode signals, runnable Method snippet).

**Reviews**: two rounds of review battery (code-reviewer, security-auditor, data-analyzer, deployment-troubleshooter). Round 1 found 2 HIGH (archive path, gitignore exception), 1 HIGH security (`.load` HMAC bypass), 1 medium (xargs `.env`), 5 medium/low — all CLOSED in fixups A/B/C. Round 2 found 1 BLOCKER (`.env` source under `set -e` would kill ARF cron) — closed in fixup D. Two open caveats deferred to documentation: exogenous-freshness skew (round-1) and bimodal P80 coverage (M2.5).

**Deployment**: merged to `main` 2026-04-30; sadalsuud pulled the merge after archive-path migration (`mv static/ml/forecasts/* ml/forecasts/`); manual dry-run of consolidate + update_shadow + evaluate_shadow succeeded end-to-end. Caught one real bug (lightgbm not in venv, installed manually). First production cron run with the new pipeline: 2026-05-01 14:45 UTC.

**Tests**: 158 passing (was 35 pre-M3). New suites: `test_lightgbm_quantile.py` (37 incl. multi-horizon + HMAC enforcement), `test_secure_pickle.py` (22), `test_update_slice_mae.py` (10), `test_update_shadow.py` (20), `test_evaluate_shadow.py` (22), `test_update_archive_path.py` (1).

**M4 expected outcome**: 14 days of `eval_log.jsonl` rows. Hypothesis log pre-commits: criterion (a) ≥25% relative MAE win at realised<30 with ≥50 low-price hours; (b) coverage in [0.75, 0.85] AND fewer than 3 days below 0.60; (c) peak-hour delta ≤ +10% relative. First eval row covers `eval_day=2026-04-30`. Cron will continue ARF in production until M5 (promotion decision) ratifies replacement.

**What was NOT changed**: ARF model architecture, dashboard frontend (still reads `augur_forecast.json`), Netlify build pipeline. Shadow artifacts are committed to the repo but not consumed by the dashboard.

---
