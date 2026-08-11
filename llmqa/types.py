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

    # --- Flexible expected-answer matching (used by exact_match) --------------
    # Additional acceptable answers, any of which counts as a full match.
    # Real questions often have several correct phrasings ("US" / "USA" /
    # "United States"), and gating on a single string produces false failures.
    accept: list[str] = Field(default_factory=list)
    # If set, the output matches when this regular expression is found in it.
    # Handy for format checks ("answer is a 4-digit year") without pinning an
    # exact string.
    expected_regex: str | None = None
    # For numeric answers, allow the output to differ from `expected` by up to
    # this absolute tolerance (e.g. tolerance: 0.01 for a rounded float).
    tolerance: float | None = None

    def acceptable(self) -> list[str]:
        """All exact-acceptable strings: the primary expected plus alternates."""
        return [self.expected, *self.accept]


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
    cost_usd: float = 0.0
    error: str | None = None

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
    # Short content hash of the dataset file (e.g. "sha256:ab12..."). Lets the
    # trend/regression views know when a score change is really an
    # apples-to-oranges comparison because the dataset itself changed.
    dataset_hash: str = ""
    model: str
    provider: str
    results: list[CaseResult] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    timestamp: str = ""
    # Set when a run was halted before every case ran (e.g. a cost ceiling was
    # hit). ``stopped_reason`` is a short human-readable explanation.
    stopped_early: bool = False
    stopped_reason: str = ""

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(1 for r in self.results if r.passed) / len(self.results)

    @property
    def avg_score(self) -> float:
        scores = [m.score for r in self.results for m in r.metrics]
        return sum(scores) / len(scores) if scores else 0.0

    def metric_observations(self) -> list[float]:
        """Every individual metric score in the run (flat), for CI estimation."""
        return [m.score for r in self.results for m in r.metrics]

    def case_scores(self) -> dict[str, float]:
        """Per-case score = mean of that case's metric scores, keyed by case id.

        This is the case-level unit used for paired regression significance
        testing against a baseline run.
        """
        out: dict[str, float] = {}
        for r in self.results:
            if r.metrics:
                out[r.case_id] = sum(m.score for m in r.metrics) / len(r.metrics)
        return out

    def score_by_metric(self) -> dict[str, float]:
        """Average score grouped by metric name."""
        buckets: dict[str, list[float]] = {}
        for r in self.results:
            for m in r.metrics:
                buckets.setdefault(m.metric, []).append(m.score)
        return {k: sum(v) / len(v) for k, v in buckets.items()}

    @property
    def avg_latency_ms(self) -> float:
        lats = [r.latency_ms for r in self.results]
        return sum(lats) / len(lats) if lats else 0.0

    @property
    def p95_latency_ms(self) -> float:
        """95th-percentile case latency (nearest-rank). Useful as a budget gate."""
        lats = sorted(r.latency_ms for r in self.results)
        if not lats:
            return 0.0
        idx = min(len(lats) - 1, int(round(0.95 * (len(lats) - 1))))
        return lats[idx]

    def pass_rate_by_tag(self) -> dict[str, float]:
        """Pass rate computed within each tag (a case counts for every tag)."""
        passed: dict[str, int] = {}
        total: dict[str, int] = {}
        for r in self.results:
            for tag in r.tags:
                total[tag] = total.get(tag, 0) + 1
                if r.passed:
                    passed[tag] = passed.get(tag, 0) + 1
        return {t: passed.get(t, 0) / n for t, n in total.items()}
