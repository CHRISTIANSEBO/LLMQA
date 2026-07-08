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


def get_provider(name: str) -> Provider:
    """Return a provider instance by name."""
    name = name.lower()
    if name in MOCK_PROVIDERS:
        return MOCK_PROVIDERS[name]()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
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