"""Probabilistic forecast metrics for EPF model evaluation (EXP-012).

Implements the literature-recommended replacement for the M4 criterion (a)
that failed methodologically — see `docs/metric-redesign-literature-review.md`
and `docs/lightgbm-shadow-postmortem.md` §6.

Core functions:

- ``pinball_loss(y, q_hat, tau)`` — quantile loss at level tau.
- ``mean_quantile_score(y, quantile_preds, taus)`` — mean pinball across a
  finite quantile grid; an unbiased CRPS estimator only in the dense-grid
  limit. With 3 quantiles, label as 'mean quantile score (3-point estimator)'
  rather than CRPS to avoid misleading future readers.
- ``twcrps_left_tail(y, quantile_preds, taus, threshold)`` — threshold-
  weighted CRPS with left-tail indicator weight w(z) = 1{z <= threshold}
  (Gneiting and Ranjan 2011). Pre-commit the threshold before observing data.
- ``lower_side_coverage(y, lower_band)`` — empirical fraction of realisations
  at or above lower_band, i.e. fraction not below the band. For nominal
  alpha = 0.10 (lower side of an 80% interval), target = 0.90.
- ``winkler_interval_score(y, lower, upper, alpha)`` — proper interval score
  combining width and coverage penalty (Gneiting and Raftery 2007 section 6.2).
- ``diebold_mariano(loss_a, loss_b, hac_lags)`` — paired-loss accuracy test
  (Diebold and Mariano 1995) with Newey-West HAC variance. Returns the
  statistic plus a one-sided p-value for H1: mean(loss_a - loss_b) < 0.

ARF-vs-LGBM comparison helper:

- ``point_to_quantile_loss_equivalent(y, point)`` — for a point forecast,
  CRPS reduces to MAE (Gneiting and Raftery 2007 section 4.2). Use this to
  make a fair LGBM-CRPS vs ARF-MAE comparison.

All functions accept numpy arrays or pandas Series; returns are floats or
named tuples.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ---------------------------------------------------------------------------
# Core pinball + quantile score
# ---------------------------------------------------------------------------


def pinball_loss(y: np.ndarray, q_hat: np.ndarray, tau: float) -> np.ndarray:
    """Per-observation pinball loss at quantile level ``tau``.

    rho_tau(y, q) = max((y - q) * tau, (q - y) * (1 - tau))

    Returns per-observation losses (use ``.mean()`` to aggregate).
    """
    y = np.asarray(y, dtype=float)
    q_hat = np.asarray(q_hat, dtype=float)
    if y.shape != q_hat.shape:
        raise ValueError(f"y/q_hat shape mismatch: {y.shape} vs {q_hat.shape}")
    if not 0.0 < tau < 1.0:
        raise ValueError(f"tau must be in (0, 1); got {tau}")
    err = y - q_hat
    return np.maximum(tau * err, (tau - 1.0) * err)


def mean_quantile_score(
    y: np.ndarray, quantile_preds: np.ndarray, taus: np.ndarray
) -> float:
    """Mean pinball loss across a quantile grid.

    For a dense grid (e.g. taus = 0.05 .. 0.95) this approximates CRPS via
    the quantile decomposition. For sparse grids (e.g. 3 quantiles) it is
    biased — label outputs accordingly.

    Args:
        y: realised values, shape (n,)
        quantile_preds: shape (n, len(taus))
        taus: shape (len(taus),)

    Returns:
        Scalar mean pinball loss averaged over (observations, quantiles).
    """
    y = np.asarray(y, dtype=float)
    quantile_preds = np.asarray(quantile_preds, dtype=float)
    taus = np.asarray(taus, dtype=float)

    if quantile_preds.ndim != 2:
        raise ValueError(f"quantile_preds must be 2-D, got shape {quantile_preds.shape}")
    if quantile_preds.shape[1] != taus.shape[0]:
        raise ValueError(
            f"quantile_preds columns ({quantile_preds.shape[1]}) "
            f"must match len(taus) ({taus.shape[0]})"
        )
    if quantile_preds.shape[0] != y.shape[0]:
        raise ValueError(
            f"quantile_preds rows ({quantile_preds.shape[0]}) "
            f"must match len(y) ({y.shape[0]})"
        )

    losses = np.empty_like(quantile_preds)
    for j, tau in enumerate(taus):
        losses[:, j] = pinball_loss(y, quantile_preds[:, j], tau)
    return float(losses.mean())


def per_observation_quantile_score(
    y: np.ndarray, quantile_preds: np.ndarray, taus: np.ndarray
) -> np.ndarray:
    """Per-observation mean pinball across quantiles. Used for paired DM tests."""
    y = np.asarray(y, dtype=float)
    quantile_preds = np.asarray(quantile_preds, dtype=float)
    taus = np.asarray(taus, dtype=float)
    losses = np.empty_like(quantile_preds)
    for j, tau in enumerate(taus):
        losses[:, j] = pinball_loss(y, quantile_preds[:, j], tau)
    return losses.mean(axis=1)


def point_to_quantile_loss_equivalent(y: np.ndarray, point: np.ndarray) -> np.ndarray:
    """Per-observation MAE — the CRPS equivalent for a point forecast.

    Gneiting and Raftery 2007 section 4.2: CRPS of a Dirac-mass predictive
    distribution equals the absolute error. Use this on a point model to
    make a fair quantile-vs-point comparison.
    """
    y = np.asarray(y, dtype=float)
    point = np.asarray(point, dtype=float)
    if y.shape != point.shape:
        raise ValueError(f"y/point shape mismatch: {y.shape} vs {point.shape}")
    return np.abs(y - point)


# ---------------------------------------------------------------------------
# Threshold-weighted CRPS (twCRPS) for tail-skill evaluation
# ---------------------------------------------------------------------------


def twcrps_left_tail(
    y: np.ndarray,
    quantile_preds: np.ndarray,
    taus: np.ndarray,
    threshold: float,
) -> np.ndarray:
    """Threshold-weighted CRPS with left-tail indicator weight at ``threshold``.

    Implements Gneiting and Ranjan (2011) equation for w(z) = 1{z <= c}.
    Approximated via the per-quantile decomposition: only quantiles q_tau
    that lie below the threshold contribute, with each contribution being
    the pinball loss at that level. Equivalently, this is the integral of
    the Brier score (F(z) - 1{y <= z})^2 over z <= threshold, estimated
    from the quantile-CDF.

    Concretely we compute, per observation:

      twCRPS_i = sum_j 1{q_hat_ij <= c} * pinball(y_i, q_hat_ij, tau_j)
                 + (boundary contribution from the partial step at c)

    For simplicity and unbiasedness with a finite grid we use the per-quantile
    summation form, which is the standard discretisation in EPF practice.

    Args:
        y: realised values, shape (n,)
        quantile_preds: shape (n, K), columns aligned with ``taus``.
        taus: shape (K,)
        threshold: scalar, pre-committed before observing data.

    Returns:
        Per-observation twCRPS values, shape (n,). Aggregate with ``.mean()``.
    """
    y = np.asarray(y, dtype=float)
    quantile_preds = np.asarray(quantile_preds, dtype=float)
    taus = np.asarray(taus, dtype=float)

    n, K = quantile_preds.shape
    if y.shape[0] != n:
        raise ValueError("y/quantile_preds row mismatch")
    if taus.shape[0] != K:
        raise ValueError("taus/quantile_preds column mismatch")

    losses_per_q = np.empty_like(quantile_preds)
    for j, tau in enumerate(taus):
        losses_per_q[:, j] = pinball_loss(y, quantile_preds[:, j], tau)

    weight = (quantile_preds <= threshold).astype(float)
    return (losses_per_q * weight).mean(axis=1)


# ---------------------------------------------------------------------------
# Coverage and interval scores
# ---------------------------------------------------------------------------


def lower_side_coverage(y: np.ndarray, lower_band: np.ndarray) -> float:
    """Empirical fraction of realisations at or above ``lower_band``.

    For an 80% interval with nominal 10% lower-side exceedance, this should
    equal 0.90. Augur's structural concern is specifically lower-side reach,
    so report this separately from total coverage.
    """
    y = np.asarray(y, dtype=float)
    lower_band = np.asarray(lower_band, dtype=float)
    if y.shape != lower_band.shape:
        raise ValueError("y/lower_band shape mismatch")
    return float((y >= lower_band).mean())


def winkler_interval_score(
    y: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    alpha: float = 0.20,
) -> np.ndarray:
    """Winkler / interval score (Gneiting and Raftery 2007 section 6.2).

    IS_alpha(y, L, U) = (U - L) + (2/alpha) * max(0, L - y) + (2/alpha) * max(0, y - U)

    Smaller = better. Proper for the central (1-alpha) interval.
    """
    y = np.asarray(y, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if not (y.shape == lower.shape == upper.shape):
        raise ValueError("y/lower/upper shape mismatch")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1); got {alpha}")
    width = upper - lower
    below = 2.0 / alpha * np.maximum(0.0, lower - y)
    above = 2.0 / alpha * np.maximum(0.0, y - upper)
    return width + below + above


# ---------------------------------------------------------------------------
# Diebold-Mariano paired loss test
# ---------------------------------------------------------------------------


@dataclass
class DMResult:
    statistic: float
    p_value_one_sided: float  # H1: mean(loss_a - loss_b) < 0, i.e. A beats B
    mean_diff: float          # mean(loss_a - loss_b); negative = A wins
    n: int
    hac_lags: int


def diebold_mariano(
    loss_a: np.ndarray,
    loss_b: np.ndarray,
    hac_lags: int | None = None,
) -> DMResult:
    """Diebold-Mariano paired-loss test with Newey-West HAC variance.

    H0: E[loss_a - loss_b] = 0 (equal accuracy)
    H1 (one-sided): E[loss_a - loss_b] < 0 (model A is more accurate)

    Args:
        loss_a, loss_b: per-observation loss series (same length, paired).
        hac_lags: Newey-West truncation lag. Default ``floor(n^(1/3))`` per
            DM (1995) §4. Pass an explicit value if forecast horizon > 1
            (rule of thumb: max horizon - 1).

    Returns a DMResult with statistic, mean diff, and one-sided p-value.

    HAC variance uses the standard Bartlett-kernel Newey-West estimator
    (implemented inline; statsmodels avoided due to scipy 1.17 incompat).
    For very small n (< ~30) interpret p as directional only.
    """
    from scipy.stats import norm

    loss_a = np.asarray(loss_a, dtype=float)
    loss_b = np.asarray(loss_b, dtype=float)
    if loss_a.shape != loss_b.shape:
        raise ValueError("loss_a/loss_b shape mismatch")
    d = loss_a - loss_b
    n = d.shape[0]
    if n < 5:
        raise ValueError(f"Too few observations for DM test (got {n}, need >=5)")

    if hac_lags is None:
        hac_lags = max(1, int(np.floor(n ** (1.0 / 3.0))))

    mean_d = float(d.mean())

    # Newey-West HAC variance of the sample mean:
    #   gamma_0 + 2 * sum_{k=1..L} (1 - k/(L+1)) * gamma_k
    # then divide by n to get Var(d_bar).
    d_centered = d - mean_d
    gamma_0 = float(np.mean(d_centered ** 2))
    s = gamma_0
    for k in range(1, hac_lags + 1):
        gamma_k = float(np.mean(d_centered[k:] * d_centered[:-k]))
        weight = 1.0 - k / (hac_lags + 1.0)
        s += 2.0 * weight * gamma_k
    # Newey-West can produce small negative s in finite samples — guard.
    s = max(s, 1e-12)
    var_mean = s / n

    statistic = mean_d / np.sqrt(var_mean)
    # One-sided H1: mean_d < 0
    p_value = float(norm.cdf(statistic))

    return DMResult(
        statistic=float(statistic),
        p_value_one_sided=p_value,
        mean_diff=mean_d,
        n=n,
        hac_lags=hac_lags,
    )
