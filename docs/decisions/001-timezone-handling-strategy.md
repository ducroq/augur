# ADR-001: Amsterdam Timezone Handling with convertUTCToAmsterdam Pattern

**Date**: 2025-11-15
**Status**: Accepted
**Deciders**: User + Claude Code
**Tags**: frontend, data-processing, timezone, chart-rendering

---

## Context

**What is the issue we're facing?**

The Augur displays time-series data from multiple sources (Energy Zero API, ENTSO-E forecasts, EPEX, Elspot) that all use different timezone representations. The dashboard serves Dutch users viewing Amsterdam-local energy prices, so all timestamps must be displayed in Europe/Amsterdam timezone (CET/CEST), which automatically switches between UTC+1 (winter) and UTC+2 (summer) for daylight saving time.

The chart's "now" indicator line was showing 1-2 hours off from the actual current time, causing user confusion about which hour's pricing was currently active.

**Forces:**
- Energy Zero API returns UTC timestamps (`2025-11-15T10:00:00Z`)
- Various forecast APIs return incorrect timezone offsets (e.g., `+00:18` instead of `+02:00`)
- Chart data must be in Amsterdam timezone for accurate display
- The "now" line must match the chart's timezone exactly
- DST transitions happen automatically (last Sunday in March/October)
- JavaScript's `.toISOString()` always returns UTC time
- Different timezone conversion approaches exist (Intl.DateTimeFormat, manual offset calculation, moment.js)

---

## Decision

**What did we decide?**

We will use the `convertUTCToAmsterdam(utcDate)` utility function from `timezone-utils.js` followed by `.toISOString()` as the **canonical pattern** for all timestamp formatting in the dashboard.

**Key aspects:**
- All chart timestamps are converted using `convertUTCToAmsterdam()` which uses `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'`
- The function returns a Date object that, when formatted with `.toISOString()`, displays Amsterdam local time
- This pattern is used consistently across:
  - Data processing (`data-processor.js:48`)
  - Chart rendering (`chart-renderer.js:18`)
  - Any future timestamp handling
- No dependency on external libraries (moment.js, date-fns) for timezone handling
- DST is handled automatically by the browser's `Intl.DateTimeFormat` implementation

**Implementation:**
```javascript
// Canonical pattern used throughout the codebase
const utcTimestamp = new Date(pricePoint.readingDate); // From API
const localTimestamp = convertUTCToAmsterdam(utcTimestamp);
const isoString = localTimestamp.toISOString(); // For chart display
```

**NOT this pattern:**
```javascript
// WRONG - Do not use formatAmsterdamISOString for chart data
const now = new Date();
const isoString = formatAmsterdamISOString(now); // ❌ Incorrect for chart display
```

---

## Consequences

### Positive ✅

- **Consistent timezone handling**: All chart data uses the same conversion pattern
- **Automatic DST handling**: No manual date math for CET/CEST transitions
- **No external dependencies**: Uses browser's native `Intl.DateTimeFormat`
- **Accurate "now" line**: Current time indicator matches chart data timezone exactly
- **Memoization**: `convertUTCToAmsterdam` caches results for performance (500-item cache)
- **Clear debugging**: All timestamps in chart traces are in Amsterdam time when inspected

### Negative ❌

- **Confusing Date object semantics**: The returned Date object internally stores a shifted timestamp that looks like UTC when formatted with `.toISOString()`
  - Example: `convertUTCToAmsterdam(new Date("2025-11-15T10:00:00Z")).toISOString()` returns `"2025-11-15T11:00:00.000Z"` (the hour is Amsterdam local, but the Z suffix is misleading)
- **Not truly ISO 8601 compliant**: The `Z` suffix means UTC, but the hour value is Amsterdam local time
- **Requires developer understanding**: New developers must understand the conversion pattern to avoid mistakes

### Neutral ⚪

- **Alternative function exists**: `formatAmsterdamISOString()` exists in the same module but has a different use case (formatting dates for display with proper `+01:00`/`+02:00` offset)
- **Two-step process**: Requires `convertUTCToAmsterdam()` + `.toISOString()` instead of single function call

---

## Alternatives Considered

### Alternative 1: Use formatAmsterdamISOString() Directly

**Description:**
Use `formatAmsterdamISOString(date)` which formats dates with proper timezone offset indicators (`+01:00` or `+02:00`).

**Pros:**
- Produces ISO 8601 compliant strings with correct offset
- Single function call
- Clearer semantics (offset explicitly shows CET vs CEST)

**Cons:**
- Expects input to already be in Amsterdam local time (incorrect assumption from `new Date()`)
- Not the pattern used by data processor for chart data
- Would cause mismatch between "now" line and chart data timestamps

**Why rejected:**
The chart data uses the `convertUTCToAmsterdam()` + `.toISOString()` pattern, so the "now" line must use the same pattern for consistency. Using `formatAmsterdamISOString()` caused a 1-hour offset bug.

**Evidence:**
```javascript
// data-processor.js:48 - How Energy Zero data is processed
const localTimestamp = convertUTCToAmsterdam(utcTimestamp);
// ...
timestamp: localTimestamp.toISOString()

// chart-renderer.js (WRONG - caused bug)
const currentTimeISO = formatAmsterdamISOString(amsterdamNow); // ❌ Mismatch!
```

### Alternative 2: Manual Offset Calculation

**Description:**
Calculate the timezone offset manually based on DST rules and apply it to UTC timestamps.

**Pros:**
- Full control over conversion logic
- No reliance on browser APIs
- Could produce truly ISO 8601 compliant strings

**Cons:**
- Complex DST logic (last Sunday in March/October)
- Brittle - DST rules can change
- Error-prone - easy to get edge cases wrong
- Reinventing the wheel

**Why rejected:**
`Intl.DateTimeFormat` already handles DST correctly and is battle-tested. Manual offset calculation adds complexity without benefit.

### Alternative 3: Use moment-timezone or date-fns-tz

**Description:**
Add external library like `moment-timezone` or `date-fns-tz` for timezone handling.

**Pros:**
- Well-tested timezone handling
- Rich API for date manipulation
- Community support

**Cons:**
- Adds dependency (moment.js is 67KB minified)
- Moment.js is in maintenance mode (no longer recommended)
- Overkill for single timezone conversion use case
- Browser's `Intl.DateTimeFormat` is sufficient

**Why rejected:**
The dashboard is dependency-light and uses vanilla JavaScript. The browser's native timezone handling is sufficient for our use case.

---

## Implementation

**How was this decision implemented?**

**Completed actions:**
1. ✅ Created `convertUTCToAmsterdam()` utility function in `timezone-utils.js`
2. ✅ Applied pattern in `data-processor.js` for Energy Zero API data (line 48)
3. ✅ Fixed `chart-renderer.js` to use same pattern for "now" line (line 18)
4. ✅ Added memoization cache (500 items) for performance
5. ✅ Tested in production - "now" line shows correct Amsterdam time

**Timeline:**
- 2025-11-14: Initial timezone utilities created
- 2025-11-15: First fix attempt using `formatAmsterdamISOString()` (incorrect)
- 2025-11-15: Second fix using `convertUTCToAmsterdam()` pattern (correct)
- 2025-11-15: Verified working in production

**Success criteria:**
- ✅ "Now" line displays at current Amsterdam local time
- ✅ "Now" line matches chart data timezone exactly
- ✅ Automatic DST handling (no manual updates needed)
- ✅ Consistent pattern used across all timestamp conversions
- ✅ No performance degradation (memoization prevents repeated calculations)

---

## Related Decisions

- [AI_AUGMENTED_WORKFLOW.md](../agents/AI_AUGMENTED_WORKFLOW.md) - Chart agent validation identified the timezone bug
- [ENERGYLIVEDATA_FEATURES_PLAN.md](../ENERGYLIVEDATA_FEATURES_PLAN.md) - Future features may need timezone handling

---

## References

- `static/js/modules/timezone-utils.js` - Implementation of `convertUTCToAmsterdam()`
- `static/js/modules/data-processor.js:48` - Usage for Energy Zero data
- `static/js/modules/chart-renderer.js:18` - Usage for "now" line
- [MDN: Intl.DateTimeFormat](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/DateTimeFormat) - Browser API documentation
- [ISO 8601](https://en.wikipedia.org/wiki/ISO_8601) - Datetime format standard

---

## Notes

**Open questions:**
- Should we add JSDoc comments explaining the "fake UTC" semantics of returned Date objects?
- Should we rename `convertUTCToAmsterdam()` to something more explicit like `convertToAmsterdamAsUTC()`?

**Future considerations:**
- If the dashboard expands to multiple timezones, may need to generalize the pattern
- Consider adding a `getAmsterdamISOString(utcDate)` convenience function that combines both steps
- Document the pattern in CLAUDE.md for future developers

**Key insight:**
The pattern `convertUTCToAmsterdam(date).toISOString()` creates Date objects whose internal UTC timestamp is shifted such that `.toISOString()` displays Amsterdam local time. This is semantically confusing but works consistently when used uniformly across the codebase.

---

## Review History

| Date | Reviewer | Action | Notes |
|------|----------|--------|-------|
| 2025-11-15 | Claude Code | Created | Initial draft based on timezone bug fix |
| 2025-11-15 | User + Claude | Accepted | Verified working in production |

---

**Last Updated**: 2025-11-15
**Version**: 1.0
