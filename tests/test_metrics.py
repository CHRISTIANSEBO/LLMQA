"""Unit tests for the scoring metrics."""
from llmqa.metrics import ExactMatchMetric, HallucinationMetric, LLMJudgeMetric, SimilarityMetric
from llmqa.types import TestCase


def _case(**kw) -> TestCase:
    base = dict(id="t", input="q", expected="Paris")
    base.update(kw)
    return TestCase(**base)


def test_exact_match_normalized():
    m = ExactMatchMetric()
    assert m.score(_case(expected="Paris"), "paris.").passed
    assert m.score(_case(expected="Paris"), "The capital is Paris").passed
    assert not m.score(_case(expected="Paris"), "London").passed


def test_exact_match_json():
    m = ExactMatchMetric()
    r = m.score(_case(expected='{"name": "Maria", "age": 34}'),
                '{"age": 34, "name": "Maria"}')
    assert r.passed and r.score == 1.0


def test_exact_match_json_in_code_fence():
    # Models routinely wrap JSON in ```json fences; we should still match.
    m = ExactMatchMetric()
    fenced = '```json\n{\n  "name": "Maria",\n  "age": 34\n}\n```'
    r = m.score(_case(expected='{"name": "Maria", "age": 34}'), fenced)
    assert r.passed and r.score == 1.0


def test_similarity_partial():
    m = SimilarityMetric(threshold=0.3)
    high = m.score(_case(expected="the cat sat on the mat"), "a cat sat on a mat")
    low = m.score(_case(expected="the cat sat on the mat"), "quantum physics rocks")
    assert high.score > low.score
    assert not low.passed


def test_hallucination_not_applicable_without_context():
    m = HallucinationMetric()
    r = m.score(_case(context=None), "anything")
    assert r.passed and "not applicable" in r.detail


def test_hallucination_rewards_refusal():
    m = HallucinationMetric()
    r = m.score(_case(context="Acme was founded in 1998."),
                "The context does not say who the CEO is.")
    assert r.passed


def test_hallucination_flags_ungrounded():
    m = HallucinationMetric(threshold=0.5)
    r = m.score(_case(context="Acme was founded in 1998 in Denver."),
                "The CEO is Jane Superlongfabricatedname from Zurich headquarters")
    assert r.score < 0.5


def test_llm_judge_heuristic_fallback():
    m = LLMJudgeMetric()  # mock judge -> heuristic
    assert m.score(_case(expected="Paris"), "Paris").passed
    assert not m.score(_case(expected="Paris"), "Berlin").passed
