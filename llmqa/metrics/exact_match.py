"""Deterministic exact / normalized match. No API calls, fast, cheap."""
from __future__ import annotations

import json
import re

from .base import Metric
from ..types import MetricResult, TestCase


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


class ExactMatchMetric(Metric):
    """Score 1.0 if the expected answer matches or is contained in the output.

    Handles JSON specially: if both sides parse as JSON, compare structurally
    so key order / whitespace don't cause false failures.
    """

    name = "exact_match"

    def __init__(self, threshold: float = 1.0) -> None:
        super().__init__(threshold)

    def score(self, case: TestCase, output: str) -> MetricResult:
        exp, out = case.expected, output

        # Structural JSON comparison when applicable.
        try:
            if json.loads(exp) == json.loads(out):
                return self._result(1.0, "exact JSON match")
        except (ValueError, TypeError):
            pass

        ne, no = _normalize(exp), _normalize(out)
        if ne == no:
            return self._result(1.0, "normalized exact match")
        if ne in no:
            return self._result(1.0, "expected found in output")
        return self._result(0.0, f"expected {exp!r} not in output")
