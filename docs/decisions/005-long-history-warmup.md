# ADR-005: Long-History Warmup

**Status**: Draft
**Date**: 2026-04-19
**Context**: The live River ARF model has seen ~64 days of training data and has never encountered winter demand, summer solar saturation, Christmas/New Year, Easter, or the 2022 gas crisis. Forecast accuracy (`mae_vs_exchange` ~17 EUR/MWh) is ~2× academic benchmarks. Before investing in ensembles (augur#9) or new features, give the model multi-year seasonal coverage.

Informed by `docs/long-history-feasibility.md`. Implementation mechanics are in `docs/long-history-implementation-plan.md` — this ADR covers only architectural decisions.

## Decision

Build a **single-tier historical warmup** that replays multi-year data chronologically through the existing River ARF model using the **current feature set unchanged**. The warmup artifact is a parallel model at `ml/models/river_v2/` that runs in shadow mode alongside the live model before cutover.

### Architectural choices

| Decision | Choice | Rationale |
|---|---|---|
| Tiering | Single-tier | Feature audit showed Augur's inputs don't change at the 2025-11-04 googleweather boundary. |
| Historical depth | **2020-01-01 onward (~6 years)** | Covers COVID demand shock, 2022 gas crisis, 2023-24 negative-price regime. Skips 2015-2019 low-volatility pre-renewable era that may bias toward a regime that no longer exists. |
| Temporal resolution | **15-minute** (match production) | Production trains on 15-min samples; warmup must match. Hourly ENTSO-E prices are forward-filled to 15-min. |
| Model initialization | **Fresh River ARF** | No state contamination from the current short-history model. Cleanest reset. |
| Feature set | **Unchanged from production** | `OnlineFeatureBuilder` is authoritative per ADR-004. Adding features is out of scope. |
| Rollout | **Shadow mode before cutover** | v2 runs in parallel with v1 for a measurement period; dashboard unaffected until cutover. |

### Data sources

| Source | Use | Auth |
|---|---|---|
| ENTSO-E Transparency | day-ahead prices (target), actual load, load forecast, day-ahead wind+solar generation forecast | api_key |
| Open-Meteo archive (ERA5) | `wind_speed_100m` offshore, `shortwave_radiation` Eindhoven | none |
| yfinance `TTF=F` | TTF gas daily close, forward-filled | none |
| `holidays` library | NL calendar features | none |

### Evaluation gate (hard)

Cutover from shadow to live only if, on a held-out slice:

1. `mae_vs_exchange` improves by **≥2 EUR/MWh** vs current baseline (~17).
2. Spike recall (predicted within 30% on actual >150 EUR/MWh hours) does **not regress**.
3. No horizon segment (1-6h / 6-24h / 24-48h / 48-72h) regresses by more than **20%** in MAE.

Fail any of these and v2 stays in shadow mode for iteration.

## Rationale

- **Single-tier is justified by the feature audit.** The original two-tier hypothesis assumed a feature-set change at 2025-11-04 that doesn't exist. See `long-history-feasibility.md` "Surprise finding."
- **2020-01-01 start** chosen for regime relevance, not length. The model that runs in 2026 needs to know what 2022 and 2023-24 looked like — it does not need to know 2015-2017 when wind capacity was half of today's.
- **15-minute resolution** preserved to avoid temporal-resolution drift at handoff. Hourly ENTSO-E prices forward-fill to 15-min (persistence within the hour) — this is a documented bias, not an architectural risk.
- **Fresh model** isolates the experiment. Bootstrapping from current pickle mixes warmup-era learning with short-history state in ways that would make comparison ambiguous.
- **Shadow mode before cutover** preserves reversibility. v1 remains the production model through the evaluation period; v2 is a read-only computation against the same live data.

## Consequences

- Production cron is unaffected throughout development.
- `feat/long-history-warmup` must rebase against `main` at least weekly (daily cron commits to main).
- Exchange-anchor mechanism (production forecast uses real exchange prices as lag features for first 24-72h) is **not exercised during warmup** — warmup sees only real-price lags via `learn_one`. The recursive prediction regime only matters at forecast time, so this is not a training gap.
- Weather data from Open-Meteo archive is **actuals**, not as-of-date forecasts. During warmup, calibrated noise is injected into wind/solar features to approximate realistic forecast error. Noise budget is parameterized and benchmarked against the pipeline's own archived forecast-vs-actual history before warmup runs.
- Consumer forecast (derived from wholesale via surcharge) is unchanged. No consumer-model warmup needed.
- EUA carbon price is **not** included (no free yfinance ticker; EEX/Sandbag scraping deferred). Revisit if backtests show 2022-2023 weakness.
- **Feature importance re-evaluation**: before cutover, re-run Lasso on the 6-year history using the current feature set. If the dropped-temperature decision (from `memory/ml-decisions.md`) flips, that's a separate ADR; the v2 model still uses the frozen production feature set for gate evaluation.

## Out of scope

- Ensemble / multi-model forecasting (augur#9)
- New features (TTF weight tuning, cross-border flows, gas storage) — deferred until v2 cutover is evaluated
- EUA carbon ingestion
- Multi-country expansion (augur#10)
- Production feature-builder changes
- Forecast-horizon changes
- Dashboard changes

## Alternatives Considered

- **Two-tier with 2025-11-04 boundary** — rejected after feature audit.
- **Keep short history, add explicit seasonal features** — can't cover regimes the model has never seen. Complementary, not a replacement.
- **Retrain from scratch with XGBoost / LightGBM** — model-choice question, separate from history-depth question. Tracked as augur#9.
- **Start from Jan 2015 (full ENTSO-E history)** — includes regime the current market no longer resembles; risk of biasing toward obsolete patterns.
- **Bootstrap warmup from current river_model.pkl** — rejected for experimental cleanliness.
