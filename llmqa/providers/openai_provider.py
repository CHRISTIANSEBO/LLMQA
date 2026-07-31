"""OpenAI chat provider. Requires OPENAI_API_KEY.

Uses the official ``openai`` SDK's Chat Completions API. Cost is computed from
the returned token usage using per-model pricing (USD per 1M tokens); unknown
models fall back to a conservative default so a run still reports *some* cost
rather than silently $0.
"""
from __future__ import annotations

import os

from .base import Provider

# Pricing in USD per 1M tokens (input, output). Update as pricing changes.
# Keys are matched by prefix so dated snapshots (e.g. gpt-4o-mini-2024-07-18)
# resolve to their family.
_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "o3-mini": (1.10, 4.40),
    "gpt-3.5-turbo": (0.50, 1.50),
}
# Used when a model isn't in the table; keeps cost non-zero and roughly sane.
_DEFAULT_PRICING = (1.00, 3.00)


def _price_for(model: str) -> tuple[float, float]:
    for prefix, price in _PRICING.items():
        if model.startswith(prefix):
            return price
    return _DEFAULT_PRICING


class OpenAIProvider(Provider):
    """OpenAI Chat Completions. Configurable model, base URL, and key env var.

    Subclassed by :class:`~llmqa.providers.xai_provider.XAIProvider`, whose API
    is OpenAI-compatible and only differs by base URL / key / pricing.
    """

    name = "openai"
    _default_model = "gpt-4o-mini"
    _api_key_env = "OPENAI_API_KEY"
    _base_url: str | None = None  # None => SDK default (api.openai.com)
    _max_tokens = 512
    # Determinism: a QA harness must be as reproducible as possible, so we pin
    # temperature to 0 and pass a fixed seed. Env-overridable for experiments.
    _temperature = 0.0
    _seed = 42
    _timeout_s = 30.0

    def __init__(self, model: str | None = None, *, use_cache: bool = True) -> None:
        super().__init__(use_cache=use_cache)
        api_key = os.environ.get(self._api_key_env)
        if not api_key:
            raise RuntimeError(
                f"{self._api_key_env} is not set. Use --provider mock for a key-free run."
            )
        import openai  # imported lazily so 'mock' runs without the dep

        self.model = model or self._default_model
        self._temperature = float(os.environ.get("LLMQA_TEMPERATURE", self._temperature))
        self._seed = int(os.environ.get("LLMQA_SEED", self._seed))
        self._client = openai.OpenAI(
            api_key=api_key, base_url=self._base_url, timeout=self._timeout_s
        )

    def _pricing(self) -> tuple[float, float]:
        return _price_for(self.model)

    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        content = prompt if context is None else f"Context:\n{context}\n\nQuestion: {prompt}"
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=self._max_tokens,
            temperature=self._temperature,
            seed=self._seed,
            messages=[{"role": "user", "content": content}],
        )
        text = (resp.choices[0].message.content or "").strip()

        in_price, out_price = self._pricing()
        usage = resp.usage
        prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
        completion_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
        cost = (
            prompt_tokens * in_price / 1_000_000
            + completion_tokens * out_price / 1_000_000
        )
        return text, cost
