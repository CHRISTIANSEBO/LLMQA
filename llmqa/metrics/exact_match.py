"""Deterministic exact / normalized match. No API calls, fast, cheap.

Beyond plain string equality this supports the flexible matching a real golden
set needs:

- **Alternatives** (`accept`): any of several correct phrasings counts.
- **Regex** (`expected_regex`): match a pattern instead of a fixed string
  (e.g. "output contains a 4-digit year").
- **Numeric tolerance** (`tolerance`): treat the answer as a number and accept
  it if it is within an absolute tolerance of the expected value.
- **JSON**: structural comparison so key order / whitespace don't matter.
"""
from __future__ import annotations

import json
import re

from ..types import MetricResult, TestCase
from .base import Metric


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower()).rstrip(".")


def _strip_code_fence(s: str) -> str:
    """Remove a surrounding Markdown code fence (```json ... ```), if present.

    LLMs very commonly wrap JSON/code in fences even when told not to, which
    would otherwise break structural JSON comparison.
    """
    m = re.match(r"^\s*```[a-zA-Z0-9]*\s*\n?(.*?)\n?\s*```\s*$", s, re.DOTALL)
    return m.group(1).strip() if m else s.strip()


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _as_number(s: str) -> float | None:
    m = _NUM.search(s.replace(",", ""))
    return float(m.group(0)) if m else None


class ExactMatchMetric(Metric):
    """Score 1.0 if the expected answer matches or is contained in the output.

    Matching order (first hit wins): explicit regex, numeric tolerance,
    structural JSON, then normalized string equality / containment against the
    expected answer and any accepted alternatives.
    """

    name = "exact_match"

    def __init__(self, threshold: float = 1.0) -> None:
        super().__init__(threshold)

    def score(self, case: TestCase, output: str) -> MetricResult:
        # 1) Regex match (format checks like "a 4-digit year").
        if case.expected_regex:
            if re.search(case.expected_regex, output):
                return self._result(1.0, f"regex {case.expected_regex!r} matched")
            return self._result(0.0, f"regex {case.expected_regex!r} not matched")

        # 2) Numeric tolerance.
        if case.tolerance is not None:
            exp_num = _as_number(case.expected)
            out_num = _as_number(output)
            if exp_num is not None and out_num is not None:
                if abs(exp_num - out_num) <= case.tolerance:
                    return self._result(1.0, f"|{out_num}-{exp_num}| <= {case.tolerance}")
                return self._result(0.0, f"{out_num} not within {case.tolerance} of {exp_num}")

        # 3) Structural JSON comparison (strip fences first).
        for candidate in case.acceptable():
            try:
                if json.loads(candidate) == json.loads(_strip_code_fence(output)):
                    return self._result(1.0, "exact JSON match")
            except (ValueError, TypeError):
                pass

        # 4) Normalized string equality / containment against any accepted form.
        no = _normalize(output)
        for candidate in case.acceptable():
            nc = _normalize(candidate)
            if nc == no:
                return self._result(1.0, "normalized exact match")
            if nc and nc in no:
                return self._result(1.0, "expected found in output")

        return self._result(0.0, f"expected {case.expected!r} not in output")
