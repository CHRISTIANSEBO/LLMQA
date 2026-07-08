"""LLM-as-judge metric.

A judge model scores the output against the expected answer on a rubric,
using chain-of-thought and a discrete scoring scale (best practice: discrete
named grades beat vague 1-10 scales). When the judge provider is the mock
(no API key), it falls back to a deterministic heuristic so CI is stable.
"""
from __future__ import annotations

import json
import re

from .base import Metric
from ..types import MetricResult, TestCase
from ..providers import Provider, MockProvider

# Discrete grades -> normalized score.
_GRADES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

_JUDGE_PROMPT = """You are a strict grader. Compare the CANDIDATE answer to the \
REFERENCE answer for the given QUESTION.

QUESTION: {question}
REFERENCE: {reference}
CANDIDATE: {candidate}

First reason briefly, then output a JSON object on the last line exactly like:
{{"grade": "correct|partial|incorrect", "reason": "<short reason>"}}
grade = correct if the candidate conveys the same answer as the reference,
partial if partially right, incorrect if wrong or missing."""


class LLMJudgeMetric(Metric):
    name = "llm_judge"

    def __init__(self, judge: Provider | None = None, threshold: float = 0.5) -> None:
        super().__init__(threshold)
        self.judge = judge or MockProvider()

    def score(self, case: TestCase, output: str) -> MetricResult:
        # Deterministic fallback when no real judge is configured.
        if isinstance(self.judge, MockProvider):
            return self._heuristic(case, output)

        prompt = _JUDGE_PROMPT.format(
            question=case.input, reference=case.expected, candidate=output
        )
        verdict = self.judge.generate(prompt).text
        match = re.search(r"\{.*\}", verdict, re.DOTALL)
        if not match:
            return self._result(0.0, "judge returned no JSON verdict")
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return self._result(0.0, "judge JSON parse failed")
        grade = str(data.get("grade", "incorrect")).lower()
        return self._result(_GRADES.get(grade, 0.0), f"judge: {grade} — {data.get('reason','')}")

    def _heuristic(self, case: TestCase, output: str) -> MetricResult:
        exp = case.expected.lower().strip().rstrip(".")
        out = output.lower()
        if exp in out:
            return self._result(1.0, "heuristic judge: reference present")
        overlap = len(set(exp.split()) & set(out.split()))
        if overlap >= max(1, len(exp.split()) // 2):
            return self._result(0.5, "heuristic judge: partial overlap")
        return self._result(0.0, "heuristic judge: no match")
