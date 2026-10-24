"""The Claude judge. Called once per submission, never on keystrokes.

Uses structured outputs (a JSON schema in ``output_config.format``), so the
reply is guaranteed to be JSON of the right shape; it is still validated with
Pydantic before the game trusts it. Effort is ``low``: this is a short
classification, and the timer is paused while it runs, but a fast verdict
keeps the game snappy.

Server-side refusal fallbacks are on (``fallbacks="default"``), so if the
judge model declines a request the API retries it on a fallback model
inside the same call.
"""

from __future__ import annotations

import json

import anthropic

from app import config

from .base import JudgeUnavailable, Verdict
from .prompt import PROMPTS, SCHEMA, user_message

class ClaudeJudge:
    name = "claude"

    def __init__(self) -> None:
        self.model = config.JUDGE_MODEL
        self._client = anthropic.Anthropic(timeout=config.JUDGE_TIMEOUT_S, max_retries=2)

    def _ask(self, original: str, snippet: str, edited: str, phrasing: str = "a"):
        return self._client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            system=PROMPTS[phrasing],
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": user_message(original, snippet, edited)}],
        )

    def judge(self, original: str, snippet: str, edited: str, phrasing: str = "a") -> Verdict:
        last_error = "no attempt made"
        for _ in range(2):                       # one retry on malformed output
            try:
                response = self._ask(original, snippet, edited, phrasing)
            except anthropic.AuthenticationError as exc:
                raise JudgeUnavailable("judge API key was rejected") from exc
            except anthropic.RateLimitError as exc:
                raise JudgeUnavailable("judge is rate-limited, try again") from exc
            except anthropic.APIStatusError as exc:
                raise JudgeUnavailable(f"judge API error {exc.status_code}") from exc
            except anthropic.APIConnectionError as exc:
                raise JudgeUnavailable("could not reach the judge") from exc

            if response.stop_reason == "refusal":
                raise JudgeUnavailable("the judge declined to rule on this edit")
            text = next((b.text for b in response.content if b.type == "text"), "")
            try:
                return Verdict.model_validate(json.loads(text))
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"malformed verdict: {exc}"
        raise JudgeUnavailable(last_error)
