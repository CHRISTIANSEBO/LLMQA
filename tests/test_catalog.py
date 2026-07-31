"""Tests for the dataset catalog (discovery, safe resolution, versioning) and
that runs record a dataset hash."""

from fastapi.testclient import TestClient

from llmqa.catalog import (
    DATASETS_DIR,
    DEFAULT_DATASET_NAME,
    dataset_hash,
    list_datasets,
    resolve_dataset_name,
)
from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.runner import run_eval
from llmqa.store import get_run, save_run
from llmqa.web.app import app

client = TestClient(app)

EXPECTED = {
    "qa_golden.yaml", "factual_qa.yaml", "summarization.yaml",
    "rag_grounding.yaml", "code_qa.yaml", "safety_refusals.yaml",
}


def test_all_datasets_present_and_load():
    from llmqa.runner import load_dataset
    names = set(list_datasets())
    assert EXPECTED <= names
    for name in EXPECTED:
        cases = load_dataset(DATASETS_DIR / name)
        assert len(cases) >= 10
        assert all(c.id and c.input and c.expected for c in cases)


def test_resolve_rejects_traversal_and_unknown():
    default = str(DATASETS_DIR / DEFAULT_DATASET_NAME)
    assert resolve_dataset_name("../../etc/passwd") == default
    assert resolve_dataset_name("nope.yaml") == default
    assert resolve_dataset_name(None) == default
    assert resolve_dataset_name("factual_qa.yaml") == str(DATASETS_DIR / "factual_qa.yaml")


def test_dataset_hash_is_stable_and_prefixed():
    p = DATASETS_DIR / DEFAULT_DATASET_NAME
    h = dataset_hash(p)
    assert h.startswith("sha256:")
    assert h == dataset_hash(p)


def test_run_records_dataset_hash_and_persists(tmp_path):
    run = run_eval(str(DATASETS_DIR / "factual_qa.yaml"), get_provider("mock"),
                   [build_metric("exact_match")])
    assert run.dataset_hash.startswith("sha256:")
    db = str(tmp_path / "runs.db")
    rid = save_run(run, db)
    fetched = get_run(rid, db)
    assert fetched["dataset_hash"] == run.dataset_hash


def test_config_lists_datasets_and_switches_cases():
    cfg = client.get("/api/config").json()
    assert set(cfg["datasets"]) >= EXPECTED
    assert cfg["default_dataset"] == "qa_golden.yaml"

    golden_ids = {c["id"] for c in cfg["cases"]}
    factual = client.get("/api/config", params={"dataset": "factual_qa.yaml"}).json()
    factual_ids = {c["id"] for c in factual["cases"]}
    assert factual["dataset"] == "factual_qa.yaml"
    assert golden_ids != factual_ids  # different dataset -> different cases


def test_run_with_selected_dataset():
    r = client.post("/api/run", json={"provider": "mock", "dataset": "code_qa.yaml", "store": False})
    assert r.status_code == 200
    body = r.json()
    assert body["dataset"].endswith("code_qa.yaml")
    assert len(body["results"]) >= 10
