"""Similarity metric: Jaccard default + embeddings backend (with fallback)."""
from __future__ import annotations

import sys
import types

from llmqa.metrics.similarity import SimilarityMetric
from llmqa.types import TestCase


def _case(expected: str) -> TestCase:
    return TestCase(id="t", input="q", expected=expected)


def test_jaccard_default():
    m = SimilarityMetric(threshold=0.3)
    high = m.score(_case("the cat sat on the mat"), "a cat sat on a mat")
    low = m.score(_case("the cat sat on the mat"), "quantum physics rocks")
    assert high.score > low.score
    assert "token overlap" in high.detail


def test_embeddings_falls_back_without_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    m = SimilarityMetric(backend="embeddings")
    r = m.score(_case("hello world"), "hello world")
    # No key -> silently falls back to Jaccard rather than erroring.
    assert "token overlap" in r.detail
    assert r.passed


def test_embeddings_backend_uses_cosine(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    class _Emb:
        def __init__(self, vec):
            self.embedding = vec

    class _Resp:
        def __init__(self, data):
            self.data = data

    class _Embeddings:
        def create(self, *, model, input):
            # Identical unit vectors -> cosine 1.0 regardless of the text.
            return _Resp([_Emb([1.0, 0.0]), _Emb([1.0, 0.0])])

    class _Client:
        def __init__(self, api_key=None):
            self.embeddings = _Embeddings()

    fake_mod = types.ModuleType("openai")
    fake_mod.OpenAI = lambda api_key=None: _Client(api_key=api_key)
    monkeypatch.setitem(sys.modules, "openai", fake_mod)

    m = SimilarityMetric(backend="embeddings")
    r = m.score(_case("anything"), "totally different words")
    assert "embedding cosine" in r.detail
    assert r.score == 1.0


def test_empty_text_scores_zero():
    m = SimilarityMetric()
    assert m.score(_case("something"), "").score == 0.0
