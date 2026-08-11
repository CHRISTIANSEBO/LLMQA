"""Tests for the PR-comment Markdown reporter and the CLI --summary flag."""
from __future__ import annotations

from cli import main
from llmqa.report import PR_COMMENT_MARKER, to_pr_comment
from llmqa.types import CaseResult, EvalRun, MetricResult

DATASET = "datasets/qa_golden.yaml"


def _run() -> EvalRun:
    return EvalRun(
        dataset="datasets/qa_golden.yaml",
        model="mock-strong",
        provider="mock",
        timestamp="2026-08-11T12:00:00Z",
        total_cost_usd=0.0,
        results=[
            CaseResult(
                case_id="capital-france", output="Paris",
                metrics=[
                    MetricResult(metric="exact_match", score=1.0, passed=True),
                    MetricResult(metric="similarity", score=0.9, passed=True),
                ],
            ),
            CaseResult(
                case_id="capital-japan", output="Osaka",
                metrics=[
                    MetricResult(metric="exact_match", score=0.0, passed=False),
                    MetricResult(metric="similarity", score=0.2, passed=False),
                ],
            ),
        ],
    )


def test_pr_comment_has_marker_and_kpis():
    md = to_pr_comment(_run())
    assert md.startswith(PR_COMMENT_MARKER)
    assert "Pass rate | 50% (1/2)" in md
    assert "Avg score |" in md and "95% CI" in md
    assert "By metric:" in md


def test_pr_comment_lists_failing_cases():
    md = to_pr_comment(_run())
    assert "1 failing case(s)" in md
    assert "capital-japan" in md
    # Passing case is not listed in the failing table.
    assert md.count("capital-france") == 0


def test_pr_comment_badge_reflects_gate_passed():
    assert "gates passed" in to_pr_comment(_run(), passed=True)
    assert "gates failed" in to_pr_comment(_run(), passed=False)


def test_pr_comment_includes_notes():
    md = to_pr_comment(_run(), notes=["regression (significant): avg score dropped"])
    assert "regression (significant)" in md


def test_pr_comment_all_passing_badge():
    run = EvalRun(
        dataset="d", model="m", provider="mock",
        results=[
            CaseResult(
                case_id="a", output="x",
                metrics=[MetricResult(metric="exact_match", score=1.0, passed=True)],
            )
        ],
    )
    md = to_pr_comment(run)
    assert "all passing" in md
    assert "failing case" not in md


def test_cli_writes_summary_file(tmp_path):
    out = tmp_path / "summary.md"
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--summary", str(out), "--min-pass-rate", "0.8",
    ])
    assert code == 0
    text = out.read_text()
    assert text.startswith(PR_COMMENT_MARKER)
    assert "Pass rate |" in text


def test_cli_github_summary_appends_env(tmp_path, monkeypatch):
    step = tmp_path / "step_summary.md"
    step.write_text("")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step))
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--github-summary",
    ])
    assert code == 0
    assert PR_COMMENT_MARKER in step.read_text()
