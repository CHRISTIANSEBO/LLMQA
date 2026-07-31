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

    # Transient-failure handling for network providers. Mocks never raise, so
    # these are effectively no-ops for them. Overridable per provider.
    max_retries: int = 2       # total extra attempts after the first
    retry_backoff_s: float = 0.6  # base for exponential backoff (with jitter)

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
        text, cost = self._complete_with_retries(prompt, context)
        latency_ms = (time.perf_counter() - start) * 1000

        if self._use_cache:
            self._cache[self._cache_key(prompt, context)] = (text, cost)

        return ModelResponse(text=text, cost_usd=cost, latency_ms=latency_ms)

    def _complete_with_retries(self, prompt: str, context: str | None) -> tuple[str, float]:
        """Call ``_complete`` with exponential backoff + jitter on transient errors.

        A flaky 429/5xx from a paid API shouldn't nuke an entire eval run, so we
        retry a bounded number of times before giving up. The final failure is
        re-raised for the runner to record as a per-case error.
        """
        import random

        attempts = self.max_retries + 1
        last_exc: Exception | None = None
        for i in range(attempts):
            try:
                return self._complete(prompt, context)
            except Exception as exc:  # noqa: BLE001 - provider SDKs raise many types
                last_exc = exc
                if i == attempts - 1:
                    break
                sleep_s = self.retry_backoff_s * (2 ** i) + random.uniform(0, 0.2)
                time.sleep(sleep_s)
        assert last_exc is not None
        raise last_exc
