# Gotcha Log

## Promoted

| Entry | Promoted to | Date |
|-------|------------|------|
| EWM variance formula wrong | Fixed in `ml/update.py` — now uses signed `ewm_mean` | 2026-03-28 |
| Double push of exchange prices | Fixed in `ml/update.py` — only push ML predictions | 2026-03-28 |

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
