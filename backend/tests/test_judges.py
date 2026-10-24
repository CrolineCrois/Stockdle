"""Both LLM judges parse, validate and fail the same way (no network: the API
call is replaced by a stub returning a canned response)."""

import json
from types import SimpleNamespace

import pytest

from judge.base import JudgeUnavailable

VERDICT = {"is_false": True, "is_plausible": True, "is_grammatical": True,
           "edit_type": "number change", "explanation": "80mph became 180mph."}


def openai_reply(content=None, refusal=None):
    msg = SimpleNamespace(content=content, refusal=refusal)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def claude_reply(text=None, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text or "")])


@pytest.fixture
def openai_judge(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    from judge.openai_judge import OpenAIJudge
    return OpenAIJudge()


@pytest.fixture
def claude_judge(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    from judge.claude_judge import ClaudeJudge
    return ClaudeJudge()


def test_openai_judge_parses_a_valid_verdict(openai_judge, monkeypatch):
    monkeypatch.setattr(openai_judge, "_ask", lambda *a: openai_reply(json.dumps(VERDICT)))
    v = openai_judge.judge("a", "b", "c")
    assert v.is_false and v.edit_type == "number change" and v.valid_lie


def test_openai_refusal_is_unavailable(openai_judge, monkeypatch):
    monkeypatch.setattr(openai_judge, "_ask", lambda *a: openai_reply(refusal="no"))
    with pytest.raises(JudgeUnavailable):
        openai_judge.judge("a", "b", "c")


def test_openai_malformed_output_retries_then_gives_up(openai_judge, monkeypatch):
    calls = []
    monkeypatch.setattr(openai_judge, "_ask", lambda *a: calls.append(1) or openai_reply("{not json"))
    with pytest.raises(JudgeUnavailable, match="malformed"):
        openai_judge.judge("a", "b", "c")
    assert len(calls) == 2


def test_verdict_with_unknown_edit_type_is_rejected(openai_judge, monkeypatch):
    bad = {**VERDICT, "edit_type": "vibes"}
    monkeypatch.setattr(openai_judge, "_ask", lambda *a: openai_reply(json.dumps(bad)))
    with pytest.raises(JudgeUnavailable):
        openai_judge.judge("a", "b", "c")


def test_claude_judge_parses_and_handles_refusal(claude_judge, monkeypatch):
    monkeypatch.setattr(claude_judge, "_ask", lambda *a: claude_reply(json.dumps(VERDICT)))
    assert claude_judge.judge("a", "b", "c").is_false
    monkeypatch.setattr(claude_judge, "_ask", lambda *a: claude_reply(stop="refusal"))
    with pytest.raises(JudgeUnavailable):
        claude_judge.judge("a", "b", "c")


def test_auto_picks_openai_when_only_its_key_is_set(monkeypatch):
    import judge
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setattr(judge.config, "JUDGE", "auto")
    judge.get_judge.cache_clear()
    try:
        assert judge.get_judge().name == "openai"
    finally:
        judge.get_judge.cache_clear()
