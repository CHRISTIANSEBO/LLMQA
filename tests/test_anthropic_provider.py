"""Tests for the Anthropic provider (no network: the SDK is monkeypatched)."""
from __future__ import annotations

import sys
import types

import pytest

from llmqa.providers import get_provider
from llmqa.providers.anthropic_provider import AnthropicProvider


class _Block:
    def __init__(self, text: str) -> None:
        self.type = "text"
        self.text = text


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _Msg:
    def __init__(self, content, usage) -> None:
        self.content = content
        self.usage = usage


class _FakeMessages:
    def __init__(self, client) -> None:
        self._client = client

    def create(self, *, model, max_tokens, messages, temperature=None):
        self._client.last_call = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        return _Msg([_Block("  Paris  ")], _Usage(1000, 500))


class _FakeClient:
    def __init__(self, api_key=None, timeout=None) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.last_call = None
        self.messages = _FakeMessages(self)


@pytest.fixture
def fake_anthropic(monkeypatch):
    fake_mod = types.ModuleType("anthropic")
    created = {}

    def _factory(api_key=None, timeout=None):
        client = _FakeClient(api_key=api_key, timeout=timeout)
        created["client"] = client
        return client

    fake_mod.Anthropic = _factory
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)
    return created


def test_anthropic_generates_text_and_cost(monkeypatch, fake_anthropic):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = AnthropicProvider()
    resp = p.generate("What is the capital of France?")

    assert resp.text == "Paris"  # stripped
    # 0.80/1M in, 4.00/1M out -> 1000*0.8/1e6 + 500*4.0/1e6
    assert resp.cost_usd == pytest.approx(1000 * 0.80 / 1e6 + 500 * 4.00 / 1e6)
    # Determinism: temperature pinned to 0.
    assert fake_anthropic["client"].last_call["temperature"] == 0.0
    assert fake_anthropic["client"].api_key == "sk-ant-test"


def test_anthropic_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


def test_anthropic_context_included(monkeypatch, fake_anthropic):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    p = AnthropicProvider()
    p.generate("Who is the CEO?", context="Acme was founded in 1998.")
    sent = fake_anthropic["client"].last_call["messages"][0]["content"]
    assert "Context:" in sent and "Acme was founded in 1998." in sent


def test_get_provider_wires_anthropic(monkeypatch, fake_anthropic):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert isinstance(get_provider("anthropic"), AnthropicProvider)
