"""Tests for the in-memory provider response cache.

The cache exists to save tokens on a paid provider: identical calls within a
process must not hit ``_complete`` a second time, and cached responses report
``cost_usd == 0`` so the run's cost reflects only newly-spent tokens.
"""
from __future__ import annotations

from llmqa.providers import get_provider
from llmqa.providers.base import Provider


class CountingProvider(Provider):
    """Counts how many times the underlying (paid) call actually fires."""

    name = "counting"
    model = "counting-1"

    def __init__(self, *, use_cache: bool = True) -> None:
        super().__init__(use_cache=use_cache)
        self.calls = 0

    def _complete(self, prompt: str, context: str | None = None):
        self.calls += 1
        # Non-zero cost so we can prove cached hits are billed at 0.
        return f"answer-to::{prompt}", 0.01


def test_identical_call_is_served_from_cache():
    p = CountingProvider()
    first = p.generate("What is the capital of France?")
    second = p.generate("What is the capital of France?")

    assert p.calls == 1, "second identical call must not re-invoke the provider"
    assert first.text == second.text
    assert first.cached is False
    assert second.cached is True
    # First call is billed, the cached repeat is free.
    assert first.cost_usd == 0.01
    assert second.cost_usd == 0.0


def test_cache_key_distinguishes_prompt_and_context():
    p = CountingProvider()
    p.generate("Q", context="A")
    p.generate("Q", context="B")   # different context -> different key
    p.generate("Q2", context="A")  # different prompt  -> different key
    assert p.calls == 3


def test_no_cache_forces_fresh_calls():
    p = CountingProvider(use_cache=False)
    p.generate("same")
    p.generate("same")
    assert p.calls == 2
    assert p.generate("same").cached is False


def test_clear_cache_resets_hits():
    p = CountingProvider()
    p.generate("x")
    p.clear_cache()
    p.generate("x")
    assert p.calls == 2


def test_get_provider_can_disable_cache():
    cached = get_provider("mock", use_cache=True)
    uncached = get_provider("mock", use_cache=False)
    assert cached._use_cache is True
    assert uncached._use_cache is False

    # A mock repeat is cached (cost is already 0 for mocks, but the flag flips).
    cached.generate("capital of france")
    assert cached.generate("capital of france").cached is True
    uncached.generate("capital of france")
    assert uncached.generate("capital of france").cached is False
