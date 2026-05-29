# ADR-007: Model promotion method (pre-commit, test, review)

**Status**: Accepted
**Date**: 2026-05-29
**Context**: After a five-iteration metric-redesign arc (M4 park → EXP-012 → EXP-013 → EXP-014 promotion) surfaced four distinct classes of error in the previous promotion process, formalising the method for deciding whether a candidate ML model should replace the incumbent.

## Decision

Promotion decisions follow a **four-layer discipline**, with each layer designed to catch a different class of error:

1. **Pre-commit one skill criterion + one calibration guardrail** in `docs/hypothesis-log.md` before the evaluation window opens. Not a bundle.
2. **Apply the criterion to existing data before running a new shadow window** whenever possible. Discretionary habit, not framework requirement.
3. **Fire an article-level review battery** on the human-readable result before publishing or acting.
4. **Fire a code-level review battery** on the implementation before drawing conclusions.

Run as many iterations as needed until a review pass surfaces nothing actionable.

## Method (operational)

### Skill gate (always)

- Paired Diebold-Mariano test on absolute-error loss differentials: candidate's `|y − p50|` vs incumbent's `|y − point|`.
- Newey-West HAC variance with bandwidth `max_horizon − 1` (not `floor(n^(1/3))`, which under-corrects autocorrelation for h-step-ahead overlapping forecasts).
- Threshold: pre-committed `α` (default 0.10 one-sided). Mean diff must be negative (candidate lower loss) AND `p < α`.
- Reported as a single number with its DM statistic. Not bundled with any other criterion.

### Calibration guardrail (one-sided, not a promotion gate)

- 80% prediction-interval coverage, both sides.
- **For a swap from an incumbent**: candidate's coverage must not be more than `0.02` worse than the incumbent's on either side. Tests "does the swap make calibration worse?", not "is calibration acceptable in absolute terms."
- **For a fresh deployment (no incumbent)**: lower-side and upper-side coverage each in `[0.85, 0.95]`.
- Either form is a **block**, not a promotion. Skill gate is what authorises promotion; calibration only blocks.
- Absolute-coverage shortfalls (e.g. lower-side at 0.81 when target is 0.90) are flagged as known weaknesses queued for follow-up experiments, not as swap-blockers — provided the incumbent has the same shortfall.

### Tail and per-horizon metrics: descriptive only

- Pinball-at-tau, twCRPS variants, per-horizon MAE, Winkler interval score — all reported in the verdict block but **never gated**.
- Non-canonical twCRPS variants can be gamed by abstention (a model that never predicts into the tail scores zero by construction). Per-horizon decomposition can be confounded by data-structure timing artefacts.
- Use these to *understand* a decision after it is made, not to *make* the decision.

### Strict propriety hygiene

- Pre-committed thresholds (e.g. the `c` in `1{z ≤ c}` for twCRPS) must come from data the evaluation window does not see. `q05(realised, prior_window)` is fine; `q05(realised, evaluation_window)` is not.
- Never condition the evaluation slice on the realised outcome. "MAE on hours where realised < 30 EUR/MWh" is the forecaster's-dilemma trap (Lerch et al. 2017) and biases the comparison toward whoever clusters near a constant.
- For probabilistic vs point comparisons, score the point model on MAE — which equals CRPS for a point mass (Gneiting & Raftery 2007 §4.2). For probabilistic models scored via mean pinball across a few quantiles, label the result as a "3-point quantile score" rather than CRPS (the estimator is biased for sparse grids; for K = 3 quantiles {0.10, 0.50, 0.90}, a degenerate quantile prediction has score `0.5 × MAE` regardless of skill).

### MAPE / sMAPE — banned

Undefined at zero, unstable around zero, meaningless for prices that can cross zero. The EPF literature (Lago, Marcjasz, De Schutter & Weron 2021) is explicit on this; don't use them.

### Iterating without loosening Method

The four-layer discipline anticipates that earlier passes will miss things. The rule: **don't loosen Method when the answer arrives.** If a criterion gives a verdict that seems wrong, the verdict stands for the criterion-as-written, and the next step is either:

- **Accept the verdict** and act on what the criterion said.
- **Open a new hypothesis-log entry** with a redesigned criterion that pre-commits to the new question, and run it afresh.

Mutating a pre-committed criterion after seeing its result is forbidden. Opening a new entry is allowed and expected — this is how iterations 4 and 5 of the M4 → EXP-014 arc are recorded.

## Rationale

The method was developed empirically. Across the five iterations leading to EXP-014, four distinct classes of error surfaced — each caught by a different layer:

| Iteration | Class of error | Layer that caught it |
|---|---|---|
| 1 (M4 park) | Wrong criterion design (forecaster's dilemma slice) | Pre-commit + mechanical run — the framework |
| 2 (EXP-012 first run) | Apparently-wrong literature prediction | Discretionary "test on existing data first" |
| 3 (article review) | Implementation non-canonical, mis-framing | Article-level multi-model review battery |
| 4 (code review) | Data-pairing bug (vintage mismatch), structural-asymmetry blind spot, HAC bandwidth too short | Code-level multi-model review battery |
| 5 (criterion redesign) | Gate measured the wrong question for a swap | Mechanical run on existing data after redesign |

Each layer was specifically the right one for the corresponding error class. Pre-commitment alone caught iteration 1; the article-review battery caught iteration 3; the code-review battery caught iteration 4. None of them is redundant.

The "test on existing data before the next shadow window" habit (between iterations) is not a framework feature — it's a judgement call about cost-of-being-wrong. It saved us from running a second 14-day shadow on a bad criterion (iteration 2) and from publishing a draft article with reversed headline findings (iterations 3-4 came from running review batteries on artefacts that were *already drafted*).

## Consequences

- **A single promotion decision can span multiple iterations.** Iteration 5 of the EXP-014 arc happened in the same session as iteration 1. The method does not require waiting for new data between iterations — it requires that each new criterion be pre-committed in `docs/hypothesis-log.md` before being run.
- **Review batteries are not optional.** Skipping the article-review or code-review battery is permissible if the user explicitly accepts that risk, but the default is to run both before any promotion is acted on.
- **Promotion criteria do not survive scope changes.** The criterion from one model class doesn't carry to another. When ADR-006 is superseded by a future production-model decision, a fresh promotion criterion is pre-committed for that change.
- **The framework is one layer of defence.** Pre-commitment catches "ad-hoc post-hoc redefinition." The other three layers exist because pre-commitment alone is insufficient.

## Alternatives considered

- **Bundle multiple criteria with "all must hold."** Rejected after M4: bundles amplify the chance that one criterion is methodologically wrong and parks a good model for the wrong reason. Single-skill-gate plus one-sided guardrail is the smallest defensible package.
- **Use only point-forecast MAE.** Rejected: ignores the probabilistic dimension that the model class was built to address. A probabilistic forecast scored only on point accuracy is a probabilistic forecast wasted.
- **Use a multi-step shadow with intermediate gating.** Rejected as over-engineering for v1. Pre-commit → test-existing → review → promote is enough discipline without adding an extra shadow-window gate.
- **Skip the calibration guardrail and gate on skill alone.** Rejected: would have shipped LightGBM with no check on whether the band display is honest. The current swap promoted LightGBM despite a known coverage shortfall because the guardrail confirmed it does not worsen the incumbent's calibration — that's the right level of check, not zero check.

## References

- First application: EXP-014 (`experiments/registry.jsonl`), `docs/hypothesis-log.md` iteration-5 entry, `scripts/exp014_evaluate_promotion.py`.
- Companion architecture decision: ADR-006 (LightGBM-Quantile production forecasting).
- Five-iteration narrative: `docs/articles/m4-metric-redesign-story.md`.
- Literature backing each layer: `docs/literature.md`, `docs/metric-redesign-literature-review.md`. Key papers cited in the literature review: Lerch et al. (2017) on the forecaster's dilemma; Gneiting & Ranjan (2011) on threshold-weighted scoring rules; Gneiting & Raftery (2007) on proper scoring rules; Diebold & Mariano (1995) and Giacomini & White (2006) on paired-loss tests; Lago, Marcjasz, De Schutter & Weron (2021) on EPF best practice.
- Tests: `tests/test_metrics.py` (19 unit tests on the metric implementations the method uses).
