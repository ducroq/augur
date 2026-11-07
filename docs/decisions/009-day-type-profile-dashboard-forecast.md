# ADR-009: The dashboard shows the day-type profile forecast

**Status**: Accepted (pending engineer review of the commit)
**Date**: 2026-11-07
**Context**: augur#37. Since 2026-10-28 forecasters are judged on cheap-hour regret per horizon block against the EXP-036 profile floor (`docs/hypothesis-log.md` [2026-10-28]). Live, the production LightGBM loses to that floor in every block.
**Supersedes**: the forecaster choice in ADR-006. ADR-006's pipeline (LightGBM retrain, CQR, consumer transform) keeps running unchanged as a shadow.

## Decision

The dashboard's price forecast becomes the **day-type profile rule**: for each of the 72 hours after production's `t0`, the mean of the same hour over the last 5 matching day types (weekday / weekend / NL holiday). "Same hour" means whole UTC days back, so in the days after a DST change the sources sit one local hour off. That is the estimator as scored, kept on purpose. It is `evaluate_shadow.naive_profile_prediction`, the arm `regret.py` has scored nightly since 2026-09-14, so the dashboard shows exactly what was measured.

- **Step**: `ml/shadow/update_profile.py`, run in `scripts/daily_update.sh` right after `update_shadow` (it reads that step's `last_t0`). It writes `static/data/augur_forecast_profile.json` in the schema of `augur_forecast_shadow.json`, consumer fields included (same VAT and ARF surcharge). A failure is `[ALARM: profile forecast failed rc=N]`, and the dashboard keeps the previous night's file. A run that writes fewer than 72 hours is `[ALARM: profile forecast Nh of 72]`.
- **Bands** (decided 2026-11-07): P10 and P90 of the rule's own errors (actual − forecast) per horizon block, over target hours in the last 28 days, recomputed nightly. A block with under 168 residuals gets no band.
- **Naming** (decided 2026-11-07): the file carries `metadata.display_name` ("Average of the last 5 similar days"). The chart legend and one line under the chart use it.
- **Swap point**: `dashboard.js:loadAugurForecast`. Revert = point it back at `augur_forecast_shadow.json`. That file has no `display_name`, so the old labels return with it.

## Why this is not an ADR-007 promotion

ADR-007 promotes a challenger on a pre-committed test over data it hasn't seen. This is a product decision on evidence already seen: the live regret log. It is recorded as such, and it claims no statistical superiority beyond what that log shows. A future challenger (the FM shadow, EXP-021a Stage 3) is promoted against this rule under ADR-007 and its signed-off criterion.

## Evidence

`ml/shadow/regret_log.jsonl`, vintages 2026-09-14..2026-11-06, mean k6 regret in EUR/MWh (recomputed 2026-11-07):

| Block | Blocks | LightGBM | Profile | Profile lower / tied |
|---|---|---|---|---|
| h1_24 | 48 | 11.6 | 5.8 | 27 / 10 |
| h25_48 | 47 | 11.0 | 5.6 | 30 / 6 |
| h49_72 | 46 | 10.0 | 5.9 | 26 / 9 |

Offline, LightGBM `p50` sits at −12.4% against the same floor (augur#29). Point accuracy is not the product; picking cheap hours is, and there the rule is about twice as good.

## Consequences

- **Bands get wider.** On 2026-11-07 the rule's mean band width is about 207 EUR/MWh against LightGBM's 106. LightGBM's band under-covers, though (P80 pooled 0.703, augur#19). The rule's band is the empirical 80% of its own recent misses, so it is honest by construction over its window, not narrow.
- **Holidays.** The parquet flags holidays only up to `t0`, so the step carries a built-in NL calendar (`nl_holidays`, pinned by a test to the dates production's parquet flags). Five earlier holidays within the 56-day lookback exist only from Easter to Whitsun. Any other holiday (Christmas, New Year) falls back to pooling with weekend days. The scored arm returns nothing on those hours, so the fallback changes no measured number.
- **The rule has no weather input.** It can't see a windy or sunny day coming. That is the headroom a challenger has to show on regret, and the floor's own regret (about 6 EUR/MWh) caps what any forecaster can add on the 6-hour choice.
- **Coupling.** The step needs `update_shadow`'s `t0`. If LightGBM fails, the dashboard forecast goes stale too, as it did before. Breaking that coupling (computing `t0` independently) is possible later. It isn't done here, because the pairing with the regret log is worth more now.
- ARF retirement (augur#32) and the LightGBM shadow's future are unchanged by this ADR.

## References

- augur#37, augur#29, augur#19, augur#32
- `docs/hypothesis-log.md` [2026-10-28] product criterion; EXP-036 (profile floor)
- ADR-006 (pipeline kept as shadow), ADR-007 (promotion method, for challengers to this rule)
