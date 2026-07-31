"""Load a dataset, run a model over it, score with metrics, aggregate a run."""
from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .metrics import Metric
from .providers import Provider
from .types import CaseResult, EvalRun, TestCase


def load_dataset(path: str | Path) -> list[TestCase]:
    raw = yaml.safe_load(Path(path).read_text())
    return [TestCase(**item) for item in raw]


def _eval_case(case: TestCase, provider: Provider, metrics: list[Metric]) -> tuple[CaseResult, float]:
    """Run one case: generate, score every metric, return (result, cost).

    Pure per-case work with no shared mutation, so it is safe to run in a
    worker thread. The caller accumulates cost/results in the main thread.
    """
    resp = provider.generate(case.input, case.context)
    cr = CaseResult(
        case_id=case.id,
        tags=case.tags,
        gate_metrics=case.gate_metrics,
        output=resp.text,
        latency_ms=round(resp.latency_ms, 1),
        metrics=[m.score(case, resp.text) for m in metrics],
    )
    return cr, resp.cost_usd


def iter_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
    case_ids: list[str] | None = None,
    *,
    concurrency: int = 1,
    max_cost_usd: float | None = None,
) -> Generator[tuple[EvalRun, CaseResult], None, None]:
    """Yield (run, case_result) incrementally as each case completes.

    The same ``EvalRun`` object is yielded with every case so callers can
    inspect cumulative state (cost, results so far) at each step. Both
    ``run_eval`` (batch) and the SSE streaming endpoint use this as their
    shared core loop.

    ``tags`` filters to cases carrying any of the given tags; ``case_ids``
    filters to specific case ids (used by the dashboard's inline single-case
    re-run). When both are given, a case must satisfy both filters.

    ``concurrency`` runs that many cases in parallel via a thread pool (real
    provider calls are I/O bound, so this is a large speedup). With the
    default of 1 the run is serial and deterministic in dataset order, which
    keeps existing behavior and tests stable. When concurrent, cases are
    yielded in completion order.

    ``max_cost_usd`` stops the run early once accumulated cost reaches the
    ceiling; the resulting run is flagged ``stopped_early``.
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

    def _record(cr: CaseResult, cost: float) -> bool:
        """Accumulate one case; return True if the cost ceiling was hit."""
        run.total_cost_usd += cost
        run.results.append(cr)
        if max_cost_usd is not None and run.total_cost_usd >= max_cost_usd:
            run.stopped_early = True
            run.stopped_reason = f"cost ceiling ${max_cost_usd:.4f} reached"
            return True
        return False

    if concurrency <= 1:
        for case in cases:
            cr, cost = _eval_case(case, provider, metrics)
            capped = _record(cr, cost)
            yield run, cr
            if capped:
                break
        return

    # Concurrent path: submit all cases, yield as each finishes.
    executor = ThreadPoolExecutor(max_workers=concurrency)
    try:
        futures = {executor.submit(_eval_case, c, provider, metrics): c for c in cases}
        for fut in as_completed(futures):
            cr, cost = fut.result()
            capped = _record(cr, cost)
            yield run, cr
            if capped:
                for pending in futures:
                    pending.cancel()
                break
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def run_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
    case_ids: list[str] | None = None,
    *,
    concurrency: int = 1,
    max_cost_usd: float | None = None,
) -> EvalRun:
    """Run every case and return the completed EvalRun. Thin wrapper over iter_eval."""
    run = None
    for run, _ in iter_eval(
        dataset_path, provider, metrics, tags, case_ids,
        concurrency=concurrency, max_cost_usd=max_cost_usd,
    ):
        pass
    if run is None:  # empty dataset or all cases filtered out
        run = EvalRun(
            dataset=str(dataset_path),
            model=provider.model,
            provider=provider.name,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
    return run
