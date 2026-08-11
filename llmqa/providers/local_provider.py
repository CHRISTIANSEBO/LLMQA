"""Local and generic OpenAI-compatible providers.

These unlock **real** model evaluations without a paid vendor key:

- :class:`OllamaProvider` targets a local `Ollama <https://ollama.com>`_ server
  (also works with LM Studio / any server that speaks Ollama's OpenAI-compatible
  ``/v1`` API). Local inference is free, so cost is reported as ``$0``.
- :class:`OpenAICompatProvider` targets *any* OpenAI-compatible endpoint via a
  ``base_url`` you supply — OpenRouter, Together, Fireworks, vLLM, LM Studio,
  a self-hosted gateway, etc. — so you are not locked to one vendor.

Both reuse :class:`~llmqa.providers.openai_provider.OpenAIProvider`'s Chat
Completions plumbing (determinism knobs, token-usage cost, retries via the base
:class:`Provider`) and only differ in how the client is configured.
"""
from __future__ import annotations

import os

from ..exceptions import ConfigError, MissingAPIKeyError
from .base import Provider
from .openai_provider import OpenAIProvider


def _normalize_base_url(host: str) -> str:
    """Return an OpenAI-style base URL, appending ``/v1`` when it is missing."""
    host = host.rstrip("/")
    return host if host.endswith("/v1") else f"{host}/v1"


class OllamaProvider(OpenAIProvider):
    """Evaluate against a local Ollama server (free, key-free, offline-friendly).

    Configuration (all optional, sensible defaults):

    - ``OLLAMA_HOST`` — server base URL (default ``http://localhost:11434``).
    - ``LLMQA_LOCAL_MODEL`` — model tag to run (default ``llama3.2``); the
      ``--model`` handling of the provider still wins when passed in code.

    No API key is required; local servers ignore it, so a placeholder is sent to
    satisfy the OpenAI SDK. Cost is always ``$0`` because inference is local.
    """

    name = "ollama"
    _default_model = "llama3.2"

    def __init__(self, model: str | None = None, *, use_cache: bool = True) -> None:
        # Skip OpenAIProvider.__init__ (which requires OPENAI_API_KEY) and set up
        # the client ourselves against the local endpoint.
        Provider.__init__(self, use_cache=use_cache)
        import openai  # lazy: 'mock' runs without the dep

        base_url = _normalize_base_url(os.environ.get("OLLAMA_HOST", "http://localhost:11434"))
        self.model = model or os.environ.get("LLMQA_LOCAL_MODEL") or self._default_model
        self._temperature = float(os.environ.get("LLMQA_TEMPERATURE", self._temperature))
        self._seed = int(os.environ.get("LLMQA_SEED", self._seed))
        # Local servers ignore the key but the SDK requires a non-empty string.
        api_key = os.environ.get("OPENAI_API_KEY") or "ollama"
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=self._timeout_s)

    def _pricing(self) -> tuple[float, float]:
        # Local inference is free — report $0 rather than a made-up vendor price.
        return (0.0, 0.0)


class OpenAICompatProvider(OpenAIProvider):
    """Evaluate against any OpenAI-compatible endpoint via a configurable base URL.

    Configuration:

    - ``LLMQA_OPENAI_BASE_URL`` (required) — e.g. ``https://openrouter.ai/api/v1``.
    - ``LLMQA_OPENAI_API_KEY`` (required, falls back to ``OPENAI_API_KEY``).
    - ``LLMQA_MODEL`` — model id to request (default ``gpt-4o-mini``).
    - ``LLMQA_PRICE_IN`` / ``LLMQA_PRICE_OUT`` — optional per-1M-token pricing so
      cost reporting is accurate for your endpoint. Unset => cost reported as $0.
    """

    name = "openai-compat"

    def __init__(self, model: str | None = None, *, use_cache: bool = True) -> None:
        Provider.__init__(self, use_cache=use_cache)
        base_url = os.environ.get("LLMQA_OPENAI_BASE_URL")
        if not base_url:
            raise ConfigError(
                "LLMQA_OPENAI_BASE_URL is not set. Point it at an OpenAI-compatible "
                "endpoint, e.g. https://openrouter.ai/api/v1 (or use --provider ollama "
                "for a local server, or --provider mock for a key-free run)."
            )
        api_key = os.environ.get("LLMQA_OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise MissingAPIKeyError(
                "LLMQA_OPENAI_API_KEY (or OPENAI_API_KEY) is not set for the "
                "openai-compat provider."
            )
        import openai  # lazy

        self.model = model or os.environ.get("LLMQA_MODEL") or self._default_model
        self._temperature = float(os.environ.get("LLMQA_TEMPERATURE", self._temperature))
        self._seed = int(os.environ.get("LLMQA_SEED", self._seed))
        self._client = openai.OpenAI(
            api_key=api_key, base_url=_normalize_base_url(base_url), timeout=self._timeout_s
        )

    def _pricing(self) -> tuple[float, float]:
        pin = os.environ.get("LLMQA_PRICE_IN")
        pout = os.environ.get("LLMQA_PRICE_OUT")
        if pin is not None and pout is not None:
            return (float(pin), float(pout))
        # Unknown endpoint pricing: report $0 rather than an invented figure.
        return (0.0, 0.0)
