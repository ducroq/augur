# Model Progress Log

Dated investigation log tracking Augur's ML forecasting model performance, diagnosed issues, and improvements.

---

## 2026-06-09 — augur#12 closed: cron → system-level systemd with EDH-freshness gate; Healthchecks.io removed

**Trigger**: Calendar event for Phase 2 verification (`Augur #12 — verify systemd timer's first fire`, 09:00 CEST). Phase 1 (user-level systemd unit + `wait_for_edh.sh` ExecStartPre + healthchecks ping kept) had deployed 2026-06-08. First fire that evening was clean — `status=0/SUCCESS` at Mon 2026-06-08 18:31:44 CEST, EDH-timestamp detected at 2026-06-08T09:04:05Z, commit `98ce3b8` landed 16:32 UTC, **107 minutes after** the cron's 14:45 UTC commit `09f7c15`. Both runs ran the same day during the observation overlap.

**Changes today (three commits)**:

1. `5149d17` — **Remove Healthchecks.io integration entirely.** During Phase 2 verification we tried to confirm the healthchecks dashboard was green, discovered the owning account is unknown (the project's busara.eu@proton.me account does not own UUID `e7771ae1-…1cc58bab0992`). Decision: cut the dependency rather than chase the account. Removed the curl ping block from `scripts/daily_update.sh`, the `HEALTHCHECKS_SHADOW_URL` line from sadalsuud's `.env`, and reworded the "absent ping is the alarm" comments in `scripts/wait_for_edh.sh` + `scripts/systemd/README.md`. New alarm path: pre-flight `SHADOW_PRE_AGE_H >36h` ALARM in `daily_update.sh` surfaces stale state in the *next day's* commit message, and a missing daily commit on origin/main is the external alive signal.

2. `719e5e6` — **Migrate systemd from user-level to system-level.** Phase 1's user-level setup required `loginctl enable-linger jeroen` (pending), or the timer would only fire while jeroen has an active session. Migrated to `/etc/systemd/system/augur-daily.{service,timer}` with `User=jeroen` + `Group=jeroen` on the service so SSH keys / venv / `.env` access stays unchanged. Eliminates the linger dependency; the timer is now owned by PID 1 and survives logouts and reboots. `WantedBy=default.target` → `WantedBy=multi-user.target`. Timer file unchanged. README rewritten for the new deployment pattern.

3. (Crontab edit, not a commit since `.env` and crontab are gitignored.) **Cron line commented** in sadalsuud's crontab with marker `# Migrated to systemd augur-daily.timer 2026-06-08 (augur#12). Restore if broken.`, backup at `/tmp/crontab.backup`. **User-level systemd symlinks removed** from `~/.config/systemd/user/`. System-level units deployed with `sudo cp` + `sudo systemctl enable --now augur-daily.timer`. Verified next fire scheduled for Tue 2026-06-09 18:30 CEST (= 16:30 UTC).

**Rationale**: Both the schedule and the orchestration model needed to change. The pre-augur#12 `45 16 * * *` cron ran at 14:45 UTC — empirically that's 75 min to 4+ hours **before** EDH's GitHub Actions collector publishes (observed window 16:23-20:13 UTC, 14-day sample). Consequence (documented in ADR-006 under Consequences): training parquet always trailed 24h, live overall MAE ran 84% above the backtest h+1 figure. The systemd unit fires at 16:30 UTC then polls EDH's `data_quality_report.json:timestamp` until today's date appears (max wait 4h, then proceeds with stale data so the run never fails closed). System-level (rather than user-level) eliminates the linger dependency entirely, matching the rest of the box's timers.

**What was NOT changed**: ARF model, LightGBM model, feature builder, CQR logic, training window, evaluation logic, dashboard rendering, output JSON schema. The change is purely orchestration — same `daily_update.sh` runs, same artefacts written, same eval log appended to. The behavioural difference is the *input* the pipeline sees: post-augur#12 the exogenous columns (wind/solar/load) in `training_history.parquet` are current-day, not 24h-stale.

**Observation plan**: 1-week observation window 2026-06-09 → 2026-06-15. Daily quick-glance for a `Daily update YYYY-MM-DD` commit landing on origin/main around 16:32 UTC = 18:32 CEST. If 7 consecutive clean fires, delete the commented cron line entirely (otherwise rollback to cron). The cleaner-data MAE comparison (live MAE under fresh exogenous data vs the 84%-above-backtest era) will be measurable from `ml/shadow/eval_log.jsonl` after the window closes; expect a meaningful drop in live MAE if the freshness-skew hypothesis is right.

**Open** (post-augur#12): augur#19 (lower-side calibration follow-up — soft-blocked on augur#12 specifically to avoid conflating freshness-fix and calibration-fix effects; now unblocked for EXP-015..017). Also two unrelated *side observations* surfaced during this work: (a) sadalsuud has two other user-level timers (`dca-fear-alert.timer`, `momentum-paper.timer`) that have the same linger fragility — not augur scope but worth flagging. (b) the orphaned healthchecks UUID will eventually start firing "down" alerts to whichever account owns it; nothing actionable here.

**Status**: augur#12 [RESOLVED, observation in progress]. ADR-006's "Freshness skew is unfixed" consequence has a 2026-06-09 resolution marker added; eval-log evidence of the live-MAE improvement to be added after the observation window closes 2026-06-15.

---

## 2026-06-06 — `pending_predictions` dedup landed (closes 2026-05-08 gotcha)

**Trigger**: End-of-session `/curate` flagged the 2026-05-08 gotcha (`update_shadow.py` appends `pending_predictions` without dedup) as a 29-day-old lingering [OPEN code] item. The operational mitigation (state reset on sadalsuud) closed the original incident, but the code-side defence had been deferred. Decision today: land the small fix rather than carry it indefinitely.

**Changes** (`ml/shadow/update_shadow.py`, one block at the `pending_predictions` write):

Before — appended new predictions without uniqueness guarantee:
```python
state["pending_predictions"] = trim_to_recent_days(
    list(state["pending_predictions"]) + new_pending, MAX_HISTORY_DAYS
)
```

After — dedups by `(timestamp_utc, eval_day)` tuple, most-recent run wins:
```python
merged = list(state["pending_predictions"]) + new_pending
deduped = {(r["timestamp_utc"], r["eval_day"]): r for r in merged}
state["pending_predictions"] = trim_to_recent_days(
    list(deduped.values()), MAX_HISTORY_DAYS
)
```

The comment block above the new code explicitly cites the 2026-05-08 incident (silent-failure recovery; three runs in one day against a stalled parquet; 144 then 216 stacked predictions for the same `eval_day`; polluted the M4 promotion metrics). Future engineers who see "why are we deduping here?" land on the answer in-file.

**Rationale**: Dict-comprehension dedup is idempotent — re-running gives the same output state. New entries (`new_pending`) append AFTER existing state in `merged`, so they win in the dict comprehension. Trims by recency happen after dedup so the `MAX_HISTORY_DAYS` cap still applies. No behaviour change in the normal (parquet-advancing) case; only kicks in when a duplicate `(timestamp_utc, eval_day)` key already exists.

**Tests**: All 20 `test_update_shadow.py` tests pass. Full 177-test augur suite green. No new tests added — the smoke test (`test_first_run_produces_artifacts`) confirms the non-duplicate path; the duplicate-input regression test would require substantial fixture setup and the existing operational mitigation (state-reset script on sadalsuud) handles the rare case where this would matter in practice.

**What was NOT changed**: ARF model, LightGBM model, feature builder, CQR logic, training window, output JSON schema, dashboard rendering. The change is purely defensive on the `pending_predictions` list-merge step.

**Status**: Gotcha 2026-05-08 marked [RESOLVED]. The code-side defence pattern (dedup at write time on append-only state) is now applied; this matches the pattern in the gotcha entry's recommendation.

---

## 2026-05-18 — M4 mid-window preview: CQR healthy, low-price failure is structural, methodology ambiguity surfaces

**Trigger**: Calendar-scheduled mid-window sanity-check on M4 collection. 9 contiguous eval rows accumulated (2026-05-08 → 2026-05-16), 5 short of the 14-row formal Method run (review-by 2026-05-22 / buffer 2026-05-29 per `docs/hypothesis-log.md`).

**Pipeline health**: ✅ — cron firing on schedule (last run 2026-05-17 14:45 UTC), state file healthy, shadow JSON written, 7 CQR calibration days active, 9 contiguous eval rows. Observability hardening from 2026-05-08 is doing its job.

**Method snippet preview against 9 rows (non-binding, framework-explicit: preview ≠ Method run)**:

| Criterion | All 9 rows | 8 rows (drop 05-08 cron-shake-out) | Threshold |
|---|---|---|---|
| (a) low-price MAE ratio | 0.94 ❌ | 1.10 ❌ | ≤ 0.75 |
| (a) n_low_price hours | 35 ❌ | 28 ❌ | ≥ 50 |
| (b) mean P80 coverage | 0.722 ❌ | 0.786 ✅ | [0.75, 0.85] |
| (b) days < 0.60 | 2 ✅ | 1 ✅ | < 3 |
| (c) peak-hour ratio | 0.484 ✅✅ | 0.484 ✅✅ | ≤ 1.10 |
| overall MAE ratio | 0.58 | 0.57 | (informational) |
| live/backtest ratio | 1.41 ⚠️ | 1.34 ⚠️ | [1.0, 1.20] |

**Three threads investigated to root cause:**

**1. `last_cqr_q = 0.0` is correct behavior, not a bug.**
- Diagnostic: 7-day calibration window has 81.7% inside-band rate (target 80%); p80 of nonconformity is **−1.09 EUR/MWh** — even the 80th-percentile residual sits *inside* the band. `conformal.py:74` clamps `max(q, 0.0)` correctly.
- Implication: LGBM's nominal P10/P90 are intrinsically calibrated on the 7-day window. Criterion (b) aggregate target is structurally achievable; per-day volatility (0.21 → 1.00 range) is the residual concern.

**2. Criterion (a) low-price MAE failure has a structural cause — not data-thin.**
- Both models miss solar-driven negative midday prices badly; ARF "wins" by accident via mean-reversion bias.
- Sample evidence (eval_day=2026-05-15 low-price hours, 14 hours, h=19..h=48):
  - LGBM p50: 57-100 EUR/MWh, mean error **74 EUR/MWh**
  - ARF: 25-40 EUR/MWh, mean error **31 EUR/MWh**
  - Realized: −1 to +20 EUR/MWh
- LGBM errors scale with horizon: h≤24 mean 64 EUR/MWh, h>24 mean 81 EUR/MWh. Long-horizon weakness consistent with weather-lag feature thinning at h>48.
- ARF's accidental win: its mean-reversion toward ~30 EUR/MWh anchors closer to realized 0 than LGBM's "midday is expensive" prior (~70 EUR/MWh).
- **This is structural**, not a sample-size issue. Extending the window won't fix it. Path C (extend) is therefore *not* the framework-correct triage if (a) fails with n_low ≥ 50 on 2026-05-22.

**3. Live-vs-backtest skew (hypothesis #2): real but secondary.**
- Live MAE 17.73 / backtest h+1 MAE 13.21 = ratio 1.34, outside [1.0, 1.20] band. Roughly +10% explainable by horizon-mix (backtest h+1 only, live h+1..h+72); residual ~+24% likely freshness skew per Alternative 1 (`consolidate.py` overwrite semantics, augur#12 territory). Doesn't change the M4 decision; corroborates the post-decision investigation.

**Methodology ambiguity surfaced (relevant for 2026-05-22 read, not changeable now):**

`evaluate_one_day(eval_day=D)` scores **predictions made on D** (h+1..h+72), not **predictions for D from various horizons**. Criterion (a) plan-text "MAE on hours where realised < 30 EUR/MWh" is therefore evaluated on a 72-hour forward window where long-horizon errors dominate the low-price slice — and LGBM is structurally weak there. ARF gets scored on the same target hours but from its own earlier forecast issuance, so the comparison is apples-to-apples for *target timestamps* even though horizons differ between models. Decision deferred to 2026-05-22 interpretation: report decomposed-by-horizon as supplementary evidence; do not modify Method or eval_log schema mid-window (framework: "Don't loosen Method when the answer arrives").

**Expected 2026-05-22 outcome (pre-committed prediction, framework-allowed)**: (a) fails for structural reasons, (b) passes once 05-08 ages out of the window, (c) crushes it. **Triage path → B (park) with structural-failure-mode reason**, not C (extend window). The postmortem becomes a useful next-bet seed: longer training history to capture multi-year solar evolution, separate model heads per horizon group, or explicit solar-forecast features at long horizons.

**Verdict**: No code changes today. Findings logged here as pre-existing context for the 2026-05-22 formal Method run. Calendar hold for 2026-05-22 stands as scheduled.

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
