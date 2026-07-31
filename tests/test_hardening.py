"""Tests for runner concurrency + provider resilience (retries, timeout, cost cap)."""
from pathlib import Path

import pytest

from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.providers.base import Provider, ProviderError
from llmqa.runner import run_eval

DATASET = str(Path(__file__).resolve().parent.parent / "datasets" / "qa_golden.yaml")


def test_concurrency_matches_serial_results():
    """Running concurrently yields the same set of cases and aggregates as serial."""
    metrics = [build_metric("exact_match"), build_metric("similarity")]
    serial = run_eval(DATASET, get_provider("mock"), metrics, concurrency=1)
    parallel = run_eval(DATASET, get_provider("mock"), metrics, concurrency=8)

    assert len(parallel.results) == len(serial.results)
    assert {r.case_id for r in parallel.results} == {r.case_id for r in serial.results}
    # Order-independent aggregates should match exactly (deterministic mock).
    assert parallel.pass_rate == serial.pass_rate
    assert round(parallel.avg_score, 6) == round(serial.avg_score, 6)


class _CountingProvider(Provider):
    """A provider whose _complete fails a fixed number of times before succeeding."""

    name = "counting"
    model = "counting-1"

    def __init__(self, fail_times: int, **kw):
        super().__init__(use_cache=False, backoff_base=0.0, **kw)
        self.fail_times = fail_times
        self.calls = 0

    def _complete(self, prompt, context=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("transient boom")
        return ("ok", 0.0)


def test_retries_recover_from_transient_failure():
    p = _CountingProvider(fail_times=2, max_retries=2)  # 2 fails then success
    resp = p.generate("hi")
    assert resp.text == "ok"
    assert p.calls == 3


def test_retries_exhausted_raises_provider_error():
    p = _CountingProvider(fail_times=5, max_retries=2)  # always fails within budget
    with pytest.raises(ProviderError):
        p.generate("hi")
    assert p.calls == 3  # initial + 2 retries


class _SlowProvider(Provider):
    name = "slow"
    model = "slow-1"

    def _complete(self, prompt, context=None):
        import time
        time.sleep(0.5)
        return ("late", 0.0)


def test_timeout_is_enforced():
    p = _SlowProvider(use_cache=False, max_retries=0, timeout_s=0.05)
    with pytest.raises(ProviderError):
        p.generate("hi")


class _PricedProvider(Provider):
    name = "priced"
    model = "priced-1"

    def _complete(self, prompt, context=None):
        return ("answer", 1.0)  # $1 per call


def test_cost_ceiling_stops_run_early():
    p = _PricedProvider(use_cache=False)
    metrics = [build_metric("exact_match")]
    run = run_eval(DATASET, p, metrics, max_cost_usd=3.0)
    assert run.stopped_early is True
    assert "cost ceiling" in run.stopped_reason
    # Stops as soon as cumulative cost >= ceiling (3 cases at $1 each).
    assert len(run.results) == 3
    assert run.total_cost_usd >= 3.0


def test_get_provider_applies_resilience_overrides():
    p = get_provider("mock", max_retries=5, timeout_s=1.5, backoff_base=0.1)
    assert p.max_retries == 5
    assert p.timeout_s == 1.5
    assert p.backoff_base == 0.1
