"""Load a dataset, run a model over it, score with metrics, aggregate a run."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import yaml

from .metrics import Metric
from .providers import Provider
from .types import CaseResult, EvalRun, TestCase


def load_dataset(path: str | Path) -> list[TestCase]:
    raw = yaml.safe_load(Path(path).read_text())
    return [TestCase(**item) for item in raw]


def run_eval(
    dataset_path: str | Path,
    provider: Provider,
    metrics: list[Metric],
    tags: list[str] | None = None,
) -> EvalRun:
    """Run every case (optionally filtered by tag) and collect scored results."""
    cases = load_dataset(dataset_path)
    if tags:
        wanted = set(tags)
        cases = [c for c in cases if wanted & set(c.tags)]

    run = EvalRun(
        dataset=str(dataset_path),
        model=provider.model,
        provider=provider.name,
        timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    for case in cases:
        resp = provider.generate(case.input, case.context)
        run.total_cost_usd += resp.cost_usd
        run.results.append(
            CaseResult(
                case_id=case.id,
                tags=case.tags,
                output=resp.text,
                latency_ms=round(resp.latency_ms, 1),
                metrics=[m.score(case, resp.text) for m in metrics],
            )
        )
    return run
