# Long-History Warmup — FMEA

**Companion to**: `docs/decisions/005-long-history-warmup.md`, `docs/long-history-implementation-plan.md`
**Branch**: `feat/long-history-warmup`
**Date**: 2026-04-19

Structured failure-mode analysis before implementation. Scoring each risk by Severity × Occurrence × Detection produces a Risk Priority Number (RPN); higher = more attention. Re-scored post-mitigation to show residual risk after controls.

## Scoring guide

| Score | Severity (S) — if it happens | Occurrence (O) — how likely | Detection (D) — before it bites |
|---|---|---|---|
| 1 | Trivial, self-resolves | Never in project lifetime | Immediate / crash |
| 3 | User sees bug, no data loss | ~1% chance | Caught in CI or first run |
| 5 | Production degraded, reversible | ~25% chance | Manual spot-check needed |
| 7 | Production down, data intact | ~50% chance | Only visible after days |
| 9 | Silent bad output in production | Near-certain | Only caught by external report |
| 10 | Persistent silent corruption affecting users | Every run | Undetectable |

RPN = S × O × D. Rough action thresholds: >100 = mandatory mitigation; 25-100 = mitigate if cheap; <25 = accept.

## Risk register

Sorted by pre-mitigation RPN, descending.

### 1. Weather-forecast leakage (ERA5 actuals as forecast lags)

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 9 | 8 | 9 | **648** |
| Post | 9 | 4 | 5 | 180 |

**Failure mode**: Open-Meteo archive returns actuals, not as-of-date forecasts. Model trains with perfect-knowledge wind/solar. Gate passes spuriously; v2 deployed; quiet degradation in production.
**Justification**: S=9 because silent deploy is the worst software failure mode. O=8 because it's a structural property, not an accident. D=9 because only shadow mode catches it, and only if the divergence is large.
**Mitigation**:
- Benchmark: pull archived `*_wind_forecast.json` / `*_solar_forecast.json` files on sadalsuud (back to 2025-09-28) vs Open-Meteo archive for the same dates. Measure actual forecast-vs-archive error at h+1, h+24, h+48, h+72.
- Calibrated noise: inject `N(0, σ(h))` into backfilled wind/solar, horizon-dependent.
- Bound residual risk with shadow mode — v2 competes against v1 on live (forecast-fed) data for 14 days before cutover. If v2 lead collapses on live, the gate holds.
- Residual D=5 because shadow mode takes 2 weeks to surface the issue, and some leakage is inherent even with calibrated noise.

### 2. Target-definition drift (ENTSO-E hourly FF vs consolidated 15-min)

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 9 | 4 | 9 | **324** |
| Post | 9 | 4 | 2 | 72 |

**Failure mode**: warmup target is pure ENTSO-E hourly forward-filled to 15-min. Production target is 15-min "wholesale price" from consolidated multi-source. If they differ systematically, v2 learns a subtly different function; gate passes because backtest target matches warmup target, not production target.
**Mitigation**: **pre-warmup target-comparison study**. Pull 1 month of both target series for the same period. Assert `mean |ENTSO-E_FF − consolidated| < 0.5 EUR/MWh` and `p95 |diff| < 2.0 EUR/MWh`. If it fails, use the consolidated target for warmup (more complex) or accept the documented bias.
**Residual D=2** because the diff check catches it before training; if the study passes, the drift is within measured tolerance.

### 3. Timezone / DST off-by-one

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 6 | 5 | 7 | **210** |
| Post | 6 | 2 | 2 | 24 |

**Failure mode**: ENTSO-E returns CET/CEST, Open-Meteo archive returns UTC, `holidays` library uses local date. Spring-forward and fall-back days have 23-hour / 25-hour handling that trips naive joins. Prices get associated with wrong weather values for ~4 days/year.
**Mitigation**:
- Normalize all sources to UTC-indexed DataFrames before merge, per ADR-001.
- Explicit unit test covering 2023-03-26 (spring forward) and 2023-10-29 (fall back) — assert 23h and 25h respectively in produced frames.
- Sanity check: hour-of-day distribution of training rows should be uniform ±5%.

### 4. Unknown-unknowns / my own errors

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 6 | 6 | 5 | **180** |
| Post | 6 | 4 | 3 | 72 |

**Failure mode**: I've already made two substantive errors in this project (the two-tier boundary hypothesis; the "500 samples/s" invented number). The pattern suggests more are hiding.
**Justification**: O=6 is a calibration. Over the length of a multi-phase project, *something* I haven't foreseen will surface.
**Mitigation**:
- Phase-gate reviews: user sign-off at end of Phase A (build) and before Phase C (cutover).
- Checklists at each phase boundary (explicit list of what must be verified).
- Shadow-mode comparison as a catch-all for the "v2 doesn't actually work in production" class.
- Still cannot fully eliminate — that's why residual is 72, not near-zero.

### 5. yfinance TTF=F ticker construction change

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 4 | 3 | 7 | **84** |
| Post | 4 | 3 | 3 | 36 |

**Failure mode**: Yahoo's `TTF=F` is a continuous front-month proxy. If Yahoo changes construction (rolling methodology, source exchange), TTF series shifts silently. Model still works but on a subtly different feature.
**Mitigation**: spot-check TTF against EEX settlement values on ~10 dates spanning 2020-2025. Pin expected ranges in an integration test. If future retraining hits different values, test fails loudly.

### 6. Accidental modification of shared code

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 8 | 5 | 2 | **80** |
| Post | 8 | 2 | 2 | 32 |

**Failure mode**: I extend `ml/features/online_features.py` or `ml/data/consolidate.py` during warmup development. Daily cron `git pull`s modified code. Production breaks or silently learns differently.
**Mitigation**:
- Explicit "read-only in this branch" rule for those paths.
- Add to ADR-005 out-of-scope list (already done).
- Unit test asserting feature-builder output signature unchanged from a recorded fixture.
- Pre-commit hook that warns when either file is in a diff from this branch.

### 7. ENTSO-E API key rate-limit / revocation

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 6 | 3 | 4 | **72** |
| Post | 6 | 1 | 4 | 24 |

**Failure mode**: HAN SharePoint key is shared with Pi collector. Heavy scouting + Pi's daily pull triggers rate-limiting or flag. Pi collection breaks; augur sees empty price files 1-2 days later.
**Mitigation**: register a **dedicated ENTSO-E key** for this initiative (free, 1-2 day email registration). Uncouples warmup load from production collection.

### 8. Price buffer seeding bug at handoff

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 5 | 4 | 3 | **60** |
| Post | 5 | 1 | 3 | 15 |

**Failure mode**: after warmup ends at ~T−2 days, the v2 `state.json.price_buffer` contains 2024-era prices instead of recent ones. Daily cron on day T computes lags from stale buffer; first-day forecast is garbage.
**Mitigation**: explicit handoff script that pulls the most recent 200 real ENTSO-E prices and seeds `price_buffer`. Integration test: v2 state.json feeds `ml.update` cleanly and produces a forecast that's within sanity range.

### 9. `requirements.txt` perturbation breaks cron

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 7 | 4 | 2 | **56** |
| Post | 7 | 1 | 2 | 14 |

**Failure mode**: adding `entsoe-py` drags pandas/numpy to new versions, breaking River ARF or secure_data_handler.
**Mitigation**: pin new deps with upper bounds that don't shift pandas/numpy. `pip install --dry-run -r requirements.txt` on sadalsuud's venv before committing. Gate the commit on the dry-run.

### 10. Shadow-mode log disk fill

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 4 | 6 | 2 | **48** |
| Post | 4 | 2 | 2 | 16 |

**Failure mode**: shadow-mode comparison log grows unbounded over 14 days.
**Mitigation**: logrotate or in-code size cap (5 MB, keep last 3). Monitor disk at shadow start.

### 11. Cutover atomicity failure

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 8 | 2 | 2 | **32** |
| Post | 8 | 1 | 2 | 16 |

**Failure mode**: cutover renames happen across multiple commits or during 16:45 UTC cron window; mid-cutover pickle/state mismatch crashes production.
**Mitigation**: cutover is a single commit touching all affected files, wrapped in `flock`, outside the 16:30-17:15 UTC window.

### 12. Concurrency warmup ↔ cron

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 6 | 2 | 3 | **36** |
| Post | 6 | 1 | 3 | 18 |

**Failure mode**: warmup and daily cron both write model files on sadalsuud at 16:45 UTC.
**Mitigation**: warmup writes only to `river_v2/` (separate from v1 paths). Schedule warmup outside 16:30-17:15 UTC. `flock` on v2 paths during warmup.

### 13. Windows ↔ Linux line-endings

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 3 | 4 | 3 | **36** |
| Post | 3 | 2 | 3 | 18 |

**Failure mode**: git warnings already observed (`LF will be replaced by CRLF`). Text fixtures differ between Windows dev and Linux runtime; pickles/parquet likely unaffected.
**Mitigation**: `.gitattributes` force LF for `*.py`, `*.md`, `*.json`, `*.csv` test fixtures.

### 14. Dashboard `metrics_history` gap post-cutover

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 3 | 10 | 1 | **30** |
| Post | 3 | 1 | 1 | 3 |

**Failure mode**: Model tab charts empty for 7-14 days after cutover until daily cron repopulates.
**Mitigation**: option **c** from implementation plan — compute per-day walk-forward MAE during warmup, populate `metrics_history` with real entries.

### 15. 2022 gas crisis destabilizes ARF

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 5 | 5 | 1 | **25** |
| Post | 5 | 5 | 1 | 25 |

**Failure mode**: €50 → €700 → €50 regime change causes ARF to build extreme trees or lose coherence; gate fails catastrophically.
**Mitigation**: **reactive only** — if Phase A backtest explodes on crisis period, restart warmup from 2023-01-01 (skip crisis). No pre-emptive control. Residual RPN unchanged; acceptable because detection is immediate and remediation is cheap.

### 16. Model pickle size breaches git push limits

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 8 | 3 | 1 | **24** |
| Post | 8 | 1 | 1 | 8 |

**Failure mode**: v2 pickle exceeds 25 MB (GitHub soft limit) or 100 MB (hard limit); daily cron push fails.
**Mitigation**: measure `river_v2/river_model.pkl` size at end of Phase A. If >25 MB, configure git-lfs **before** cutover. Document in runbook.

### 17. Disk fill on sadalsuud

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 7 | 1 | 2 | **14** |
| Post | 7 | 1 | 2 | 14 |

**Failure mode**: intermediate warmup artifacts accumulate; cron or dashboard can't write.
**Mitigation**: `df -h` check before warmup; clean intermediate parquet after warmup completes. Not changing much because artifacts are small (~10 MB total).

### 18. Branch rot

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 2 | 6 | 1 | **12** |
| Post | 2 | 3 | 1 | 6 |

**Failure mode**: main advances ~1 commit/day (daily cron). Branch diverges; rebase conflicts on merge.
**Mitigation**: rebase at start of every working session.

### 19. Pickle compatibility across River versions

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 8 | 2 | 1 | **16** |
| Post | 8 | 1 | 1 | 8 |

**Failure mode**: River upgraded between warmup and load → pickle fails to unpickle.
**Mitigation**: pin river version in requirements.txt; document pickle-version-binding in RUNBOOK.

### 20. Encryption/HMAC key confusion

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 7 | 3 | 1 | **21** |
| Post | 7 | 1 | 1 | 7 |

**Failure mode**: editing augur's `.env` to add ENTSO-E credentials, mis-merging existing encryption keys; dashboard decryption breaks.
**Mitigation**: use a **separate** gitignored file `~/local_dev/augur/.env.long-history` on sadalsuud. Never touch production `.env`.

### 21. Open-Meteo endpoint change

|  | S | O | D | RPN |
|---|---|---|---|---|
| Pre | 3 | 2 | 1 | **6** |
| Post | 3 | 2 | 1 | 6 |

**Failure mode**: archive API URL or schema changes between scouting and runtime.
**Mitigation**: pin endpoint URL in config constant; integration test detects immediately. Minor issue.

## Summary — post-mitigation ranking

| Rank | Risk | Residual RPN | Why it stays |
|---|---|---|---|
| 1 | Weather-forecast leakage | **180** | Structural; partial mitigation only |
| 2 | Unknown-unknowns | **72** | Cannot fully eliminate |
| 3 | Target-definition drift | **72** | Pre-warmup study reduces D, but S and O stay |
| 4 | yfinance TTF rotation | **36** | Silent by nature |
| 5 | Shared code modification | **32** | Discipline-dependent |
| 6 | 2022 crisis destabilization | **25** | Accepted — reactive remediation |
| 7 | ENTSO-E rate-limit | **24** | Dedicated key gets us to 24, not lower |
| 8 | Timezone / DST | **24** | Tests catch most, some residual |

Everything else is RPN ≤ 18 post-mitigation.

## Pre-flight checklist (before Phase A code starts)

Derived from the mitigations above. None of these involve writing implementation code — they're verification/setup steps that reduce RPN before we invest in the build.

- [ ] **Register dedicated ENTSO-E API key** (email `transparency@entsoe.eu`)
- [ ] **Target-definition diff study**: pull 1 month of ENTSO-E hourly FF and production consolidated 15-min. Assert `mean |diff| < 0.5`, `p95 |diff| < 2.0` EUR/MWh. Go/no-go.
- [ ] **Weather-noise calibration study**: benchmark `*_wind_forecast.json`, `*_solar_forecast.json` on sadalsuud vs Open-Meteo archive for same dates. Report σ per horizon.
- [ ] **yfinance TTF spot-check**: compare against EEX settlement (or another reference) on 10 dates across 2020-2025.
- [ ] **Create separate `.env.long-history`** on sadalsuud (gitignored). Do **not** touch production `.env`.
- [ ] **`pip install --dry-run`** on sadalsuud with candidate pinned versions; confirm no pandas/numpy churn.
- [ ] **Add to ADR-005 out-of-scope** (already in): `online_features.py` and `consolidate.py` are read-only on this branch.
- [ ] **`.gitattributes`** entry forcing LF for text files.
- [ ] **Disk check** on sadalsuud: confirm ≥5 GB free before any warmup.
- [ ] **User sign-off on ADR-005** architectural decisions (start date, resolution, execution env).

Ten steps, probably a day of work. Each one either retires or substantially reduces a row above.

## Decision points from this FMEA

Three calls that belong to the user, not the agent:

1. **Proceed past pre-flight** — after the checklist, do we start Phase A? Or does the weather-noise benchmark or target-drift study turn up something that changes the plan?
2. **Residual risk tolerance** — Weather leakage at RPN 180 is the highest residual. Accept and rely on shadow mode, or invest in a harder mitigation (e.g., refuse to use Tier-1 weather and backfill with persistence-model forecasts)?
3. **Unknown-unknowns reserve** — willing to budget an extra 20% of engineering time as "things I haven't foreseen surfacing"? Or target the timeline strictly and cut scope if new risks emerge?
