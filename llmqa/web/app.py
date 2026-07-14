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

from ..metrics import REGISTRY, build_metric
from ..providers import MOCK_PROVIDERS, get_provider
from ..runner import load_dataset, run_eval
from ..seed import seed_if_empty
from ..store import DEFAULT_DB, get_run, list_runs, save_run

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
REPO_ROOT = ROOT.parent.parent
DEFAULT_DATASET = str(REPO_ROOT / "datasets" / "qa_golden.yaml")
DB_PATH = os.environ.get("LLMQA_DB", str(REPO_ROOT / "llmqa_runs.db"))

@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Seed the DB with historical mock runs on first boot so the trend chart
    is never empty for a first-time visitor."""
    inserted = seed_if_empty(DEFAULT_DATASET, DB_PATH)
    if inserted:
        print(f"[llmqa] Seeded {inserted} historical runs into {DB_PATH}")
    yield  # application runs here


app = FastAPI(
    title="LLMQA Dashboard",
    description="LLM Quality Assurance — run evaluations and track quality over time.",
    version="0.2.0",
    lifespan=lifespan,
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
        provider = get_provider(name, use_cache=True)
        _PROVIDER_CACHE[name] = provider
    return provider


class RunRequest(BaseModel):
    provider: str = "mock"
    metrics: list[str] = Field(
        default_factory=lambda: ["exact_match", "similarity", "llm_judge", "hallucination"]
    )
    tags: list[str] | None = None
    dataset: str | None = None
    store: bool = True


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
def config() -> dict:
    dataset_path = DEFAULT_DATASET
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
        "dataset": dataset_path,
        "cases": [
            {"id": c.id, "input": c.input, "expected": c.expected,
             "tags": c.tags, "has_context": bool(c.context),
             "gate_metrics": c.gate_metrics}
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

    dataset = req.dataset or DEFAULT_DATASET
    eval_run = run_eval(dataset, provider, metrics, tags=req.tags)

    run_id = save_run(eval_run, DB_PATH) if req.store else None

    payload = eval_run.model_dump()
    payload["pass_rate"] = eval_run.pass_rate
    payload["avg_score"] = eval_run.avg_score
    payload["score_by_metric"] = eval_run.score_by_metric()
    payload["run_id"] = run_id
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

    dataset_path = req.dataset or DEFAULT_DATASET
    store = req.store

    def _event_gen():
        from datetime import datetime, timezone
        from ..types import CaseResult, EvalRun

        cases = load_dataset(dataset_path)
        if req.tags:
            wanted = set(req.tags)
            cases = [c for c in cases if wanted & set(c.tags)]

        run = EvalRun(
            dataset=dataset_path,
            model=provider.model,
            provider=provider.name,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )

        for case in cases:
            resp = provider.generate(case.input, case.context)
            run.total_cost_usd += resp.cost_usd
            scored = [m.score(case, resp.text) for m in metrics]
            cr = CaseResult(
                case_id=case.id,
                tags=case.tags,
                gate_metrics=case.gate_metrics,
                output=resp.text,
                latency_ms=round(resp.latency_ms, 1),
                metrics=scored,
            )
            run.results.append(cr)
            case_data = cr.model_dump()
            case_data["passed"] = cr.passed
            yield f"data: {_json.dumps({'type': 'case', 'result': case_data})}\n\n"

        run_id = save_run(run, DB_PATH) if store else None
        summary = {
            "type": "done",
            "pass_rate": run.pass_rate,
            "avg_score": run.avg_score,
            "total_cost_usd": run.total_cost_usd,
            "model": run.model,
            "provider": run.provider,
            "run_id": run_id,
        }
        yield f"data: {_json.dumps(summary)}\n\n"

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- Static frontend (mounted last so /api routes take precedence) ----------
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.exception_handler(404)
    async def spa_fallback(request, exc):  # noqa: ANN001
        # SPA fallback: non-API 404s serve index.html so client routing works.
        if request.url.path.startswith("/api"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return FileResponse(STATIC_DIR / "index.html")
