"""Load a dataset, run a model over it, score with metrics, aggregate a run."""
from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from pathlib import Path

import yaml

from .metrics import Metric
from .providers import Provider
from .types import CaseResult, EvalRun, TestCase


def load_dataset(path: str | Path) -> list[TestCase]:
    raw = yaml.safe_load(Path(path).read_text())
    return [TestCase(**item) for item in raw]


def iter_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
) -> Generator[tuple[EvalRun, CaseResult], None, None]:
    """Yield (run, case_result) incrementally as each case completes.

    The same ``EvalRun`` object is yielded with every case so callers can
    inspect cumulative state (cost, results so far) at each step. Both
    ``run_eval`` (batch) and the SSE streaming endpoint use this as their
    shared core loop.
    """
    cases = load_dataset(dataset_path)
    if tags:
        wanted = set(tags)
        cases = [c for c in cases if wanted & set(c.tags)]

    run = EvalRun(
        dataset=str(dataset_path),
        model=provider.model,
        provider=provider.name,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
    )

    for case in cases:
        error: str | None = None
        try:
            resp = provider.generate(case.input, case.context)
            text, cost, latency = resp.text, resp.cost_usd, resp.latency_ms
        except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't abort the run
            # A provider failure (after retries) shouldn't kill the whole run.
            # Record it as a failed case with an empty output so metrics score
            # it as a fail and the report/gates surface the problem.
            error = f"{type(exc).__name__}: {exc}"
            text, cost, latency = "", 0.0, 0.0

        run.total_cost_usd += cost
        cr = CaseResult(
            case_id=case.id,
            tags=case.tags,
            gate_metrics=case.gate_metrics,
            output=text,
            latency_ms=round(latency, 1),
            cost_usd=round(cost, 6),
            error=error,
            metrics=[m.score(case, text) for m in metrics],
        )
        run.results.append(cr)
        yield run, cr


def run_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
) -> EvalRun:
    """Run every case and return the completed EvalRun. Thin wrapper over iter_eval."""
    run = None
    for run, _ in iter_eval(dataset_path, provider, metrics, tags):  # noqa: B007 - keep last run
        pass
    if run is None:  # empty dataset or all cases filtered out
        run = EvalRun(
            dataset=str(dataset_path),
            model=provider.model,
            provider=provider.name,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    return run
