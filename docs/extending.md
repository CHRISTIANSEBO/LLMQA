# Extending LLMQA

LLMQA is designed to be extended in three places: **datasets**, **metrics**, and
**providers**. Each is a small, self-contained addition. This guide walks
through all three with working examples. Runnable versions live in
[`examples/`](../examples).

- [Add a custom dataset](#add-a-custom-dataset)
- [Add a metric](#add-a-metric)
- [Add a provider](#add-a-provider)

---

## Add a custom dataset

A dataset is a YAML (or JSON) **list of test cases**. The full schema is
[`datasets/dataset.schema.json`](../datasets/dataset.schema.json) (JSON Schema
draft-07); point your editor at it for autocomplete and validation.

A case has three required fields (`id`, `input`, `expected`) plus optional
matching and gating hints:

```yaml
- id: capital-usa
  input: "What is the capital of the United States? One word."
  expected: "Washington"
  accept: ["Washington, D.C.", "D.C."]   # any alternative counts as a match
  tags: ["geography", "capital"]
  gate_metrics: ["exact_match"]          # only exact_match decides pass/fail

- id: pi
  input: "What is pi to two decimal places?"
  expected: "3.14"
  tolerance: 0.001                       # numeric answers within a delta

- id: apollo
  input: "In what year did Apollo 11 land?"
  expected: "1969"
  expected_regex: "\\b1969\\b"           # match a pattern, not a fixed string

- id: grounded-answer
  input: "According to the passage, when was the company founded?"
  context: "Acme Corp was founded in 1998 in Denver."
  expected: "1998"
  gate_metrics: ["hallucination", "llm_judge"]
```

| Field            | Required | Purpose |
|------------------|----------|---------|
| `id`             | yes      | Unique, stable id (shown in reports, used for single-case re-runs). |
| `input`          | yes      | The prompt sent to the model. |
| `expected`       | yes      | Reference answer for `exact_match` / `similarity`. |
| `context`        | no       | Grounding passage; enables the `hallucination` metric. |
| `tags`           | no       | Labels for `--tags` filtering and per-tag gates. |
| `gate_metrics`   | no       | Which metric(s) gate this case. Empty = all metrics must pass. |
| `accept`         | no       | Extra acceptable exact answers. |
| `expected_regex` | no       | Output matches if this regex is found in it. |
| `tolerance`      | no       | Absolute tolerance for numeric answers. |

Run it by path:

```bash
llmqa run --provider mock --dataset path/to/your_dataset.yaml
```

Or drop the file into the packaged `datasets/` directory and refer to it by name
(`--dataset your_dataset.yaml`). Every run records a content hash of the dataset
so the trend and regression views can tell when a score change is really an
apples-to-oranges comparison.

See [`examples/custom_dataset.py`](../examples/custom_dataset.py) for a fully
programmatic run over a custom dataset.

---

## Add a metric

A metric scores one case's output between `0.0` and `1.0` and decides whether
that score passes. Subclass `Metric` (in `llmqa/metrics/base.py`) and register
it.

```python
# llmqa/metrics/keyword.py
from __future__ import annotations

from ..types import MetricResult, TestCase
from .base import Metric


class KeywordMetric(Metric):
    """Passes when the output contains every keyword in `expected` (comma-split)."""

    name = "keyword"

    def score(self, case: TestCase, output: str) -> MetricResult:
        keywords = [k.strip().lower() for k in case.expected.split(",") if k.strip()]
        hits = sum(1 for k in keywords if k in output.lower())
        score = hits / len(keywords) if keywords else 0.0
        return MetricResult(
            metric=self.name,
            score=score,
            passed=score >= self.threshold,
            detail=f"{hits}/{len(keywords)} keywords present",
        )
```

Register it in `llmqa/metrics/__init__.py` so `--metrics keyword` (and the
dashboard) can find it:

```python
from .keyword import KeywordMetric

REGISTRY = {
    # ...existing metrics...
    "keyword": KeywordMetric,
}
```

Add a test in `tests/test_metrics.py`, then:

```bash
llmqa run --provider mock --metrics keyword
```

**Metric conventions**

- Keep `score` deterministic where possible so CI and regression views are
  stable. LLM-based metrics should support a heuristic fallback (see
  `llm_judge.py`) so they still work under the key-free `mock` provider.
- Return `score=0.0, passed=... ` with a clear `detail` rather than raising; the
  runner shows `detail` in reports.
- Metrics that need context should treat a missing `case.context` as N/A rather
  than a failure (see `hallucination.py`).

---

## Add a provider

A provider turns a prompt into text plus cost. Subclass `Provider` (in
`llmqa/providers/base.py`) and implement one method, `_complete`. The base class
gives you retries, timeouts, and the response cache for free.

```python
# llmqa/providers/echo_provider.py
from __future__ import annotations

from .base import Provider


class EchoProvider(Provider):
    """Trivial example: echoes the prompt back. Real providers call an API."""

    name = "echo"
    model = "echo-1"

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        text = prompt if context is None else f"{context}\n{prompt}"
        cost_usd = 0.0  # compute from token usage for a real, paid provider
        return text, cost_usd
```

Wire it into `get_provider` in `llmqa/providers/__init__.py`:

```python
elif name == "echo":
    from .echo_provider import EchoProvider
    inst = EchoProvider(use_cache=use_cache)
```

Then:

```bash
llmqa run --provider echo
```

**Provider conventions**

- Import heavy SDKs **lazily** inside `__init__` (like `anthropic_provider.py`)
  so the core package installs and the mocks run without that dependency.
- Read credentials from the environment and fail with a clear message that
  points at `--provider mock` when a key is missing.
- Compute `cost_usd` from the returned token usage so cost gates and budgets are
  accurate.
- For determinism, prefer `temperature=0` (and a fixed seed where the API
  supports it) so gating is reproducible.

See [`examples/custom_provider.py`](../examples/custom_provider.py) for a
self-contained provider used in a run without touching the package.
