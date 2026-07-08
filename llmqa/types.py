"""Core data models for LLMQA, using Pydantic for structured, validated results."""
from __future__ import annotations

from pydantic import BaseModel, Field


class TestCase(BaseModel):
    """A single golden test case loaded from a dataset file."""

    id: str
    input: str
    expected: str
    context: str | None = None
    tags: list[str] = Field(default_factory=list)


class MetricResult(BaseModel):
    """The outcome of one metric scoring one test case."""

    metric: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    detail: str = ""


class CaseResult(BaseModel):
    """All metric results for a single test case, plus the model's raw output."""

    case_id: str
    tags: list[str] = Field(default_factory=list)
    output: str
    metrics: list[MetricResult] = Field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def passed(self) -> bool:
        """A case passes only if every metric passed."""
        return all(m.passed for m in self.metrics) if self.metrics else False


class EvalRun(BaseModel):
    """A full evaluation run: every case result plus aggregate stats."""

    dataset: str
    model: str
    provider: str
    results: list[CaseResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    timestamp: str = ""

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def avg_score(self) -> float:
        scores = [m.score for r in self.results for m in r.metrics]
        return sum(scores) / len(scores) if scores else 0.0

    def score_by_metric(self) -> dict[str, float]:
        """Average score grouped by metric name."""
        buckets: dict[str, list[float]] = {}
        for r in self.results:
            for m in r.metrics:
                buckets.setdefault(m.metric, []).append(m.score)
        return {k: sum(v) / len(v) for k, v in buckets.items()}
