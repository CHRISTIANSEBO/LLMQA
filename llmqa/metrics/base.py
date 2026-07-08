"""Metric interface."""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..types import MetricResult, TestCase


class Metric(ABC):
    name: str = "base"

    def __init__(self, threshold: float = 0.5) -> None:
        # A case passes this metric when score >= threshold.
        self.threshold = threshold

    @abstractmethod
    def score(self, case: TestCase, output: str) -> MetricResult:
        ...

    def _result(self, score: float, detail: str = "") -> MetricResult:
        return MetricResult(
            metric=self.name,
            score=score,
            passed=score >= self.threshold,
            detail=detail,
        )
