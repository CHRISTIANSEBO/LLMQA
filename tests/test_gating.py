"""Aggregate helpers that power the CLI gates (per-tag, latency, cost)."""
from __future__ import annotations

from llmqa.types import CaseResult, EvalRun, MetricResult


def _cr(case_id, tags, passed, latency, score=1.0, cost=0.0):
    return CaseResult(
        case_id=case_id,
        tags=tags,
        output="x",
        latency_ms=latency,
        cost_usd=cost,
        metrics=[MetricResult(metric="exact_match", score=score if passed else 0.0, passed=passed)],
    )


def _run():
    return EvalRun(
        dataset="d", model="m", provider="mock",
        results=[
            _cr("a", ["easy", "rag"], True, 100, cost=0.001),
            _cr("b", ["rag"], False, 300, cost=0.002),
            _cr("c", ["easy"], True, 200, cost=0.0),
        ],
        total_cost_usd=0.003,
    )


def test_pass_rate_by_tag():
    r = _run()
    by_tag = r.pass_rate_by_tag()
    assert by_tag["easy"] == 1.0        # a, c both pass
    assert by_tag["rag"] == 0.5         # a passes, b fails


def test_latency_aggregates():
    r = _run()
    assert r.avg_latency_ms == (100 + 300 + 200) / 3
    # p95 nearest-rank of [100,200,300] -> top value
    assert r.p95_latency_ms == 300


def test_score_by_metric_present():
    r = _run()
    assert "exact_match" in r.score_by_metric()


def test_cli_kv_parser():
    from cli import _parse_kv

    assert _parse_kv(["rag=0.9", "easy=1.0"], kind="x") == {"rag": 0.9, "easy": 1.0}


def test_cli_gate_fails_on_tag_and_latency():
    import argparse

    from cli import _evaluate_gates

    args = argparse.Namespace(
        min_pass_rate=None,
        min_tag_pass_rate=["rag=0.9"],
        min_metric_score=None,
        max_avg_latency_ms=100,   # avg is 200 -> fail
        max_p95_latency_ms=None,
        max_cost=None,
        regression_tolerance=0.05,
    )
    code = _evaluate_gates(_run(), args, baseline=None)
    assert code == 1


def test_cli_gate_passes_when_thresholds_met():
    import argparse

    from cli import _evaluate_gates

    args = argparse.Namespace(
        min_pass_rate=0.5,
        min_tag_pass_rate=["easy=1.0"],
        min_metric_score=None,
        max_avg_latency_ms=1000,
        max_p95_latency_ms=1000,
        max_cost=1.0,
        regression_tolerance=0.05,
    )
    code = _evaluate_gates(_run(), args, baseline=None)
    assert code == 0
