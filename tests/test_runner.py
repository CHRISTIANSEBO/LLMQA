"""End-to-end runner tests using the deterministic mock provider."""
from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.runner import run_eval, load_dataset

DATASET = "datasets/qa_golden.yaml"


def test_dataset_loads():
    cases = load_dataset(DATASET)
    assert len(cases) >= 5
    assert all(c.id and c.input and c.expected for c in cases)


def test_full_run_with_mock_passes_most():
    provider = get_provider("mock")
    metrics = [build_metric("exact_match"), build_metric("similarity")]
    run = run_eval(DATASET, provider, metrics)
    assert len(run.results) == len(load_dataset(DATASET))
    # The mock returns correct canned answers, so pass rate should be high.
    assert run.pass_rate >= 0.75
    assert 0.0 <= run.avg_score <= 1.0


def test_tag_filtering():
    provider = get_provider("mock")
    run = run_eval(DATASET, provider, [build_metric("exact_match")], tags=["easy"])
    assert all("easy" in r.tags for r in run.results)
    assert len(run.results) >= 1


def test_all_metrics_run():
    provider = get_provider("mock")
    metrics = [build_metric(n) if n in ("exact_match", "similarity")
               else build_metric(n, judge=provider)
               for n in ("exact_match", "similarity", "llm_judge", "hallucination")]
    run = run_eval(DATASET, provider, metrics)
    names = {m.metric for r in run.results for m in r.metrics}
    assert names == {"exact_match", "similarity", "llm_judge", "hallucination"}
