# Gotcha Log

## Promoted

| Entry | Promoted to | Date |
|-------|------------|------|
| EWM variance formula wrong | Fixed in `ml/update.py` — now uses signed `ewm_mean` | 2026-03-28 |
| Double push of exchange prices | Fixed in `ml/update.py` — only push ML predictions | 2026-03-28 |

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

### Python stdout encoding breaks on Unicode arrows under Git Bash (2026-04-19)
**Problem**: Probe script printing `→` arrow crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` on Windows. Aborted a multi-probe parallel run mid-way.
**Root cause**: Windows Python defaults to cp1252 stdout when invoked via Git Bash without explicit encoding. Non-ASCII output fails immediately.
**Fix**: Set `PYTHONIOENCODING=utf-8` before the python invocation, or avoid non-ASCII characters in print statements for throwaway scripts.
**Pattern**: If running ad-hoc python on Windows Git Bash with any non-ASCII output, prepend `PYTHONIOENCODING=utf-8`. For saved scripts, use ASCII-only separators (`->`, `..`) over Unicode.
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
