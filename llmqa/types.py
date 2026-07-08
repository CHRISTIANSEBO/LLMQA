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
    # Which metrics decide pass/fail for THIS case. Metrics not listed are
    # still scored and reported, but do not gate the case. Empty = all metrics
    # gate (backwards-compatible default). This mirrors real eval harnesses:
    # you don't fail a summarization case on exact string match.
    gate_metrics: list[str] = Field(default_factory=list)


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

    # Metric names that gate this case's pass/fail. Empty list => every metric
    # gates (backwards-compatible). Set from TestCase.gate_metrics by the runner.
    gate_metrics: list[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        """A case passes only if every *gating* metric passed.

        If gate_metrics is set, only those metrics decide pass/fail; the rest
        are informational. If it is empty, all metrics must pass.
        """
        if not self.metrics:
            return False
        gating = (
            [m for m in self.metrics if m.metric in self.gate_metrics]
            if self.gate_metrics
            else self.metrics
        )
        # If gate_metrics named metrics that weren't run, fall back to all.
        if not gating:
            gating = self.metrics
        return all(m.passed for m in gating)


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
