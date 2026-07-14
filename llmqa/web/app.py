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
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from ..metrics import REGISTRY, build_metric
from ..providers import MOCK_PROVIDERS, get_provider
from ..runner import load_dataset, run_eval
from ..store import DEFAULT_DB, get_run, list_runs, save_run

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
REPO_ROOT = ROOT.parent.parent
DEFAULT_DATASET = str(REPO_ROOT / "datasets" / "qa_golden.yaml")
DB_PATH = os.environ.get("LLMQA_DB", str(REPO_ROOT / "llmqa_runs.db"))

app = FastAPI(
    title="LLMQA Dashboard",
    description="LLM Quality Assurance — run evaluations and track quality over time.",
    version="0.2.0",
)

# CORS is env-configurable so a split frontend/backend deploy still works.
_origins = os.environ.get("ALLOWED_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins],
    allow_methods=["*"],
    allow_headers=["*"],
)


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
        provider = get_provider(req.provider)
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
