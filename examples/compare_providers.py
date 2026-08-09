#!/usr/bin/env python3
"""Run two providers on the same dataset and diff their pass rates.

Uses the key-free mock tiers (`mock-strong` vs `mock-legacy`) so it runs with no
API key. Swap in `anthropic` / `openai` / `xai` (with keys set) to compare real
models.

    python examples/compare_providers.py
"""
from __future__ import annotations

from pathlib import Path

from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.runner import run_eval

HERE = Path(__file__).parent
DATASET = HERE / "custom_dataset.yaml"

PROVIDER_A = "mock-strong"
PROVIDER_B = "mock-legacy"


def _run(name: str):
    provider = get_provider(name)
    metrics = [
        build_metric("exact_match"),
        build_metric("similarity"),
        build_metric("hallucination", judge=provider),
    ]
    return run_eval(DATASET, provider, metrics)


def main() -> int:
    run_a = _run(PROVIDER_A)
    run_b = _run(PROVIDER_B)

    by_id_a = {r.case_id: r for r in run_a.results}
    by_id_b = {r.case_id: r for r in run_b.results}

    print(f"{'case':<22} {PROVIDER_A:>12} {PROVIDER_B:>12}   delta")
    print("-" * 62)
    for case_id in by_id_a:
        a, b = by_id_a[case_id], by_id_b.get(case_id)
        a_ok = "PASS" if a.passed else "FAIL"
        b_ok = "PASS" if (b and b.passed) else "FAIL"
        mark = "" if (b and a.passed == b.passed) else "  <-- differs"
        print(f"{case_id:<22} {a_ok:>12} {b_ok:>12}{mark}")

    print("-" * 62)
    print(f"{'pass rate':<22} {run_a.pass_rate:>11.0%} {run_b.pass_rate:>11.0%}")
    print(f"{'avg score':<22} {run_a.avg_score:>12.2f} {run_b.avg_score:>12.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
