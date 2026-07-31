"""Flexible expected-answer matching: alternatives, regex, numeric tolerance."""
from __future__ import annotations

from llmqa.metrics import ExactMatchMetric
from llmqa.types import TestCase


def _case(**kw) -> TestCase:
    base = dict(id="t", input="q", expected="Washington")
    base.update(kw)
    return TestCase(**base)


def test_accept_alternatives():
    m = ExactMatchMetric()
    case = _case(expected="Washington", accept=["Washington, D.C.", "D.C."])
    assert m.score(case, "Washington, D.C.").passed
    assert m.score(case, "The capital is Washington").passed
    assert not m.score(case, "New York").passed


def test_expected_regex():
    m = ExactMatchMetric()
    case = _case(expected="1969", expected_regex=r"\b1969\b")
    assert m.score(case, "It happened in 1969, a famous year.").passed
    assert not m.score(case, "It was 1970.").passed


def test_numeric_tolerance():
    m = ExactMatchMetric()
    case = _case(expected="3.14", tolerance=0.001)
    assert m.score(case, "pi is about 3.140").passed
    assert m.score(case, "3.1416").passed is False  # outside 0.001
    assert not m.score(case, "3.1416").passed


def test_numeric_tolerance_handles_commas():
    m = ExactMatchMetric()
    case = _case(expected="1000000", tolerance=0)
    assert m.score(case, "1,000,000").passed


def test_json_still_matches_with_alternatives():
    m = ExactMatchMetric()
    case = _case(expected='["apples", "bananas"]')
    assert m.score(case, '```json\n["apples", "bananas"]\n```').passed
