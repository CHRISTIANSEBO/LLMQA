"""A deterministic mock provider so the harness runs with no API key.

It returns canned answers for the golden dataset. This is what makes LLMQA
runnable in CI and in offline demos: the pipeline is fully exercised without
spending money or needing secrets. Swap in a real provider for live evals.
"""
from __future__ import annotations

from .base import Provider

# Canned, mostly-correct answers keyed by a substring of the prompt.
_CANNED: dict[str, str] = {
    "capital of france": "Paris",
    "12 multiplied by 12": "144",
    "maria is 34": '{"name": "Maria", "age": 34}',
    "year was the company founded": "1998",
    "who is the ceo": "The context does not say who the CEO is.",
    "mitochondria": "Mitochondria produce the cell's energy (ATP) via cellular respiration.",
    "capital of japan": "Tokyo",
    "worst product": "negative",
}


class MockProvider(Provider):
    name = "mock"
    model = "mock-1"

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        low = prompt.lower()
        for key, answer in _CANNED.items():
            if key in low:
                return answer, 0.0
        return "I don't know.", 0.0
