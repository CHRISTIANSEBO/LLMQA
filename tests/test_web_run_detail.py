"""Contract for /api/runs/{id} that the dashboard drill-down + ?run deep link
depend on: top-level summary fields plus the full run under `detail.results`,
each case carrying its metrics (with `detail` rationale), latency, and cost."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llmqa.web.app import app

client = TestClient(app)


def _make_run(provider="mock-legacy"):
    r = client.post("/api/run", json={"provider": provider, "store": True})
    assert r.status_code == 200
    return r.json()["run_id"]


def test_run_detail_shape_for_dashboard():
    run_id = _make_run()
    d = client.get(f"/api/runs/{run_id}").json()
    # Top-level summary the KPI cards read.
    assert "pass_rate" in d and "avg_score" in d and "cost_usd" in d
    # Full run nested under `detail`, with per-case results.
    assert "detail" in d and isinstance(d["detail"], dict)
    results = d["detail"]["results"]
    assert results, "expected per-case results under detail.results"
    case = results[0]
    for key in ("case_id", "metrics", "latency_ms", "cost_usd", "gate_metrics"):
        assert key in case, f"case missing {key}"
    # Each metric carries a score + a human 'detail' rationale (drill-down).
    m = case["metrics"][0]
    assert "metric" in m and "score" in m and "passed" in m and "detail" in m


def test_run_detail_404():
    assert client.get("/api/runs/999999").status_code == 404
