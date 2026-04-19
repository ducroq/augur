# Long-History Mini-Warmup — Results

**Branch**: `feat/long-history-warmup`
**Date**: 2026-04-19
**Scope**: 1-day check (per ADR-005 and implementation plan §16)
**Purpose**: decide whether to scale to full 6-year warmup or stop

## What was run

Two warmup variants, identical except for calibrated weather noise:

| Variant | Weather handling |
|---|---|
| **Noisy** (production candidate) | ERA5 actuals + calibrated noise: wind σ=1.8 m/s, solar σ=30 W/m² (GHI-gated) |
| **Clean** (leakage-probe ceiling) | ERA5 actuals as-is (perfect-knowledge weather) |

Both trained on **2025-01-01 → 2025-09-30** (9 months, 26,018 samples after skip, hourly era forward-filled to 15-min), backtested on **2025-10-01 → 2025-10-31** (2,786 samples, predict+learn).

End-to-end wall time: ~3 minutes per variant on sadalsuud. Plumbing verified across consolidation, warmup, backtest.

## Metrics

| | Training MAE | Training last-168 MAE | Backtest MAE | Backtest MAPE | RMSE | Spike recall @30% |
|---|---|---|---|---|---|---|
| **Noisy** | 14.98 | 20.65 | **16.36** | 94.1% | 28.16 | 39.6% |
| **Clean** | 16.40 | 21.24 | **18.06** | 143.2% | 29.67 | 38.3% |

Both on October 2025 held-out. `spike_n`=154 samples with actual price > 150 EUR/MWh.

Production (v1) reference from same git repo, state.json dated 2026-04-18:
- `update_mae` (most recent day): 11.89
- `last_week_mae`: 11.3
- `mae` (rolling 500): 14.13
- `mae_vs_exchange`: 17.59

## Unexpected finding — noise improves, not degrades

The leakage-probe assumption was: clean (perfect knowledge) should beat noisy on backtest, and the gap quantifies how much we'd lose in production deployment.

Observed: **noisy wins on both training and backtest** (16.36 vs 18.06 MAE backtest).

Plausible explanations:
- **Regularization**: calibrated noise prevents River ARF from overfitting to weather features; trees become more price-lag-dominated, which is apparently the right inductive bias for NL day-ahead price prediction.
- **Feature importance mismatch**: per `memory/ml-decisions.md`, the Lasso analysis dropped temperature as signal-free. If wind/solar are similarly weak signals, reducing their precision doesn't hurt.
- **ERA5-as-forecast isn't meaningful leakage**: the "perfect knowledge" in clean weather may not translate into predictive advantage because the model doesn't lean on weather much to begin with.

Implication: **weather-leakage risk (FMEA row 1, residual RPN 180) is probably overstated**. Shadow mode is still the final arbiter, but the concern that v2 will deploy and silently underperform due to weather leakage is weaker than feared.

## Interpretation against project premise

The guiding question was: **does 9+ months of historical training beat the current short-history model?**

The numbers do **not** cleanly answer yes:

- v2-mini backtest MAE 16.36 on October 2025
- v1 production MAE recently ranges 11-17 (period-dependent)
- Spike recall 40% is plausible but we have no v1 baseline to compare

The comparison is **not apples-to-apples**:
- v2-mini is tested on October 2025, a period with wider price swings (-8 to +438 EUR/MWh)
- v1 is measured on April 2026, a different regime
- Neither model has been tested on the other's data

In absolute terms, v2-mini is **in the ballpark** of v1 — not clearly better, not clearly worse.

## The 1-day check delivered its stated purpose

The point of the mini was to avoid committing to 3 weeks for an uncertain payoff. It did:

- ✓ Plumbing works end-to-end (consolidation → parquet → warmup → backtest)
- ✓ Scale is trivial (3 minutes per variant, ~1.7 MB model artifact)
- ✓ Leakage concern can be downgraded (noise helps rather than hurts)
- ✗ **No evidence that more history dominates short-history training**

The third bullet was the main risk. The first two are de-risking gains that carry forward regardless of what we decide.

## Decision paths

Three honest options:

### A. Stop here, pocket the de-risking, revisit later

No cutover. v1 continues running. Code stays on the branch; when we next want to test history or add features, this plumbing accelerates it. Cheapest path if the project premise turns out wrong.

### B. One more comparison before committing (~½ day)

Run a fairer A/B: extend v2-mini training through 2026-02-28, backtest both v2-mini and v1 on March-April 2026 (needs rolling v1 back to a pre-March state from git, or comparing v2-mini-extended to v1-current on separate held-outs). Gives a direct "more history vs less history" answer on recent data.

### C. Commit to Phase A (3-week full warmup) despite ambiguous signal

Not recommended. The data doesn't support this level of investment yet.

## Recommendation

**Option A or B.** Both respect the 1-day scope.

- If you want a cleaner answer: do **B** (half-day extension of this same session or next).
- If you want to defer: do **A** and revisit when either (i) live MAE degrades seasonally or (ii) a new feature like TTF gas becomes critical to add — the historical pull is then ready.

Option C — committing to full Phase A — is not supported by the numbers.

## Artifacts produced

Committed to `feat/long-history-warmup` at `e65b4ff`:
- `ml/data/consolidate_historical.py`
- `ml/training/warmup_mini.py`
- `ml/evaluation/backtest.py`

Local artifacts (gitignored, ~5 MB total):
- `ml/data/mini_warmup{,_clean}.parquet` (~880 KB each)
- `ml/data/mini_holdout{,_clean}.parquet` (~100 KB each)

On sadalsuud:
- `/home/jeroen/local_dev/augur/ml/models/river_v2_mini/` (noisy)
- `/home/jeroen/local_dev/augur/ml/models/river_v2_mini_clean/` (clean)

Neither touches production paths.
