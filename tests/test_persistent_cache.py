"""Tests for the SQLite-backed persistent response cache."""
from __future__ import annotations

from llmqa.cache import MemoryCache, SqliteCache, build_cache, cache_key
from llmqa.providers import get_provider
from llmqa.providers.base import Provider


class CountingProvider(Provider):
    name = "counting"
    model = "counting-1"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.calls = 0

    def _complete(self, prompt, context=None):
        self.calls += 1
        return f"answer::{prompt}", 0.01


def test_cache_key_is_stable_and_distinguishing():
    a = cache_key("p", "m", "prompt", None)
    assert a == cache_key("p", "m", "prompt", None)          # stable
    assert a != cache_key("p", "m", "prompt", "ctx")          # context matters
    assert a != cache_key("p", "m2", "prompt", None)          # model matters


def test_sqlite_cache_roundtrip(tmp_path):
    c = SqliteCache(tmp_path / "cache.db")
    assert c.get("k") is None
    c.set("k", "hello", 0.02)
    assert c.get("k") == ("hello", 0.02)
    c.clear()
    assert c.get("k") is None


def test_build_cache_selects_backend(tmp_path):
    assert isinstance(build_cache(None), MemoryCache)
    assert isinstance(build_cache(tmp_path / "c.db"), SqliteCache)


def test_persistent_cache_survives_new_provider_instance(tmp_path):
    """A second provider instance pointed at the same cache file gets a hit
    without calling _complete - proving the cache persists across processes."""
    path = str(tmp_path / "responses.db")

    p1 = CountingProvider(use_cache=True, cache_path=path)
    first = p1.generate("What is 2+2?")
    assert first.cached is False and p1.calls == 1

    # Fresh instance (simulates a restart/other worker) sharing the same file.
    p2 = CountingProvider(use_cache=True, cache_path=path)
    second = p2.generate("What is 2+2?")
    assert second.cached is True
    assert second.cost_usd == 0.0
    assert p2.calls == 0, "a persisted hit must not re-invoke the provider"


def test_get_provider_cache_path_upgrades_backend(tmp_path):
    p = get_provider("mock", use_cache=True, cache_path=str(tmp_path / "c.db"))
    from llmqa.cache import SqliteCache as _S
    assert isinstance(p._cache_backend, _S)

    p_mem = get_provider("mock", use_cache=True)
    assert isinstance(p_mem._cache_backend, MemoryCache)
