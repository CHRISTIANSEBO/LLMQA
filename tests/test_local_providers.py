"""Tests for the local (Ollama) and generic OpenAI-compatible providers.

These construct the providers (which sets up an OpenAI SDK client but makes no
network call) and assert configuration/pricing/selection behavior. No server or
API key is required.
"""
from __future__ import annotations

import pytest

from llmqa.exceptions import ConfigError, MissingAPIKeyError
from llmqa.providers import get_provider
from llmqa.providers.local_provider import (
    OllamaProvider,
    OpenAICompatProvider,
    _normalize_base_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("http://localhost:11434", "http://localhost:11434/v1"),
        ("http://localhost:11434/", "http://localhost:11434/v1"),
        ("http://localhost:11434/v1", "http://localhost:11434/v1"),
        ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1"),
    ],
)
def test_normalize_base_url(raw, expected):
    assert _normalize_base_url(raw) == expected


def test_ollama_needs_no_key_and_is_free(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("LLMQA_LOCAL_MODEL", raising=False)

    p = OllamaProvider(use_cache=False)
    assert p.name == "ollama"
    assert p.model == "llama3.2"
    assert p._pricing() == (0.0, 0.0)
    # Client points at the default local endpoint.
    assert str(p._client.base_url).startswith("http://localhost:11434/v1")


def test_ollama_honors_env(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434")
    monkeypatch.setenv("LLMQA_LOCAL_MODEL", "qwen2.5:7b")
    p = OllamaProvider(use_cache=False)
    assert p.model == "qwen2.5:7b"
    assert str(p._client.base_url).startswith("http://gpu-box:11434/v1")


def test_ollama_selectable_by_alias(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for alias in ("ollama", "local"):
        p = get_provider(alias, use_cache=False)
        assert isinstance(p, OllamaProvider)


def test_openai_compat_requires_base_url(monkeypatch):
    monkeypatch.delenv("LLMQA_OPENAI_BASE_URL", raising=False)
    with pytest.raises(ConfigError, match="LLMQA_OPENAI_BASE_URL"):
        OpenAICompatProvider(use_cache=False)


def test_openai_compat_requires_key(monkeypatch):
    monkeypatch.setenv("LLMQA_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.delenv("LLMQA_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(MissingAPIKeyError):
        OpenAICompatProvider(use_cache=False)


def test_openai_compat_builds_and_prices(monkeypatch):
    monkeypatch.setenv("LLMQA_OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLMQA_OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("LLMQA_MODEL", "meta-llama/llama-3.1-8b-instruct")
    monkeypatch.setenv("LLMQA_PRICE_IN", "0.05")
    monkeypatch.setenv("LLMQA_PRICE_OUT", "0.10")

    p = get_provider("openai-compat", use_cache=False)
    assert isinstance(p, OpenAICompatProvider)
    assert p.model == "meta-llama/llama-3.1-8b-instruct"
    assert p._pricing() == (0.05, 0.10)
    assert str(p._client.base_url).startswith("https://openrouter.ai/api/v1")


def test_openai_compat_pricing_defaults_to_zero(monkeypatch):
    monkeypatch.setenv("LLMQA_OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLMQA_OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("LLMQA_PRICE_IN", raising=False)
    monkeypatch.delenv("LLMQA_PRICE_OUT", raising=False)
    p = OpenAICompatProvider(use_cache=False)
    assert p._pricing() == (0.0, 0.0)
