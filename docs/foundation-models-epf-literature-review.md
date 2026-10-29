# Foundation models for EPF — Lipiecki & Weron (2026)

**Purpose**: Ingest of arXiv:2609.00089 (v1, 31 Aug 2026; read in full from the
HTML version on 2026-10-29). It is the first long-test-period comparison of
zero-shot foundation models (FMs) against strong EPF-specific benchmarks that
also scores economic value, and it bears on three open threads here: the
EXP-028a covariate question, the 2026-10-28 product criterion (regret, not
MAE), and the foundation-model candidate queue (EXP-021a). Output: backlog
entry EXP-040, a note on EXP-028a and the product criterion in
`docs/hypothesis-log.md`, and the index lines in `docs/literature.md`.

**One-line verdict**: the strongest evidence yet that a *tabular*,
synthetic-pretrained FM fed known-future covariates beats both the time-series
FMs and the best EPF benchmarks on day-ahead accuracy. It says nothing about
horizons beyond 24h, which is where Augur's product question sits.

---

## 1. What they did

- **Markets**: DE-LU, PL, ES day-ahead, hourly. Data 2017-01-06..2025-12-31,
  **test 2021-01-01..2025-12-31 (1,826 days)**. NL is not in it; DE is the
  closest market to ours.
- **Horizon**: day-ahead only. One forecast = the 24 prices of day *d*.
- **Covariates**: ENTSO-E day-ahead load forecast and renewable forecast
  (onshore + offshore wind + solar, summed), plus EUA, TTF, Brent and API2
  futures at lag 2 days.
- **Nine FM variants, all zero-shot** (Table 1):

  | Model | Released | Type | Size | Pretraining | Paper's † (not free for commercial use) |
  |---|---|---|---|---|---|
  | Chronos-2 / -synth / -small | Oct–Nov 2025 | TS, multivariate | 120M / 120M / 28M | mixed / **synthetic** / mixed | — |
  | Moirai-2 | Aug 2025 | TS, no covariates | 11M | mixed | **†** |
  | TimesFM-2.5 | Sep 2025 | TS, covariates via linear XReg on residuals | 200M | mixed | — |
  | TabPFN-2 | Jan 2025 | tabular | 11M | **synthetic** | — |
  | TabPFN-3 | May 2026 | tabular | 58M | **synthetic** | **†** |
  | TabPFN-TS-3 | May 2026 | TS feature pipeline → TabPFN-3 TS checkpoint | 58M | **synthetic** | **†** |
  | Mitra (+ conformal) | Jul 2025 | tabular, point only | 72M | synthetic | — |

- **Benchmarks**: LEAR+CP (Lasso, windows 56/84/728/1,092 days averaged,
  asinh transform, one-year conformal calibration) and DDNN-JSU (2-layer MLP
  emitting Johnson's SU parameters, four Optuna-tuned nets, median-combined).
  Both are serious benchmarks, not strawmen.
- **Tabular input recipe (Eq. 5)**, used by TabPFN-2/3, Mitra, LEAR and DDNN:
  the 24-hour price vectors at lags 1, 2, 3, 7 days; load and RES forecast
  vectors at lags 0, 1, 7; day of week (categorical for the FMs); market
  variables at lag 2. **Context: the most recent 1,449 days** (~4 years).
- **TabPFN-TS-3 / TimesFM**: one univariate task per hour, with the other 23
  hours of *d−1* as extra covariates.
- **Scoring**: MAE and RMSE of the median, CRPS (dense quantile grid), and a
  multivariate Giacomini-White CPA test on daily losses, one-sided vs each
  benchmark.
- **Economic test**: 1 MWh battery, η = 0.95 each way, €25 per round trip, one
  buy hour and one later sell hour per day chosen to maximise predicted profit.
  *UB*: market orders whenever predicted profit > 0. *QB*: a loop bid with
  limits at the quantiles implied by α ∈ {90..50%}. **Higher α means wider
  limits, more fills, more risk.** Oracle = perfect foresight.

## 2. What they found

**Accuracy (CRPS; lower is better):**

| | Chronos-2 | Chronos-2-synth | TabPFN-2 | TabPFN-3 | TabPFN-TS-3 | LEAR+CP | DDNN-JSU |
|---|---|---|---|---|---|---|---|
| DE | 11.80 | 11.53 | 9.55 | **9.15** | 9.33 | 12.23 | 10.70 |
| PL | 10.74 | 10.62 | 9.90 | **9.61** | 9.64 | 11.44 | 10.96 |
| ES | 9.46 | 9.66 | 8.29 | **8.15** | 8.35 | 10.06 | 9.30 |

1. **Only the TabPFN family beats the benchmarks everywhere.** All three
   variants beat DDNN-JSU at the 1% level on MAE, RMSE and CRPS in all three
   markets. CRPS gains differ by variant. TabPFN-3 is 12–15% better than
   DDNN-JSU and **10–22% better than Chronos-2**. TabPFN-2 is 10–11% and 8–19%
   better; TabPFN-TS-3 is 10–13% better than DDNN-JSU.
2. **TabPFN-2 is nearly as good as TabPFN-3**, within 1.7–4.4% CRPS and best on
   MAE/RMSE in Spain, at a fifth of the size.
3. **Synthetic-only pretraining costs nothing measurable.** Chronos-2-synth
   matches Chronos-2 (better in DE and PL, 2% worse in ES).
4. Time-series FMs are inconsistent. Chronos-2 beats DDNN-JSU only in PL, and
   Moirai-2 and TimesFM-2.5 never do.

**Economics (total profit over 5 years):**

5. **The accuracy ranking doesn't carry into profit.** TabPFN variants win UB
   and the riskier QB settings (α 90–70% in DE and PL, 90% only in ES).
   **DDNN-JSU wins the risk-averse settings** (α 60–50% everywhere, 80–70% in
   ES), despite never having the best statistical score. TabPFN-TS-3 out-earns
   TabPFN-3 in every QB setting, though TabPFN-3 has the better CRPS.
6. **Most gaps are small, but not in Spain.** In DE at α 60%, DDNN-JSU leads
   TabPFN-TS-3 by 1.0%, and the UB leaders differ by under 1%. In ES at
   α 70–50%, DDNN-JSU earns 3.9–10.8% more than the best TabPFN. At α 50% it
   earns 18% more than TabPFN-3, the CRPS winner (46,714 vs 39,610). The authors themselves
   warn against reading the order of close models.
7. Best UB captures 92.5% (DE), 86.4% (PL) and 83.3% (ES) of Oracle profit.
8. QB trades less often but earns more per trade, because the limits avoid
   large losses. A tighter-limit strategy depends on how good the *tails* are,
   which is plausibly why the well-calibrated parametric DDNN wins there
   (our reading; the paper doesn't test it).
9. **The authors' own caveat: trading profit is not a proper scoring
   function.** It is an application score, not a replacement for CRPS.

## 3. What transfers to Augur, and what doesn't

**Transfers:**

- **Contamination is solved by construction for synthetic-pretrained models.**
  This is the most actionable point. EXP-028a's main threat (Alternative 1) is
  that Chronos-2's weights postdate the window and may have seen NL prices,
  which is why EXP-028 could only score `t0 > 2026-06-05` (77 vintages).
  **Chronos-2-synth has the same API, comparable accuracy and synthetic-only
  pretraining**, so it could re-run EXP-028's covariate arm on the full
  260-vintage window. A contamination-free covariate gain there would answer
  Alternative 1 directly. TabPFN-2/3 are synthetic-only too. Chronos-Bolt (our
  current candidate) was frozen 2025-11-21 and was already contamination-free
  by date.
- **Covariates need a model that is built to use them.** Their pattern matches
  ours: LightGBM gets nothing from exogenous data (EXP-018, EXP-020), Chronos-2 does
  (EXP-028), and in the paper the univariate or bolt-on models (Moirai-2,
  TimesFM-XReg) are the weakest. Marchesi et al. 2025, in their review, found
  limited covariate gains for Moirai.
- **Keep a proper score next to the decision metric.** The 2026-10-28
  criterion adds k6 regret as a *swap* condition on top of ADR-007's skill
  gate rather than replacing it. The paper supports exactly that pairing:
  regret, like trading profit, is not a proper score and can reward a
  forecaster that isn't honest about its distribution.
- **Simple floors are hard to beat, and on NL specifically.** In their review,
  Hornek et al. 2025 benchmark six time-series FMs, including Chronos-Bolt, on
  five markets *including NL* (test year 2024). None beats MSTL significantly.
  That is the published counterpart of augur#29 and EXP-036.

**Doesn't transfer:**

- **Horizon.** Day-ahead only. Augur's open risk is h25–72 (amplitude
  collapse, EXP-037; the Chronos tie with the profile floor at h49–72,
  EXP-038). The paper is silent there.
- **History length.** They give TabPFN 1,449 days of context. Augur's
  price history starts **2025-09-28** (the 2026-10-28 snapshot,
  `~/lab/augur/data/training_history_2026-10-28.parquet`, is ~13 months), and
  the covariates start later still: load, wind and solar forecasts only from
  2025-11-30..2025-12-02 (`training_history_fundamentals.parquet`). TabPFN is
  designed for small data, but the paper's numbers are for ~4× more context
  than we can supply today, and less again for the covariate rows.
- **The decision.** One battery round trip per day, buying low and selling
  high, which depends on both ends of the daily range. Augur's k-cheapest-hours
  load shift depends only on the bottom of the ranking. The two are related,
  not interchangeable.
- **Licensing.** TabPFN-3 and TabPFN-TS-3 aren't licensed for free commercial
  use. TabPFN-2 isn't marked restricted in the paper; check its actual license
  before it goes anywhere near production.
- **Code.** No code release is mentioned.

**On terminology**: they note that EPF papers often call the mean pinball over
99 percentiles "CRPS", which is **half** the real CRPS. `ml/shadow/metrics.py`
already calls our 3-quantile mean a quantile score, not a CRPS. Never compare
our QS magnitudes with their CRPS numbers.

## 4. Implications, ranked

1. **EXP-028a review (due 2026-10-31)**: name Chronos-2-synth as the
   contamination-free re-run of the covariate arm across all 260 vintages, and
   TabPFN as the second covariate challenger. Both are outside the frozen
   Method, so both need new entries.
2. **EXP-040 (backlog)**: TabPFN-2 (shippable if its license allows) and
   TabPFN-3 (research arm) with covariates, on stored vintages, scored per
   horizon block against the profile floor. The open question it answers is
   whether a tabular in-context model keeps diurnal amplitude beyond 24h.
3. **Calibration matters most for decisions that act on the tails** (finding
   8). If the dashboard ever uses p10/p90 for risk-aware scheduling rather
   than ranking on p50, augur#19 becomes a product issue rather than a
   statistics one. That's speculative; no entry for now.

## 5. Related work from its review, worth a look later

- Hornek, Sartipi, Tchappi & Fridgen (2025), EEM. Six time-series FMs
  including Chronos-Bolt; AT/BE/FR/DE/**NL**, 2024; none beats MSTL.
- Marchesi, Ballarino & Brusaferri (2025), *Energies* 18:6269. Moirai
  zero-shot vs fine-tuned, probabilistic; exogenous gains limited.
- Lettner, El Ashhab, Hagenmeyer & Schäfer (2026), arXiv:2604.14739.
  Moirai/ChronosX vs NHITS+QRA on DE 2024; the FM gains are modest relative to
  compute.
- Hirsch & Ziel (2026), arXiv:2604.19580. Battery trading strategies and the
  economic evaluation of probabilistic EPF; the reference for the QB/UB
  design.
- Yu et al. (2026), arXiv:2508.04875. PriceFM, an EPF-specific FM over 38
  European bidding zones, with covariates. Trained through 2024, so it
  needs a contamination check against our window.
- Lipiecki, Bilińska, Kourentzes & Weron (2026), *IJF*. THieF: reconciling
  hourly, block and baseload forecasts improves accuracy. Possibly relevant to
  block-level decisions.
- Qiu et al. (2026), arXiv:2603.06726. FutureBoosting: an FM forecasts
  covariates that a regression model then consumes.

## References

- Lipiecki, A. & Weron, R. (2026). "Foundation models for electricity price
  forecasting and battery arbitrage: Can they replace market-specific
  forecasting models?" arXiv:2609.00089. CC BY 4.0.
- Grinsztajn, L. et al. (2026). "TabPFN-3: technical report."
  arXiv:2605.13986.
- Hollmann, N. et al. (2025). "Accurate predictions on small data with a
  tabular foundation model." *Nature* 637: 319–326. (TabPFN-2)
- Hoo, S. B., Müller, S., Salinas, D. & Hutter, F. (2026). "From tables to
  time: extending TabPFN-v2 to time series forecasting." arXiv:2501.02945.
- Ansari, A. F. et al. (2025). "Chronos-2: from univariate to universal
  forecasting." arXiv:2510.15821.
