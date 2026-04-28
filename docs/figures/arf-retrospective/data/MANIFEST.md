# ARF Retrospective — Data Package Manifest

**Generated**: 2026-04-28 (compiled while branch `feat/new-features-ttf-genmix` was checked out; all reads of other branches done via `git show <ref>:<path>`).
**Purpose**: Preserve the historical record of the production River ARFRegressor (10 trees) model so it can support a postmortem retrospective and a future technical publication. The model is being retired.
**Scope**: `origin/main` daily commits, the embedded `metrics_history` array inside the latest `state.json`, the on-server forecast archive on `sadalsuud`, and a read-only inventory of related artifacts.

---

## Files recovered

### `metrics_trajectory.csv`
- **Source**: every commit on `origin/main` that touches `ml/models/state.json` (`git log --format='%H %cI' origin/main -- ml/models/state.json`).
- **Rows**: 35 (header + 35 data rows).
- **Date range covered**: 2026-03-26T15:18:55+01:00 → 2026-04-28T16:45:06+02:00.
- **Columns**: `commit_hash, commit_date, last_timestamp, n_samples, mae, mape, last_week_mae, update_mae, ewm_std_full, last24_std, price_buffer_len, error_history_len, consumer_surcharge`.
- **EWM formula**: replicates `ml/update.py` lines 254-262 — `alpha = 1 - exp(-ln(2)/24)`, recursive `ewm_mean`, `ewm_sq` over the entire `error_history` array (up to 500 points). `ewm_std = sqrt(max(0, ewm_sq - ewm_mean^2))`. The first commit on 2026-03-26 15:18 has `error_history_len=0` so `ewm_std_full` is empty there; from 15:54 onward the buffer is full at 500.
- **`last24_std`**: simple population std of the trailing 24 entries of `error_history`. Provided as a sanity-check proxy.
- **`consumer_surcharge`**: numeric `value_eur_mwh` extracted from the nested object (added on 2026-03-27); blank for earlier commits where the field was absent or scalar.
- **n_samples range**: 3848 → 7143 (delta = +3295 hourly samples over 33 calendar days).
- **MAPE note**: virtually constant at 40.8% from 2026-03-29 onward — appears frozen/cached. This matches the "metrics frozen" issue called out in `memory/forecast-fix-verified.md`.

### `metrics_history.csv`
- **Source**: the embedded `metrics_history` array inside `git show origin/main:ml/models/state.json`.
- **Rows**: 25 daily entries.
- **Date range**: 2026-04-02 → 2026-04-28 (gaps: 2026-04-08, 2026-04-22 — the daily cron skipped those days; matches the missing daily-update commits on those dates).
- **Columns**: `date, update_mae, mae, last_week_mae, n_samples, mae_vs_exchange`.
- **Why it matters**: This is the only place `mae_vs_exchange` (the convergence-vs-EPEX/Exchange metric) is preserved per day. The per-commit `metrics` object does not carry it.
- **Range observed**: `mae_vs_exchange` 7.15 (2026-04-20, best) → 48.15 (2026-04-25, ENTSO-E-related blow-up).

### Forecast archives — pulled from sadalsuud
- `forecast_2026-04-25.json` — 40 026 bytes
- `forecast_2026-04-26.json` — 40 098 bytes
- `forecast_2026-04-27.json` — 40 473 bytes
- `forecast_2026-04-28.json` — 40 478 bytes

Source path on sadalsuud: `~/local_dev/augur/static/ml/forecasts/<YYYYMMDD>_1445_forecast.json`. Each contains a metadata block (timestamps, n_training_samples, metrics, the same metrics_history array, vs_exchange overlap details) plus the 72-hour hourly forecast with confidence bands. These four cover the regression visible in `metrics_history.csv` (mae_vs_exchange 48.15 on 04-25, recovery on 04-28).

### Helper scripts (kept alongside the data, not used in publication)
- `_build_trajectory.js` — reproduces `metrics_trajectory.csv` from git log.
- `_build_metrics_history.js` — reproduces `metrics_history.csv` from latest state.json.

  Both are pure-Node (no deps) so the package is self-rebuilding. They were necessary because `python` execution was sandbox-blocked in this session; `node` was permitted.

---

## Files lost / not recovered

### Forecast archives older than 2026-03-27 15:45
- The earliest file present on sadalsuud is `20260327_1545_forecast.json` (mtime 2026-03-27 16:45). No earlier files exist in `~/local_dev/augur/static/ml/forecasts/` and `find ~/local_dev/augur -name '*forecast*.json'` produced no other candidates. This means the entire pre-warmup / pre-2026-03-27 forecast record is gone. Forecasts produced during 2025-09 → 2026-03-26 daily runs were either (a) never archived under a timestamped filename, (b) overwritten in place at `static/data/augur_forecast.json` (the live file), or (c) rotated. There is no evidence of a backup tarball anywhere under `~/local_dev/augur` on sadalsuud.

### Pre-2026-03-25 daily commits
- `git log origin/main -- ml/models/state.json` returns 35 commits; the earliest is 2026-03-26 15:18 (the warmup commit `7c1b79731e3`). The CLAUDE.md context states the model has been running daily since "around 2025-09" but no commits older than 2026-03-25 touch any file under `ml/models/`. Either the artifact-commit workflow only began at warmup on 2026-03-25, or earlier state was stored under a different path that was later removed. No attempt to recover earlier git history succeeded.

### `ml/data/training_history.parquet`
- **Status**: NOT in any branch on the remote (`git log --all -- '*.parquet'` returns one commit `904c524` whose tree-entry resolves to `fatal: path 'ml/data/training_history.parquet' did not match any file(s) known to git` — that commit message was just "Daily update: consumer forecast with surcharge 110.85 EUR/MWh" and the parquet is .gitignored).
- **Lives on sadalsuud**: `/home/jeroen/local_dev/augur/ml/data/training_history.parquet` — 101 739 bytes, mtime 2026-03-28 15:27. This file is the consolidated warmup training set and has not been updated since the warmup. It has not been pulled to local in this session (out-of-scope: caller did not request it, and CLAUDE.md hard constraint prefers not duplicating data unnecessarily). Recommend pulling it before the model is fully decommissioned.

### Forecast file for 2026-03-26 (warmup day, before the archive existed)
- Earliest archived forecast is 2026-03-27 15:45. The forecasts emitted on 2026-03-26 during the four iterative warmup commits (15:18, 15:54, 17:40, 19:22) were not archived to a timestamped file. Only the metrics in those four state.json snapshots remain — captured in `metrics_trajectory.csv`.

### Forecast archive gaps (cron-skipped days)
- 2026-04-08 — no `20260408_*_forecast.json` on sadalsuud, no commit, no metrics_history entry. Cron skipped or failed silently.
- 2026-04-22 — same pattern: missing forecast file, missing commit, missing metrics_history entry.
- 2026-03-26 → 2026-03-28 also have multiple intra-day commits (warmup iterations and ENTSO-E rollback) which is normal, not a gap.

---

## Inventory of related artifacts (read-only)

### `ml/models/river_model.pkl` snapshots on origin/main
- **35 commits** touch this file (same set as `state.json`).
- **Earliest**: `7c1b79731e3` 2026-03-26T15:18:55+01:00 — "Daily model update: 3848 samples, MAE 20.69".
- **Latest**: `b32f6514e6d` 2026-04-28T16:45:06+02:00 — "Daily model update 2026-04-28".
- **Not deserialized**: pickle binaries are recorded in git only; no attempt was made to load them (River version pinning + sklearn dependency hell). They are recoverable individually via `git show <hash>:ml/models/river_model.pkl > out.pkl` if a future replay is needed.

### `ml/data/training_history.parquet`
- Not in any branch (.gitignored). Exists on sadalsuud only (101 739 bytes, mtime 2026-03-28 15:27). See "Files lost / not recovered" above.

### ADRs in `docs/decisions/` (origin/main)
- `001-timezone-handling-strategy.md` — 2025-11-15. Amsterdam timezone handling with `convertUTCToAmsterdam` pattern; mandates `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'` instead of hardcoded +2h offset.
- `002-grid-imbalance-data-in-energydatahub.md` — 2025-11-15. Grid imbalance data collection in energyDataHub (TenneT real-time grid health indicators).
- `003-netlify-cache-force-refresh-fix.md` — 2025-11-18. Netlify build cache bypass with `--force` flag in `decrypt_data_cached.py` so webhook-triggered builds don't reuse stale cached data.
- `004-river-online-learning-architecture.md` — 2026-03-28. The architectural decision to use River ARFRegressor (10 trees) with online learning instead of XGBoost batch training. Most relevant to the retrospective.
- `005-*` — referenced in `memory/long-history-warmup-paused.md` ("ADR-005 Phase A not executed") but **no `005-*.md` file exists in `docs/decisions/`**. Either the ADR was never written or it lives on the parked `feat/long-history-warmup` branch.

---

## Anything ambiguous worth noting

1. **MAPE freeze at 40.8**: The `mape` field in `state.json` reads exactly 40.8 from 2026-03-29 onward across all 30 commits, while `mae` and `update_mae` move freely. The 2026-03-26 → 2026-03-28 commits show mape values of 43.2 and 47.3, so it was once being updated. This is consistent with the "metrics unfrozen" fix on 2026-04-14 referenced in `memory/forecast-fix-verified.md` — but `mape` apparently was never re-included in that fix. Treat `mape` in this dataset as effectively constant / suspect.

2. **`last_week_mae = 21.12` freeze 2026-03-29 → 2026-04-13** (16 days). Matches the same metrics-cache bug. Unfreezes on 2026-04-14 (forecast fix commit) and varies daily thereafter. The metrics_trajectory CSV makes this visible immediately.

3. **`mae` freeze at 13.8 from 2026-03-29 → 2026-04-13** — same root cause; recovers on 2026-04-14 with mae=23.56 (which is the first honest reading after the unfreeze).

4. **`error_history_len` is 500 from row 3 onward** because the deque is bounded at 500. The earlier rows have 0 (warmup hadn't populated it yet). This makes the `ewm_std_full` and `last24_std` columns directly comparable from 2026-03-26T15:54 onward.

5. **`ewm_std_full` peaks at 104.05 on 2026-04-26** — the regression spike. Recovers to 36.08 by 2026-04-28. Useful for figure annotation.

6. **`mae_vs_exchange` first appears 2026-04-02** in `metrics_history`, reflecting when the convergence metric was added to the daily run. There is no pre-2026-04-02 record of this metric anywhere.

7. **The four pulled forecasts** all have a top-level `metadata.metrics_history` that is a *snapshot* of the array at that day's run. Cross-checking `forecast_2026-04-28.json` confirms the same 25 entries as the latest `state.json` — so any of those files is sufficient as a backup of `metrics_history.csv`.

8. **The repo is on `feat/new-features-ttf-genmix`**. All extractions used `git show <ref>:<path>` against `origin/main`; no branch switch occurred. The metrics on this branch (per `memory/project_new_features_rewarmup.md`) reflect the parked Phase 1 A/B and are not on `main`.

---

**Authoritative output**: `C:/local_dev/augur/docs/figures/arf-retrospective/data/MANIFEST.md` (this file).
