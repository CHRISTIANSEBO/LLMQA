"""The base provider retries transient failures before giving up."""
from __future__ import annotations

import pytest

from llmqa.providers.base import Provider


class _FlakyProvider(Provider):
    name = "flaky"
    model = "flaky-1"
    retry_backoff_s = 0.0  # no real sleeping in tests

    def __init__(self, fail_times: int, **kw) -> None:
        super().__init__(**kw)
        self._fail_times = fail_times
        self.calls = 0

    def _complete(self, prompt, context=None):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise RuntimeError("transient 503")
        return "ok", 0.0


def test_retries_then_succeeds():
    p = _FlakyProvider(fail_times=2, use_cache=False)  # default max_retries=2 -> 3 attempts
    resp = p.generate("hi")
    assert resp.text == "ok"
    assert p.calls == 3


def test_gives_up_after_max_retries():
    p = _FlakyProvider(fail_times=99, use_cache=False)
    with pytest.raises(RuntimeError, match="transient 503"):
        p.generate("hi")
    assert p.calls == 3  # first attempt + 2 retries


def test_runner_records_error_instead_of_crashing(tmp_path):
    """A provider that always fails should degrade to a failed case, not abort."""
    from llmqa.metrics import build_metric
    from llmqa.runner import run_eval

    ds = tmp_path / "d.yaml"
    ds.write_text(
        "- id: c1\n  input: q\n  expected: Paris\n  gate_metrics: [exact_match]\n"
    )
    p = _FlakyProvider(fail_times=99, use_cache=False)
    run = run_eval(str(ds), p, [build_metric("exact_match")])
    assert len(run.results) == 1
    assert run.results[0].error is not None
    assert not run.results[0].passed
