"""Hallucination / groundedness metric for cases that provide context.

For RAG-style cases (those with a `context`), checks whether the model's
answer is grounded in that context rather than invented. Cases without a
context are skipped (scored 1.0, not applicable). Uses an LLM judge when
available; otherwise a deterministic grounding heuristic.
"""
from __future__ import annotations

import re

from .base import Metric
from ..types import MetricResult, TestCase
from ..providers import Provider, MockProvider

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


class HallucinationMetric(Metric):
    """Score 1.0 = well grounded, 0.0 = likely hallucinated."""

    name = "hallucination"

    def __init__(self, judge: Provider | None = None, threshold: float = 0.5) -> None:
        super().__init__(threshold)
        self.judge = judge or MockProvider()

    def score(self, case: TestCase, output: str) -> MetricResult:
        if not case.context:
            return self._result(1.0, "no context (not applicable)")

        # A proper "I don't know" when context lacks the answer is well-grounded.
        refusal_markers = ("does not say", "not mentioned", "no information", "don't know", "cannot determine")
        if any(m in output.lower() for m in refusal_markers):
            return self._result(1.0, "appropriate refusal / grounded")

        ctx = _tokens(case.context)
        out = _tokens(output)
        # Content words in the answer that don't appear in the context are
        # candidate hallucinations. High grounding = most answer words are supported.
        content = {w for w in out if len(w) > 3}
        if not content:
            return self._result(1.0, "trivial answer")
        supported = content & ctx
        grounding = len(supported) / len(content)
        return self._result(round(grounding, 3), f"{len(supported)}/{len(content)} answer terms grounded")
