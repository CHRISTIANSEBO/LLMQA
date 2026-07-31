"""Tests for the LLM-judge robustness: parsing, retry, self-consistency, fallback."""
from __future__ import annotations

from llmqa.metrics.llm_judge import LLMJudgeMetric, _extract_grade
from llmqa.providers.base import Provider
from llmqa.types import TestCase


class ScriptedJudge(Provider):
    """Returns a scripted sequence of replies, one per call (cache disabled)."""

    name = "scripted-judge"
    model = "scripted-1"

    def __init__(self, replies):
        super().__init__(use_cache=False)
        self._replies = list(replies)
        self.calls = 0

    def _complete(self, prompt, context=None):
        reply = self._replies[min(self.calls, len(self._replies) - 1)]
        self.calls += 1
        return reply, 0.0


CASE = TestCase(id="c", input="Q", expected="Paris")


def test_extract_grade_prefers_last_json_object():
    text = 'Thinking... {"grade": "partial"} then final {"grade": "correct", "reason": "ok"}'
    grade, reason = _extract_grade(text)
    assert grade == "correct"
    assert reason == "ok"


def test_extract_grade_ignores_reasoning_braces():
    text = 'The set {a, b} is irrelevant.\n{"grade": "incorrect", "reason": "wrong"}'
    assert _extract_grade(text)[0] == "incorrect"


def test_extract_grade_keyword_fallback():
    grade, _ = _extract_grade("No JSON, but my verdict is: correct.")
    assert grade == "correct"


def test_extract_grade_none_when_unparseable():
    assert _extract_grade("completely unrelated text") is None


def test_valid_json_scores_directly():
    j = LLMJudgeMetric(judge=ScriptedJudge(['{"grade": "correct", "reason": "match"}']))
    res = j.score(CASE, "Paris")
    assert res.score == 1.0 and res.passed


def test_parse_retry_recovers():
    # First reply is garbage; the retry (with nonce) returns valid JSON.
    judge = ScriptedJudge(["garbage no verdict", '{"grade": "correct"}'])
    j = LLMJudgeMetric(judge=judge, parse_retries=2)
    res = j.score(CASE, "Paris")
    assert res.score == 1.0
    assert judge.calls == 2  # one failed parse, one recovery


def test_self_consistency_majority_vote():
    # correct, correct, incorrect -> majority correct.
    judge = ScriptedJudge([
        '{"grade": "correct"}',
        '{"grade": "correct"}',
        '{"grade": "incorrect"}',
    ])
    j = LLMJudgeMetric(judge=judge, samples=3)
    res = j.score(CASE, "Paris")
    assert res.score == 1.0
    assert judge.calls == 3
    assert "votes" in res.detail


def test_unparseable_falls_back_to_heuristic_not_zero():
    # Every reply is unparseable, but the candidate literally contains the
    # reference, so the heuristic should rescue it to 1.0 (not score 0).
    judge = ScriptedJudge(["nonsense", "still nonsense", "no grade here"])
    j = LLMJudgeMetric(judge=judge, parse_retries=2)
    res = j.score(CASE, "The capital is Paris")
    assert res.score == 1.0
    assert "heuristic fallback" in res.detail
