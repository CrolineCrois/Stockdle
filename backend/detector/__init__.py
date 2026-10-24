"""The misinformation detector: P(false | headline, article snippet).

It reads the headline *together with* the source snippet, so it is judging
whether the headline is supported by its source -- claim verification, not
headline style. It must be fast: the live suspicion meter calls it on every
debounced keystroke.

    base.py        the interface every version implements
    baseline.py    phase-1 stub: logistic regression on consistency features
    registry.py    which version is current; loading and caching versions
    train_stub.py  trains the stub on seed headlines + rule-made fakes
    bounties.py    flags the headlines the current detector suspects most
"""

from .registry import current, current_name, load

__all__ = ["current", "current_name", "load"]
