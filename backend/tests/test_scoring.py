"""Unit tests for the scoring module."""

from __future__ import annotations

import math

import numpy as np
import pytest

import scoring
from scoring import (
    CURVE_LEN,
    base_score,
    find_turning_point,
    rmse,
    score_round,
    skipped_round,
    step_sigma,
    streak_multiplier,
)


def flat(value: float = 0.5) -> list[float]:
    return [value] * CURVE_LEN


def ramp(start: float, end: float) -> list[float]:
    return list(np.linspace(start, end, CURVE_LEN))


def hump(peak_at: int, height: float = 0.6, base: float = 0.2) -> list[float]:
    x = np.arange(CURVE_LEN)
    return list(base + height * np.exp(-0.5 * ((x - peak_at) / 6.0) ** 2))


def dip(trough_at: int, depth: float = 0.6, base: float = 0.8) -> list[float]:
    return [base - v for v in np.asarray(hump(trough_at, depth, 0.0))]


# --- primitives -----------------------------------------------------------
def test_rmse_is_zero_for_identical_curves():
    curve = ramp(0.1, 0.9)
    assert rmse(curve, curve) == pytest.approx(0.0)


def test_rmse_matches_hand_computation():
    a = [0.0] * CURVE_LEN
    b = [0.1] * CURVE_LEN
    assert rmse(a, b) == pytest.approx(0.1)


def test_step_sigma_is_floored_for_a_flat_curve():
    assert step_sigma(flat()) == pytest.approx(scoring.SIGMA_EPS)


def test_step_sigma_of_a_straight_ramp_is_zero_before_the_floor():
    # Constant first differences -> zero std -> the floor takes over.
    assert step_sigma(ramp(0.0, 1.0)) == pytest.approx(scoring.SIGMA_EPS)


def test_step_sigma_grows_with_volatility():
    rng = np.random.default_rng(0)
    quiet = np.cumsum(rng.normal(0, 0.002, CURVE_LEN))
    wild = np.cumsum(rng.normal(0, 0.05, CURVE_LEN))
    assert step_sigma(quiet) < step_sigma(wild)


# --- base score -----------------------------------------------------------
def test_perfect_drawing_scores_100():
    truth = hump(25)
    base, err_rmse, _, err = base_score(truth, truth)
    assert base == 100
    assert err_rmse == pytest.approx(0.0)
    assert err == pytest.approx(0.0)


def test_base_score_is_clamped_to_zero_one_hundred():
    truth = hump(25)
    terrible = [1.0 - v for v in truth]
    base, *_ = base_score(terrible, truth)
    assert 0 <= base <= 100


def test_base_score_follows_the_documented_formula():
    rng = np.random.default_rng(3)
    truth = list(np.cumsum(rng.normal(0, 0.02, CURVE_LEN)) + 0.5)
    player = [v + 0.03 for v in truth]
    base, err_rmse, sigma, err = base_score(player, truth)
    expected_err = err_rmse / max(sigma * scoring.SIGMA_MULT, scoring.SIGMA_FLOOR)
    assert err == pytest.approx(expected_err)
    assert base == round(100.0 * math.exp(-scoring.K * expected_err))


def test_closer_drawings_always_score_at_least_as_well():
    truth = hump(25)
    near = [v + 0.02 for v in truth]
    far = [v + 0.12 for v in truth]
    assert base_score(near, truth)[0] > base_score(far, truth)[0]


def test_same_absolute_error_scores_higher_on_a_volatile_round():
    rng = np.random.default_rng(11)
    quiet = list(np.cumsum(rng.normal(0, 0.003, CURVE_LEN)) + 0.5)
    wild = list(np.cumsum(rng.normal(0, 0.05, CURVE_LEN)) + 0.5)
    offset = 0.04
    quiet_score = base_score([v + offset for v in quiet], quiet)[0]
    wild_score = base_score([v + offset for v in wild], wild)[0]
    assert wild_score > quiet_score


def test_wrong_length_curve_is_rejected():
    with pytest.raises(ValueError, match="50 points"):
        base_score([0.5] * 49, flat())


def test_non_finite_curve_is_rejected():
    bad = flat()
    bad[7] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        base_score(bad, flat())


# --- turning points -------------------------------------------------------
def test_clear_peak_is_detected():
    turn = find_turning_point(hump(25))
    assert turn is not None and turn["kind"] == "max" and turn["index"] == 25


def test_clear_trough_is_detected():
    turn = find_turning_point(dip(30))
    assert turn is not None and turn["kind"] == "min" and turn["index"] == 30


def test_monotone_ramp_has_no_turning_point():
    assert find_turning_point(ramp(0.1, 0.9)) is None
    assert find_turning_point(ramp(0.9, 0.1)) is None


def test_flat_curve_has_no_turning_point():
    assert find_turning_point(flat()) is None


def test_extremum_at_the_very_edge_does_not_count():
    assert find_turning_point(hump(1)) is None


def test_turning_point_bonus_awarded_within_tolerance():
    truth = hump(25)
    result = score_round(hump(25 + scoring.TURN_TOLERANCE), truth)
    assert "turning_point" in {b.key for b in result.bonuses}
    assert result.turning_point["hit"] is True


def test_turning_point_bonus_withheld_outside_tolerance():
    truth = hump(25)
    result = score_round(hump(25 + scoring.TURN_TOLERANCE + 1), truth)
    assert "turning_point" not in {b.key for b in result.bonuses}
    assert result.turning_point["hit"] is False


def test_turning_point_bonus_is_worth_the_documented_points():
    truth = hump(25)
    hit = score_round(hump(25), truth)
    assert next(b for b in hit.bonuses if b.key == "turning_point").points == 25


# --- direction ------------------------------------------------------------
def test_direction_bonus_when_signs_match():
    result = score_round(ramp(0.2, 0.8), ramp(0.1, 0.9))
    assert "direction" in {b.key for b in result.bonuses}


def test_no_direction_bonus_when_signs_differ():
    result = score_round(ramp(0.8, 0.2), ramp(0.1, 0.9))
    assert "direction" not in {b.key for b in result.bonuses}


def test_two_flat_curves_count_as_matching_direction():
    result = score_round(flat(0.5), flat(0.5))
    assert "direction" in {b.key for b in result.bonuses}


# --- beating the AI and the crowd ----------------------------------------
def test_beat_ai_bonus_when_player_is_closer():
    truth = hump(25)
    player = [v + 0.01 for v in truth]
    ai = [v + 0.20 for v in truth]
    result = score_round(player, truth, ai_curve=ai)
    assert "beat_ai" in {b.key for b in result.bonuses}
    assert result.ai_rmse == pytest.approx(0.20, abs=1e-6)


def test_no_beat_ai_bonus_when_the_ai_is_closer():
    truth = hump(25)
    result = score_round([v + 0.20 for v in truth], truth,
                         ai_curve=[v + 0.01 for v in truth])
    assert "beat_ai" not in {b.key for b in result.bonuses}


def test_crowd_bonus_requires_three_prior_drawings():
    truth = hump(25)
    player = [v + 0.01 for v in truth]
    crowd = [v + 0.20 for v in truth]
    thin = score_round(player, truth, crowd_curve=crowd, crowd_n=2)
    assert "beat_crowd" not in {b.key for b in thin.bonuses}
    assert thin.crowd_rmse is None

    thick = score_round(player, truth, crowd_curve=crowd, crowd_n=3)
    assert "beat_crowd" in {b.key for b in thick.bonuses}
    assert thick.crowd_rmse == pytest.approx(0.20, abs=1e-6)


def test_ghost_curves_are_optional():
    result = score_round(hump(25), hump(25))
    assert result.ai_rmse is None and result.crowd_rmse is None


# --- bullseye, streaks, totals -------------------------------------------
def test_bullseye_flag_tracks_the_threshold():
    truth = hump(25)
    assert score_round(truth, truth).bullseye is True
    assert score_round([v + 0.5 for v in truth], truth).bullseye is False


def test_streak_multiplier_steps_and_caps():
    assert streak_multiplier(0) == pytest.approx(1.0)
    assert streak_multiplier(3) == pytest.approx(1.3)
    assert streak_multiplier(10) == pytest.approx(2.0)
    assert streak_multiplier(50) == pytest.approx(2.0)   # capped
    assert streak_multiplier(-4) == pytest.approx(1.0)   # defensive


def test_total_is_subtotal_times_multiplier():
    truth = hump(25)
    result = score_round(hump(25), truth, streak=4)
    assert result.multiplier == pytest.approx(1.4)
    assert result.total == round((result.base + result.bonus_points) * 1.4)


def test_streak_advances_on_a_good_round_and_dies_on_a_bad_one():
    truth = hump(25)
    good = score_round(truth, truth, streak=2)
    assert good.base >= scoring.STREAK_AT and good.streak_after == 3

    bad = score_round([1.0 - v for v in truth], truth, streak=2)
    assert bad.base < scoring.STREAK_AT and bad.streak_after == 0


def test_skipped_round_scores_zero_and_resets_the_streak():
    result = skipped_round(streak=6)
    assert result.base == 0 and result.total == 0
    assert result.streak_after == 0 and result.bonuses == []


def test_breakdown_serialises_for_the_api():
    truth = hump(25)
    payload = score_round(hump(26), truth, ai_curve=ramp(0.2, 0.8),
                          crowd_curve=hump(30), crowd_n=5, streak=1).to_dict()
    assert payload["bonus_points"] == sum(b["points"] for b in payload["bonuses"])
    assert {"base", "total", "multiplier", "bullseye", "turning_point"} <= payload.keys()
    assert all(isinstance(b["label"], str) for b in payload["bonuses"])


# --- calibration guardrail ------------------------------------------------
@pytest.mark.parametrize(
    "noise_scale,lo,hi",
    [(1.2, 60, 85), (0.35, 86, 100)],   # "decent" band, then "great"
)
def test_simulated_players_land_in_the_intended_bands(noise_scale, lo, hi):
    """A decent guess should score 60-85 and a great one 90-ish and up."""
    rng = np.random.default_rng(42)
    scores = []
    for _ in range(120):
        truth = np.cumsum(rng.normal(0, 0.02, CURVE_LEN)) + 0.5
        sigma = step_sigma(truth)
        wobble = np.convolve(rng.normal(0, sigma * noise_scale, CURVE_LEN),
                             np.ones(7) / 7, mode="same")
        player = np.clip(truth + np.cumsum(wobble) * 0.6, 0, 1)
        scores.append(base_score(player, truth)[0])
    assert lo <= float(np.mean(scores)) <= hi
