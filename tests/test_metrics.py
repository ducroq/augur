"""Unit tests for ml/shadow/metrics.py.

Priority tests recommended by the 2026-05-29 code-review battery on EXP-012.
Focus: sign conventions, boundary cases, known-answer checks for the
implementations that drive the article's headline numbers.
"""
from __future__ import annotations

import numpy as np
import pytest

from ml.shadow.metrics import (
    diebold_mariano,
    lower_side_coverage,
    mean_quantile_score,
    pinball_loss,
    point_to_quantile_loss_equivalent,
    twcrps_left_tail,
    winkler_interval_score,
)


# ---------------------------------------------------------------------------
# pinball_loss
# ---------------------------------------------------------------------------


def test_pinball_perfect_prediction_zero_loss():
    y = np.array([10.0, 20.0, 30.0])
    q = np.array([10.0, 20.0, 30.0])
    for tau in (0.1, 0.5, 0.9):
        assert np.allclose(pinball_loss(y, q, tau), 0.0), f"tau={tau}"


def test_pinball_tau_05_equals_half_mae():
    y = np.array([10.0, 20.0, 30.0])
    q = np.array([12.0, 19.0, 35.0])
    mae = np.mean(np.abs(y - q))
    got = pinball_loss(y, q, 0.5).mean()
    assert np.isclose(got, 0.5 * mae)


def test_pinball_low_tau_punishes_over_prediction_more():
    # At tau = 0.1: over-prediction (q > y) penalty weight = 1 - tau = 0.9
    # Under-prediction (q < y) penalty weight = tau = 0.1
    y = np.array([10.0])
    q_over = np.array([20.0])   # over by 10
    q_under = np.array([0.0])   # under by 10
    pen_over = pinball_loss(y, q_over, 0.1)[0]
    pen_under = pinball_loss(y, q_under, 0.1)[0]
    assert pen_over == pytest.approx(9.0)  # 10 * 0.9
    assert pen_under == pytest.approx(1.0)  # 10 * 0.1


def test_pinball_high_tau_punishes_under_prediction_more():
    # At tau = 0.9: symmetric flip of the above
    y = np.array([10.0])
    q_over = np.array([20.0])
    q_under = np.array([0.0])
    pen_over = pinball_loss(y, q_over, 0.9)[0]
    pen_under = pinball_loss(y, q_under, 0.9)[0]
    assert pen_over == pytest.approx(1.0)  # 10 * 0.1
    assert pen_under == pytest.approx(9.0)  # 10 * 0.9


def test_pinball_rejects_invalid_tau():
    y = np.array([10.0])
    q = np.array([10.0])
    with pytest.raises(ValueError):
        pinball_loss(y, q, 0.0)
    with pytest.raises(ValueError):
        pinball_loss(y, q, 1.0)


# ---------------------------------------------------------------------------
# point_to_quantile_loss_equivalent (= MAE)
# ---------------------------------------------------------------------------


def test_point_to_quantile_equals_abs_error():
    y = np.array([10.0, 20.0, 30.0])
    p = np.array([12.0, 19.0, 32.0])
    expected = np.array([2.0, 1.0, 2.0])
    np.testing.assert_array_equal(point_to_quantile_loss_equivalent(y, p), expected)


# ---------------------------------------------------------------------------
# mean_quantile_score
# ---------------------------------------------------------------------------


def test_mean_quantile_score_degenerate_equals_half_mae():
    """A degenerate quantile prediction (p10=p50=p90=p) has mean pinball
    across {0.1, 0.5, 0.9} = 0.5 * |y - p|. This is the structural
    asymmetry flagged in the 2026-05-29 data-analyzer review: comparing
    a 3-quantile MQS to a point MAE has a ~2x head start for the quantile
    model independent of any real skill."""
    y = np.array([10.0, 20.0, 30.0])
    p = 15.0
    quantile_preds = np.full((3, 3), p)
    taus = np.array([0.1, 0.5, 0.9])
    mqs = mean_quantile_score(y, quantile_preds, taus)
    mae = np.mean(np.abs(y - p))
    assert np.isclose(mqs, 0.5 * mae), f"MQS {mqs} should equal 0.5*MAE {0.5*mae}"


# ---------------------------------------------------------------------------
# twcrps_left_tail
# ---------------------------------------------------------------------------


def test_twcrps_zero_when_no_quantile_below_threshold():
    """Documents the abstention behavior of the non-canonical variant:
    if no quantile prediction falls below the threshold, the score is 0
    regardless of where the realisation fell. ARF in EXP-012 hit this
    pattern for all 546 paired observations with the pre-committed
    threshold of -27.76 EUR/MWh."""
    y = np.array([-50.0])  # realised in the deep tail
    preds = np.array([[10.0, 20.0, 30.0]])  # all above threshold
    taus = np.array([0.1, 0.5, 0.9])
    threshold = 0.0
    score = twcrps_left_tail(y, preds, taus, threshold)
    assert score[0] == 0.0


def test_twcrps_equals_mqs_when_all_quantiles_below_threshold():
    y = np.array([5.0])
    preds = np.array([[-10.0, -5.0, 0.0]])
    taus = np.array([0.1, 0.5, 0.9])
    # All three quantiles below threshold=10 -> twCRPS variant = full MQS
    tw = twcrps_left_tail(y, preds, taus, threshold=10.0)
    mqs = mean_quantile_score(y, preds, taus)
    assert np.isclose(tw[0], mqs)


# ---------------------------------------------------------------------------
# lower_side_coverage
# ---------------------------------------------------------------------------


def test_lower_side_coverage_all_above():
    y = np.array([10.0, 20.0, 30.0])
    lower = np.array([5.0, 15.0, 25.0])
    assert lower_side_coverage(y, lower) == 1.0


def test_lower_side_coverage_all_below():
    y = np.array([10.0, 20.0, 30.0])
    lower = np.array([15.0, 25.0, 35.0])
    assert lower_side_coverage(y, lower) == 0.0


def test_lower_side_coverage_mixed():
    y = np.array([10.0, 20.0, 30.0, 5.0])
    lower = np.array([8.0, 22.0, 25.0, 6.0])
    # 10>=8 ok, 20<22 fail, 30>=25 ok, 5<6 fail -> 2/4 = 0.5
    assert lower_side_coverage(y, lower) == 0.5


# ---------------------------------------------------------------------------
# winkler_interval_score
# ---------------------------------------------------------------------------


def test_winkler_covered_only_width():
    # y inside band -> IS = width only
    y = np.array([5.0])
    L = np.array([0.0])
    U = np.array([10.0])
    got = winkler_interval_score(y, L, U, alpha=0.2)
    assert got[0] == 10.0


def test_winkler_below_band_penalised():
    # y=1, L=3, U=8, alpha=0.2 -> width=5 + (2/0.2)*(3-1)=20 = 25
    y = np.array([1.0])
    L = np.array([3.0])
    U = np.array([8.0])
    got = winkler_interval_score(y, L, U, alpha=0.2)
    assert got[0] == pytest.approx(25.0)


def test_winkler_above_band_penalised():
    # y=15, L=0, U=10, alpha=0.2 -> width=10 + (2/0.2)*(15-10)=50 = 60
    y = np.array([15.0])
    L = np.array([0.0])
    U = np.array([10.0])
    got = winkler_interval_score(y, L, U, alpha=0.2)
    assert got[0] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# diebold_mariano
# ---------------------------------------------------------------------------


def test_dm_tied_losses_zero_statistic():
    """When loss_a == loss_b everywhere, mean_diff = 0 and the statistic
    is well-defined (variance is degenerate, guarded by the 1e-12 floor)."""
    loss = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    res = diebold_mariano(loss, loss)
    assert res.mean_diff == 0.0
    assert res.statistic == 0.0
    assert res.p_value_one_sided == pytest.approx(0.5)


def test_dm_clear_winner():
    """A clearly beats B -> statistic strongly negative -> small p."""
    rng = np.random.default_rng(42)
    loss_a = rng.normal(1.0, 0.5, 100)
    loss_b = rng.normal(2.0, 0.5, 100)
    res = diebold_mariano(loss_a, loss_b)
    assert res.mean_diff < 0
    assert res.statistic < -5
    assert res.p_value_one_sided < 0.001


def test_dm_too_few_observations_raises():
    with pytest.raises(ValueError):
        diebold_mariano(np.array([1.0]), np.array([2.0]))


def test_dm_shape_mismatch_raises():
    with pytest.raises(ValueError):
        diebold_mariano(np.array([1.0, 2.0]), np.array([1.0, 2.0, 3.0]))
