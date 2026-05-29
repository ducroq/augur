# Literature index

Topic-indexed bibliography for Augur. Update when a research pass produces
citations that future work will likely revisit. Keep entries terse — one
line per source with author + year + topic. Deep-dive reviews go in their
own file under `docs/` and are linked here.

## How to use

- **Before starting a literature-driven task**, check this file first; an
  existing deep-dive may already cover the question.
- **After a research pass**, add any new key citations and link the deep-
  dive file if one was written.
- Don't paste the deep-dive content here — keep this an index. The point
  is fast lookup, not narrative.

---

## Topic deep-dives

- [Metric redesign for probabilistic EPF with negative prices](metric-redesign-literature-review.md) (2026-05-29)
  — input to EXP-012; covers CRPS/pinball/twCRPS, Diebold-Mariano,
    forecaster's dilemma, what to drop from M4 criterion (a).

---

## Citations by topic

### Probabilistic electricity-price forecasting (EPF)

- Nowotarski & Weron (2018). "Recent advances in electricity price
  forecasting: A review of probabilistic forecasting." *Renewable and
  Sustainable Energy Reviews* 81: 1548-1568. — canonical EPF probabilistic-
  review reference.
- Lago, Marcjasz, De Schutter & Weron (2021). "Forecasting day-ahead
  electricity prices: A review of state-of-the-art algorithms, best
  practices and an open-access benchmark." *Applied Energy* 293: 116983. —
  modern best-practice paper; introduces the `epftoolbox` reference impl.
- Maciejowska, Uniejewski, Weron (2022). "Forecasting Electricity Prices."
  arXiv:2204.11735. — review with focus on negative-price regimes.
- Marcjasz, Narajewski, Weron & Ziel (2023). "Distributional neural networks
  for electricity price forecasting." arXiv:2207.02832. — DDNN for EPF,
  evaluation methodology for negative-price markets.
- Uniejewski & Weron (2021). "Regularized quantile regression averaging."
  *Energy Economics*. — LQRA; quantile averaging for EPF.

### Proper scoring rules and metric theory

- Gneiting & Raftery (2007). "Strictly proper scoring rules, prediction,
  and estimation." *JASA* 102: 359-378. — CRPS, interval score, the
  CRPS=MAE degeneracy for point forecasts (§4.2, §6.2).
- Gneiting & Ranjan (2011). "Comparing density forecasts using threshold-
  and quantile-weighted scoring rules." *JBES* 29: 411-422. — twCRPS;
  the canonical tool for slice-evaluation without forecaster's-dilemma trap.
- Gneiting (2011). "Making and evaluating point forecasts." *JASA* 106:
  746-762. — pinball as the elicitable scoring rule for individual
  quantiles.
- Lerch, Thorarinsdottir, Ravazzolo & Gneiting (2017). "Forecaster's
  dilemma: Extreme events and forecast evaluation." *Statistical Science*
  32: 106-127. — the trap that bit M4 criterion (a); why
  conditional-on-extreme-y scoring is not proper.

### Statistical significance for forecast comparison

- Diebold & Mariano (1995). "Comparing predictive accuracy." *JBES* 13:
  253-263. — paired loss-difference test; the field default.
- Diebold (2015). "Comparing predictive accuracy, twenty years later."
  *JBES*. — robustness commentary; clarifies what DM does and does not
  test.
- Giacomini & White (2006). "Tests of conditional predictive ability."
  *Econometrica* 74: 1545-1578. — generalisation for rolling-retraining
  setups; recommended over plain DM when model state changes.

### Conformal prediction / calibration

- Romano, Patterson & Candès (2019). "Conformalized quantile regression."
  NeurIPS. — CQR, the basis of Augur's split-conformal band correction
  (`ml/shadow/conformal.py`).
- Gibbs & Candès (2021). "Adaptive conformal inference under distribution
  shift." NeurIPS. — ACI; principled replacement for static-window CQR
  when single-day regime shifts break coverage. Candidate for any
  next-bet shadow.

### LightGBM and quantile regression

- Chung et al. (2021). "Beyond Pinball Loss: Quantile Methods for
  Calibrated Uncertainty Quantification." OpenReview. — known caveat
  that minimising aggregate pinball at training can leave individual
  quantiles miscalibrated.

### GEFCom competitions (benchmarks)

- Hong et al. (2016). "Probabilistic energy forecasting: Global Energy
  Forecasting Competition 2014 and beyond." *International Journal of
  Forecasting* 32: 896-913. — GEFCom2014; 99-quantile pinball-based
  evaluation; benchmark of probabilistic EPF.
