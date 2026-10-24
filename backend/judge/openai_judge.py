"""The OpenAI judge: same prompt, same schema, same validation as Claude's.

Uses Chat Completions with a strict JSON schema (``response_format``), so the
reply must match the verdict shape; it is still validated with Pydantic before
the game trusts it. A refusal comes back in ``message.refusal`` and is treated
like any other unavailable verdict: the attempt isn't counted, the clock is
refunded.
"""

from __future__ import annotations

import json

import openai

from app import config

from .base import JudgeUnavailable, Verdict
from .prompt import SCHEMA, SYSTEM


class OpenAIJudge:
    name = "openai"

    def __init__(self) -> None:
        self.model = config.OPENAI_JUDGE_MODEL
        self._client = openai.OpenAI(timeout=config.JUDGE_TIMEOUT_S, max_retries=2)

    def _ask(self, original: str, snippet: str, edited: str):
        return self._client.chat.completions.create(
            model=self.model,
            max_completion_tokens=2000,
            response_format={"type": "json_schema",
                             "json_schema": {"name": "verdict", "strict": True, "schema": SCHEMA}},
            messages=[
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (f"Original headline: {original}\n\n"
                                             f"Article snippet: {snippet or '(none)'}\n\n"
                                             f"Edited headline: {edited}")},
            ],
        )

    def judge(self, original: str, snippet: str, edited: str) -> Verdict:
        last_error = "no attempt made"
        for _ in range(2):                       # one retry on malformed output
            try:
                response = self._ask(original, snippet, edited)
            except openai.AuthenticationError as exc:
                raise JudgeUnavailable("judge API key was rejected") from exc
            except openai.RateLimitError as exc:
                raise JudgeUnavailable("judge is rate-limited, try again") from exc
            except openai.APIStatusError as exc:
                raise JudgeUnavailable(f"judge API error {exc.status_code}") from exc
            except openai.APIConnectionError as exc:
                raise JudgeUnavailable("could not reach the judge") from exc

            message = response.choices[0].message
            if message.refusal:
                raise JudgeUnavailable("the judge declined to rule on this edit")
            try:
                return Verdict.model_validate(json.loads(message.content or ""))
            except (json.JSONDecodeError, ValueError) as exc:
                last_error = f"malformed verdict: {exc}"
        raise JudgeUnavailable(last_error)
