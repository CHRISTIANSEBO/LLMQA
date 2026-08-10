"""Phase-1 web hardening: version, security headers, body limit, typed errors,
lazy context, per-case endpoint, and the SSE heartbeat contract."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llmqa import __version__
from llmqa.web.app import app

client = TestClient(app)


def test_health_version_matches_package():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["version"] == __version__


def test_openapi_version_matches_package():
    assert client.get("/api/openapi.json").json()["info"]["version"] == __version__


def test_security_headers_present():
    r = client.get("/api/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Content-Security-Policy" in r.headers
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_hsts_only_over_https():
    # Plain HTTP (the TestClient default) must NOT get HSTS.
    assert "Strict-Transport-Security" not in client.get("/api/health").headers
    # Simulated TLS via the forwarded-proto header does.
    r = client.get("/api/health", headers={"X-Forwarded-Proto": "https"})
    assert "Strict-Transport-Security" in r.headers


def test_body_limit_rejects_oversize(monkeypatch):
    monkeypatch.setenv("LLMQA_MAX_BODY_BYTES", "500")
    big = {"provider": "mock", "tags": ["x" * 2000]}
    r = client.post("/api/run", json=big)
    assert r.status_code == 413


def test_config_omits_context_by_default_and_endpoint_serves_it():
    cfg = client.get("/api/config").json()
    # A dataset with at least one context-bearing case exists (rag_grounding).
    rag = client.get("/api/config?dataset=rag_grounding.yaml").json()
    with_ctx = [c for c in rag["cases"] if c["has_context"]]
    assert with_ctx, "expected a context-bearing case in rag_grounding"
    # Context is NOT inlined in the default config payload...
    assert all("context" not in c for c in rag["cases"])
    # ...but include_context=1 opts back in.
    full = client.get("/api/config?dataset=rag_grounding.yaml&include_context=true").json()
    assert any(c.get("context") for c in full["cases"])
    # ...and the per-case endpoint serves it on demand.
    cid = with_ctx[0]["id"]
    detail = client.get(f"/api/cases/{cid}?dataset=rag_grounding.yaml")
    assert detail.status_code == 200
    assert detail.json()["context"]
    # Sanity: the default dataset config still returns cases.
    assert cfg["cases"]


def test_case_detail_404_for_unknown():
    assert client.get("/api/cases/does-not-exist").status_code == 404


def test_run_stream_emits_heartbeat_and_done():
    with client.stream("POST", "/api/run/stream", json={"provider": "mock", "store": False}) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    # Heartbeat/open comments are present...
    assert ": ping" in text or ": llmqa stream open" in text
    # ...and the terminal summary event is well-formed.
    done = [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ") and '"done"' in line
    ]
    assert done and done[0]["type"] == "done"
    assert 0.0 <= done[0]["pass_rate"] <= 1.0


def test_unknown_metric_still_400():
    r = client.post("/api/run", json={"provider": "mock", "metrics": ["nope"]})
    assert r.status_code == 400
