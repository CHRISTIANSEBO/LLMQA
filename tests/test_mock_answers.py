"""The mock providers must produce meaningful, tier-appropriate results on every
shipped dataset, not just the original golden set.

Because the hosted showcase is mock-only, a real regression/trend story depends
on the canned answers actually satisfying each case's gating metric. These tests
lock that in: if a dataset case is edited so a mock answer no longer matches (or
a mock tier is silently degraded to noise), they fail loudly.
"""
from __future__ import annotations

import pytest

from llmqa.catalog import DATASETS_DIR
from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.runner import run_eval

# The datasets added alongside the mock answers under test.
TOPICAL_DATASETS = [
    "factual_qa.yaml",
    "summarization.yaml",
    "rag_grounding.yaml",
    "code_qa.yaml",
    "safety_refusals.yaml",
]

# Mirror the CLI's default metric stack (deterministic with a mock judge).
DEFAULT_METRIC_NAMES = ["exact_match", "similarity", "llm_judge", "hallucination"]


def _build_metrics(provider):
    metrics = []
    for name in DEFAULT_METRIC_NAMES:
        if name in ("llm_judge", "hallucination"):
            metrics.append(build_metric(name, judge=provider))
        else:
            metrics.append(build_metric(name))
    return metrics


def _run(model: str, dataset: str):
    provider = get_provider(model, use_cache=False)
    return run_eval(DATASETS_DIR / dataset, provider, _build_metrics(provider))


@pytest.mark.parametrize("dataset", TOPICAL_DATASETS)
def test_mock_strong_is_a_perfect_baseline(dataset):
    """mock-strong is the correct baseline: it must pass every case so the
    weaker tiers have a clean reference to regress against."""
    run = _run("mock-strong", dataset)
    failed = [r.id for r in run.results if not r.passed]
    assert run.pass_rate == 1.0, f"{dataset}: mock-strong failed {failed}"


@pytest.mark.parametrize("dataset", TOPICAL_DATASETS)
def test_weaker_tiers_are_meaningful_not_noise(dataset):
    """The weaker tiers degrade realistically: still mostly correct (so the
    signal is a regression, not garbage), but never better than the baseline."""
    strong = _run("mock-strong", dataset).pass_rate
    for model in ("mock-lite", "mock-legacy"):
        rate = _run(model, dataset).pass_rate
        assert rate <= strong, f"{dataset}: {model} ({rate}) beat strong ({strong})"
        assert rate >= 0.7, f"{dataset}: {model} pass rate {rate} looks like noise"


def test_legacy_actually_regresses_somewhere():
    """Across the topical datasets, the legacy tier must visibly fabricate/fail
    at least once, or it is not demonstrating regression detection at all."""
    total_fail = 0
    for dataset in TOPICAL_DATASETS:
        run = _run("mock-legacy", dataset)
        total_fail += sum(1 for r in run.results if not r.passed)
    assert total_fail >= 3, f"mock-legacy only failed {total_fail} cases overall"
