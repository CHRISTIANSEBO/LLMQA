"""Pluggable model providers. Select by name via get_provider()."""
from __future__ import annotations

from .base import Provider, ModelResponse
from .mock import (
    MockProvider,
    MockStrongProvider,
    MockLiteProvider,
    MockLegacyProvider,
)
from .openai_provider import OpenAIProvider
from .grok_provider import GrokProvider

# Key-free mock tiers, selectable by name. `mock` aliases the strong baseline.
MOCK_PROVIDERS = {
    "mock": MockStrongProvider,
    "mock-strong": MockStrongProvider,
    "mock-lite": MockLiteProvider,
    "mock-legacy": MockLegacyProvider,
}


def get_provider(name: str) -> Provider:
    """Return a provider instance by name.

    Supports both simple names and model-specific names:
        - "openai"               → openai + default model
        - "openai/gpt-4o"        → openai + specific model
        - "grok"                 → grok + default model
        - "grok/grok-4"          → grok + specific model
    """
    name = name.lower().strip()

    if name in MOCK_PROVIDERS:
        return MOCK_PROVIDERS[name]()

    # Support "provider/model" syntax
    if "/" in name:
        provider_name, model = name.split("/", 1)
    else:
        provider_name, model = name, None

    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(model=model) if model else AnthropicProvider()
    if provider_name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(model=model) if model else OpenAIProvider()
    if provider_name in ("xai", "grok"):
        from .grok_provider import GrokProvider
        return GrokProvider(model=model) if model else GrokProvider()

    raise ValueError(
        f"Unknown provider: {name!r} "
        f"(try mock tiers, 'anthropic', 'openai', 'grok', or 'provider/model')"
    )


__all__ = [
    "Provider",
    "ModelResponse",
    "MockProvider",
    "MockStrongProvider",
    "MockLiteProvider",
    "MockLegacyProvider",
    "MOCK_PROVIDERS",
    "OpenAIProvider",
    "GrokProvider",
    "get_provider",
]
