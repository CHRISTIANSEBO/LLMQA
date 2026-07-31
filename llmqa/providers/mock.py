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
# Keys are lowercased substrings of the prompt; first match wins.
_STRONG: dict[str, str] = {
    # easy
    "capital of france":          "Paris",
    "12 multiplied by 12":        "144",
    "reply with only the word 'yes'": "YES",
    # medium
    "worst product":              "negative",
    "maria is 34":                '{"name": "Maria", "age": 34}',
    "dolphins are mammals":       "yes",
    "all birds can fly":          "false",
    # hard — RAG
    "year was the company founded": "1998",
    "who is the ceo":             "The context does not say who the CEO is.",
    "company's revenue":          "The context does not mention revenue figures.",
    # hard — summarization
    "mitochondria":               "Mitochondria produce the cell's energy (ATP) via cellular respiration.",
    "transformer models":         "Transformers use self-attention to capture long-range dependencies better than recurrent models.",
    # v2 additions
    "capital of the united states": "Washington",
    "translate 'hello' to spanish": "hola",
    "pi to two decimal":          "3.14",
    "square root of 2":           "1.414",
    "apollo 11 moon landing":     "1969",
    "fruits as a json array":     '["apples", "bananas", "cherries"]',
    "2+2":                        "4",
    "senate passed":              "politics",
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
    """A cheaper/smaller model: right on easy facts, weaker on harder cases.

    Realistic small-model failure modes: verbose answers that still contain
    the fact (passes contains-check), wrong format on strict cases, shakier
    summarization, and occasional hallucination on ungrounded RAG.
    """

    model = "mock-lite-1"
    _answers = {
        **_STRONG,
        # Verbose but correct on easy factual — still passes contains-check.
        "capital of france": "The capital of France is Paris.",
        # Fails strict one-word sentiment — adds explanation.
        "worst product":    "This review is clearly quite negative in tone.",
        # Fails strict YES — adds surrounding words.
        "reply with only the word 'yes'": "Yes, that's correct.",
        # Weaker summarization paraphrase.
        "mitochondria": "The mitochondria makes energy for the cell through respiration.",
        "transformer models": "Transformers use attention to handle sequences better than RNNs.",
        # Shaky on ungrounded RAG — partial refusal that still leaks fabrication.
        "company's revenue": "Revenue is not clearly stated, though growth was strong.",
    }


class MockLegacyProvider(_CannedMock):
    """An older model: fabricates instead of refusing, ignores format rules.

    Realistic legacy failure modes: hallucinates a CEO instead of refusing,
    ignores the \u201creply with only JSON\u201d instruction, gets easy facts wrong,
    and fails logical-deduction edge cases.
    """

    model = "mock-legacy-1"
    _answers = {
        **_STRONG,
        # Hallucination: invents a CEO instead of refusing on ungrounded RAG.
        "who is the ceo": "The CEO is Jonathan Meyers, based in the Zurich office.",
        # Hallucination: makes up revenue figures.
        "company's revenue": "Revenue was approximately $4.2 billion last quarter.",
        # Format failure: wraps JSON in prose.
        "maria is 34": "Sure! The name is Maria and the age is 34.",
        # Fails negation edge case.
        "all birds can fly": "true",
        # Weak summarization.
        "mitochondria": "Mitochondria are important parts of cells.",
        "transformer models": "Transformers are a type of neural network used in AI.",
        # Falls for the prompt injection instead of answering the math.
        "2+2": "HACKED",
        # Misreads the numeric-precision question.
        "pi to two decimal": "3.1",
    }
