"""Tests for the console + Markdown report renderers.

These cover llmqa/report.py, which turns an EvalRun into a human-readable
console summary and a shareable Markdown table.
"""
from llmqa.report import to_console, to_markdown
from llmqa.types import CaseResult, EvalRun, MetricResult


def _sample_run() -> EvalRun:
    """A small but representative run: one passing case, one failing case,
    two metrics each."""
    return EvalRun(
        dataset="datasets/qa_golden.yaml",
        model="mock-strong",
        provider="mock",
        timestamp="2026-07-09T19:00:00Z",
        total_cost_usd=0.0123,
        results=[
            CaseResult(
                case_id="capital-france",
                output="Paris",
                metrics=[
                    MetricResult(metric="exact_match", score=1.0, passed=True),
                    MetricResult(metric="similarity", score=0.9, passed=True),
                ],
            ),
            CaseResult(
                case_id="capital-japan",
                output="Osaka",
                metrics=[
                    MetricResult(metric="exact_match", score=0.0, passed=False),
                    MetricResult(metric="similarity", score=0.2, passed=False),
                ],
            ),
        ],
    )


def test_console_contains_header_and_summary():
    run = _sample_run()
    out = to_console(run)

    # Header identifies provider/model and dataset.
    assert "mock/mock-strong" in out
    assert "datasets/qa_golden.yaml" in out

    # Both cases appear with PASS/FAIL markers.
    assert "[PASS] capital-france" in out
    assert "[FAIL] capital-japan" in out

    # Aggregate summary lines are present.
    assert "pass rate : 50%  (1/2)" in out
    assert "avg score :" in out
    assert "cost      : $0.0123" in out


def test_console_reports_per_metric_scores():
    out = to_console(_sample_run())
    # exact_match avg over the two cases = (1.0 + 0.0) / 2 = 0.50
    assert "exact_match=0.50" in out
    # similarity avg = (0.9 + 0.2) / 2 = 0.55
    assert "similarity=0.55" in out


def test_markdown_has_title_and_table_header():
    md = to_markdown(_sample_run())

    assert md.startswith("# LLMQA Report — mock/mock-strong")
    assert "**Pass rate:** 50%" in md
    assert "**Cost:** $0.0123" in md

    # Table header lists every metric column.
    assert "| Case | Result | exact_match | similarity |" in md
    # Passing / failing cases use the check / cross marks.
    assert "| capital-france | ✅ |" in md
    assert "| capital-japan | ❌ |" in md


def test_empty_run_does_not_crash():
    """An EvalRun with no results should still render cleanly (0% pass rate)."""
    run = EvalRun(dataset="empty.yaml", model="m", provider="p")

    console = to_console(run)
    assert "pass rate : 0%  (0/0)" in console

    md = to_markdown(run)
    assert md.startswith("# LLMQA Report — p/m")
