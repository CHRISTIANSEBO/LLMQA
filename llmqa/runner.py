"""Load a dataset, run a model over it, score with metrics, aggregate a run."""
from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import ValidationError

from .catalog import dataset_hash
from .exceptions import DatasetError
from .metrics import Metric
from .providers import Provider
from .types import CaseResult, EvalRun, TestCase


def load_dataset(path: str | Path) -> list[TestCase]:
    """Load and validate a dataset file into TestCase objects.

    Raises :class:`DatasetError` with an actionable message when the file is
    missing, isn't valid YAML/JSON, isn't a list of cases, or a case fails
    validation, instead of surfacing a raw traceback.
    """
    p = Path(path)
    try:
        text = p.read_text()
    except FileNotFoundError as exc:
        raise DatasetError(
            f"Dataset not found: {p}. Pass a path to a YAML/JSON file, or a "
            f"packaged dataset name (e.g. qa_golden.yaml)."
        ) from exc
    except OSError as exc:
        raise DatasetError(f"Could not read dataset {p}: {exc}") from exc
    return parse_dataset_text(text, label=str(p))


def parse_dataset_text(text: str, *, label: str = "dataset") -> list[TestCase]:
    """Validate raw YAML/JSON dataset *text* into TestCase objects.

    Shared by :func:`load_dataset` (files) and the web layer (pasted/uploaded
    datasets), so on-disk and in-memory datasets are validated identically and
    raise the same actionable :class:`DatasetError`. ``label`` is used only in
    error messages.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise DatasetError(f"{label} is not valid YAML/JSON: {exc}") from exc

    if not isinstance(raw, list):
        got = type(raw).__name__
        raise DatasetError(
            f"{label} must be a list of cases, got {got}. "
            f"See datasets/dataset.schema.json."
        )

    cases: list[TestCase] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise DatasetError(
                f"{label}: case #{i + 1} must be a mapping, got "
                f"{type(item).__name__}."
            )
        try:
            cases.append(TestCase(**item))
        except ValidationError as exc:
            cid = item.get("id", f"#{i + 1}")
            raise DatasetError(
                f"{label}: case {cid!r} is invalid: {exc.errors()[0]['msg']} "
                f"(field: {'.'.join(str(x) for x in exc.errors()[0]['loc']) or '?'}). "
                f"See datasets/dataset.schema.json."
            ) from exc
    if not cases:
        raise DatasetError(f"{label} is empty (no cases).")
    return cases


def _eval_case(case: TestCase, provider: Provider, metrics: list[Metric]) -> tuple[CaseResult, float]:
    """Run one case: generate, score every metric, return (result, cost).

    Pure per-case work with no shared mutation, so it is safe to run in a
    worker thread. The caller accumulates cost/results in the main thread.

    A provider failure (after its own retries) is degraded to a failed case
    with an empty output and a recorded ``error`` rather than aborting the
    whole run, so one flaky call can't lose an entire evaluation.
    """
    error: str | None = None
    try:
        resp = provider.generate(case.input, case.context)
        text, cost, latency = resp.text, resp.cost_usd, resp.latency_ms
    except Exception as exc:  # noqa: BLE001 - degrade gracefully, don't abort the run
        error = f"{type(exc).__name__}: {exc}"
        text, cost, latency = "", 0.0, 0.0

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
    return cr, cost


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
        dataset_hash=dataset_hash(dataset_path),
        model=provider.model,
        provider=provider.name,
        timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
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
    for run, _ in iter_eval(  # noqa: B007 - keep last run
        dataset_path, provider, metrics, tags, case_ids,
        concurrency=concurrency, max_cost_usd=max_cost_usd,
    ):
        pass
    if run is None:  # empty dataset or all cases filtered out
        run = EvalRun(
            dataset=str(dataset_path),
            model=provider.model,
            provider=provider.name,
            timestamp=datetime.now(UTC).isoformat(timespec="seconds"),
        )
    return run
