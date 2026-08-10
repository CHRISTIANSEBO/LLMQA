"""FastAPI app for the LLMQA dashboard.

Endpoints
---------
GET  /api/health             -> liveness + which providers are usable
GET  /api/config             -> available providers, metrics, dataset cases
GET  /api/history            -> recent runs (summary rows)
GET  /api/runs/{id}          -> one run with per-case detail
POST /api/run                -> execute an evaluation and persist it

The built frontend (llmqa/web/static) is mounted at / so the whole thing
ships as a single service (good for Railway).
"""
from __future__ import annotations

import json as _json
import logging
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..catalog import list_datasets, resolve_dataset_name
from ..exceptions import ConfigError, DatasetError, LLMQAError, MissingAPIKeyError
from ..metrics import REGISTRY, build_metric
from ..providers import MOCK_PROVIDERS, get_provider
from ..runner import iter_eval, load_dataset, parse_dataset_text, run_eval
from ..store import get_run, list_runs, save_run
from .security import (
    SecurityHeadersMiddleware,
    check_provider_allowed,
    enforce_body_limit,
    guard_mutation,
    require_auth,
)

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
REPO_ROOT = ROOT.parent.parent
DATASETS_DIR = REPO_ROOT / "datasets"
DEFAULT_DATASET = str(DATASETS_DIR / "qa_golden.yaml")
DB_PATH = os.environ.get("LLMQA_DB", str(REPO_ROOT / "llmqa_runs.db"))

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """No startup seeding by design: the dashboard always starts fresh so every
    visit reflects only the runs you actually trigger — no preset/demo runs.
    The trend chart fills in from your own runs as you go."""
    yield  # application runs here


app = FastAPI(
    title="LLMQA Dashboard",
    description="LLM Quality Assurance — run evaluations and track quality over time.",
    # Single source of truth: the installed package version (llmqa.__version__),
    # so /api/health and the OpenAPI spec never drift from the package.
    version=__version__,
    lifespan=lifespan,
    # The site uses /docs for its own documentation page, so move the
    # auto-generated OpenAPI UIs out of the way.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS is locked down by default: the dashboard frontend is served by this same
# app (same-origin), so no cross-origin access is needed. Set ALLOWED_ORIGINS
# (comma-separated) only for an intentional split frontend/backend deploy.
# We deliberately do NOT default to "*" so a public deploy isn't callable from
# arbitrary origins.
_origins_env = os.environ.get("ALLOWED_ORIGINS", "").strip()
_origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-API-Token"],
    )

# Baseline security headers on every response (CSP, nosniff, referrer policy,
# frame-deny, and HSTS behind TLS). Cheap hardening for a public deploy; see
# SecurityHeadersMiddleware for the exact policy and its env overrides.
app.add_middleware(SecurityHeadersMiddleware)

_access_log = logging.getLogger("llmqa.web.access")


@app.middleware("http")
async def request_logging(request: Request, call_next):
    """Structured access logging with a per-request id.

    Assigns/propagates an ``X-Request-ID`` (accepts an inbound one from a proxy)
    and logs method, path, status, and duration. Quiet by default — set
    ``LLMQA_LOG_LEVEL=INFO`` (or DEBUG) to see it. Static/asset noise is skipped.
    """
    req_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    response.headers.setdefault("X-Request-ID", req_id)
    path = request.url.path
    if not path.startswith("/assets"):
        dur_ms = (time.perf_counter() - start) * 1000
        _access_log.info(
            "%s %s -> %s (%.1fms)", request.method, path, response.status_code, dur_ms,
            extra={"request_id": req_id},
        )
    return response


def _http_from_llmqa_error(exc: LLMQAError) -> HTTPException:
    """Map a typed LLMQA error to the right HTTP status.

    User-fixable problems (missing key, bad config, bad dataset) are 4xx; any
    other LLMQAError is a 500. Avoids the previous blanket ``except Exception``
    that turned genuine server faults into a misleading 400.
    """
    if isinstance(exc, MissingAPIKeyError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, (ConfigError, DatasetError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# Provider instances are reused across requests so the in-memory response
# cache actually pays off for the dashboard: repeated runs of the same golden
# cases (or a judge re-asking an identical prompt) are served from cache
# instead of re-hitting a paid API. Without this, FastAPI would build a fresh
# provider per /api/run call and every click would start with an empty cache.
_PROVIDER_CACHE: dict[str, object] = {}


def _get_cached_provider(name: str):
    """Return a process-local, cache-enabled provider instance for ``name``.

    Instances are memoized by provider name so their response cache survives
    across requests. Errors (e.g. missing API key) are not cached.
    """
    provider = _PROVIDER_CACHE.get(name)
    if provider is None:
        # Opt into a persistent, cross-restart response cache by setting
        # LLMQA_CACHE to a file path (recommended for a self-hosted deploy
        # using real, paid providers).
        provider = get_provider(name, use_cache=True, cache_path=os.environ.get("LLMQA_CACHE"))
        _PROVIDER_CACHE[name] = provider
    return provider


class CompareRequest(BaseModel):
    providers: list[str] = Field(default=["mock-strong", "mock-lite"], min_length=2, max_length=4)
    metrics: list[str] = Field(
        default_factory=lambda: ["exact_match", "similarity", "llm_judge", "hallucination"]
    )
    tags: list[str] | None = None
    dataset: str | None = None


class RunRequest(BaseModel):
    provider: str = "mock"
    metrics: list[str] = Field(
        default_factory=lambda: ["exact_match", "similarity", "llm_judge", "hallucination"]
    )
    tags: list[str] | None = None
    case_ids: list[str] | None = None
    dataset: str | None = None
    store: bool = True
    # Run cases in parallel (I/O-bound provider calls). Clamped server-side.
    concurrency: int = 1
    # Optional safety ceiling: stop the run once cost reaches this many USD.
    max_cost_usd: float | None = None


# Upper bound on request-supplied concurrency so a single call can't exhaust
# the server's thread pool.
MAX_CONCURRENCY = 16


def _clamp_concurrency(value: int) -> int:
    return max(1, min(int(value or 1), MAX_CONCURRENCY))


# --- Lightweight in-process metrics (no external dependency) ----------------
# Just enough for a self-hoster to scrape run volume, quality, and spend without
# pulling in a metrics client. Reset on restart; scrape via GET /metrics.
_METRICS = {
    "runs_total": 0,
    "cases_total": 0,
    "cases_passed_total": 0,
    "cost_usd_total": 0.0,
}
_METRICS_LOCK = threading.Lock()


def _record_metrics(run) -> None:
    """Fold a completed EvalRun into the process metrics counters."""
    if run is None:
        return
    with _METRICS_LOCK:
        _METRICS["runs_total"] += 1
        _METRICS["cases_total"] += len(run.results)
        _METRICS["cases_passed_total"] += sum(1 for r in run.results if r.passed)
        _METRICS["cost_usd_total"] += run.total_cost_usd


@app.get("/api/health")
def health(deep: bool = False) -> dict:
    payload = {
        "status": "ok",
        "version": app.version,
        "keys_detected": {
            "ANTHROPIC_API_KEY": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
            "XAI_API_KEY": bool(os.environ.get("XAI_API_KEY")),
        },
        "providers_in_config": list(MOCK_PROVIDERS)
        + ( ["anthropic"] if os.environ.get("ANTHROPIC_API_KEY") else [] )
        + ( ["openai"] if os.environ.get("OPENAI_API_KEY") else [] )
        + ( ["xai"] if os.environ.get("XAI_API_KEY") else [] ),
    }
    if deep:
        # Cheap liveness probe: can we load the default dataset and does the
        # deterministic mock provider actually answer? No paid calls are made.
        checks: dict[str, dict] = {}
        try:
            n = len(load_dataset(DEFAULT_DATASET))
            checks["dataset"] = {"ok": True, "cases": n}
        except Exception as exc:  # noqa: BLE001 - health must never raise
            checks["dataset"] = {"ok": False, "error": str(exc)}
        try:
            resp = _get_cached_provider("mock").generate("healthcheck ping")
            checks["mock_provider"] = {"ok": bool(resp.text is not None)}
        except Exception as exc:  # noqa: BLE001
            checks["mock_provider"] = {"ok": False, "error": str(exc)}
        payload["checks"] = checks
        payload["status"] = "ok" if all(c.get("ok") for c in checks.values()) else "degraded"
    return payload


class ValidateDatasetRequest(BaseModel):
    # Raw YAML/JSON text of a dataset (a list of cases). Capped by the body
    # limit + this length so a paste can't be abused.
    content: str = Field(min_length=1, max_length=200_000)


@app.post("/api/validate-dataset")
async def validate_dataset(req: ValidateDatasetRequest, request: Request) -> dict:
    """Validate a pasted/uploaded dataset without persisting it.

    Returns a per-case summary on success (so the UI can preview what would
    run), or a 400 with the same actionable message the CLI gives. The dataset
    is never written to disk; running it is a separate, in-memory concern.
    """
    await enforce_body_limit(request)
    require_auth(request)
    try:
        cases = parse_dataset_text(req.content, label="uploaded dataset")
    except LLMQAError as exc:
        raise _http_from_llmqa_error(exc) from exc
    return {
        "valid": True,
        "count": len(cases),
        "cases": [
            {"id": c.id, "input": c.input, "expected": c.expected,
             "tags": c.tags, "has_context": bool(c.context),
             "gate_metrics": c.gate_metrics}
            for c in cases
        ],
    }


@app.get("/api/config")
def config(dataset: str | None = None, include_context: bool = False) -> dict:
    dataset_path = resolve_dataset_name(dataset)
    cases = load_dataset(dataset_path)

    real_providers = []
    if os.environ.get("ANTHROPIC_API_KEY"):
        real_providers.append("anthropic")
    if os.environ.get("OPENAI_API_KEY"):
        real_providers.append("openai")
    if os.environ.get("XAI_API_KEY"):
        real_providers.append("xai")

    return {
        "providers": list(MOCK_PROVIDERS) + real_providers,
        "all_providers": list(MOCK_PROVIDERS) + ["anthropic", "openai", "xai"],
        "metrics": list(REGISTRY),
        "dataset": Path(dataset_path).name,
        "datasets": list_datasets(),
        "default_dataset": Path(DEFAULT_DATASET).name,
        # Context can be large (grounding passages), so it's omitted here and
        # served per-case via /api/runs detail / the row drill-down. `has_context`
        # is enough for the UI to show the right badge. Pass include_context=1
        # to opt back into the full payload.
        "cases": [
            {"id": c.id, "input": c.input, "expected": c.expected,
             "tags": c.tags, "has_context": bool(c.context),
             "gate_metrics": c.gate_metrics,
             **({"context": c.context} if include_context else {})}
            for c in cases
        ],
    }


@app.get("/api/cases/{case_id}")
def case_detail(case_id: str, dataset: str | None = None) -> dict:
    """Full detail for one case, including its (possibly large) context.

    /api/config omits context by default to keep the initial payload small;
    the dashboard fetches this lazily when a result row is expanded.
    """
    dataset_path = resolve_dataset_name(dataset)
    for c in load_dataset(dataset_path):
        if c.id == case_id:
            return {
                "id": c.id, "input": c.input, "expected": c.expected,
                "tags": c.tags, "has_context": bool(c.context),
                "context": c.context, "gate_metrics": c.gate_metrics,
            }
    raise HTTPException(status_code=404, detail=f"Case {case_id!r} not found")


@app.get("/api/history")
def history(limit: int = 50) -> dict:
    return {"runs": list_runs(DB_PATH, limit=limit)}


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus text-format metrics for self-hosted monitoring.

    Process-local counters (reset on restart): run/case volume, cumulative
    passes, and cumulative cost. No external metrics dependency.
    """
    with _METRICS_LOCK:
        m = dict(_METRICS)
    lines = [
        "# HELP llmqa_runs_total Evaluations run since start.",
        "# TYPE llmqa_runs_total counter",
        f"llmqa_runs_total {m['runs_total']}",
        "# HELP llmqa_cases_total Cases evaluated since start.",
        "# TYPE llmqa_cases_total counter",
        f"llmqa_cases_total {m['cases_total']}",
        "# HELP llmqa_cases_passed_total Cases that passed since start.",
        "# TYPE llmqa_cases_passed_total counter",
        f"llmqa_cases_passed_total {m['cases_passed_total']}",
        "# HELP llmqa_cost_usd_total Cumulative provider cost (USD) since start.",
        "# TYPE llmqa_cost_usd_total counter",
        f"llmqa_cost_usd_total {m['cost_usd_total']:.6f}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = get_run(run_id, DB_PATH)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@app.post("/api/run")
async def run(req: RunRequest, request: Request) -> dict:
    await enforce_body_limit(request)
    guard_mutation(request, provider=req.provider)
    if req.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY not configured on the server. Use the mock provider.",
        )
    try:
        provider = _get_cached_provider(req.provider)
    except LLMQAError as exc:
        raise _http_from_llmqa_error(exc) from exc

    metrics = []
    for name in req.metrics:
        if name not in REGISTRY:
            raise HTTPException(status_code=400, detail=f"Unknown metric {name!r}")
        if name in ("llm_judge", "hallucination"):
            metrics.append(build_metric(name, judge=provider))
        else:
            metrics.append(build_metric(name))

    dataset = resolve_dataset_name(req.dataset)
    eval_run = run_eval(
        dataset, provider, metrics,
        tags=req.tags, case_ids=req.case_ids,
        concurrency=_clamp_concurrency(req.concurrency),
        max_cost_usd=req.max_cost_usd,
    )

    run_id = save_run(eval_run, DB_PATH) if req.store else None
    _record_metrics(eval_run)

    payload = eval_run.model_dump()
    payload["pass_rate"] = eval_run.pass_rate
    payload["avg_score"] = eval_run.avg_score
    payload["score_by_metric"] = eval_run.score_by_metric()
    payload["run_id"] = run_id
    payload["stopped_early"] = eval_run.stopped_early
    payload["stopped_reason"] = eval_run.stopped_reason
    # `passed` is a computed property, so inject it per case for the frontend.
    for case_payload, case_result in zip(payload["results"], eval_run.results, strict=False):
        case_payload["passed"] = case_result.passed
    return payload


@app.post("/api/run/stream")
async def run_stream(req: RunRequest, request: Request):
    """Stream case results via Server-Sent Events as each case completes.

    Each SSE event is JSON with a ``type`` field:
    - ``{"type": "case", "result": <CaseResult>}``  — one per completed case
    - ``{"type": "done", "pass_rate": ..., "avg_score": ..., ...}`` — final summary
    """
    guard_mutation(request, provider=req.provider)
    try:
        provider = _get_cached_provider(req.provider)
    except LLMQAError as exc:
        raise _http_from_llmqa_error(exc) from exc

    metrics: list = []
    for name in req.metrics:
        if name not in REGISTRY:
            raise HTTPException(status_code=400, detail=f"Unknown metric {name!r}")
        if name in ("llm_judge", "hallucination"):
            metrics.append(build_metric(name, judge=provider))
        else:
            metrics.append(build_metric(name))

    dataset_path = resolve_dataset_name(req.dataset)
    store = req.store

    conc = _clamp_concurrency(req.concurrency)

    def _event_gen():
        # Open with a comment line so proxies flush headers immediately and the
        # client's reader starts before the first (possibly slow) case.
        yield ": llmqa stream open\n\n"
        run = None
        for run, cr in iter_eval(  # noqa: B007 - keep last run
            dataset_path, provider, metrics, req.tags, req.case_ids,
            concurrency=conc, max_cost_usd=req.max_cost_usd,
        ):
            case_data = cr.model_dump()
            case_data["passed"] = cr.passed
            # A heartbeat comment before each case keeps idle proxies from
            # closing the connection during a long gap between slow cases.
            yield ": ping\n\n"
            yield f"data: {_json.dumps({'type': 'case', 'result': case_data})}\n\n"

        run_id = save_run(run, DB_PATH) if (store and run is not None) else None
        _record_metrics(run)
        summary = {
            "type": "done",
            "pass_rate": run.pass_rate if run else 0.0,
            "avg_score": run.avg_score if run else 0.0,
            "total_cost_usd": run.total_cost_usd if run else 0.0,
            "model": provider.model,
            "provider": provider.name,
            "run_id": run_id,
            "stopped_early": run.stopped_early if run else False,
            "stopped_reason": run.stopped_reason if run else "",
        }
        yield f"data: {_json.dumps(summary)}\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
@app.post("/api/compare")
async def compare(req: CompareRequest, request: Request) -> dict:
    """Run the same dataset through multiple providers and return all results
    keyed by provider name for side-by-side comparison."""
    await enforce_body_limit(request)
    guard_mutation(request)
    for prov_name in req.providers:
        check_provider_allowed(prov_name)

    # Validate metric names once up front so a bad request fails fast (before
    # spending any compute) with a clear 400.
    for name in req.metrics:
        if name not in REGISTRY:
            raise HTTPException(status_code=400, detail=f"Unknown metric {name!r}")

    dataset = resolve_dataset_name(req.dataset)

    def _run_one(prov_name: str) -> dict:
        provider = _get_cached_provider(prov_name)
        metrics = [
            build_metric(name, judge=provider)
            if name in ("llm_judge", "hallucination")
            else build_metric(name)
            for name in req.metrics
        ]
        eval_run = run_eval(dataset, provider, metrics, tags=req.tags)
        _record_metrics(eval_run)
        payload = eval_run.model_dump()
        payload["pass_rate"] = eval_run.pass_rate
        payload["avg_score"] = eval_run.avg_score
        payload["score_by_metric"] = eval_run.score_by_metric()
        for case_payload, case_result in zip(payload["results"], eval_run.results, strict=False):
            case_payload["passed"] = case_result.passed
        return payload

    # Run the providers concurrently: each is an independent, I/O-bound eval, so
    # comparing two real models no longer takes the sum of their latencies.
    all_runs: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(req.providers)) as ex:
        futures = {ex.submit(_run_one, p): p for p in req.providers}
        for fut in as_completed(futures):
            prov_name = futures[fut]
            try:
                all_runs[prov_name] = fut.result()
            except LLMQAError as exc:
                raise _http_from_llmqa_error(exc) from exc

    return {"runs": all_runs, "providers": req.providers}


# --- Static frontend (mounted last so /api routes take precedence) ----------
# Multi-page site: each route maps to its own HTML document. Clean URLs
# (e.g. /dashboard) serve the matching <name>.html so links stay pretty.
PAGES = {
    "/": "index.html",
    "/dashboard": "dashboard.html",
    "/docs": "docs.html",
    "/about": "about.html",
}

if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    def _page(name: str) -> FileResponse:
        return FileResponse(STATIC_DIR / name)

    @app.get("/")
    def index() -> FileResponse:
        return _page("index.html")

    @app.get("/dashboard")
    def dashboard() -> FileResponse:
        return _page("dashboard.html")

    @app.get("/docs")
    def docs() -> FileResponse:
        return _page("docs.html")

    @app.get("/about")
    def about() -> FileResponse:
        return _page("about.html")

    # --- PWA plumbing: served from the site root so the service worker can
    # control the whole origin (scope "/") and the manifest resolves cleanly. ---
    @app.get("/sw.js")
    def service_worker() -> FileResponse:
        # Allow the worker to claim the root scope even though the file lives
        # under /static, and keep it uncached so updates ship immediately.
        return FileResponse(
            STATIC_DIR / "sw.js",
            media_type="application/javascript",
            headers={
                "Service-Worker-Allowed": "/",
                "Cache-Control": "no-cache",
            },
        )

    @app.get("/manifest.webmanifest")
    def manifest() -> FileResponse:
        return FileResponse(
            STATIC_DIR / "manifest.webmanifest",
            media_type="application/manifest+json",
        )

    @app.exception_handler(404)
    async def not_found(request, exc):  # noqa: ANN001
        # API 404s stay JSON. For a bare clean-URL that matches a known page
        # (e.g. a trailing-slash variant), serve it; otherwise fall back to home.
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        page = PAGES.get(request.url.path.rstrip("/") or "/")
        return FileResponse(STATIC_DIR / (page or "index.html"))
