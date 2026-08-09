#!/usr/bin/env python3
"""Run an evaluation over your own dataset file, programmatically.

Uses the free, deterministic `mock` provider, so no API key is needed:

    python examples/custom_dataset.py
"""
from __future__ import annotations

from pathlib import Path

from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.report import to_console
from llmqa.runner import run_eval

HERE = Path(__file__).parent
DATASET = HERE / "custom_dataset.yaml"


def main() -> int:
    provider = get_provider("mock")

    # Score with a couple of metrics; each case's `gate_metrics` decides which
    # of these actually gate its pass/fail (the rest are informational).
    metrics = [build_metric("exact_match"), build_metric("hallucination", judge=provider)]

    run = run_eval(DATASET, provider, metrics)
    print(to_console(run))
    print(f"\npass rate: {run.pass_rate:.0%}  avg score: {run.avg_score:.2f}")

    # Note: the deterministic `mock` provider only "knows" the answers to the
    # packaged datasets, so a hand-written dataset like this one will show some
    # failures. Point --provider at a real model (anthropic/openai/xai) to get a
    # meaningful pass rate, then gate on it, e.g.:
    #   return 0 if run.pass_rate >= 0.8 else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
