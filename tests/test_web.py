"""Smoke tests for the FastAPI dashboard backend (mock provider only)."""
import os
import tempfile

from fastapi.testclient import TestClient

# Use a throwaway DB so tests never touch a real run history.
os.environ["LLMQA_DB"] = os.path.join(tempfile.gettempdir(), "llmqa_test_web.db")

from llmqa.web.app import app  # noqa: E402

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_config_lists_mock_and_metrics():
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert "mock" in body["providers"]
    assert set(body["metrics"]) >= {"exact_match", "llm_judge"}
    assert len(body["cases"]) >= 5


def test_run_mock_and_persist_and_fetch():
    r = client.post("/api/run", json={"provider": "mock"})
    assert r.status_code == 200
    body = r.json()
    assert body["pass_rate"] == 1.0
    assert len(body["results"]) >= 5
    assert all("passed" in c for c in body["results"])
    run_id = body["run_id"]
    assert run_id is not None

    # History should now include the run.
    h = client.get("/api/history")
    assert h.status_code == 200
    assert any(row["id"] == run_id for row in h.json()["runs"])

    # Detail endpoint returns per-case results.
    d = client.get(f"/api/runs/{run_id}")
    assert d.status_code == 200
    assert d.json()["detail"]["results"]


def test_run_live_provider_without_key_is_rejected():
    # Any live provider raises RuntimeError when its key is missing -> 400.
    for provider in ("anthropic", "openai", "xai"):
        env_key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY"}[provider]
        prev = os.environ.pop(env_key, None)
        try:
            r = client.post("/api/run", json={"provider": provider})
            assert r.status_code == 400, f"{provider} should return 400 without key"
        finally:
            if prev is not None:
                os.environ[env_key] = prev


def test_unknown_metric_rejected():
    r = client.post("/api/run", json={"provider": "mock", "metrics": ["nope"]})
    assert r.status_code == 400


def test_dashboard_reuses_provider_instance_across_runs():
    """Repeated dashboard runs must share one cache-enabled provider instance.

    This is what makes the response cache actually save tokens for the
    dashboard: without instance reuse each /api/run would start cache-empty
    and re-hit a paid API for the same golden cases.
    """
    from llmqa.web import app as web_app

    web_app._PROVIDER_CACHE.clear()
    client.post("/api/run", json={"provider": "mock", "store": False})
    first = web_app._PROVIDER_CACHE["mock"]
    client.post("/api/run", json={"provider": "mock", "store": False})
    second = web_app._PROVIDER_CACHE["mock"]

    assert first is second, "dashboard must reuse the same provider instance"
    assert first._use_cache is True
