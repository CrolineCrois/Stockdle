"""The judge: did the edit actually make the headline false?

``get_judge()`` picks, with ``SIP_JUDGE=auto``: Claude if ANTHROPIC_API_KEY is
set, else OpenAI if OPENAI_API_KEY is set, else the rule-based mock. Set
``SIP_JUDGE=claude|openai|mock`` to force one.
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
        if os.environ.get("ANTHROPIC_API_KEY"):
            choice = "claude"
        elif os.environ.get("OPENAI_API_KEY"):
            choice = "openai"
        else:
            choice = "mock"
    if choice == "claude":
        from .claude_judge import ClaudeJudge
        return ClaudeJudge()
    if choice == "openai":
        from .openai_judge import OpenAIJudge
        return OpenAIJudge()
    from .mock_judge import MockJudge
    return MockJudge()


__all__ = ["EDIT_TYPES", "Judge", "JudgeUnavailable", "Verdict", "get_judge"]
