# ADR-006: LightGBM-Quantile production forecasting architecture

**Status**: Accepted
**Date**: 2026-05-29
**Context**: After ARF's retirement (ADR-004 superseded) and a five-iteration metric-redesign arc culminating in EXP-014, formalising the production price-prediction architecture.

## Decision

Use **multi-horizon LightGBM-Quantile** (9 LGBMRegressor instances, 3 horizon groups × 3 quantiles) with **split-conformal calibration (CQR)** as the production day-ahead electricity-price forecasting model for Augur. The model is retrained nightly from scratch on a rolling 56-day window. Consumer pricing is derived from wholesale via a VAT + surcharge transform, where the surcharge is cached daily by the ARF backup pipeline.

This decision supersedes ADR-004 (River ARF online learning). ARF cron continues running as a backup signal, but the dashboard's price charts are driven by LightGBM-Quantile from 2026-05-29 forward.

## Architecture summary

- **Target**: ENTSO-E NL wholesale day-ahead price (EUR/MWh), hourly resolution, h+1..h+72 horizon.
- **Training**: rolling 56-day window from `ml/data/training_history.parquet`, regenerated each night by `ml.data.consolidate`. Trained from scratch — no warm-starting, no online learning.
- **Features** (24 total, `ml/shadow/features_pandas.py`): 8 price lags (1-168h), 3 rolling means + 3 rolling stds (6h/24h/168h), 7 calendar features (hour/dow/month sin/cos + is_weekend), 3 exogenous (wind_speed_80m / solar_ghi / load_forecast), and the prediction horizon `h` itself as a feature for multi-horizon stacking.
- **Model** (`ml/shadow/lightgbm_quantile.py`): three horizon groups (h+1..h+6 / h+7..h+24 / h+25..h+72), each backed by three LGBMRegressor instances at quantiles p10/p50/p90. Within each group the model is fit on training data stacked across the group's horizon range with `h` as an additional feature — direct multi-horizon forecasting, no iterated lag substitution. Total: 9 models.
- **Hyperparameters**: `n_estimators=300, learning_rate=0.05, num_leaves=31, min_child_samples=20`.
- **Calibration** (`ml/shadow/conformal.py`): split-conformal quantile regression (Romano, Patterson & Candès 2019). Trailing 7-day calibration window, target 0.80 coverage. Per-day `q` adjusts band width; production stores both sorted-CQR-widened `p10/p50/p90` and raw model outputs `p10_raw/p50_raw/p90_raw` so pinball scoring can use true tau-quantile values.
- **Consumer pricing** (`ml/shadow/update_shadow.py:read_arf_surcharge`): `consumer = wholesale × VAT_RATE (1.21) + surcharge`, where `surcharge` is read from ARF's cached `state.json:consumer_surcharge.value_eur_mwh` (derived nightly by ARF from Energy Zero × ENTSO-E overlap). Falls back to `DEFAULT_SURCHARGE_EUR_MWH = 95.0` if ARF state absent. Consumer lower band floored at 0.
- **Daily cycle** (`scripts/daily_update.sh`, cron 16:45 CEST on sadalsuud): pull energyDataHub + Augur, run ARF (backup), regenerate parquet, retrain LightGBM, predict 72h, CQR-widen, write `static/data/augur_forecast_shadow.json`, evaluate vs ARF, commit + push, Netlify rebuilds dashboard.

## Rationale

- **Negative-price expressiveness.** LightGBM-Quantile can place probability mass below zero, addressing the structural limitation that retired ARF (trees cannot extrapolate to negative prices because no training leaf contains them). Pinball-at-p10 confirms LightGBM's p10 reaches the negative tail when realised prices crash; ARF's lower band, computed as `point − 1.282 · EWM_std`, cannot.
- **Calibrated probabilistic output.** Three native quantiles + CQR correction give a proper 80% predictive interval, not a Gaussian-assumption parametric band. Coverage is bounded by construction within the CQR exchangeability assumption.
- **Statistically dominant on the M4 paired data.** Diebold-Mariano paired test on `|y − p50|` vs ARF's `|y − point|` over 546 paired hourly observations (HAC bandwidth 71): mean diff −9.48 EUR/MWh, one-sided p = 0.029. LightGBM 25% more accurate on MAE. Particularly strong at peak hours (LGBM/ARF ratio 0.45) and short horizons (h≤24 MAE 6.4 vs ARF 19.1).
- **Calibration not worse than the incumbent.** Lower-side coverage 0.811 vs ARF 0.824 (within 0.02 tolerance); upper-side coverage 0.870 vs ARF 0.621 (LightGBM 0.25 *better* — ARF's upper band severely under-covered).
- **Nightly-from-scratch training is fast enough.** A full retrain of 9 LGBMRegressor on ~56 × 24 = ~1300 rows takes seconds. No warmup, no incremental state to maintain, no concept-drift bookkeeping. The 56-day window is short enough to adapt to regime shifts and long enough to capture weekly seasonality.
- **The promotion criterion that admitted this model is itself defensible.** See ADR-007.

## Consequences

- **ARF retained as backup signal, not retired infrastructure.** ARF cron continues producing `augur_forecast.json` (read by `model-viz.js` for Model-tab metrics) and `ml/models/state.json` (cached surcharge consumed by LightGBM's consumer-pricing step). Without ARF running, LightGBM falls back to default surcharge and the Model tab shows stale metrics.
- **Model-tab metrics still come from ARF.** LightGBM's metadata schema (cqr_q, n_train_samples, horizon_groups) differs from ARF's (metrics_history, error_history, n_training_samples). Until `update_shadow.py` is extended to emit ARF-equivalent fields and `model-viz.js` updated, the Model tab continues to display ARF's training history and MAE-over-time charts. The user-visible price forecast comes from LightGBM regardless.
- **Lower-side coverage 0.81 is below the 0.90 nominal target.** Inherited from the ARF era; the swap does not worsen it. Next experiment: horizon-conditioned CQR (separate calibration windows per horizon group) or adaptive conformal inference (Gibbs & Candès 2021) to restore the nominal target.
- **Long-horizon (h>48) skill is weaker than ARF's.** LightGBM's features thin out at long horizons; ARF's mean-reverting prior accidentally wins pinball-at-p10 on those hours. Accepted limitation — the dashboard prioritises near-term decisions.
- **Freshness skew is unfixed.** The daily cron runs at 16:45 CEST before energyDataHub's exogenous collector, so the training parquet sees 24h-stale wind/solar/load forecasts. Live overall MAE is 84% above the backtest h+1 figure. Tracked as augur#12 (cron → systemd with `After=edh.service` dependency).
- **Calibration_history schema extended.** `pending_predictions` and `calibration_history` now include both sorted (`p10/p50/p90`) and raw (`p10_raw/p50_raw/p90_raw`) quantile values. Past calibration_history entries written before 2026-05-29 lack the `_raw` fields; pinball scoring on historical data is biased (the sorted "p10" is `min(q0.10, q0.50, q0.90)`).
- **One-line revert.** `static/js/dashboard.js:loadAugurForecast` is the swap point. Changing the fetched path from `augur_forecast_shadow.json` back to `augur_forecast.json` reverts to ARF without any other rollback. ARF cron and artefacts remain intact.

## Alternatives considered

- **Keep River ARF as production.** Rejected per ARF retirement reasoning in `docs/river-arf-retrospective.md`: structural inability to extrapolate to negative prices is a hard ceiling no parameter tuning lifts. Empirically dominated by LightGBM-Quantile on every relevant metric (overall MAE, peak-hour MAE, pinball-at-p10 with vintage-corrected pairing, Winkler interval score, upper-side coverage).
- **Hybrid LightGBM (h≤48) + ARF (h>48).** Per-horizon decomposition shows ARF wins on long-horizon pinball-at-p10. A horizon-conditioned hybrid would extract that value. Rejected for v1 because it adds significant complexity (two model serialisations, two prediction calls, merge logic in the forecast file writer) for marginal gain in a regime the dashboard de-emphasises. Reconsider if long-horizon use cases emerge.
- **Single-horizon LightGBM with iterated lag substitution.** Tested in EXP-009 backtest (MAE 13.21 at h+1, perfect-lag). Rejected for production because variance collapses at long horizons (predictions are fed back as lag inputs, compounding errors).
- **Wider quantile grid (9 or 19 quantiles).** Would enable canonical CRPS scoring and more honest probabilistic comparisons. Rejected for v1 because 3 quantiles suffice for the production interval (p10/p90 band + p50 point) and the additional models are pure overhead at predict time. Queued as a follow-up experiment (canonical twCRPS and CRPS estimation need a denser grid).
- **Adaptive Conformal Inference (ACI) instead of static CQR.** Would address the lower-side coverage shortfall. Deferred because CQR with horizon-conditioned calibration is a smaller incremental change and should be tried first.

## Performance evidence

Quoted from EXP-014 (`experiments/registry.jsonl`), evaluated on the M4 trailing-14 paired window (2026-05-14 → 2026-05-27, 546 paired hourly observations, vintage-corrected ARF archive join):

| Metric | LightGBM | ARF | Delta |
|---|---|---|---|
| MAE (paired) | 28.94 | 38.42 | −24.7% |
| DM stat (HAC lag 71) | −1.903 | — | one-sided p = 0.029 |
| Lower-side coverage (target 0.90) | 0.811 | 0.824 | −0.013 |
| Upper-side coverage (target 0.90) | 0.870 | 0.621 | +0.249 |
| Peak-hour MAE ratio (LGBM/ARF) | 0.45 | — | (from M4 verdict) |
| h≤24 MAE | 6.36 | 19.14 | −66.8% |
| 24<h≤48 MAE | 24.78 | 39.57 | −37.4% |
| 48<h≤72 MAE | 42.59 | 40.90 | +4.1% |

Notes on the comparison:
- ARF's lower band is treated as a Gaussian-residual p10 surrogate (`point − 1.282 · EWM_std`); not a clean quantile prediction.
- LightGBM's `p10` is the sorted minimum of the three independent quantile regressions for that row, not the raw tau=0.10 output (forward fix in place via `p10_raw` field; past data biased).
- Both models share a lower-side coverage shortfall vs the 0.90 nominal target; the swap does not worsen it.

## References

- Replaces / supersedes: ADR-004 (River Online Learning Architecture)
- Promotion process: ADR-007 (Model promotion method)
- Implementation: `ml/shadow/lightgbm_quantile.py`, `ml/shadow/conformal.py`, `ml/shadow/update_shadow.py`, `ml/shadow/features_pandas.py`
- Daily cron: `scripts/daily_update.sh`
- Promotion record: `experiments/registry.jsonl` EXP-014, `docs/hypothesis-log.md` iteration-5 entry
- Narrative: `docs/articles/m4-metric-redesign-story.md` (five-iteration arc from M4 park to EXP-014 promotion)
- Retirement context: `docs/river-arf-retrospective.md` (closing addendum)
- Literature: `docs/literature.md`, `docs/metric-redesign-literature-review.md`
- Key papers: Romano, Patterson & Candès (2019) — CQR; Gneiting & Raftery (2007) — proper scoring rules; Lago, Marcjasz, De Schutter & Weron (2021) — EPF best practice.
