"""Tests for committed baseline snapshot files and their significance-aware gate."""
from __future__ import annotations

import json

import pytest

from cli import main
from llmqa.baseline import (
    build_baseline,
    compare_to_baseline,
    load_baseline,
    write_baseline,
)
from llmqa.exceptions import DatasetError
from llmqa.types import CaseResult, EvalRun, MetricResult

DATASET = "datasets/qa_golden.yaml"


def _run(scores: dict[str, float], *, dataset_hash: str = "sha256:aaa") -> EvalRun:
    return EvalRun(
        dataset="d", model="m", provider="mock", dataset_hash=dataset_hash,
        results=[
            CaseResult(
                case_id=cid, output="x",
                metrics=[MetricResult(metric="similarity", score=s, passed=s >= 0.5)],
            )
            for cid, s in scores.items()
        ],
    )


def test_build_and_roundtrip(tmp_path):
    run = _run({f"c{i}": 1.0 for i in range(5)})
    data = build_baseline(run)
    assert data["n_cases"] == 5
    assert data["case_scores"]["c0"] == 1.0

    path = tmp_path / "b.json"
    write_baseline(run, path)
    loaded = load_baseline(path)
    assert loaded["case_scores"] == data["case_scores"]


def test_write_creates_parent_dirs(tmp_path):
    path = tmp_path / "nested" / "dir" / "b.json"
    write_baseline(_run({"a": 1.0}), path)
    assert path.exists()
    assert json.loads(path.read_text())["case_scores"] == {"a": 1.0}


def test_load_missing_raises_friendly(tmp_path):
    with pytest.raises(DatasetError, match="Baseline file not found"):
        load_baseline(tmp_path / "nope.json")


def test_load_invalid_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text('{"not": "a baseline"}')
    with pytest.raises(DatasetError, match="not a valid LLMQA baseline"):
        load_baseline(p)


def test_significant_drop_is_regression():
    base = build_baseline(_run({f"c{i}": 1.0 for i in range(12)}))
    cur = _run({f"c{i}": 0.4 for i in range(12)})
    cmp = compare_to_baseline(cur, base, tolerance=0.05)
    assert cmp.is_regression
    assert cmp.comparable


def test_tiny_drop_not_regression():
    base = build_baseline(_run({f"c{i}": 0.80 for i in range(12)}))
    cur = _run({f"c{i}": 0.78 for i in range(12)})
    cmp = compare_to_baseline(cur, base, tolerance=0.05)
    assert not cmp.is_regression


def test_hash_change_is_warned():
    base = build_baseline(_run({"a": 1.0, "b": 1.0}, dataset_hash="sha256:old"))
    cur = _run({"a": 1.0, "b": 1.0}, dataset_hash="sha256:new")
    cmp = compare_to_baseline(cur, base)
    assert cmp.hash_changed
    assert any(level == "warn" for level, _ in cmp.lines())


def test_added_and_removed_cases_tracked():
    base = build_baseline(_run({"a": 1.0, "b": 1.0}))
    cur = _run({"a": 1.0, "c": 1.0})
    cmp = compare_to_baseline(cur, base)
    assert cmp.added_cases == ["c"]
    assert cmp.removed_cases == ["b"]


def test_no_overlap_cannot_compare():
    base = build_baseline(_run({"a": 1.0}))
    cur = _run({"z": 1.0})
    cmp = compare_to_baseline(cur, base)
    assert not cmp.comparable
    assert any(level == "fail" for level, _ in cmp.lines())


# --- End-to-end CLI: record a baseline, then gate against it ------------------

def test_cli_update_then_check_passes(tmp_path):
    path = tmp_path / "baseline.json"
    # Record a baseline from a strong run (does not gate).
    assert main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--baseline", str(path), "--update-baseline",
    ]) == 0
    assert path.exists()
    # The same strong provider checked against it: no regression.
    assert main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--baseline", str(path), "--check-baseline",
    ]) == 0


def test_cli_check_catches_regression(tmp_path):
    path = tmp_path / "baseline.json"
    main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--baseline", str(path), "--update-baseline",
    ])
    # A weaker provider checked against the strong baseline should fail (exit 1).
    assert main([
        "run", "--dataset", DATASET, "--provider", "mock-legacy",
        "--no-store", "--baseline", str(path), "--check-baseline",
    ]) == 1


def test_cli_update_requires_baseline_path():
    # --update-baseline without --baseline is a user error (exit 2).
    assert main([
        "run", "--dataset", DATASET, "--provider", "mock",
        "--no-store", "--update-baseline",
    ]) == 2
