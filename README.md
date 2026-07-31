# LLMQA — LLM Quality Assurance

[![live demo](https://img.shields.io/badge/live%20demo-online-brightgreen)](https://llmqa-production.up.railway.app/)
[![tests](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml/badge.svg)](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**[▶ Try the live dashboard →](https://llmqa-production.up.railway.app/)**

**LLMQA** is an open-source harness for making LLM quality **measurable, reviewable, and gate-able in CI** — free, key-optional, and provider-agnostic. It treats LLM outputs like software you can test: point it at a golden dataset, pick your metrics, and get a pass/fail report plus **CI quality gates** and **regression detection** so a model or prompt change can't silently degrade quality.

Packaged as a reusable, testable tool usable from the **CLI** or a **web dashboard**.

## Web dashboard

LLMQA ships with a FastAPI + vanilla-JS dashboard: trigger runs, see per-case pass/fail with metric breakdowns, and track a quality trend across runs. It's a single service (the API serves the built frontend), so it deploys anywhere in one process.

![LLMQA dashboard demo](docs/demo.gif)

*Run an evaluation, compare two providers side-by-side, and track the quality trend across runs.*

```bash
pip install -r requirements.txt
python server.py            # -> http://localhost:8000
# optional, for the live providers in the UI (any one enables that model):
export ANTHROPIC_API_KEY=***
export OPENAI_API_KEY=***
export XAI_API_KEY=***
```

API: `GET /api/health`, `GET /api/config`, `GET /api/history`, `GET /api/runs/{id}`, `POST /api/run`.

## Why

Prompt and model changes are notoriously hard to review. "Looks better" isn't a diff you can gate a deploy on. LLMQA turns quality into something measurable and enforceable:

- **Golden dataset** of tagged Q&A cases (factual, math, structured/JSON, RAG grounding, adversarial, summarization, classification).
- **Pluggable metrics** — exact match, similarity, LLM-as-judge, and a hallucination/grounding check.
- **Quality gate** — fail CI (exit 1) if pass rate drops below a threshold.
- **Regression gate** — fail if the average score regresses vs. the last stored run.
- **Provider-agnostic** — deterministic, key-free `mock` provider *tiers* (strong / lite / legacy) for fast/free CI and for demoing regressions, plus real `anthropic`, `openai`, and `xai` (Grok) providers.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run the full suite against the free, deterministic mock provider
python cli.py run --provider mock
```

```
LLMQA run — mock/mock-1
----------------------------------------------------------------
[PASS] capital-france         exact_match=1.00 similarity=1.00 llm_judge=1.00 hallucination=1.00
...
pass rate : 100%  (8/8)
avg score : 1.00
by metric : exact_match=1.00, similarity=1.00, llm_judge=1.00, hallucination=1.00
cost      : $0.0000
```

### Mock provider tiers

The key-free mocks simulate models of different quality, so CI, offline demos,
and the regression/trend dashboard are all meaningful without an API key:

| Provider | Simulates | Behavior |
|----------|-----------|----------|
| `mock` / `mock-strong` | A strong current-gen model | Correct, well formatted, grounded (100% on the golden set). |
| `mock-lite` | A cheaper/smaller model | Right on easy facts, weaker summarization/formatting. |
| `mock-legacy` | An older model | Fabricates instead of refusing, ignores "JSON only", misses facts. |

```bash
python cli.py run --provider mock-strong   # baseline: passes
python cli.py run --provider mock-legacy    # regresses — great for demoing the gates
```

### Run against a real model

Each live provider reads its own key from the environment and is selected by
name. The judge for LLM-based metrics defaults to the same provider.

```bash
# Anthropic Claude (default: claude-haiku-4-5)
export ANTHROPIC_API_KEY=sk-ant-...
python cli.py run --provider anthropic

# OpenAI (default: gpt-4o-mini)
export OPENAI_API_KEY=sk-...
python cli.py run --provider openai

# xAI Grok (default: grok-4-fast) — `grok` is an alias for `xai`
export XAI_API_KEY=xai-...
python cli.py run --provider xai
```

xAI uses an OpenAI-compatible API, so it reuses the `openai` SDK against xAI's
base URL — no extra dependency. Costs for every live provider are computed from
the returned token usage using per-model pricing.

## Usage

```bash
python cli.py run [options]

  --dataset PATH             Golden dataset (default: datasets/qa_golden.yaml)
  --provider NAME            mock | anthropic | openai | xai/grok (default: mock)
  --judge-provider NAME      Separate model for llm_judge/hallucination
                             (avoids a model grading its own output)
  --metrics M [M ...]        exact_match similarity llm_judge hallucination
  --tags T [T ...]           Only run cases with these tags (e.g. rag adversarial)

  # Quality gates (any failing gate exits 1)
  --min-pass-rate FLOAT      Overall pass-rate gate
  --min-tag-pass-rate TAG=R  Per-tag pass-rate gates, e.g. rag=0.9 adversarial=0.8
  --min-metric-score M=S     Per-metric average-score gates, e.g. llm_judge=0.7
  --max-avg-latency-ms FLOAT Latency budget (average case latency)
  --max-p95-latency-ms FLOAT Latency budget (p95 case latency)
  --max-cost FLOAT           Cost budget (total run cost, USD)

  # Regression / baselines
  --regression               Compare to a stored baseline run
  --regression-baseline LBL  Compare to the latest run labeled LBL (default: last run)
  --regression-tolerance F   Allowed avg-score drop before failing (default: 0.05)
  --label LBL                Tag this stored run with a label (e.g. baseline)

  --markdown PATH            Also write a Markdown report to PATH
  --db PATH                  SQLite run history (default: llmqa_runs.db)
  --no-store                 Don't persist this run
  --no-cache                 Disable the in-memory response cache
```

### Determinism & reliability

Because a QA harness has to be reproducible, live providers run at
`temperature=0` with a fixed `seed` (OpenAI/xAI) and a request timeout. Transient
provider errors (429/5xx) are retried with exponential backoff, and a call that
still fails is recorded as a failed case (with the error) instead of aborting the
whole run. Override with `LLMQA_TEMPERATURE` / `LLMQA_SEED`.

### Flexible expected answers

Real golden sets rarely have one exact string answer. Each case can declare:

```yaml
- id: capital-usa
  input: "What is the capital of the United States? One word."
  expected: "Washington"
  accept: ["Washington, D.C.", "D.C."]   # any alternative counts
- id: pi
  input: "What is pi to two decimal places?"
  expected: "3.14"
  tolerance: 0.001                       # numeric answers within a delta
- id: apollo
  input: "In what year did Apollo 11 land?"
  expected: "1969"
  expected_regex: "\\b1969\\b"            # match a pattern, not a fixed string
```

### Response cache (cost saver)

Providers keep an **in-memory response cache** keyed on
`(provider, model, prompt, context)`. Identical calls within a process are
served from the cache instead of re-hitting a paid API a cached hit is billed
at `$0` and marked `cached`. This matters most for the live `anthropic` provider
and the web dashboard, where the same golden case (or a repeated judge prompt)
would otherwise be paid for again on every run. The dashboard reuses one
cache-enabled provider instance per name across requests, so repeated runs
really do hit the cache. The cache is processed local and
never written to disk, so there's no risk of serving stale answers across
restarts. Pass `--no-cache` to force a fresh call per case.

### Examples

```bash
# Only the RAG / grounding cases
python cli.py run --provider mock --tags rag grounding

# CI quality gate: fail the build if pass rate < 80%
python cli.py run --provider mock --min-pass-rate 0.8

# Regression gate: fail if avg score dropped vs the last stored run
python cli.py run --provider mock --regression

# Human-readable report artifact
python cli.py run --provider mock --markdown report.md
```

## The CI-gate story

`tests.yml` runs two things on every push:

1. **Unit tests** (`pytest`) — the harness itself is tested.
2. **Self-eval gate** — `python cli.py run --provider mock --min-pass-rate 0.8`, which exits non-zero if quality drops.

Because the `mock` provider is deterministic and needs no API key, CI is fast, free, and reproducible. Swap in `--provider anthropic` (with a secret key) to gate on a real model.

## Metrics

| Metric | What it measures |
|--------|------------------|
| `exact_match` | Normalized string match, with structural JSON comparison for JSON answers. |
| `similarity` | Token overlap (Jaccard) by default; real embedding cosine similarity via `LLMQA_SIMILARITY=embeddings` (falls back to Jaccard if no key). |
| `llm_judge` | LLM-as-judge with discrete grades + chain-of-thought; heuristic fallback on the mock provider. |
| `hallucination` | Grounding check for cases with context; rewards correct refusals, N/A without context. |

## Architecture

```
llmqa/
  types.py        # Pydantic models: TestCase, MetricResult, CaseResult, EvalRun
  providers/      # base ABC + mock tiers (key-free) + anthropic + openai + xai (Grok)
  metrics/        # base ABC + exact_match, similarity, llm_judge, hallucination
  runner.py       # load dataset, run eval (tag filtering, cost/latency capture)
  report.py       # console + Markdown reporters
  store.py        # SQLite run history for regression/trend
  web/            # FastAPI app + static dashboard (single-service deploy)
cli.py            # `run` command with quality + regression gates
server.py         # web dashboard entrypoint (honors $PORT)
datasets/
  qa_golden.yaml  # tagged golden Q&A cases (with per-case gate_metrics)
tests/            # pytest suite for metrics + runner + web API
```

## Per-case metric gating

Real eval harnesses don't fail a summarization task on exact string match. Each golden case can declare `gate_metrics` — the metric(s) that decide its pass/fail. Other metrics are still scored and shown, but are informational. Omit `gate_metrics` and every metric must pass.

```yaml
- id: summarize
  input: "Summarize in one sentence: ..."
  expected: "..."
  gate_metrics: [llm_judge]   # exact_match is reported but doesn't gate
```

## Contributing

LLMQA is open source (MIT) and contributions are welcome — bug fixes, new
metrics or providers, more golden-dataset cases, and docs. Because the `mock`
providers are deterministic and key-free, you can run the full test suite and
the self-eval gate without any API key:

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
python cli.py run --provider mock --min-pass-rate 0.8 --no-store
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full dev setup, the two CI gates,
and how to add a metric, provider, or dataset case. Please also read the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Deploy

Deploys as a single service — Railway-ready via `railway.json` + `nixpacks.toml`, or with the included **`Dockerfile`** (`docker build -t llmqa . && docker run -p 8000:8000 llmqa`). It honors `$PORT`. Set any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `XAI_API_KEY` to enable that live provider; without any key the dashboard still runs on the free, deterministic `mock` provider.

### Hardening the public API

The dashboard's run endpoints are guarded so a public deploy can't be abused or
burn your API budget. All are env-configurable:

| Env var | Default | Effect |
|---------|---------|--------|
| `LLMQA_ALLOW_REAL_PROVIDERS` | off | Real (paid) providers are **blocked** unless this is truthy — even if keys are set. Mocks always work. |
| `LLMQA_API_TOKEN` | unset | When set, mutating endpoints require `Authorization: Bearer <token>` (or `X-API-Token`). |
| `LLMQA_RATE_LIMIT` / `LLMQA_RATE_WINDOW_S` | 30 / 60 | Per-IP sliding-window rate limit on run endpoints (0 disables). |
| `ALLOWED_ORIGINS` | none | CORS is closed by default (frontend is same-origin); set a comma list only for a split deploy. |

Custom dataset paths sent to the API are restricted to the `datasets/` directory
(no path traversal / arbitrary file reads).

## License

MIT © 2026 Christian Sebo
