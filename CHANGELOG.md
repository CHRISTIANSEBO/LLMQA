# Changelog

All notable changes to LLMQA are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project aims
to follow [Semantic Versioning](https://semver.org/).

## [0.3.0] — 2026-08-11

Theme: *from pass/fail to real evaluation* — make the harness statistically
credible, able to run real models for free, and CI-native.

### Added

- **Local & OpenAI-compatible providers** for real evaluations without a paid
  vendor key:
  - `ollama` (alias `local`): evaluate against a local Ollama / LM Studio server
    via its OpenAI-compatible API. No key required; cost reported as `$0`.
    Configurable via `OLLAMA_HOST` and `LLMQA_LOCAL_MODEL`.
  - `openai-compat` (alias `compat`): evaluate against **any** OpenAI-compatible
    endpoint (OpenRouter, Together, Fireworks, vLLM, LM Studio, self-hosted
    gateways) via `LLMQA_OPENAI_BASE_URL` + `LLMQA_OPENAI_API_KEY`, model from
    `LLMQA_MODEL`, optional pricing via `LLMQA_PRICE_IN`/`LLMQA_PRICE_OUT`.
- **Statistical significance on the regression gate** (`llmqa/stats.py`,
  stdlib-only percentile bootstrap): a regression now requires **both** a
  point-estimate drop beyond `--regression-tolerance` **and** a paired bootstrap
  CI for `(current - baseline)` entirely below zero, so the gate stops firing on
  noise. New `--regression-confidence` flag (default 0.95). The console
  `avg score` line now shows a 95% bootstrap confidence interval.
- **Committed baseline snapshot files** (`llmqa/baseline.py`) for DB-free
  regression detection in ephemeral CI: `--baseline PATH` with
  `--update-baseline` (record a diffable JSON snapshot) and `--check-baseline`
  (significance-aware gate). Warns on dataset-hash changes and added/removed
  cases.
- **Pull-request results comment** from the GitHub Action: a sticky, in-place
  comment with a pass/fail badge, KPI table (pass rate, avg score + CI, latency,
  cost), per-metric scores, and a collapsible failing-cases table. New CLI
  `--summary PATH` and `--github-summary` (writes the same Markdown to
  `$GITHUB_STEP_SUMMARY`). New action inputs `comment-on-pr`, `github-token`,
  `summary-path`.

### Changed

- Gate evaluation refactored into `GateOutcome` / `_run_gates()` so the PR
  summary reflects the actual gate result (existing gate behavior unchanged).
- `EvalRun` gains `case_scores()` and `metric_observations()` helpers.

## [0.2.0] — 2026-07-30

### Added

- **Security controls for the public API** (`llmqa/web/security.py`):
  - Optional bearer-token auth on mutating endpoints (`LLMQA_API_TOKEN`).
  - Real (paid) providers are blocked unless `LLMQA_ALLOW_REAL_PROVIDERS=1`,
    so an anonymous visitor can't burn the operator's API budget.
  - In-memory per-IP rate limiting (`LLMQA_RATE_LIMIT`, `LLMQA_RATE_WINDOW_S`).
  - Dataset-path allowlist preventing path traversal / arbitrary file reads.
  - CORS is locked down by default (no wildcard); set `ALLOWED_ORIGINS` to opt in.
- **Eval correctness**
  - Deterministic real-provider calls: `temperature=0` + fixed `seed` (OpenAI/xAI)
    and `temperature=0` (Anthropic), with request timeouts. Override via
    `LLMQA_TEMPERATURE` / `LLMQA_SEED`.
  - Automatic retries with exponential backoff + jitter on transient provider
    errors; a failed case is recorded (per-case `error`) instead of aborting the run.
  - Separate judge model via `--judge-provider` to avoid a model grading itself.
  - Optional embeddings-based `similarity` backend (`LLMQA_SIMILARITY=embeddings`),
    falling back to Jaccard when unavailable.
- **Flexible expected-answer matching** in `exact_match`: alternative answers
  (`accept:`), regex (`expected_regex:`), and numeric tolerance (`tolerance:`).
- **Gating**: per-tag pass-rate gates (`--min-tag-pass-rate`), per-metric score
  gates (`--min-metric-score`), latency budgets (`--max-avg-latency-ms`,
  `--max-p95-latency-ms`), and cost budgets (`--max-cost`).
- **Named baselines**: tag a stored run with `--label` and gate against it with
  `--regression-baseline LABEL` (instead of always comparing to the last run).
- **Dataset v2**: expanded from 12 → 20 golden cases, including alternatives,
  regex, numeric-tolerance, and adversarial prompt-injection cases.
- **Packaging / CI**: `Dockerfile` + `.dockerignore`, pinned dependency ranges,
  ruff lint, coverage gate (`fail_under = 80`), and a Python 3.11/3.12/3.13 test
  matrix. Added Python 3.13 classifier and Changelog/Issues project URLs.

### Changed

- Reports and the SSE/stream payloads now include per-case latency and cost, and
  runs surface average / p95 latency.

## [0.1.0]

- Initial release: golden dataset, pluggable metrics (exact_match, similarity,
  llm_judge, hallucination), mock provider tiers, SQLite run history,
  CLI quality + regression gates, and the FastAPI + vanilla-JS dashboard.
