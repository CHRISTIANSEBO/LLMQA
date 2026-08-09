"""Anthropic Claude provider. Requires ANTHROPIC_API_KEY."""
from __future__ import annotations

import os

from .base import Provider

# Approximate Claude Haiku pricing (USD per token); update as needed.
_INPUT_COST_PER_TOKEN = 0.80 / 1_000_000
_OUTPUT_COST_PER_TOKEN = 4.00 / 1_000_000


class AnthropicProvider(Provider):
    name = "anthropic"

    # Determinism: temperature 0 for reproducible gating. Env-overridable.
    _temperature = 0.0
    _timeout_s = 30.0

    def __init__(self, model: str = "claude-haiku-4-5-20251001", *, use_cache: bool = True) -> None:
        super().__init__(use_cache=use_cache)
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            from .base import MissingAPIKeyError
            raise MissingAPIKeyError(
                "ANTHROPIC_API_KEY is not set. Use --provider mock for a key-free run."
            )
        import anthropic  # imported lazily so 'mock' runs without the dep
        self.model = model
        self._temperature = float(os.environ.get("LLMQA_TEMPERATURE", self._temperature))
        self._client = anthropic.Anthropic(api_key=api_key, timeout=self._timeout_s)

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        content = prompt if context is None else f"Context:\n{context}\n\nQuestion: {prompt}"
        msg = self._client.messages.create(
            model=self.model,
            max_tokens=512,
            temperature=self._temperature,
            messages=[{"role": "user", "content": content}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text").strip()
        cost = (
            msg.usage.input_tokens * _INPUT_COST_PER_TOKEN
            + msg.usage.output_tokens * _OUTPUT_COST_PER_TOKEN
        )
        return text, cost
