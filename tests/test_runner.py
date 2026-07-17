"""End-to-end runner tests using the deterministic mock provider."""
from pathlib import Path

from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.runner import run_eval, load_dataset

# Resolve relative to the repo root so tests pass regardless of CWD.
DATASET = str(Path(__file__).resolve().parent.parent / "datasets" / "qa_golden.yaml")


def test_dataset_loads():
    cases = load_dataset(DATASET)
    assert len(cases) == 12
    assert all(c.id and c.input and c.expected for c in cases)


def test_full_run_with_mock_passes_most():
    provider = get_provider("mock")
    metrics = [build_metric("exact_match"), build_metric("similarity")]
    run = run_eval(DATASET, provider, metrics)
    assert len(run.results) == len(load_dataset(DATASET))
    # The mock returns correct canned answers, so pass rate should be high.
    assert run.pass_rate >= 0.75
    assert 0.0 <= run.avg_score <= 1.0


def test_mock_tiers_differ_in_quality():
    # The strong mock should pass the whole suite; the weaker tiers should
    # score no higher, and at least one should genuinely regress. This is what
    # makes the mock tiers useful for demoing the regression/trend dashboard.
    metrics = [build_metric("exact_match"), build_metric("similarity")]
    strong = run_eval(DATASET, get_provider("mock-strong"), metrics)
    lite = run_eval(DATASET, get_provider("mock-lite"), metrics)
    legacy = run_eval(DATASET, get_provider("mock-legacy"), metrics)

    assert strong.pass_rate >= 0.9  # mock-strong is correct on all gating metrics
    assert lite.pass_rate <= strong.pass_rate
    assert legacy.pass_rate <= strong.pass_rate
    # At least one weaker tier must actually fail a case (otherwise the tiers
    # are indistinguishable and add no value).
    assert min(lite.pass_rate, legacy.pass_rate) < 1.0


def test_mock_alias_matches_strong():
    assert get_provider("mock").model == get_provider("mock-strong").model


def test_tag_filtering():
    provider = get_provider("mock")
    run = run_eval(DATASET, provider, [build_metric("exact_match")], tags=["easy"])
    assert all("easy" in r.tags for r in run.results)
    assert len(run.results) >= 1


def test_gate_metrics_scoped_pass_fail():
    # A case that gates only on exact_match should pass even if a non-gating
    # metric (similarity) scores low.
    from llmqa.types import CaseResult, MetricResult
    cr = CaseResult(
        case_id="t",
        gate_metrics=["exact_match"],
        output="The capital is Paris",
        metrics=[
            MetricResult(metric="exact_match", score=1.0, passed=True),
            MetricResult(metric="similarity", score=0.1, passed=False),
        ],
    )
    assert cr.passed  # only exact_match gates

    # With no gate_metrics, every metric must pass (backwards-compatible).
    cr2 = CaseResult(
        case_id="t",
        output="x",
        metrics=[
            MetricResult(metric="exact_match", score=1.0, passed=True),
            MetricResult(metric="similarity", score=0.1, passed=False),
        ],
    )
    assert not cr2.passed


def test_all_metrics_run():
    provider = get_provider("mock")
    metrics = [build_metric(n) if n in ("exact_match", "similarity")
               else build_metric(n, judge=provider)
               for n in ("exact_match", "similarity", "llm_judge", "hallucination")]
    run = run_eval(DATASET, provider, metrics)
    names = {m.metric for r in run.results for m in r.metrics}
    assert names == {"exact_match", "similarity", "llm_judge", "hallucination"}


def test_tag_filtering_no_matches():
    """Filtering to a tag set that matches zero cases produces an empty run.

    This exercises the run=None fallback in run_eval (empty dataset or all
    cases filtered) and verifies the resulting EvalRun has sane aggregates.
    """
    provider = get_provider("mock")
    run = run_eval(
        DATASET, provider, [build_metric("exact_match")], tags=["no-such-tag-xyz123"]
    )
    assert len(run.results) == 0
    assert run.pass_rate == 0.0
    assert run.avg_score == 0.0
    assert run.total_cost_usd == 0.0
    # Still has the expected metadata
    assert run.dataset.endswith("qa_golden.yaml")
    assert run.provider == "mock"
