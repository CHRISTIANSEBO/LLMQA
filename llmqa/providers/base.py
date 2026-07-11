"""Provider interface: anything that can turn a prompt into text + cost/latency."""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ModelResponse:
    text: str
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False


class Provider(ABC):
    name: str = "base"
    model: str = "unknown"

    def __init__(self, *, use_cache: bool = True) -> None:
        # In-memory response cache: de-duplicates identical calls within this
        # process so repeated runs (dashboard clicks, regression compares, a
        # judge re-asking the same prompt) don't re-spend tokens on a paid API.
        # It is intentionally NOT persisted to disk — no risk of serving stale
        # answers across process restarts, and no cache file to manage.
        self._use_cache = use_cache
        self._cache: dict[tuple[str, str, str, str | None], tuple[str, float]] = {}

    def _cache_key(self, prompt: str, context: str | None) -> tuple[str, str, str, str | None]:
        return (self.name, self.model, prompt, context)

    def clear_cache(self) -> None:
        self._cache.clear()

    @abstractmethod
    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        """Return (text, cost_usd). Implemented per provider."""

    def generate(self, prompt: str, context: str | None = None) -> ModelResponse:
        """Time the call and wrap the result. Shared by all providers.

        On a cache hit the stored text is returned with ``cost_usd=0.0`` (the
        tokens were already paid for the first time) and ``cached=True``.
        """
        if self._use_cache:
            key = self._cache_key(prompt, context)
            hit = self._cache.get(key)
            if hit is not None:
                text, _original_cost = hit
                return ModelResponse(text=text, cost_usd=0.0, latency_ms=0.0, cached=True)

        start = time.perf_counter()
        text, cost = self._complete(prompt, context)
        latency_ms = (time.perf_counter() - start) * 1000

        if self._use_cache:
            self._cache[self._cache_key(prompt, context)] = (text, cost)

        return ModelResponse(text=text, cost_usd=cost, latency_ms=latency_ms)
