"""Pluggable model providers. Select by name via get_provider()."""
from __future__ import annotations

from .base import Provider, ModelResponse
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


def get_provider(name: str, *, use_cache: bool = True) -> Provider:
    """Return a provider instance by name.

    ``use_cache`` enables the in-memory response cache so repeated identical
    calls within the process don't re-spend tokens on a paid provider.
    """
    name = name.lower()
    if name in MOCK_PROVIDERS:
        return MOCK_PROVIDERS[name](use_cache=use_cache)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(use_cache=use_cache)
    raise ValueError(
        f"Unknown provider: {name!r} "
        f"(try {', '.join(repr(k) for k in MOCK_PROVIDERS)}, 'anthropic')"
    )


__all__ = [
    "Provider",
    "ModelResponse",
    "MockProvider",
    "MockStrongProvider",
    "MockLiteProvider",
    "MockLegacyProvider",
    "MOCK_PROVIDERS",
    "get_provider",
]