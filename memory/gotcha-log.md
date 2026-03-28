# Gotcha Log

## Promoted

| Entry | Promoted to | Date |
|-------|------------|------|
| EWM variance formula wrong | Fixed in `ml/update.py` — now uses signed `ewm_mean` | 2026-03-28 |
| Double push of exchange prices | Fixed in `ml/update.py` — only push ML predictions | 2026-03-28 |

---

### Netlify --force flag not bypassing hash cache (2026-03, pre-Augur)
**Problem**: Webhook-triggered builds were serving stale data despite --force flag.
**Root cause**: `decrypt_data_cached.py` --force bypassed age check but not hash check. Cached hash matched → skipped decryption even when forced.
**Fix**: Added `if not force_refresh` guard around hash comparison at line 292.
**Status**: [RESOLVED] — fix deployed, documented in ADR-003.

### Elspot timezone offset malformed (2026-03, pre-Augur)
**Problem**: Elspot data had `+00:09` timezone offset instead of `+02:00`.
**Root cause**: Bug in energyDataHub's Elspot collector producing malformed timezone strings.
**Fix**: energyDataHub migrated from nordpool to pynordpool (API v2) in 40632f6, and upstream entsoe-py/tenneteu-py timezone bugs fixed in 33fc596.
**Status**: [RESOLVED] — root cause fixed in energyDataHub. Client-side workaround in legacy chart.js can be removed when chart.js is deprecated.

### energyDataHub ENTSO-E backfill completed (2026-03-28)
**Problem**: 43% of energyDataHub price files (123 of 235) were missing `entsoe` and/or `entsoe_de` datasets due to silent API failures since Sep 2025. Augur's warmup training used incomplete price data.
**Fix**: energyDataHub backfilled 100 files with historical ENTSO-E day-ahead prices (NL + DE). Commit ducroq/energydatahub@7a1e4c1.
**Action needed**: Re-run warmup consolidation (`ml/data/consolidate.py`) to rebuild training parquet with the patched price files. The daily `ml.update` pipeline will automatically use the latest data.
**Remaining**: 26 early files (Sep-Oct 2025) still degraded due to malformed timestamps — low impact, predates most Augur training data.
**Status**: [RESOLVED]

### Energy Zero hardcoded +2h offset assumes summer time (ongoing)
**Problem**: `chart.js:185-186` adds fixed +2 hours for NL timezone, incorrect during winter (UTC+1).
**Root cause**: Quick implementation without proper timezone library.
**Fix**: Modular `timezone-utils.js` uses `Intl.DateTimeFormat` correctly. Legacy `chart.js` still has the bug.
**Status**: [RESOLVED] — legacy `chart.js` deleted 2026-03-28. Modular `timezone-utils.js` handles DST correctly.
