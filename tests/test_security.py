"""Security controls: auth, rate limiting, provider gate, dataset allowlist."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi import HTTPException

from llmqa.catalog import resolve_dataset_name
from llmqa.web import security
from llmqa.web.security import (
    RateLimiter,
    check_provider_allowed,
)

DATASETS_DIR = Path(__file__).resolve().parent.parent / "datasets"
DEFAULT_DATASET = str(DATASETS_DIR / "qa_golden.yaml")


# --- Real-provider gate -----------------------------------------------------
def test_real_provider_blocked_by_default(monkeypatch):
    monkeypatch.delenv("LLMQA_ALLOW_REAL_PROVIDERS", raising=False)
    with pytest.raises(HTTPException) as exc:
        check_provider_allowed("openai")
    assert exc.value.status_code == 403
    # Mocks are always allowed.
    check_provider_allowed("mock")
    check_provider_allowed("mock-legacy")


def test_real_provider_allowed_when_enabled(monkeypatch):
    monkeypatch.setenv("LLMQA_ALLOW_REAL_PROVIDERS", "1")
    check_provider_allowed("openai")  # no raise
    check_provider_allowed("anthropic")


# --- Rate limiter -----------------------------------------------------------
def test_rate_limiter_blocks_after_limit():
    rl = RateLimiter(limit=2, window_s=60)
    rl.check("1.2.3.4")
    rl.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        rl.check("1.2.3.4")
    assert exc.value.status_code == 429
    # A different client is unaffected.
    rl.check("5.6.7.8")


def test_rate_limiter_disabled_when_zero():
    rl = RateLimiter(limit=0, window_s=60)
    for _ in range(100):
        rl.check("x")  # never raises


# --- Dataset resolution is traversal-safe (catalog.resolve_dataset_name) -----
def test_resolve_dataset_default():
    # No/empty name falls back to the default packaged dataset.
    assert resolve_dataset_name(None).endswith("qa_golden.yaml")
    assert resolve_dataset_name("").endswith("qa_golden.yaml")


def test_resolve_dataset_blocks_traversal():
    # Untrusted input with separators / traversal never escapes datasets/;
    # it safely falls back to the default instead of reading arbitrary files.
    assert resolve_dataset_name("/etc/passwd").endswith("qa_golden.yaml")
    assert resolve_dataset_name("../secrets.yaml").endswith("qa_golden.yaml")
    assert resolve_dataset_name("a/b.yaml").endswith("qa_golden.yaml")


def test_resolve_dataset_accepts_known_name():
    # A real packaged dataset name resolves to that file.
    assert resolve_dataset_name("qa_golden.yaml").endswith("qa_golden.yaml")


# --- Auth (integration) -----------------------------------------------------
def test_auth_required_when_token_set(monkeypatch):
    os.environ["LLMQA_DB"] = os.path.join(tempfile.gettempdir(), "llmqa_test_sec.db")
    monkeypatch.setenv("LLMQA_API_TOKEN", "secret123")
    security._LIMITER = None  # reset limiter so prior tests don't bleed in

    from fastapi.testclient import TestClient

    from llmqa.web.app import app

    client = TestClient(app)
    # No token -> 401.
    r = client.post("/api/run", json={"provider": "mock", "store": False})
    assert r.status_code == 401
    # Correct token -> allowed (200).
    r = client.post(
        "/api/run",
        json={"provider": "mock", "store": False},
        headers={"Authorization": "Bearer secret123"},
    )
    assert r.status_code == 200
