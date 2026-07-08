"""Semantic-ish similarity without heavy deps.

Uses token-overlap (Jaccard) as a dependency-free proxy for semantic
similarity, so the harness runs anywhere. The interface is designed so this
can be swapped for real embedding cosine similarity (e.g. sentence-transformers
or an embeddings API) without changing callers.
"""
from __future__ import annotations

import re

from .base import Metric
from ..types import MetricResult, TestCase

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


class SimilarityMetric(Metric):
    name = "similarity"

    def __init__(self, threshold: float = 0.3) -> None:
        super().__init__(threshold)

    def score(self, case: TestCase, output: str) -> MetricResult:
        a, b = _tokens(case.expected), _tokens(output)
        if not a or not b:
            return self._result(0.0, "empty text")
        jaccard = len(a & b) / len(a | b)
        return self._result(round(jaccard, 3), f"token overlap={jaccard:.2f}")
