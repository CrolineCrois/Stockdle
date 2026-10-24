"""Points and timer rules."""

import pytest

from app import config, scoring


def test_base_points_from_suspicion():
    p = scoring.sneak_points(suspicion=0.2, num_words=3, streak=0, remaining_s=0,
                             start_s=20, is_novel=False, is_bounty=False)
    assert p.base == 800 and p.total == 800


@pytest.mark.parametrize("words,mult", [(1, 3.0), (2, 2.0), (3, 1.0)])
def test_word_multiplier(words, mult):
    p = scoring.sneak_points(suspicion=0.0, num_words=words, streak=0, remaining_s=0,
                             start_s=20, is_novel=False, is_bounty=False)
    assert p.word_mult == mult and p.total == round(1000 * mult)


def test_streak_multiplier_caps_at_two():
    assert scoring.streak_multiplier(0) == 1.0
    assert scoring.streak_multiplier(3) == pytest.approx(1.3)
    assert scoring.streak_multiplier(50) == 2.0


def test_time_multiplier_and_quick_hands():
    full = scoring.sneak_points(suspicion=0.0, num_words=3, streak=0, remaining_s=20,
                                start_s=20, is_novel=False, is_bounty=False)
    assert full.time_mult == 1.5 and full.total == 1500 and full.quick_hands
    slow = scoring.sneak_points(suspicion=0.0, num_words=3, streak=0, remaining_s=5,
                                start_s=20, is_novel=False, is_bounty=False)
    assert not slow.quick_hands


def test_all_multipliers_stack():
    p = scoring.sneak_points(suspicion=0.1, num_words=1, streak=2, remaining_s=10,
                             start_s=20, is_novel=True, is_bounty=True)
    assert p.total == round(900 * 3 * 1.2 * 1.25 * 1.5 * 3)


def test_timer_shrinks_with_streak_and_floors():
    assert scoring.timer_seconds(0, False) == config.TIMER_BASE_S
    assert scoring.timer_seconds(3, False) == config.TIMER_BASE_S - 3 * config.TIMER_STREAK_STEP_S
    assert scoring.timer_seconds(99, False) == config.TIMER_MIN_S
    assert scoring.timer_seconds(0, True) == config.TIMER_BASE_S + config.TIMER_BOUNTY_BONUS_S


def test_near_miss_band():
    assert scoring.is_near_miss(0.45)
    assert not scoring.is_near_miss(0.39)
    assert not scoring.is_near_miss(0.5)
