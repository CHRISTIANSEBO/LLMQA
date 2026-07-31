"""LLM-as-judge metric.

A judge model scores the output against the expected answer on a rubric,
using chain-of-thought and a discrete scoring scale (best practice: discrete
named grades beat vague 1-10 scales). When the judge provider is the mock
(no API key), it falls back to a deterministic heuristic so CI is stable.

Reliability (matters once a real judge is in the loop):
- Robust verdict parsing: the grade is read from the LAST valid JSON object in
  the reply (reasoning above it is ignored), with a keyword fallback.
- Parse-retry: if a reply can't be parsed, the judge is re-asked a couple of
  times (with a varied nonce so the response cache doesn't just replay the bad
  reply) before giving up.
- Heuristic fallback: if every attempt is unparseable, we fall back to the
  deterministic heuristic instead of scoring a good answer 0 on a formatting
  glitch.
- Self-consistency (opt-in): with samples>1 the judge is polled N times and the
  majority grade wins, which denoises a flaky judge. Default 1 keeps behavior
  and cost unchanged.
"""
from __future__ import annotations

import json
import re
from collections import Counter

from .base import Metric
from ..types import MetricResult, TestCase
from ..providers import Provider, MockProvider

# Discrete grades -> normalized score.
_GRADES = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0}

# Flat JSON objects only (our verdict has no nested braces); this avoids the
# greedy "first { to last }" capture that could swallow reasoning text.
_JSON_OBJ = re.compile(r"\{[^{}]*\}", re.DOTALL)
_GRADE_WORD = re.compile(r"\b(correct|partial|incorrect)\b", re.IGNORECASE)

_JUDGE_PROMPT = """You are a strict grader. Compare the CANDIDATE answer to the \
REFERENCE answer for the given QUESTION.

QUESTION: {question}
REFERENCE: {reference}
CANDIDATE: {candidate}

First reason briefly, then output a JSON object on the last line exactly like:
{{"grade": "correct|partial|incorrect", "reason": "<short reason>"}}
grade = correct if the candidate conveys the same answer as the reference,
partial if partially right, incorrect if wrong or missing."""


def _extract_grade(text: str) -> tuple[str, str] | None:
    """Pull (grade, reason) from a judge reply, or None if unparseable.

    Prefers the last valid JSON object carrying a recognized ``grade``; if none
    parses, falls back to the last bare grade keyword in the text.
    """
    for chunk in reversed(_JSON_OBJ.findall(text)):
        try:
            data = json.loads(chunk)
        except ValueError:
            continue
        grade = str(data.get("grade", "")).lower().strip()
        if grade in _GRADES:
            return grade, str(data.get("reason", ""))
    matches = _GRADE_WORD.findall(text)
    if matches:
        return matches[-1].lower(), "recovered from unstructured reply"
    return None


class LLMJudgeMetric(Metric):
    name = "llm_judge"

    def __init__(
        self,
        judge: Provider | None = None,
        threshold: float = 0.5,
        *,
        samples: int = 1,
        parse_retries: int = 2,
    ) -> None:
        super().__init__(threshold)
        self.judge = judge or MockProvider()
        self.samples = max(1, samples)
        self.parse_retries = max(0, parse_retries)

    def score(self, case: TestCase, output: str) -> MetricResult:
        # Deterministic fallback when no real judge is configured.
        if isinstance(self.judge, MockProvider):
            return self._heuristic(case, output)

        base_prompt = _JUDGE_PROMPT.format(
            question=case.input, reference=case.expected, candidate=output
        )

        votes: list[tuple[str, str]] = []
        for sample_i in range(self.samples):
            parsed = self._ask_once(base_prompt, sample_i)
            if parsed is not None:
                votes.append(parsed)

        # Every attempt was unparseable -> don't score a good answer 0 on a
        # formatting glitch; use the deterministic heuristic instead.
        if not votes:
            res = self._heuristic(case, output)
            return self._result(res.score, f"judge unparseable; heuristic fallback: {res.detail}")

        tally = Counter(g for g, _ in votes)
        majority, count = tally.most_common(1)[0]
        reason = next(r for g, r in votes if g == majority)
        if self.samples > 1:
            breakdown = ", ".join(f"{g}x{n}" for g, n in tally.most_common())
            detail = f"judge: {majority} ({count}/{len(votes)} votes; {breakdown})"
        else:
            detail = f"judge: {majority} \u2014 {reason}"
        return self._result(_GRADES[majority], detail)

    def _ask_once(self, base_prompt: str, sample_i: int) -> tuple[str, str] | None:
        """One vote: ask the judge, retrying on unparseable replies.

        The first call of the first sample uses the bare prompt (so it stays
        cache-compatible and deterministic). Retries and extra samples append a
        nonce so the response cache returns a fresh reply rather than replaying.
        """
        for attempt in range(self.parse_retries + 1):
            prompt = base_prompt
            if sample_i > 0 or attempt > 0:
                prompt = f"{base_prompt}\n\n[grading pass {sample_i}.{attempt}]"
            text = self.judge.generate(prompt).text
            parsed = _extract_grade(text)
            if parsed is not None:
                return parsed
        return None

    def _heuristic(self, case: TestCase, output: str) -> MetricResult:
        exp = case.expected.lower().strip().rstrip(".")
        out = output.lower()
        if exp in out:
            return self._result(1.0, "heuristic judge: reference present")
        overlap = len(set(exp.split()) & set(out.split()))
        if overlap >= max(1, len(exp.split()) // 2):
            return self._result(0.5, "heuristic judge: partial overlap")
        return self._result(0.0, "heuristic judge: no match")
