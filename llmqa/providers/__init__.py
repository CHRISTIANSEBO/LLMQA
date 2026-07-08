"""Pluggable model providers. Select by name via get_provider()."""
from __future__ import annotations

from .base import Provider, ModelResponse
from .mock import MockProvider


def get_provider(name: str) -> Provider:
    """Return a provider instance by name.

    'mock' always works with no API key (used in CI and offline demos).
    'anthropic' / 'openai' require the matching API key in the environment.
    """
    name = name.lower()
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider()
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider()
    raise ValueError(f"Unknown provider: {name!r} (try 'mock', 'anthropic', 'openai')")


__all__ = ["Provider", "ModelResponse", "MockProvider", "get_provider"]
