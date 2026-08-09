#!/usr/bin/env python3
"""Plug in a brand-new provider without modifying the package.

Subclass `Provider` and implement `_complete`; the base class gives you retries,
timeouts, and the response cache for free. Here we build a trivial rule-based
provider and run it over the example dataset.

    python examples/custom_provider.py

To make a provider selectable by name on the CLI/dashboard, register it in
`llmqa/providers/__init__.py` (see docs/extending.md).
"""
from __future__ import annotations

from pathlib import Path

from llmqa.metrics import build_metric
from llmqa.providers.base import Provider
from llmqa.report import to_console
from llmqa.runner import run_eval

HERE = Path(__file__).parent
DATASET = HERE / "custom_dataset.yaml"


class RuleBasedProvider(Provider):
    """A toy provider that answers a few known questions and echoes otherwise.

    A real provider would call an API inside `_complete` and compute `cost_usd`
    from the returned token usage.
    """

    name = "rule-based"
    model = "rules-1"

    _ANSWERS = {
        "capital of france": "Paris",
        "capital of the united states": "Washington",
        "apollo 11 land": "1969",
    }

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        low = prompt.lower()
        for key, answer in self._ANSWERS.items():
            if key in low:
                return answer, 0.0
        # Grounded fallback: if context is provided, return it verbatim.
        return (context or prompt), 0.0


def main() -> int:
    provider = RuleBasedProvider()
    metrics = [build_metric("exact_match"), build_metric("hallucination", judge=provider)]
    run = run_eval(DATASET, provider, metrics)
    print(to_console(run))
    print(f"\n{provider.name}/{provider.model}: pass rate {run.pass_rate:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
