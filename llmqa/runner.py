"""Load a dataset, run a model over it, score with metrics, aggregate a run."""
from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timezone
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
    case_ids: list[str] | None = None,
) -> Generator[tuple[EvalRun, CaseResult], None, None]:
    """Yield (run, case_result) incrementally as each case completes.

    The same ``EvalRun`` object is yielded with every case so callers can
    inspect cumulative state (cost, results so far) at each step. Both
    ``run_eval`` (batch) and the SSE streaming endpoint use this as their
    shared core loop.

    ``tags`` filters to cases carrying any of the given tags; ``case_ids``
    filters to specific case ids (used by the dashboard's inline single-case
    re-run). When both are given, a case must satisfy both filters.
    """
    cases = load_dataset(dataset_path)
    if tags:
        wanted = set(tags)
        cases = [c for c in cases if wanted & set(c.tags)]
    if case_ids:
        wanted_ids = set(case_ids)
        cases = [c for c in cases if c.id in wanted_ids]

    run = EvalRun(
        dataset=str(dataset_path),
        model=provider.model,
        provider=provider.name,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    for case in cases:
        resp = provider.generate(case.input, case.context)
        run.total_cost_usd += resp.cost_usd
        cr = CaseResult(
            case_id=case.id,
            tags=case.tags,
            gate_metrics=case.gate_metrics,
            output=resp.text,
            latency_ms=round(resp.latency_ms, 1),
            metrics=[m.score(case, resp.text) for m in metrics],
        )
        run.results.append(cr)
        yield run, cr


def run_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
    case_ids: list[str] | None = None,
) -> EvalRun:
    """Run every case and return the completed EvalRun. Thin wrapper over iter_eval."""
    run = None
    for run, _ in iter_eval(dataset_path, provider, metrics, tags, case_ids):
        pass
    if run is None:  # empty dataset or all cases filtered out
        run = EvalRun(
            dataset=str(dataset_path),
            model=provider.model,
            provider=provider.name,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    return run
