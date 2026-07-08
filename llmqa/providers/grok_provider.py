"""Grok (xAI) provider. Requires XAI_API_KEY."""
from __future__ import annotations

import os

from .base import Provider

# Approximate Grok pricing (USD per 1M tokens) — update as needed.
_INPUT_COST_PER_MTOK = 5.00
_OUTPUT_COST_PER_MTOK = 15.00


class GrokProvider(Provider):
    name = "grok"

    def __init__(self, model: str = "grok-4") -> None:
        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "XAI_API_KEY is not set. Use --provider mock for a key-free run."
            )
        import openai  # xAI uses OpenAI-compatible API
        self.model = model
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        content = prompt if context is None else f"Context:\n{context}\n\nQuestion: {prompt}"

        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=512,
        )

        text = resp.choices[0].message.content.strip() if resp.choices[0].message.content else ""
        usage = resp.usage

        cost = (
            (usage.prompt_tokens / 1_000_000) * _INPUT_COST_PER_MTOK
            + (usage.completion_tokens / 1_000_000) * _OUTPUT_COST_PER_MTOK
        )
        return text, cost
