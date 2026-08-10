"""Phase-3a backend: dataset validation endpoint, deep health, /metrics."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llmqa.web.app import app

client = TestClient(app)

VALID_DS = """
- id: capital-france
  input: What is the capital of France?
  expected: Paris
  gate_metrics: [exact_match]
- id: pi
  input: Pi to two decimals?
  expected: "3.14"
  tolerance: 0.001
"""


def test_validate_dataset_ok():
    r = client.post("/api/validate-dataset", json={"content": VALID_DS})
    assert r.status_code == 200
    data = r.json()
    assert data["valid"] and data["count"] == 2
    assert {c["id"] for c in data["cases"]} == {"capital-france", "pi"}


def test_validate_dataset_not_a_list():
    r = client.post("/api/validate-dataset", json={"content": "just: a mapping\n"})
    assert r.status_code == 400
    assert "list of cases" in r.json()["detail"]


def test_validate_dataset_missing_required_field():
    r = client.post("/api/validate-dataset", json={"content": "- id: x\n  input: q\n"})
    assert r.status_code == 400
    assert "invalid" in r.json()["detail"]


def test_validate_dataset_bad_yaml():
    r = client.post("/api/validate-dataset", json={"content": "- id: x\n  input: [oops\n"})
    assert r.status_code == 400
    assert "not valid YAML" in r.json()["detail"]


def test_deep_health_probes_dataset_and_mock():
    r = client.get("/api/health?deep=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert body["checks"]["dataset"]["ok"] is True
    assert body["checks"]["mock_provider"]["ok"] is True


def test_metrics_endpoint_prometheus_format():
    # Trigger a run so the counters are non-zero.
    client.post("/api/run", json={"provider": "mock", "store": False})
    r = client.get("/metrics")
    assert r.status_code == 200
    text = r.text
    assert "llmqa_runs_total" in text
    assert "llmqa_cases_total" in text
    assert "llmqa_cost_usd_total" in text
    # Counter lines are 'name value'.
    line = next(ln for ln in text.splitlines() if ln.startswith("llmqa_runs_total "))
    assert int(line.split()[1]) >= 1
