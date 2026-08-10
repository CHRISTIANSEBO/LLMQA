"""Phase-3b infra: strict CSP (no script-src unsafe-inline), asset caching,
externalized head scripts."""
from __future__ import annotations

from fastapi.testclient import TestClient

from llmqa.web.app import app

client = TestClient(app)


def test_csp_script_src_has_no_unsafe_inline():
    csp = client.get("/dashboard").headers["Content-Security-Policy"]
    # script-src must be strict 'self' with no inline escape hatch.
    parts = {p.strip().split(" ")[0]: p.strip() for p in csp.split(";")}
    assert "script-src 'self'" in csp
    assert "'unsafe-inline'" not in parts["script-src"]
    # style-src intentionally keeps unsafe-inline for runtime chart styles.
    assert "style-src" in parts


def test_head_scripts_are_external():
    for path in ("/", "/dashboard", "/docs", "/about"):
        html = client.get(path).text
        assert "<script>" not in html  # no inline scripts anywhere
        assert "/assets/theme-init.js" in html.split("</head>")[0]


def test_theme_init_and_prefetch_served():
    assert client.get("/assets/theme-init.js").status_code == 200
    assert client.get("/assets/prefetch.js").status_code == 200


def test_asset_cache_control_present():
    r = client.get("/assets/app.css")
    assert r.status_code == 200
    cc = r.headers.get("Cache-Control", "")
    assert "max-age=" in cc and "must-revalidate" in cc


def test_dashboard_is_tabbed():
    """The dashboard ships a tablist with the five sections and matching panels,
    so JS tab-switching + #hash deep links have something to bind to."""
    html = client.get("/dashboard").text
    assert 'role="tablist"' in html
    for tab in ("run", "results", "history", "compare", "validate"):
        assert f'data-tab="{tab}"' in html, f"missing tab button {tab}"
        assert f'id="tab-{tab}"' in html, f"missing tab panel {tab}"
    # History tab surfaces the trend + a searchable history table with the new
    # identity columns.
    assert 'id="historySearch"' in html
    assert ">Dataset<" in html and ">Label<" in html


def test_home_hero_demo_wired():
    """The home page ships the live hero demo container + its external script,
    and hero.js is served (external so it complies with the strict CSP)."""
    html = client.get("/").text
    assert 'id="heroDemo"' in html
    assert 'id="hd-rows"' in html
    assert "/assets/hero.js" in html
    js = client.get("/assets/hero.js")
    assert js.status_code == 200
    assert "regression caught" in js.text
