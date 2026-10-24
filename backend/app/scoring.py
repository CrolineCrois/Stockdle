"""Points and timer rules. Pure functions, so they are easy to test and tune.

    points = round(1000 * (1 - suspicion))
             x word multiplier     1 word = 3x, 2 words = 2x, 3 words = 1x
             x streak multiplier   1 + 0.1 * streak, capped at 2x
             x time multiplier     1 + 0.5 * (seconds left / starting seconds)
             x novelty             1.5x for a "zero-day exploit"
             x bounty              3x on bounty headlines
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from . import config

WORD_MULT = {1: 3.0, 2: 2.0, 3: 1.0}
STREAK_STEP, STREAK_CAP = 0.1, 2.0
TIME_BONUS = 0.5
NOVELTY_MULT = 1.5
BOUNTY_MULT = 3.0
QUICK_HANDS_AT = 0.5     # more than half the clock left


def timer_seconds(streak: int, is_bounty: bool) -> float:
    """Starting clock for a headline: shorter as the streak grows."""
    s = max(config.TIMER_MIN_S, config.TIMER_BASE_S - config.TIMER_STREAK_STEP_S * streak)
    return s + (config.TIMER_BOUNTY_BONUS_S if is_bounty else 0.0)


def streak_multiplier(streak: int) -> float:
    return min(1.0 + STREAK_STEP * max(0, streak), STREAK_CAP)


def time_multiplier(remaining_s: float, start_s: float) -> float:
    if start_s <= 0:
        return 1.0
    frac = min(1.0, max(0.0, remaining_s / start_s))
    return 1.0 + TIME_BONUS * frac


@dataclass
class Points:
    base: int
    word_mult: float
    streak_mult: float
    time_mult: float
    novelty_mult: float
    bounty_mult: float
    total: int
    quick_hands: bool

    def to_dict(self) -> dict:
        return asdict(self)


def sneak_points(*, suspicion: float, num_words: int, streak: int, remaining_s: float,
                 start_s: float, is_novel: bool, is_bounty: bool) -> Points:
    """Points for a successful sneak. ``streak`` is the streak *before* this one."""
    base = round(1000 * (1.0 - min(1.0, max(0.0, suspicion))))
    word = WORD_MULT.get(num_words, 1.0)
    streak_m = streak_multiplier(streak)
    time_m = time_multiplier(remaining_s, start_s)
    novelty = NOVELTY_MULT if is_novel else 1.0
    bounty = BOUNTY_MULT if is_bounty else 1.0
    total = round(base * word * streak_m * time_m * novelty * bounty)
    quick = start_s > 0 and remaining_s / start_s > QUICK_HANDS_AT
    return Points(base, word, round(streak_m, 2), round(time_m, 3), novelty, bounty,
                  total, quick)


def is_near_miss(suspicion: float) -> bool:
    return config.NEAR_MISS_FROM <= suspicion < config.SNEAK_THRESHOLD
