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

import os
from contextlib import asynccontextmanager
from pathlib import Path

import json as _json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from ..catalog import list_datasets, resolve_dataset_name
from ..metrics import REGISTRY, build_metric
from ..providers import MOCK_PROVIDERS, get_provider
from ..runner import iter_eval, load_dataset, run_eval
from ..store import DEFAULT_DB, get_run, list_runs, save_run

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
REPO_ROOT = ROOT.parent.parent
DEFAULT_DATASET = str(REPO_ROOT / "datasets" / "qa_golden.yaml")
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
    version="0.2.0",
    lifespan=lifespan,
    # The site uses /docs for its own documentation page, so move the
    # auto-generated OpenAPI UIs out of the way.
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS is env-configurable so a split frontend/backend deploy still works.
_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/health")
def health() -> dict:
    return {
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


@app.get("/api/config")
def config(dataset: str | None = None) -> dict:
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
        "cases": [
            {"id": c.id, "input": c.input, "expected": c.expected,
             "tags": c.tags, "has_context": bool(c.context),
             "context": c.context, "gate_metrics": c.gate_metrics}
            for c in cases
        ],
    }


@app.get("/api/history")
def history(limit: int = 50) -> dict:
    return {"runs": list_runs(DB_PATH, limit=limit)}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: int) -> dict:
    run = get_run(run_id, DB_PATH)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return run


@app.post("/api/run")
def run(req: RunRequest) -> dict:
    if req.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            status_code=400,
            detail="ANTHROPIC_API_KEY not configured on the server. Use the mock provider.",
        )
    try:
        provider = _get_cached_provider(req.provider)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    payload = eval_run.model_dump()
    payload["pass_rate"] = eval_run.pass_rate
    payload["avg_score"] = eval_run.avg_score
    payload["score_by_metric"] = eval_run.score_by_metric()
    payload["run_id"] = run_id
    payload["stopped_early"] = eval_run.stopped_early
    payload["stopped_reason"] = eval_run.stopped_reason
    # `passed` is a computed property, so inject it per case for the frontend.
    for case_payload, case_result in zip(payload["results"], eval_run.results):
        case_payload["passed"] = case_result.passed
    return payload


@app.post("/api/run/stream")
def run_stream(req: RunRequest):
    """Stream case results via Server-Sent Events as each case completes.

    Each SSE event is JSON with a ``type`` field:
    - ``{"type": "case", "result": <CaseResult>}``  — one per completed case
    - ``{"type": "done", "pass_rate": ..., "avg_score": ..., ...}`` — final summary
    """
    try:
        provider = _get_cached_provider(req.provider)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        run = None
        for run, cr in iter_eval(
            dataset_path, provider, metrics, req.tags, req.case_ids,
            concurrency=conc, max_cost_usd=req.max_cost_usd,
        ):
            case_data = cr.model_dump()
            case_data["passed"] = cr.passed
            yield f"data: {_json.dumps({'type': 'case', 'result': case_data})}\n\n"

        run_id = save_run(run, DB_PATH) if (store and run is not None) else None
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
def compare(req: CompareRequest) -> dict:
    """Run the same dataset through multiple providers and return all results
    keyed by provider name for side-by-side comparison."""
    all_runs: dict[str, dict] = {}

    for prov_name in req.providers:
        try:
            provider = _get_cached_provider(prov_name)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        metrics = []
        for name in req.metrics:
            if name not in REGISTRY:
                raise HTTPException(status_code=400, detail=f"Unknown metric {name!r}")
            if name in ("llm_judge", "hallucination"):
                metrics.append(build_metric(name, judge=provider))
            else:
                metrics.append(build_metric(name))

        eval_run = run_eval(resolve_dataset_name(req.dataset), provider, metrics, tags=req.tags)

        payload = eval_run.model_dump()
        payload["pass_rate"] = eval_run.pass_rate
        payload["avg_score"] = eval_run.avg_score
        payload["score_by_metric"] = eval_run.score_by_metric()
        for case_payload, case_result in zip(payload["results"], eval_run.results):
            case_payload["passed"] = case_result.passed
        all_runs[prov_name] = payload

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

    @app.exception_handler(404)
    async def not_found(request, exc):  # noqa: ANN001
        # API 404s stay JSON. For a bare clean-URL that matches a known page
        # (e.g. a trailing-slash variant), serve it; otherwise fall back to home.
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        page = PAGES.get(request.url.path.rstrip("/") or "/")
        return FileResponse(STATIC_DIR / (page or "index.html"))
