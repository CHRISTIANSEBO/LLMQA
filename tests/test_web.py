"""Smoke tests for the FastAPI dashboard backend (mock provider only)."""
import json
import os
import tempfile

from fastapi.testclient import TestClient

# Use a throwaway DB so tests never touch a real run history.
os.environ["LLMQA_DB"] = os.path.join(tempfile.gettempdir(), "llmqa_test_web.db")

from llmqa.web.app import app  # noqa: E402

client = TestClient(app)


def test_pages_served():
    """Each clean URL serves its own HTML document."""
    for path, marker in [
        ("/", "How it works"),
        ("/dashboard", "Run an evaluation"),
        ("/docs", "Quickstart"),
        ("/about", "About LLMQA"),
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert "text/html" in r.headers["content-type"], path
        assert marker in r.text, f"{marker!r} missing from {path}"


def test_every_page_has_theme_toggle_and_no_flash_script():
    """Light/dark theming must be wired on every page: the pre-paint no-flash
    snippet, the masthead toggle button, and the shared theme.js."""
    for path in ("/", "/dashboard", "/docs", "/about"):
        html = client.get(path).text
        assert 'id="theme-toggle"' in html, f"toggle missing from {path}"
        assert "/assets/theme.js" in html, f"theme.js missing from {path}"
        assert 'localStorage.getItem("llmqa-theme")' in html, f"no-flash snippet missing from {path}"


def test_theme_assets_served():
    """The theme script is reachable and the CSS defines a dark palette."""
    assert client.get("/assets/theme.js").status_code == 200
    css = client.get("/assets/app.css").text
    assert '[data-theme="dark"]' in css
    assert "prefers-color-scheme: dark" in css


def test_brand_logo_variants_wired_and_served():
    """Every page shows both brand-logo variants (light/dark), and both SVGs
    plus the favicon are served."""
    for path in ("/", "/dashboard", "/docs", "/about"):
        html = client.get(path).text
        assert "/assets/logo-light.svg" in html, f"light logo missing from {path}"
        assert "/assets/logo-dark.svg" in html, f"dark logo missing from {path}"
    for asset in ("/assets/logo-light.svg", "/assets/logo-dark.svg", "/assets/favicon.svg"):
        r = client.get(asset)
        assert r.status_code == 200, asset
        assert "svg" in r.text[:200].lower(), asset


def test_api_docs_not_shadowed_by_docs_page():
    """The site's /docs page must not clobber the OpenAPI schema/UI."""
    assert client.get("/api/openapi.json").status_code == 200
    # /docs returns the HTML docs page, not Swagger UI.
    assert "Quickstart" in client.get("/docs").text


def test_unknown_page_falls_back_to_home():
    r = client.get("/does-not-exist")
    assert r.status_code == 200
    assert "How it works" in r.text


def test_startup_does_not_seed(monkeypatch, tmp_path):
    """Always-fresh: app startup must NOT auto-populate the DB with preset runs.

    Uses a throwaway DB and runs the real lifespan (context-managed client);
    a fresh install must report an empty run history.
    """
    from llmqa.web import app as web_app

    fresh_db = str(tmp_path / "fresh.db")
    monkeypatch.setattr(web_app, "DB_PATH", fresh_db)
    with TestClient(web_app.app) as c:  # entering the context runs lifespan
        runs = c.get("/api/history").json()["runs"]
    assert runs == [], "startup must not seed preset runs"


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


def test_real_provider_blocked_by_default():
    # Real (paid) providers are gated off unless explicitly enabled, so an
    # anonymous request can't burn the operator's API budget -> 403.
    os.environ.pop("LLMQA_ALLOW_REAL_PROVIDERS", None)
    r = client.post("/api/run", json={"provider": "anthropic"})
    assert r.status_code == 403


def test_run_case_ids_filter_runs_only_that_case():
    # Grab a real case id from the config, then run only that one.
    cfg = client.get("/api/config").json()
    assert cfg["cases"], "expected a non-empty golden dataset"
    target = cfg["cases"][0]["id"]

    r = client.post(
        "/api/run",
        json={"provider": "mock", "case_ids": [target], "store": False},
    )
    assert r.status_code == 200
    body = r.json()
    ids = [c["case_id"] for c in body["results"]]
    assert ids == [target]
    assert body["run_id"] is None  # store=False must not persist


def test_run_stream_respects_case_ids():
    cfg = client.get("/api/config").json()
    target = cfg["cases"][0]["id"]
    with client.stream(
        "POST",
        "/api/run/stream",
        json={"provider": "mock", "case_ids": [target], "store": False},
    ) as resp:
        assert resp.status_code == 200
        case_ids = []
        for line in resp.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            evt = json.loads(line[6:])
            if evt.get("type") == "case":
                case_ids.append(evt["result"]["case_id"])
    assert case_ids == [target]


def test_run_anthropic_without_key_is_rejected():
    # With real providers enabled but no key configured -> 400, not a crash.
    prev = os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ["LLMQA_ALLOW_REAL_PROVIDERS"] = "1"
    try:
        r = client.post("/api/run", json={"provider": "anthropic"})
        assert r.status_code == 400
    finally:
        os.environ.pop("LLMQA_ALLOW_REAL_PROVIDERS", None)
        if prev is not None:
            os.environ["ANTHROPIC_API_KEY"] = prev


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
