"""Text similarity metric.

Two backends behind one interface:

- ``jaccard`` (default): dependency-free token-overlap similarity, so the
  harness runs anywhere with no API key.
- ``embeddings``: real semantic cosine similarity via an embeddings API
  (OpenAI-compatible). Enabled by passing ``backend="embeddings"`` or setting
  ``LLMQA_SIMILARITY=embeddings``. Falls back to Jaccard if the embeddings call
  is unavailable (no key / no dependency), so callers never hard-fail.
"""
from __future__ import annotations

import math
import os
import re

from ..types import MetricResult, TestCase
from .base import Metric

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


def _jaccard(expected: str, output: str) -> float:
    a, b = _tokens(expected), _tokens(output)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _cosine(u: list[float], v: list[float]) -> float:
    dot = sum(x * y for x, y in zip(u, v, strict=False))
    nu = math.sqrt(sum(x * x for x in u))
    nv = math.sqrt(sum(y * y for y in v))
    if nu == 0 or nv == 0:
        return 0.0
    return dot / (nu * nv)


class SimilarityMetric(Metric):
    name = "similarity"

    def __init__(
        self,
        threshold: float = 0.3,
        *,
        backend: str | None = None,
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        super().__init__(threshold)
        self.backend = (backend or os.environ.get("LLMQA_SIMILARITY", "jaccard")).lower()
        self.embedding_model = embedding_model
        self._client = None  # lazy embeddings client

    # -- embeddings backend --------------------------------------------------
    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        """Return embeddings for ``texts`` or None if embeddings are unavailable."""
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        try:
            if self._client is None:
                import openai  # lazy: only needed for the embeddings backend

                self._client = openai.OpenAI(api_key=api_key)
            resp = self._client.embeddings.create(model=self.embedding_model, input=texts)
            return [d.embedding for d in resp.data]
        except Exception:
            return None

    def score(self, case: TestCase, output: str) -> MetricResult:
        if not case.expected.strip() or not output.strip():
            return self._result(0.0, "empty text")

        if self.backend == "embeddings":
            vecs = self._embed([case.expected, output])
            if vecs is not None:
                sim = max(0.0, _cosine(vecs[0], vecs[1]))
                return self._result(round(sim, 3), f"embedding cosine={sim:.2f}")
            # Fall through to Jaccard if embeddings weren't available.

        jaccard = _jaccard(case.expected, output)
        return self._result(round(jaccard, 3), f"token overlap={jaccard:.2f}")
