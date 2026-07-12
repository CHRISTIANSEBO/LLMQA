"""Tests for the OpenAI and xAI (Grok) providers.

These never hit the network: the ``openai`` SDK client is monkeypatched with a
fake that records the request and returns a canned completion + usage, so we
can assert wiring (base URL, model, key env), text extraction, and token-based
cost math deterministically.
"""
from __future__ import annotations

import sys
import types

import pytest

from llmqa.providers import get_provider
from llmqa.providers.openai_provider import OpenAIProvider, _price_for
from llmqa.providers.xai_provider import XAIProvider


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str, usage: _FakeUsage) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, client: "_FakeClient") -> None:
        self._client = client

    def create(self, *, model, max_tokens, messages):
        self._client.last_call = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        return _FakeCompletion(
            "  Paris  ", _FakeUsage(prompt_tokens=1000, completion_tokens=500)
        )


class _FakeClient:
    def __init__(self, api_key=None, base_url=None) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.last_call = None
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(self))


@pytest.fixture
def fake_openai(monkeypatch):
    """Install a fake ``openai`` module exposing ``OpenAI`` -> _FakeClient."""
    fake_mod = types.ModuleType("openai")
    created = {}

    def _factory(api_key=None, base_url=None):
        client = _FakeClient(api_key=api_key, base_url=base_url)
        created["client"] = client
        return client

    fake_mod.OpenAI = _factory
    monkeypatch.setitem(sys.modules, "openai", fake_mod)
    return created


def test_openai_generates_text_and_cost(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = OpenAIProvider()  # default gpt-4o-mini
    resp = p.generate("What is the capital of France?")

    assert resp.text == "Paris"  # stripped
    # gpt-4o-mini: 0.15/1M in, 0.60/1M out -> 1000*0.15/1e6 + 500*0.60/1e6
    assert resp.cost_usd == pytest.approx(0.00015 + 0.00030)
    # Default OpenAI base URL is the SDK default (None passed through).
    assert fake_openai["client"].base_url is None
    assert fake_openai["client"].api_key == "sk-test"


def test_openai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIProvider()


def test_xai_uses_xai_base_url_and_key(monkeypatch, fake_openai):
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    p = XAIProvider()  # default grok-4-fast
    resp = p.generate("hi")

    assert resp.text == "Paris"
    assert p.name == "xai"
    assert p.model == "grok-4-fast"
    assert fake_openai["client"].base_url == "https://api.x.ai/v1"
    assert fake_openai["client"].api_key == "xai-test"
    # grok-4-fast: 0.20/1M in, 0.50/1M out
    assert resp.cost_usd == pytest.approx(1000 * 0.20 / 1e6 + 500 * 0.50 / 1e6)


def test_xai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="XAI_API_KEY"):
        XAIProvider()


def test_get_provider_wires_openai_and_xai(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("XAI_API_KEY", "xai-test")
    assert isinstance(get_provider("openai"), OpenAIProvider)
    assert isinstance(get_provider("xai"), XAIProvider)
    # `grok` is an alias for xai.
    assert isinstance(get_provider("grok"), XAIProvider)


def test_context_is_included_in_prompt(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = OpenAIProvider()
    p.generate("Who is the CEO?", context="Acme was founded in 1998.")
    sent = fake_openai["client"].last_call["messages"][0]["content"]
    assert "Context:" in sent and "Acme was founded in 1998." in sent


def test_unknown_model_uses_default_pricing():
    assert _price_for("some-future-model") == (1.00, 3.00)
    assert _price_for("gpt-4o-mini-2024-07-18") == (0.15, 0.60)


def test_cached_repeat_is_free(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    p = OpenAIProvider(use_cache=True)
    first = p.generate("same prompt")
    second = p.generate("same prompt")
    assert first.cached is False and second.cached is True
    assert second.cost_usd == 0.0
