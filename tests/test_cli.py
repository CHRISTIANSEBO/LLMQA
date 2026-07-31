"""End-to-end CLI tests driving main() directly."""
from __future__ import annotations

from pathlib import Path

from cli import main

DATASET = str(Path(__file__).resolve().parent.parent / "datasets" / "qa_golden.yaml")


def test_cli_run_mock_passes(tmp_path, capsys):
    db = tmp_path / "runs.db"
    md = tmp_path / "report.md"
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--db", str(db), "--markdown", str(md), "--min-pass-rate", "0.8",
    ])
    out = capsys.readouterr().out
    assert code == 0
    assert "pass rate" in out
    assert md.exists() and md.read_text().startswith("# LLMQA Report")
    assert db.exists()


def test_cli_legacy_fails_gate(tmp_path):
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock-legacy",
        "--no-store", "--min-pass-rate", "0.95",
    ])
    assert code == 1


def test_cli_tag_and_latency_gates(tmp_path):
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock", "--no-store",
        "--min-tag-pass-rate", "rag=0.9", "--min-metric-score", "exact_match=0.7",
        "--max-avg-latency-ms", "1000", "--max-cost", "1.0",
    ])
    assert code == 0


def test_cli_separate_judge_provider(tmp_path):
    # --judge-provider builds a distinct judge; mock keeps it deterministic.
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--judge-provider", "mock-strong", "--no-store", "--min-pass-rate", "0.8",
    ])
    assert code == 0


def test_cli_named_baseline_regression(tmp_path):
    db = tmp_path / "runs.db"
    # Store a strong baseline under a label.
    assert main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--db", str(db), "--label", "baseline",
    ]) == 0
    # A weaker run compared to that baseline should trip the regression gate.
    code = main([
        "run", "--dataset", DATASET, "--provider", "mock-legacy",
        "--db", str(db), "--no-store", "--regression",
        "--regression-baseline", "baseline",
    ])
    assert code == 1
