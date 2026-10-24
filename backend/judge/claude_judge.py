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

from .base import EDIT_TYPES, JudgeUnavailable, Verdict

SYSTEM = """You are the referee in "Sneak It Past", a research game that collects \
adversarial examples to train a misinformation detector.

A player took a TRUE news headline and edited up to three words, trying to make it \
FALSE while still sounding believable. You receive the original headline, a snippet \
of the source article, and the edited headline. Decide:

- is_false: true if the edited headline states something the original headline or \
the article snippet contradicts, or materially changes a fact (who, what, how many, \
when, where, why) so that a reader would be misinformed. False for paraphrases, \
synonyms, tone or emphasis changes that keep the facts, and edits so vague they \
claim nothing checkable.
- is_plausible: true if an ordinary reader could believe it at a glance as a real \
headline. False for absurd, joking or obviously impossible claims.
- is_grammatical: true if it reads as well-formed headline English (headline \
style, dropped articles and present tense are fine).
- edit_type: the main kind of change - "number change", "negation", "entity swap" \
(a person, place, organisation or object replaced), "causal claim" (a cause or \
consequence invented or reversed), or "other".
- explanation: one or two plain sentences a player will read, saying what changed \
and why it is or is not false.

Judge only what the edit claims relative to the original and the snippet. Do not \
use outside knowledge to call the original headline wrong."""

SCHEMA = {
    "type": "object",
    "properties": {
        "is_false": {"type": "boolean"},
        "is_plausible": {"type": "boolean"},
        "is_grammatical": {"type": "boolean"},
        "edit_type": {"type": "string", "enum": list(EDIT_TYPES)},
        "explanation": {"type": "string"},
    },
    "required": ["is_false", "is_plausible", "is_grammatical", "edit_type", "explanation"],
    "additionalProperties": False,
}


class ClaudeJudge:
    name = "claude"

    def __init__(self) -> None:
        self.model = config.JUDGE_MODEL
        self._client = anthropic.Anthropic(timeout=config.JUDGE_TIMEOUT_S, max_retries=2)

    def _ask(self, original: str, snippet: str, edited: str):
        return self._client.beta.messages.create(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{
                "role": "user",
                "content": (f"Original headline: {original}\n\n"
                            f"Article snippet: {snippet or '(none)'}\n\n"
                            f"Edited headline: {edited}"),
            }],
        )

    def judge(self, original: str, snippet: str, edited: str) -> Verdict:
        last_error = "no attempt made"
        for _ in range(2):                       # one retry on malformed output
            try:
                response = self._ask(original, snippet, edited)
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
