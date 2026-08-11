# LLMQA: LLM Quality Assurance

[![PyPI](https://img.shields.io/pypi/v/llmqa)](https://pypi.org/project/llmqa/)
[![live demo (mock)](https://img.shields.io/badge/live%20demo-mock-brightgreen)](https://llmqa-production.up.railway.app/)
[![tests](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml/badge.svg)](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml)
[![coverage](https://codecov.io/gh/CHRISTIANSEBO/LLMQA/branch/main/graph/badge.svg)](https://codecov.io/gh/CHRISTIANSEBO/LLMQA)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**LLMQA** is an open-source harness that makes LLM quality measurable, reviewable, and gate-able in CI. It treats model outputs like software you can test: point it at a golden dataset, pick your metrics, and get a pass/fail report plus CI quality gates and regression detection, so a model or prompt change cannot silently degrade quality.

It runs from the **CLI**, a **web dashboard**, or a **reusable GitHub Action**, and it is provider-agnostic (deterministic key-free mocks for CI, Anthropic, OpenAI, and xAI/Grok for hosted models, plus **local models via Ollama** and **any OpenAI-compatible endpoint** for free, self-hosted, real evaluations).

> The hosted dashboard at the badge above is a **mock-only** showcase (no API keys, so it stays free and safe to share). Real-provider evaluation is intended to run **self-hosted**, where you supply your own keys.

**Key features**

- Golden datasets with per-case metric gating
- Quality + regression gates for CI
- Deterministic key-free mocks + real Anthropic / OpenAI / xAI providers
- Web dashboard with live streaming and trend tracking
- Reusable GitHub Action for PR gating
- Persistent response cache (dramatically reduces cost on repeated runs)

## Table of Contents

- [Why](#why)
- [Quickstart](#quickstart)
- [Web dashboard](#web-dashboard)
- [Gate a pull request (GitHub Action)](#gate-a-pull-request-github-action)
- [Datasets](#datasets)
- [Provider tiers and real models](#provider-tiers-and-real-models)
- [Production runner](#production-runner)
- [Usage](#usage)
  - [Errors & exit codes](#errors-exit-codes)
  - [Determinism & reliability](#determinism-reliability)
  - [Flexible expected answers](#flexible-expected-answers)
  - [Response cache (cost saver)](#response-cache-cost-saver)
  - [Examples](#examples)
- [Metrics](#metrics)
- [Per-case metric gating](#per-case-metric-gating)
- [Architecture](#architecture)
- [The CI-gate story](#the-ci-gate-story)
- [Deploy](#deploy)
  - [Hardening the public API](#hardening-the-public-api)
- [Contributing](#contributing)
- [License](#license)

## Why

Prompt and model changes are hard to review. "Looks better" is not a diff you can gate a deploy on. LLMQA turns quality into something measurable and enforceable:

- **Golden datasets** of tagged cases: factual QA, summarization, RAG grounding, code QA, and safety refusals.
- **Pluggable metrics**: exact match, similarity, LLM-as-judge, and a hallucination/grounding check.
- **Quality gate**: fail CI (exit 1) if the pass rate drops below a threshold.
- **Regression gate**: fail if the average score regresses versus the last stored run.
- **Production runner**: parallel execution, per-call retries and timeouts, a cost ceiling, and a persistent response cache.

## Quickstart

```bash
pip install llmqa

# Run the full suite against the free, deterministic mock provider
llmqa run --provider mock
```

Optional extras: `pip install "llmqa[web]"` for the dashboard, `"llmqa[providers]"`
for real Anthropic/OpenAI/xAI models, or `"llmqa[all]"` for everything. To hack on
LLMQA itself, install from source (see [Contributing](#contributing)):

```bash
git clone https://github.com/CHRISTIANSEBO/LLMQA && cd LLMQA
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"
llmqa run --provider mock       # or `python cli.py run --provider mock`
```

### Most common commands

```bash
# Basic evaluation (mock provider is free & deterministic)
llmqa run --provider mock

# CI quality gate
llmqa run --provider mock --min-pass-rate 0.85

# Regression check against last run
llmqa run --provider mock --regression

# Run only RAG/grounding cases
llmqa run --provider mock --tags rag grounding

# Real model (requires API key)
llmqa run --provider anthropic --dataset factual_qa.yaml
```

```
LLMQA run: mock/mock-strong-1
----------------------------------------------------------------
[PASS] capital-france         exact_match=1.00 similarity=1.00 llm_judge=1.00 hallucination=1.00
...
pass rate : 100%  (12/12)
avg score : 1.00
by metric : exact_match=1.00, similarity=1.00, llm_judge=1.00, hallucination=1.00
cost      : $0.0000
```

## Web dashboard

LLMQA ships with a FastAPI and vanilla-JS dashboard: pick a dataset, trigger runs that stream in case by case, see per-case pass/fail with metric breakdowns, compare two providers, and track a quality trend across runs. It is a single service (the API serves the frontend), so it deploys anywhere in one process.

![LLMQA dashboard demo](docs/demo.gif)

```bash
pip install "llmqa[web]"
python -m llmqa.web         # http://localhost:8000  (or `python server.py` from source)
# Self-hosted only: set any of these to enable a real provider in the UI:
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export XAI_API_KEY=...
# Optional: persist the response cache across restarts
export LLMQA_CACHE=.llmqa_cache.db
```

Dashboard features: a dataset picker, live streaming runs with a pass/fail progress bar, an inline single-case re-run, downloadable Markdown/JSON run reports, provider comparison with a per-case diff, a drag-to-diff of any two historical runs, and a first-visit guided tour.

API: `GET /api/health`, `GET /api/config`, `GET /api/history`, `GET /api/runs/{id}`, `POST /api/run`, `POST /api/run/stream`, `POST /api/compare`.

## Gate a pull request (GitHub Action)

LLMQA is packaged as a reusable composite Action, so a PR can be gated on quality out of the box. It runs an evaluation, writes a JUnit XML report, and annotates failing cases inline on the diff.

```yaml
- name: LLMQA quality gate
  id: llmqa
  uses: CHRISTIANSEBO/LLMQA@main
  with:
    provider: mock            # swap for openai/anthropic/xai on a self-hosted runner
    dataset: qa_golden.yaml   # a packaged dataset name, or a path in your repo
    min-pass-rate: "0.8"
    junit-path: llmqa-results.xml
  # env:
  #   OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
```

A ready-to-copy workflow lives at [.github/workflows/llmqa-example.yml](.github/workflows/llmqa-example.yml). You can also produce the same artifacts from the CLI with `--junit PATH` and `--github-annotations`.

### Baseline snapshots (regression detection without a database)

The SQLite store powers regression detection locally, but CI runners are ephemeral — there is no "previous run" to compare against. A **committed baseline file** fixes this the way snapshot testing does: you record expected per-case scores into a small JSON file, commit it, and gate every run against it. The file is diffable, so a change in expected quality is an explicit, reviewable edit in the PR rather than invisible state.

```bash
# 1) Record a baseline, then commit the file
python cli.py run --provider mock --baseline baselines/qa.json --update-baseline
git add baselines/qa.json && git commit -m "chore: record LLMQA baseline"

# 2) Gate future runs against it (significance-aware; no DB needed)
python cli.py run --provider mock --baseline baselines/qa.json --check-baseline
```

`--check-baseline` reuses the same paired-bootstrap significance test as the regression gate, so it fails only on a real, confident drop — not noise. It also warns when the dataset hash changed (an apples-to-oranges comparison) or when cases were added/removed versus the baseline.

## Datasets

Six datasets ship in `datasets/` (78 cases total). Each case declares which metric(s) gate its pass/fail (see below).

| Dataset | Focus | Typical gate |
|---------|-------|--------------|
| `qa_golden.yaml` | Mixed factual/math/JSON/RAG/adversarial baseline | per case |
| `factual_qa.yaml` | Closed-book facts | exact match / similarity |
| `summarization.yaml` | Passage to short summary | llm_judge |
| `rag_grounding.yaml` | Context-grounded QA, including "not in the context" cases | hallucination, llm_judge |
| `code_qa.yaml` | Python, git, HTTP, SQL, regex | llm_judge / similarity |
| `safety_refusals.yaml` | Prompts a model should refuse, plus benign look-alikes | llm_judge |

Pick a dataset in the dashboard's Dataset dropdown, or with `--dataset` on the CLI (a packaged name like `code_qa.yaml`, or a path to your own file). Every run records a short content hash of the dataset (`dataset_hash`) so the trend and regression views can tell when a score change is really an apples-to-oranges comparison.

**Bring your own dataset.** A dataset is a YAML/JSON list of cases; the full schema is [`datasets/dataset.schema.json`](datasets/dataset.schema.json) (point your editor at it for autocomplete/validation). See [docs/extending.md](docs/extending.md) for a walkthrough and [`examples/`](examples/) for runnable scripts (custom dataset, provider comparison, a custom provider).

## Provider tiers and real models

The key-free mocks simulate models of different quality, so CI, offline demos, and the regression/trend views are meaningful without an API key:

| Provider | Simulates | Behavior |
|----------|-----------|----------|
| `mock` / `mock-strong` | A strong current-gen model | Correct, well formatted, grounded. |
| `mock-lite` | A cheaper/smaller model | Right on easy facts, weaker on summarization/formatting. |
| `mock-legacy` | An older model | Fabricates instead of refusing, ignores "JSON only", misses facts. |

Real providers read their own key from the environment and are selected by name. The judge for LLM-based metrics defaults to the same provider.

```bash
export ANTHROPIC_API_KEY=sk-ant-...   ; python cli.py run --provider anthropic
export OPENAI_API_KEY=sk-...          ; python cli.py run --provider openai
export XAI_API_KEY=xai-...            ; python cli.py run --provider xai   # `grok` is an alias
```

xAI uses an OpenAI-compatible API, so it reuses the `openai` SDK against xAI's base URL with no extra dependency. Costs for every live provider are computed from the returned token usage using per-model pricing.

### Local & OpenAI-compatible models (free, no vendor key)

Evaluate **real** models without a paid key by pointing LLMQA at a local server or any OpenAI-compatible endpoint:

```bash
# Local model via Ollama (https://ollama.com) — free, offline, cost reported as $0
ollama pull llama3.2
LLMQA_LOCAL_MODEL=llama3.2 python cli.py run --provider ollama
#   OLLAMA_HOST overrides the server URL (default http://localhost:11434)

# Any OpenAI-compatible endpoint (OpenRouter, Together, Fireworks, vLLM, LM Studio, ...)
export LLMQA_OPENAI_BASE_URL=https://openrouter.ai/api/v1
export LLMQA_OPENAI_API_KEY=sk-...        # or reuse OPENAI_API_KEY
export LLMQA_MODEL=meta-llama/llama-3.1-8b-instruct
export LLMQA_PRICE_IN=0.05 LLMQA_PRICE_OUT=0.10   # optional, for accurate cost
python cli.py run --provider openai-compat
```

Both reuse the `openai` SDK, so no extra dependency is needed. Ollama reports `$0` (local inference is free); `openai-compat` reports `$0` unless you supply `LLMQA_PRICE_IN`/`LLMQA_PRICE_OUT`.

## Production runner

Built for real evaluations against paid providers:

- **Concurrency**: `--concurrency N` runs cases in parallel (provider calls are I/O bound, so this is a large speedup). The default of 1 stays serial and deterministic.
- **Retries and timeouts**: each provider call retries with exponential backoff (`--retries`) and can enforce a hard per-call timeout (`--timeout`). Exhausted retries raise a typed error instead of aborting a run.
- **Cost ceiling**: `--max-cost USD` stops a run the moment accumulated cost crosses the ceiling and flags it as stopped early.
- **Persistent cache**: `--cache-path FILE` (or `LLMQA_CACHE` for the web app) keeps a SQLite response cache keyed on a content hash, so identical calls are free across restarts and across workers. Without a path the cache is per-process/in-memory. Use `--no-cache` to force a fresh call per case.

## Usage

<details>
<summary><strong>Full CLI flag reference</strong> (click to expand)</summary>

```bash
python cli.py run [options]

  --dataset NAME|PATH        Packaged dataset name (e.g. qa_golden.yaml) or a file path
  --provider NAME            mock | mock-strong | mock-lite | mock-legacy | anthropic | openai |
                             xai/grok | ollama (local, free) | openai-compat (any OpenAI URL)
  --judge-provider NAME      Separate model for llm_judge/hallucination
                             (avoids a model grading its own output)
  --metrics M [M ...]        exact_match similarity llm_judge hallucination
  --tags T [T ...]           Only run cases with these tags (e.g. rag adversarial)

  # Execution / resilience
  --concurrency N            Run N cases in parallel (default: 1)
  --timeout SECONDS          Hard per-call timeout for a provider request
  --retries N                Retries per provider call on failure (default: 2)
  --judge-samples N          Poll the LLM judge N times and take the majority grade
  --max-cost USD             Stop the run once accumulated cost reaches this ceiling

  # Quality gates (any failing gate exits 1)
  --min-pass-rate FLOAT      Overall pass-rate gate
  --min-tag-pass-rate TAG=R  Per-tag pass-rate gates, e.g. rag=0.9 adversarial=0.8
  --min-metric-score M=S     Per-metric average-score gates, e.g. llm_judge=0.7
  --max-avg-latency-ms FLOAT Latency budget (average case latency)
  --max-p95-latency-ms FLOAT Latency budget (p95 case latency)
  --max-cost-budget USD      Cost budget gate (fail if total run cost exceeds)

  # Regression / baselines
  --regression               Compare to a stored baseline run
  --regression-baseline LBL  Compare to the latest run labeled LBL (default: last run)
  --regression-tolerance F   Allowed avg-score drop before failing (default: 0.05)
  --label LBL                Tag this stored run with a label (e.g. baseline)

  -v, --verbose              Verbose logging on stderr (retries, cache hits, timings)
  --markdown PATH            Also write a Markdown report to PATH
  --junit PATH               Write a JUnit XML report to PATH (for CI test reporting)
  --github-annotations       Emit ::error:: annotations for failing cases (GitHub Actions)
  --db PATH                  SQLite run history (default: llmqa_runs.db)
  --no-store                 Do not persist this run
  --no-cache                 Disable the response cache
  --cache-path FILE          Persist the response cache to this SQLite file
```

</details>

### Errors & exit codes

LLMQA fails loudly but cleanly. User-fixable problems (a missing/malformed
dataset, an unset API key, a bad option) print a one-line `error: ...` on stderr
and exit **2** instead of dumping a traceback; a failing quality/regression gate
exits **1**; a clean pass exits **0**. Add `-v/--verbose` to see the full stack
and debug logging (provider retries, cache hits, timings). `llmqa --version`
prints the version.

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
served from the cache instead of re-hitting a paid API. A cached hit is billed
at `$0` and marked `cached`. This matters most for the live `anthropic` provider
and the web dashboard, where the same golden case (or a repeated judge prompt)
would otherwise be paid for again on every run. The dashboard reuses one
cache-enabled provider instance per name across requests, so repeated runs
really do hit the cache. Pass `--cache-path FILE` to persist the cache to a
SQLite file (shared across processes / surviving restarts), or `--no-cache` to
force a fresh call per case.

### Examples

```bash
# Only the RAG / grounding cases
python cli.py run --provider mock --tags rag grounding

# CI quality gate: fail the build if the pass rate is under 80%
python cli.py run --provider mock --min-pass-rate 0.8

# Regression gate: fail if avg score dropped versus the last stored run
python cli.py run --provider mock --regression

# A real run: parallel, with a timeout, a cost ceiling, a persistent cache, and CI artifacts
python cli.py run --provider openai --dataset factual_qa.yaml \
  --concurrency 8 --timeout 30 --max-cost 0.50 --cache-path .llmqa_cache.db \
  --junit results.xml --github-annotations
```

## Metrics

| Metric | What it measures |
|--------|------------------|
| `exact_match` | Normalized string match, with structural JSON comparison for JSON answers. |
| `similarity` | Token overlap (Jaccard) by default; real embedding cosine similarity via `LLMQA_SIMILARITY=embeddings` (falls back to Jaccard if no key). |
| `llm_judge` | LLM-as-judge with discrete grades and chain-of-thought. Robust verdict parsing with a heuristic fallback, and optional self-consistency (majority vote over N samples via `--judge-samples`). Uses a deterministic heuristic on the mock provider. |
| `hallucination` | Grounding check for cases with context; rewards correct refusals, and is N/A without context. |

## Per-case metric gating

Real eval harnesses do not fail a summarization task on exact string match. Each case can declare `gate_metrics`, the metric(s) that decide its pass/fail. Other metrics are still scored and shown, but are informational. Omit `gate_metrics` and every metric must pass.

```yaml
- id: summarize
  input: "Summarize in one sentence: ..."
  expected: "..."
  gate_metrics: [llm_judge]   # exact_match is reported but does not gate
```

## Architecture

```
llmqa/
  types.py        # Pydantic models: TestCase, MetricResult, CaseResult, EvalRun
  catalog.py      # dataset discovery, safe name resolution, content hashing
  cache.py        # response cache backends (in-memory + SQLite)
  providers/      # base ABC (retries/timeout/cache) + mock tiers + anthropic + openai + xai
  metrics/        # base ABC + exact_match, similarity, llm_judge, hallucination
  runner.py       # load dataset, run eval (concurrency, cost ceiling, cost/latency capture)
  report.py       # console + Markdown + JUnit XML reporters
  store.py        # SQLite run history for regression/trend
  web/            # FastAPI app + static dashboard (single-service deploy)
cli.py            # `run` command with quality + regression gates
server.py         # web dashboard entrypoint (honors $PORT)
action.yml        # reusable GitHub Action (composite)
datasets/         # six tagged datasets with per-case gate_metrics
tests/            # pytest suite for metrics, runner, cache, catalog, judge, web, reports
```

## The CI-gate story

`tests.yml` runs two things on every push: the unit tests (`pytest`), and a self-eval gate (`python cli.py run --provider mock --min-pass-rate 0.8`) that exits non-zero if quality drops. Because the `mock` provider is deterministic and key-free, CI is fast, free, and reproducible. Swap in a real provider (with a secret key, on a self-hosted runner) to gate on a real model.

## Deploy

Deploys as a single service — Railway-ready via `railway.json` and `nixpacks.toml`, or with the included **`Dockerfile`** (`docker build -t llmqa . && docker run -p 8000:8000 llmqa`). It honors `$PORT`. On a self-hosted deploy, set any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `XAI_API_KEY` to enable that live provider, and set `LLMQA_CACHE` to a file path to persist the response cache. Without any key the dashboard runs on the free, deterministic `mock` provider.

### Hardening the public API

The dashboard's run endpoints are guarded so a public deploy can't be abused or
burn your API budget. All are env-configurable:

| Env var | Default | Effect |
|---------|---------|--------|
| `LLMQA_ALLOW_REAL_PROVIDERS` | off | Real (paid) providers are **blocked** unless this is truthy — even if keys are set. Mocks always work. |
| `LLMQA_API_TOKEN` | unset | When set, mutating endpoints require `Authorization: Bearer <token>` (or `X-API-Token`). |
| `LLMQA_RATE_LIMIT` / `LLMQA_RATE_WINDOW_S` | 30 / 60 | Per-IP sliding-window rate limit on run endpoints (0 disables). |
| `ALLOWED_ORIGINS` | none | CORS is closed by default (frontend is same-origin); set a comma list only for a split deploy. |

Request-supplied dataset names are resolved only against the packaged
`datasets/` directory (no path traversal / arbitrary file reads). Uploaded/pasted
datasets (via the dashboard's validator or `POST /api/validate-dataset`) are
validated in memory and never written to disk.

Additional response headers and limits are applied automatically: a baseline
**Content-Security-Policy** and security headers (override the CSP with
`LLMQA_CSP`), a request **body-size cap** (`LLMQA_MAX_BODY_BYTES`, default 256
KiB), and a per-request `X-Request-ID` for log correlation. A `GET /metrics`
endpoint exposes Prometheus counters, and `GET /api/health?deep=1` runs a cheap
liveness probe.

> **Note:** the per-IP rate limiter is **in-process** (per worker). Behind
> multiple workers or replicas each process keeps its own window, so the
> effective limit scales with the worker count. For a hard global limit, run a
> single worker or enforce the limit at your proxy/load balancer.

## Contributing

LLMQA is open source (MIT) and contributions are welcome: bug fixes, new metrics or providers, more dataset cases, and docs. Because the mock providers are deterministic and key-free, you can run the full test suite and the self-eval gate without any API key:

```bash
pip install -e ".[web,dev]"
pytest tests/ -v
python cli.py run --provider mock --min-pass-rate 0.8 --no-store
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full dev setup and how to add a metric, provider, or dataset case. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

## License

MIT (c) 2026 Christian Sebo

See [CHANGELOG.md](CHANGELOG.md) for recent changes.
