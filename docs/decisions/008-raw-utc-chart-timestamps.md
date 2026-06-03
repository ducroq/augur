# ADR-008: Raw UTC timestamps for chart data; browser-local rendering via Plotly

**Status**: Accepted
**Date**: 2026-06-03
**Context**: Replacing the `convertUTCToAmsterdam` + `.toISOString()` pattern from ADR-001 after augur#16 revealed it caused systematic time-axis misalignment between EnergyZero and Augur forecast traces.

## Decision

All time-series data flowing into Plotly carries **real UTC ISO strings** end-to-end. Plotly renders those strings in the browser's local timezone, which for the dashboard's target audience (Dutch users on the Augur dashboard) is Europe/Amsterdam — CEST in summer, CET in winter, with DST transitions handled by the browser.

No mutation of `Date` UTC fields anywhere in the data pipeline. The `convertUTCToAmsterdam` utility from `timezone-utils.js` has been removed.

This decision supersedes ADR-001.

## Why ADR-001 was wrong

`convertUTCToAmsterdam(utcDate)` constructed a Date whose **internal UTC timestamp was pre-shifted by the Amsterdam offset** so that `.toISOString()` would emit a string whose UTC component looked like the Amsterdam wall-clock value. ADR-001 acknowledged this as semantically confusing (see its own *Negative Consequences* §76: *"the Z suffix is misleading"*) but accepted it on the grounds that uniform application across the codebase would make the convention work.

It didn't, for two reasons:

1. **Application was not actually uniform.** The Augur ML forecast trace (added later in `ml/update.py` and `ml/shadow/update_shadow.py`) wrote its forecast JSON with **real UTC** timestamps and the dashboard rendered those directly without conversion. So *one* trace family followed ADR-001's convention (EnergyZero, current-time line) and the *other* trace family did not (Augur forecast, confidence band). Plotly then placed them on different x-grids — by construction in different frames — and they could not align. In summer the discrepancy is +2h.
2. **The mutation pattern violates the CLAUDE.md hard constraint.** *"Never use hardcoded +2h timezone offset — use `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'`."* `convertUTCToAmsterdam` used `Intl` correctly to *read* the components, but then re-encoded those components into a Date's UTC field, which is morally identical to a hardcoded offset and produces the same class of bug. The constraint should be read as forbidding both: *no offset baked into stored timestamps, ever*.

## Why raw UTC + browser rendering works

Plotly's `xaxis` of `type: 'date'` parses ISO 8601 strings and renders them in the browser's local timezone by default. The Augur forecast trace has been using this convention since it was added — that's why it was always correct without any "conversion." The fix for augur#16 brings EnergyZero and the current-time vertical line onto the same convention.

Consequences:

- A user browsing from outside Europe/Amsterdam sees times in their browser's local timezone, not Amsterdam time. For the dashboard's intended audience (NL energy users) this is identical to Amsterdam. For visitors from other timezones it is a minor display quirk but never a misalignment: every trace is in the same frame.
- DST transitions are handled by the browser; no code path needs to know about CET vs CEST.
- The `addNoise` and unit-conversion steps in `data-processor.js` remain unchanged.
- Date comparisons inside data-processor.js (e.g. filtering `today_prices` by `startDateTime` / `endDateTime`) are now frame-consistent. The previous mixed-frame comparison was a latent off-by-2h bug that happened to be invisible because the typical filter window (00:00 today through 23:59 day-after-tomorrow) is much wider than 2h.

## What changed in code

| File | Change |
|---|---|
| `static/js/modules/data-processor.js` | Removed `convertUTCToAmsterdam` import. `processEnergyZeroData` stores `utcTimestamp.toISOString()` (real UTC) instead of `localTimestamp.toISOString()` (lied UTC). Filter / `current_price` detection / `hour` field switched to `utcTimestamp` accordingly. |
| `static/js/modules/chart-renderer.js` | `getCurrentTimeLineShape` uses `new Date().toISOString()` directly; no longer calls `convertUTCToAmsterdam`. |
| `static/js/modules/timezone-utils.js` | `convertUTCToAmsterdam`, `amsterdamFormatter`, and the memoization cache deleted. `formatDateTime` kept (still used by `ui-controller.js` for display strings unrelated to chart axes). |

177/177 Python tests pass (Python pipeline does not depend on any of this).

## Trade-offs accepted

- **Cross-timezone display:** non-NL visitors see their local time. This was already true for the Augur forecast trace under ADR-001; now it is uniformly true. If true Amsterdam-time display becomes a requirement, the right fix is Plotly-side via `layout.xaxis` formatting with explicit `Europe/Amsterdam` rendering — never data-side mutation.
- **ADR-001 narrative cost:** ADR-001's "uniform application" rationale was always fragile because the dashboard pipeline was already partly bypassing it (forecast traces). This ADR documents the bypass as the correct path.

## Open follow-ups (not blocking)

- `augur#18` (clarify wholesale vs consumer comparators; verify EZ endpoint really returns all-in pricing) is unaffected by this ADR and remains open.
- A future cleanup could remove the now-vestigial fields `hour` and `current_price` from `processEnergyZeroData` if a grep confirms zero consumers. Out of scope for the augur#16 fix.

## References

- augur#16 (the bug report that triggered this)
- ADR-001 (superseded)
- CLAUDE.md hard constraint on `Intl.DateTimeFormat` with `timeZone: 'Europe/Amsterdam'`
- `static/js/modules/data-processor.js`, `chart-renderer.js`, `timezone-utils.js`
