"""Phase-2 web features: parallel compare, request-id header, run cost ceiling
via the stream, and stored-run detail for the ?run deep link."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from llmqa.web.app import app

client = TestClient(app)


def test_compare_runs_all_providers_and_keys_by_name():
    r = client.post(
        "/api/compare",
        json={"providers": ["mock-strong", "mock-lite"], "metrics": ["exact_match"]},
    )
    assert r.status_code == 200
    data = r.json()
    assert set(data["runs"].keys()) == {"mock-strong", "mock-lite"}
    assert data["providers"] == ["mock-strong", "mock-lite"]
    for run in data["runs"].values():
        assert "pass_rate" in run and run["results"]


def test_compare_unknown_metric_fails_fast():
    r = client.post(
        "/api/compare",
        json={"providers": ["mock-strong", "mock-lite"], "metrics": ["nope"]},
    )
    assert r.status_code == 400


def test_request_id_header_present_and_echoed():
    # Generated when absent...
    r = client.get("/api/health")
    assert r.headers.get("X-Request-ID")
    # ...and echoed back when the client supplies one.
    r2 = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r2.headers.get("X-Request-ID") == "abc123"


def test_run_returns_run_id_for_deep_link_then_fetchable():
    r = client.post("/api/run", json={"provider": "mock", "store": True})
    run_id = r.json()["run_id"]
    assert run_id is not None
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id


def test_stream_cost_ceiling_stops_early_flag():
    # A zero-ish ceiling on a mock run (cost 0) won't stop; just assert the
    # done event carries the stopped_early contract fields.
    with client.stream(
        "POST", "/api/run/stream",
        json={"provider": "mock", "store": False, "max_cost_usd": 0.0},
    ) as r:
        text = "".join(r.iter_text())
    done = [
        json.loads(line[6:])
        for line in text.splitlines()
        if line.startswith("data: ") and '"done"' in line
    ][0]
    assert "stopped_early" in done and "stopped_reason" in done
