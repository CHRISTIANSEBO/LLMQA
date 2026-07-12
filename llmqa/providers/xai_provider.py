"""xAI Grok provider. Requires XAI_API_KEY.

xAI exposes an OpenAI-compatible API, so this reuses the OpenAI SDK against
xAI's base URL and only overrides the key env var, default model, and pricing.
"""
from __future__ import annotations

from .openai_provider import OpenAIProvider

# Pricing in USD per 1M tokens (input, output). Update as pricing changes.
_PRICING: dict[str, tuple[float, float]] = {
    "grok-4-fast": (0.20, 0.50),
    "grok-4": (3.00, 15.00),
    "grok-3-mini": (0.30, 0.50),
    "grok-3": (3.00, 15.00),
    "grok-2": (2.00, 10.00),
}
_DEFAULT_PRICING = (2.00, 10.00)


class XAIProvider(OpenAIProvider):
    name = "xai"
    _default_model = "grok-4-fast"
    _api_key_env = "XAI_API_KEY"
    _base_url = "https://api.x.ai/v1"

    def _pricing(self) -> tuple[float, float]:
        for prefix, price in _PRICING.items():
            if self.model.startswith(prefix):
                return price
        return _DEFAULT_PRICING
