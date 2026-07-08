"""Metrics score a model output against a test case (0.0-1.0 + pass/fail)."""
from __future__ import annotations

from .base import Metric
from .exact_match import ExactMatchMetric
from .similarity import SimilarityMetric
from .llm_judge import LLMJudgeMetric
from .hallucination import HallucinationMetric

# Registry so the CLI / config can select metrics by name.
REGISTRY: dict[str, type[Metric]] = {
    "exact_match": ExactMatchMetric,
    "similarity": SimilarityMetric,
    "llm_judge": LLMJudgeMetric,
    "hallucination": HallucinationMetric,
}


def build_metric(name: str, **kwargs) -> Metric:
    if name not in REGISTRY:
        raise ValueError(f"Unknown metric {name!r}. Available: {list(REGISTRY)}")
    return REGISTRY[name](**kwargs)


__all__ = ["Metric", "REGISTRY", "build_metric"]
