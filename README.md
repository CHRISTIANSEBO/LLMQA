# LLMQA: LLM Quality Assurance

[![live demo (mock)](https://img.shields.io/badge/live%20demo-mock-brightgreen)](https://llmqa-production.up.railway.app/)
[![tests](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml/badge.svg)](https://github.com/CHRISTIANSEBO/LLMQA/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

**LLMQA** is an open-source harness that makes LLM quality measurable, reviewable, and gate-able in CI. It treats model outputs like software you can test: point it at a golden dataset, pick your metrics, and get a pass/fail report plus CI quality gates and regression detection, so a model or prompt change cannot silently degrade quality.

It runs from the **CLI**, a **web dashboard**, or a **reusable GitHub Action**, and it is provider-agnostic (deterministic key-free mocks for CI, plus Anthropic, OpenAI, and xAI/Grok for real evaluations).

> The hosted dashboard at the badge above is a **mock-only** showcase (no API keys, so it stays free and safe to share). Real-provider evaluation is intended to run **self-hosted**, where you supply your own keys.

## Why

Prompt and model changes are hard to review. "Looks better" is not a diff you can gate a deploy on. LLMQA turns quality into something measurable and enforceable:

- **Golden datasets** of tagged cases: factual QA, summarization, RAG grounding, code QA, and safety refusals.
- **Pluggable metrics**: exact match, similarity, LLM-as-judge, and a hallucination/grounding check.
- **Quality gate**: fail CI (exit 1) if the pass rate drops below a threshold.
- **Regression gate**: fail if the average score regresses versus the last stored run.
- **Production runner**: parallel execution, per-call retries and timeouts, a cost ceiling, and a persistent response cache.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[web,dev]"

# Run the full suite against the free, deterministic mock provider
python cli.py run --provider mock       # or `llmqa run --provider mock` after install
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
pip install -e ".[web]"
python server.py            # http://localhost:8000
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

## Production runner

Built for real evaluations against paid providers:

- **Concurrency**: `--concurrency N` runs cases in parallel (provider calls are I/O bound, so this is a large speedup). The default of 1 stays serial and deterministic.
- **Retries and timeouts**: each provider call retries with exponential backoff (`--retries`) and can enforce a hard per-call timeout (`--timeout`). Exhausted retries raise a typed error instead of aborting a run.
- **Cost ceiling**: `--max-cost USD` stops a run the moment accumulated cost crosses the ceiling and flags it as stopped early.
- **Persistent cache**: `--cache-path FILE` (or `LLMQA_CACHE` for the web app) keeps a SQLite response cache keyed on a content hash, so identical calls are free across restarts and across workers. Without a path the cache is per-process/in-memory. Use `--no-cache` to force a fresh call per case.

## Usage

```bash
python cli.py run [options]

  --dataset NAME|PATH        Packaged dataset name (e.g. qa_golden.yaml) or a file path
  --provider NAME            mock | mock-strong | mock-lite | mock-legacy | anthropic | openai | xai/grok
  --metrics M [M ...]        exact_match similarity llm_judge hallucination
  --tags T [T ...]           Only run cases with these tags (e.g. rag adversarial)
  --concurrency N            Run N cases in parallel (default: 1)
  --timeout SECONDS          Hard per-call timeout for a provider request
  --retries N                Retries per provider call on failure (default: 2)
  --max-cost USD             Stop the run once accumulated cost reaches this ceiling
  --judge-samples N          Poll the LLM judge N times and take the majority grade
  --min-pass-rate FLOAT      Quality gate: exit 1 if the pass rate is below this
  --regression               Compare to the last stored run
  --regression-tolerance F   Allowed avg-score drop before failing (default: 0.05)
  --markdown PATH            Write a Markdown report to PATH
  --junit PATH               Write a JUnit XML report to PATH (for CI test reporting)
  --github-annotations       Emit ::error:: annotations for failing cases (GitHub Actions)
  --db PATH                  SQLite run history (default: llmqa_runs.db)
  --no-store                 Do not persist this run
  --no-cache                 Disable the response cache
  --cache-path FILE          Persist the response cache to this SQLite file
```

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
| `similarity` | Token overlap (Jaccard) similarity, swappable for embeddings later. |
| `llm_judge` | LLM-as-judge with discrete grades and chain-of-thought. Robust verdict parsing with a heuristic fallback, and optional self-consistency (majority vote over N samples). Uses a deterministic heuristic on the mock provider. |
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

Deploys as a single service (Railway-ready via `railway.json` and `nixpacks.toml`, honors `$PORT`). On a self-hosted deploy, set any of `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `XAI_API_KEY` to enable that live provider, and set `LLMQA_CACHE` to a file path to persist the response cache. Without any key the dashboard runs on the free, deterministic `mock` provider.

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
