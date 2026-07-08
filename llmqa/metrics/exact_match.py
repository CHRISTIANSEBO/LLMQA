"""Deterministic exact / normalized match. No API calls, fast, cheap."""
from __future__ import annotations

import json
import re

from .base import Metric
from ..types import MetricResult, TestCase


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


def _strip_code_fence(s: str) -> str:
    """Remove a surrounding Markdown code fence (```json ... ```), if present.

    LLMs very commonly wrap JSON/code in fences even when told not to, which
    would otherwise break structural JSON comparison.
    """
    m = re.match(r"^\s*```[a-zA-Z0-9]*\s*\n?(.*?)\n?\s*```\s*$", s, re.DOTALL)
    return m.group(1).strip() if m else s.strip()


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

        # Structural JSON comparison when applicable. Strip code fences first,
        # since models routinely wrap JSON in ```json ... ``` blocks.
        try:
            if json.loads(exp) == json.loads(_strip_code_fence(out)):
                return self._result(1.0, "exact JSON match")
        except (ValueError, TypeError):
            pass

        ne, no = _normalize(exp), _normalize(out)
        if ne == no:
            return self._result(1.0, "normalized exact match")
        if ne in no:
            return self._result(1.0, "expected found in output")
        return self._result(0.0, f"expected {exp!r} not in output")
