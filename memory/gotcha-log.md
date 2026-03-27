# Gotcha Log

## Promoted

| Entry | Promoted to | Date |
|-------|------------|------|
| (none yet) | | |

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

### Energy Zero hardcoded +2h offset assumes summer time (ongoing)
**Problem**: `chart.js:185-186` adds fixed +2 hours for NL timezone, incorrect during winter (UTC+1).
**Root cause**: Quick implementation without proper timezone library.
**Fix**: Modular `timezone-utils.js` uses `Intl.DateTimeFormat` correctly. Legacy `chart.js` still has the bug.
**Status**: Active — fixed in modular code, legacy code still broken. Will resolve when chart.js is fully deprecated.
