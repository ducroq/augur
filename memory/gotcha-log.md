# Gotcha Log

## Promoted

| Entry | Promoted to | Date |
|-------|------------|------|
| EWM variance formula wrong | Fixed in `ml/update.py` — now uses signed `ewm_mean` | 2026-03-28 |
| Double push of exchange prices | Fixed in `ml/update.py` — only push ML predictions | 2026-03-28 |

---

### sadalsuud venv missing a Python dep that the cron script silently needed (2026-04-30)
**Problem**: First manual dry-run of EXP-009 M3 shadow pipeline on sadalsuud crashed with `ModuleNotFoundError: No module named 'lightgbm'`. The M3 commits added `lightgbm>=4.0` to `requirements.txt` but cron doesn't `pip install -r requirements.txt` — it just activates the venv and runs.
**Root cause**: `scripts/daily_update.sh` activates `.venv` and runs Python directly. There's no dependency-install step. New deps land in requirements.txt locally, get pushed to origin, sadalsuud pulls main, and the cron uses whatever the venv currently has — which may not match requirements.txt.
**Fix**: `pip install lightgbm>=4.0` manually in sadalsuud's venv. Updated `memory/sadalsuud-server.md` (auto-memory) with the manual-install discipline.
**Pattern**: When adding a new Python dep that ships in cron, install it manually on sadalsuud BEFORE the next cron, OR extend `daily_update.sh` with an idempotent install (`pip install -r requirements.txt --quiet` is fast on a no-op). The dry-run-before-cron discipline catches this in 30 seconds; the alternative is silent shadow-block failure for a day until someone reads the log.
**Status**: [RESOLVED] — installed manually 2026-04-30; augur#12 (systemd migration) should also address this with a service-file `ExecStartPre` that ensures deps are current.

---

### Path-fix commit left orphan tracked files in the wrong location (2026-04-30)
**Problem**: M3 review fixup A redirected ARF forecast archives from `static/ml/forecasts/` (where the buggy `output_dir.parent` calculation wrote them) to `ml/forecasts/` (the documented location). On sadalsuud, the migration `mv` for the existing files surfaced as a working-tree disaster: `git status` showed dozens of deleted files, and the deletions weren't committed to ANY branch. The next `git pull` or branch checkout would have either conflicted or wiped the moved files.
**Root cause**: `static/ml/forecasts/` was NOT gitignored (only `static/data/*.json` was). So the buggy code had been committing forecast archives to git for weeks. The path-fix commit corrected future writes but didn't address the historical files at the old path — leaving them tracked forever, and any filesystem-level migration showing up as untracked deletions on every machine that runs the cron.
**Fix**: On sadalsuud, `git restore static/ml/forecasts/` to undo the local deletion (files are tracked, restoration is a checkout); leave the old files in place as frozen historical archives; new writes go to the new path. Both locations now exist; the duplication wastes ~few MB.
**Pattern**: A path-fix commit should EITHER (a) include `git rm -r <old-path>/` in the same commit so the move is atomic, OR (b) add `<old-path>/` to `.gitignore` so future writes to that path stop being tracked but historical files remain. Option (a) loses history, option (b) leaves orphan tracked files. Check whether the old path was gitignored BEFORE the fix; if not, the fix is incomplete without one of those follow-ups.
**Status**: [RESOLVED] — sadalsuud and Windows both reconciled; old archives retained as historical reference.

---

### Pandas mixed timezone offsets in CSV parse to object dtype (2026-04-28)
**Problem**: `pd.read_csv("metrics_trajectory.csv", parse_dates=["commit_date"])` returned the column as object dtype instead of datetime64. Subsequent `.dt.tz_convert(...)` raised `AttributeError: Can only use .dt accessor with datetimelike values`.
**Root cause**: The CSV had ISO-8601 timestamps spanning the EU DST transition — values like `2026-03-26T15:18:55+01:00` and `2026-03-29T16:45:06+02:00` in the same column. Pandas' `parse_dates` heuristic falls back to object dtype rather than picking a single dtype with mixed offsets.
**Fix**: Don't rely on `parse_dates=`. Read first, then explicitly `pd.to_datetime(col, utc=True)` — `utc=True` normalises offsets to UTC, producing a clean tz-aware datetime64 column. Pattern saved in `_load_trajectory()` in `scripts/build_arf_retrospective_figures.py`.
**Pattern**: Any time-series CSV that spans a DST boundary (or aggregates from multiple timezone sources) will trigger this. Default to `pd.to_datetime(..., utc=True)` for any timestamp column you intend to use as a real datetime. The `parse_dates=` shortcut only works for single-offset data.
**Status**: [RESOLVED]

---

### Local main can lag origin/main when working from parked feature branch (2026-04-28)
**Problem**: While diagnosing live model degradation, the initial read of `ml/models/state.json` showed `last_timestamp: 2026-04-21` and `git log -- ml/models/state.json` on `main` ended on the same date. Concluded production pipeline had been silent for 7 days. Wrong.
**Root cause**: Local checkout was on `feat/new-features-ttf-genmix` (parked), forked at `12f0177 Daily model update 2026-04-21`. Local `main` was 7 commits behind `origin/main`, which had been receiving daily updates through 2026-04-28. The live dashboard reads from `origin/main`, not the local working tree.
**Fix**: `git fetch origin && git show origin/main:ml/models/state.json` revealed the true production state — cron healthy, real degradation driven by a price regime shift. The misdiagnosis cost ~5 minutes and one round of pushback from the user.
**Pattern**: Before claiming a production pipeline is stale or broken from local artifact inspection, run `git fetch origin` and read the relevant file via `git show origin/main:<path>`. The local working branch may not reflect what is actually deployed. Especially when the working branch is non-main / parked.
**Status**: [RESOLVED]

---

### Calibrated weather noise improved rather than degraded model (2026-04-19)
**Problem**: Designed a "leakage probe" for long-history warmup expecting perfect-knowledge weather to win over calibrated-noise weather. Got the opposite — noisy variant beat clean on both training MAE (14.98 vs 16.40) and backtest MAE (16.36 vs 18.06).
**Root cause**: Calibrated noise (wind σ=1.8 m/s, solar σ=30 W/m² GHI-gated) acted as regularization, not leakage simulation. Price lags dominate the feature set; reducing weather feature precision prevented River ARF from overfitting to weak weather signals.
**Fix**: Not a bug — downgrade the weather-leakage risk (FMEA #1, pre-RPN 648 / residual 180) going forward. Assume calibrated noise is safe-or-beneficial rather than a necessary evil.
**Pattern**: When a feature has been shown low-importance by Lasso (temperature dropped per `memory/ml-decisions.md`), "perfect" vs "noisy" variants of that feature family are not meaningfully different. Test the assumption before architecting around it.
**Status**: [RESOLVED] — captured in `docs/long-history-mini-results.md` on `feat/long-history-warmup` branch.

### Backtest "N/N wins" claim missed an ARF cron-skip day (2026-04-29)
**Problem**: Milestone 2 writeup led with "LightGBM wins 14/14 days" on the 14-day apples-to-apples window. Surfaced in review: window is 15 calendar days (04-14 → 04-28 inclusive), but ARF's `metrics_history.csv` is missing 04-22 (cron skip). The merge produced 14 rows — every one a LGBM win — so "14/14 wins" is technically correct but reads as "swept a contiguous 14-day window" when actually it's "all 14 evaluable days out of 15 calendar days, with 04-22 unrepresented in ARF". LGBM had predictions for 04-22 too (MAE 8.17) and would have won.
**Root cause**: When merging on an external metrics series with cron gaps, headlines built from the merge silently inherit the gap. Sample-size phrasing didn't distinguish "evaluable rows" from "calendar days".
**Fix**: State explicitly in summary: "LGBM wins all N evaluable days of the M-day calendar window; the gap on YYYY-MM-DD is an external-cron skip, not a LGBM failure." Done in `ml/shadow/backtest_results/summary.md`, `milestone_2_5_summary.md`, `docs/model-progress-log.md`.
**Pattern**: Whenever a comparison merges against an external metrics series (ARF's `metrics_history.csv`, an exchange feed, etc.), check `len(merged) == calendar_days` before stating "N/N" claims. ARF cron has historical gaps on 04-08 and 04-22 in this corpus; future merges into this series should expect occasional skips.
**Status**: [RESOLVED]

---

### Backtest MAE headlines need an explicit horizon qualifier (2026-04-29)
**Problem**: Milestone 2/2.5 summaries originally led with "MAE 12.83" / "+46% vs ARF" without specifying that this measures next-hour prediction with realized lag inputs ("h+1 perfect-lag"). The deployed system forecasts 72 hours ahead via iterated lag feeding; iterated MAE will be materially higher. A reader who saw only the headline could assume the deployed system would land at 12-13 EUR/MWh — which is the model-quality ceiling, not the deployed-system quality. Surfaced in the data-analyzer review.
**Root cause**: Internal comparison framework focuses on h+1 because that's apples-to-apples with ARF's `update_mae` (which is also predict-before-learn at h+1). Easy to forget the qualifier when stating numbers in summaries.
**Fix**: Always pair MAE headlines from a contemporaneous-prediction backtest with the qualifier "h+1 perfect-lag" or equivalent. Once iterated multi-horizon validation lands (milestone 3+), state which horizon the headline measures. Updated `summary.md`, `milestone_2_5_summary.md`, `model-progress-log.md`, `memory/arf-retired.md` (auto-memory).
**Pattern**: For any forecasting model with a multi-step horizon, the headline metric must specify the horizon it covers. Single-step quality is the ceiling, not the operating point.
**Status**: [RESOLVED]

---

### Python stdout encoding breaks on Unicode arrows under Git Bash (2026-04-19, recurred 2026-04-29)
**Problem**: Probe script printing `→` arrow crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` on Windows. Aborted a multi-probe parallel run mid-way.
**Root cause**: Windows Python defaults to cp1252 stdout when invoked via Git Bash without explicit encoding. Non-ASCII output fails immediately.
**Fix**: Set `PYTHONIOENCODING=utf-8` before the python invocation, or avoid non-ASCII characters in print statements for committed scripts.
**Recurrence (2026-04-29)**: Same trap in `ml/shadow/backtest.py` startup line — `print(f"... {a} -> {b} ...")` originally written with a Unicode arrow. Caught immediately on first invocation; one-character fix.
**Pattern**: If running ad-hoc python on Windows Git Bash with any non-ASCII output, prepend `PYTHONIOENCODING=utf-8`. For committed scripts use ASCII-only separators (`->`, `..`) over Unicode — environment-independent and survives cp1252 callers. Two recurrences in 10 days makes this a write-time discipline, not a runtime workaround.
**Status**: [RESOLVED]

---

### Energy Zero consumer prices contaminating training target (2026-04-02)
**Problem**: When ENTSO-E collector is down, `parse_price_file()` silently fell back to Energy Zero consumer prices (incl. VAT + ~110 EUR/MWh surcharge) as the training target. Model learned from wrong price series for ~5 days (March 26-31), causing last_week_mae to degrade from ~17 to 21.
**Root cause**: `parse_price_file()` merged all sources including `energy_zero` with ENTSO-E overwriting — but when ENTSO-E is absent, Energy Zero remained as the "price".
**Fix**: Removed `energy_zero` from the merge loop in `parse_price_file()` — only wholesale sources (entsoe, elspot, epex) are used. Added warning log when ENTSO-E is missing. Rolled back model to pre-contamination checkpoint (bbaa2c8, 4119 samples).
**Pattern**: Any multi-source merge with silent fallback can corrupt data when the authoritative source disappears. Always validate that the primary source is present, or fail loudly.
**Status**: [RESOLVED]

### CI workflow references stale file names (2026-04-01)
**Problem**: CI failed on `chart.js not copied` and `No module named 'decrypt_data'` — both files were renamed/deleted in earlier refactors but `.github/workflows/test.yml` was never updated.
**Root cause**: File renames (chart.js → dashboard.js, decrypt_data.py → decrypt_data_cached.py) didn't include CI workflow updates.
**Fix**: Updated test.yml to reference `dashboard.js` and `decrypt_data_cached`. Added `sourceType:module` for ESLint on ES6 imports.
**Status**: [RESOLVED]

### Netlify --force flag not bypassing hash cache (2026-03, pre-Augur)
**Problem**: Webhook-triggered builds were serving stale data despite --force flag.
**Root cause**: `decrypt_data_cached.py` --force bypassed age check but not hash check. Cached hash matched → skipped decryption even when forced.
**Fix**: Added `if not force_refresh` guard around hash comparison at line 292.
**Status**: [RESOLVED] — fix deployed, documented in ADR-003.

### Elspot timezone offset malformed (2026-03, pre-Augur)
**Problem**: Elspot data had `+00:09` timezone offset instead of `+02:00`.
**Root cause**: Bug in energyDataHub's Elspot collector producing malformed timezone strings.
**Fix**: energyDataHub migrated from nordpool to pynordpool (API v2) in 40632f6, and upstream entsoe-py/tenneteu-py timezone bugs fixed in 33fc596.
**Status**: [RESOLVED] — root cause fixed in energyDataHub. Legacy `chart.js` deleted 2026-03-28.

### energyDataHub ENTSO-E backfill completed (2026-03-28)
**Problem**: 43% of energyDataHub price files (123 of 235) were missing `entsoe` and/or `entsoe_de` datasets due to silent API failures since Sep 2025. Augur's warmup training used incomplete price data.
**Fix**: energyDataHub backfilled 100 files with historical ENTSO-E day-ahead prices (NL + DE). Commit ducroq/energydatahub@7a1e4c1. Re-warmup completed 2026-03-28 (4,192 rows, MAE 13.80).
**Remaining**: 26 early files (Sep-Oct 2025) still degraded due to malformed timestamps — low impact.
**Status**: [RESOLVED]

### Non-monotonic price index crashes _nearest (2026-03-28)
**Problem**: `_nearest()` in `ml/update.py` crashed with `ValueError: index must be monotonic` during forecast generation after ENTSO-E backfill.
**Root cause**: `parse_price_file` merges multiple sources (energy_zero, elspot, epex, entsoe) by overwriting — the resulting series can have an unsorted index.
**Fix**: Added `if not series.index.is_monotonic_increasing: series = series.sort_index()` guard in `_nearest`.
**Status**: [RESOLVED]

### Energy Zero hardcoded +2h offset (2026-03, pre-Augur)
**Problem**: Legacy code added fixed +2 hours for NL timezone, incorrect during winter (UTC+1).
**Root cause**: Quick implementation without proper timezone library.
**Fix**: Modular `timezone-utils.js` uses `Intl.DateTimeFormat` correctly. Legacy `chart.js` deleted.
**Status**: [RESOLVED]
