"""Pluggable model providers. Select by name via get_provider()."""
from __future__ import annotations

from .base import Provider, ModelResponse, ProviderError
from .mock import (
    MockProvider,
    MockStrongProvider,
    MockLiteProvider,
    MockLegacyProvider,
)

# Key-free mock tiers, selectable by name. `mock` aliases the strong baseline.
MOCK_PROVIDERS = {
    "mock": MockStrongProvider,
    "mock-strong": MockStrongProvider,
    "mock-lite": MockLiteProvider,
    "mock-legacy": MockLegacyProvider,
}


def get_provider(
    name: str,
    *,
    use_cache: bool = True,
    max_retries: int | None = None,
    backoff_base: float | None = None,
    timeout_s: float | None = None,
) -> Provider:
    """Return a provider instance by name.

    ``use_cache`` enables the in-memory response cache so repeated identical
    calls within the process don't re-spend tokens on a paid provider.

    ``max_retries``/``backoff_base``/``timeout_s`` override the provider's
    resilience defaults when given. They are applied post-construction so
    provider subclasses don't each need to thread the kwargs through.
    """
    name = name.lower()
    if name in MOCK_PROVIDERS:
        inst: Provider = MOCK_PROVIDERS[name](use_cache=use_cache)
    elif name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        inst = AnthropicProvider(use_cache=use_cache)
    elif name == "openai":
        from .openai_provider import OpenAIProvider
        inst = OpenAIProvider(use_cache=use_cache)
    elif name in ("xai", "grok"):
        from .xai_provider import XAIProvider
        inst = XAIProvider(use_cache=use_cache)
    else:
        raise ValueError(
            f"Unknown provider: {name!r} "
            f"(try {', '.join(repr(k) for k in MOCK_PROVIDERS)}, "
            f"'anthropic', 'openai', 'xai'/'grok')"
        )

    if max_retries is not None:
        inst.max_retries = max_retries
    if backoff_base is not None:
        inst.backoff_base = backoff_base
    if timeout_s is not None:
        inst.timeout_s = timeout_s
    return inst


__all__ = [
    "Provider",
    "ModelResponse",
    "ProviderError",
    "MockProvider",
    "MockStrongProvider",
    "MockLiteProvider",
    "MockLegacyProvider",
    "MOCK_PROVIDERS",
    "get_provider",
]