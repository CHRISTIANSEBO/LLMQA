"""Deterministic mock providers so the harness runs with no API key.

These simulate models of different quality tiers against the golden dataset,
so CI, offline demos, and the regression/trend dashboard are all meaningful
without spending money or needing secrets:

- ``mock-strong``  a strong current-gen model: correct, well-grounded answers.
- ``mock-lite``    a cheaper/smaller model: mostly right, but weaker on
                   formatting and the harder (RAG / classification) cases.
- ``mock-legacy``  an older model: fabricates instead of refusing, ignores
                   "JSON only" instructions, and gets some facts wrong.

Each variant keys canned answers off a substring of the prompt. Swap in a real
provider (``anthropic`` / ``openai``) for live evals. The plain ``mock`` name
is an alias for ``mock-strong`` for backwards compatibility.
"""
from __future__ import annotations

from .base import Provider

# Prompt-substring -> answer. The "strong" model is the correct baseline; the
# weaker variants override individual entries to introduce realistic failures.
_STRONG: dict[str, str] = {
    "capital of france": "Paris",
    "12 multiplied by 12": "144",
    "maria is 34": '{"name": "Maria", "age": 34}',
    "year was the company founded": "1998",
    "who is the ceo": "The context does not say who the CEO is.",
    "mitochondria": "Mitochondria produce the cell's energy (ATP) via cellular respiration.",
    "capital of japan": "Tokyo",
    "worst product": "negative",
}


class _CannedMock(Provider):
    """Base for canned-answer mocks. Subclasses set ``model`` and ``_answers``."""

    name = "mock"
    model = "mock-1"
    _answers: dict[str, str] = _STRONG
    _fallback = "I don't know."

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        low = prompt.lower()
        for key, answer in self._answers.items():
            if key in low:
                return answer, 0.0
        return self._fallback, 0.0


class MockStrongProvider(_CannedMock):
    """A strong current-gen model: correct, well-formatted, grounded."""

    model = "mock-strong-1"
    _answers = _STRONG


# Backwards-compatible default: `mock` == the strong baseline.
MockProvider = MockStrongProvider


class MockLiteProvider(_CannedMock):
    """A cheaper/smaller model: right on easy facts, weaker on hard cases.

    Realistic small-model failure modes: verbose answers that still contain
    the fact (fine), a wrong classification label, and shakier summarization.
    """

    model = "mock-lite-1"
    _answers = {
        **_STRONG,
        # Verbose but still correct on easy facts.
        "capital of france": "The capital of France is Paris.",
        "capital of japan": "That would be Tokyo, the capital of Japan.",
        # Small models often botch strict sentiment labels.
        "worst product": "This review is clearly quite negative.",
        # Weaker paraphrase on summarization.
        "mitochondria": "The mitochondria makes energy for the cell.",
    }


class MockLegacyProvider(_CannedMock):
    """An older model: fabricates instead of refusing, ignores format rules.

    Realistic legacy failure modes: hallucinates a CEO instead of refusing,
    ignores the "respond with only JSON" instruction, and misses a fact.
    """

    model = "mock-legacy-1"
    _answers = {
        **_STRONG,
        # Hallucination: invents a CEO instead of refusing on ungrounded RAG.
        "who is the ceo": "The CEO is Jonathan Meyers, based in the Zurich office.",
        # Format failure: wraps JSON in prose instead of returning only JSON.
        "maria is 34": 'Sure! Here is the data: name is Maria and age is 34.',
        # Factual error on an easy case.
        "capital of japan": "Kyoto",
    }
