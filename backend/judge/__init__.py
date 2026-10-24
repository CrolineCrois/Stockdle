"""The judge: did the edit actually make the headline false?

``get_judge()`` returns the Claude judge when an API key is available (or
``SIP_JUDGE=claude``) and the rule-based mock otherwise.
"""

from __future__ import annotations

import os
from functools import lru_cache

from app import config

from .base import EDIT_TYPES, Judge, JudgeUnavailable, Verdict


@lru_cache(maxsize=1)
def get_judge() -> Judge:
    choice = config.JUDGE
    if choice == "auto":
        choice = "claude" if os.environ.get("ANTHROPIC_API_KEY") else "mock"
    if choice == "claude":
        from .claude_judge import ClaudeJudge
        return ClaudeJudge()
    from .mock_judge import MockJudge
    return MockJudge()


__all__ = ["EDIT_TYPES", "Judge", "JudgeUnavailable", "Verdict", "get_judge"]
