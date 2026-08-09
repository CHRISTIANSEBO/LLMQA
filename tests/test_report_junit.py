"""Tests for JUnit XML report output (CI test-reporting integration)."""
from xml.etree import ElementTree as ET

from llmqa.catalog import DATASETS_DIR, resolve_cli_dataset
from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.report import to_junit
from llmqa.runner import run_eval

DATASET = str(DATASETS_DIR / "qa_golden.yaml")


def _run():
    return run_eval(DATASET, get_provider("mock-legacy"),
                    [build_metric("exact_match"), build_metric("similarity")])


def test_junit_is_wellformed_and_counts_match():
    run = _run()
    xml = to_junit(run)
    root = ET.fromstring(xml)  # raises if malformed
    assert root.tag == "testsuites"
    suite = root.find("testsuite")
    n_fail = sum(1 for r in run.results if not r.passed)
    assert int(suite.get("tests")) == len(run.results)
    assert int(suite.get("failures")) == n_fail
    testcases = suite.findall("testcase")
    assert len(testcases) == len(run.results)
    # Failing cases carry a <failure>; passing ones do not.
    failing_xml = [tc for tc in testcases if tc.find("failure") is not None]
    assert len(failing_xml) == n_fail


def test_junit_escapes_special_characters():
    # Should not raise and should remain parseable even with an XML-hostile id.
    from llmqa.types import CaseResult, EvalRun, MetricResult
    run = EvalRun(dataset="d", model="m", provider="p", results=[
        CaseResult(case_id='a<b>&"x"', output="o",
                   metrics=[MetricResult(metric="exact_match", score=0.0, passed=False)]),
    ])
    ET.fromstring(to_junit(run))  # parses cleanly


def test_resolve_cli_dataset_by_name_and_path(tmp_path):
    assert resolve_cli_dataset("qa_golden.yaml") == str(DATASETS_DIR / "qa_golden.yaml")
    f = tmp_path / "custom.yaml"
    f.write_text("- {id: x, input: q, expected: a, tags: [t], gate_metrics: [exact_match]}\n")
    assert resolve_cli_dataset(str(f)) == str(f)
    from llmqa.exceptions import DatasetError
    try:
        resolve_cli_dataset("does-not-exist.yaml")
        assert False, "expected DatasetError"
    except DatasetError:
        pass
