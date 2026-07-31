"""Provider interface: anything that can turn a prompt into text + cost/latency."""
from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from dataclasses import dataclass


class ProviderError(RuntimeError):
    """Raised when a provider call fails after exhausting its retries.

    Carries the underlying exception as ``__cause__`` so callers can inspect
    the root cause (rate limit, timeout, auth, etc.).
    """


@dataclass
class ModelResponse:
    text: str
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    cached: bool = False


class Provider(ABC):
    name: str = "base"
    model: str = "unknown"

    def __init__(
        self,
        *,
        use_cache: bool = True,
        max_retries: int = 2,
        backoff_base: float = 0.5,
        timeout_s: float | None = None,
    ) -> None:
        # In-memory response cache: de-duplicates identical calls within this
        # process so repeated runs (dashboard clicks, regression compares, a
        # judge re-asking the same prompt) don't re-spend tokens on a paid API.
        # It is intentionally NOT persisted to disk — no risk of serving stale
        # answers across process restarts, and no cache file to manage.
        self._use_cache = use_cache
        self._cache: dict[tuple[str, str, str, str | None], tuple[str, float]] = {}
        # The cache is read/written from worker threads when the runner uses
        # concurrency, so guard it with a lock.
        self._cache_lock = threading.Lock()
        # Resilience knobs (matter for real paid providers; mocks never fail).
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout_s = timeout_s

    def _cache_key(self, prompt: str, context: str | None) -> tuple[str, str, str, str | None]:
        return (self.name, self.model, prompt, context)

    def clear_cache(self) -> None:
        with self._cache_lock:
            self._cache.clear()

    @abstractmethod
    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        """Return (text, cost_usd). Implemented per provider."""

    def _complete_guarded(self, prompt: str, context: str | None) -> tuple[str, float]:
        """Call ``_complete`` with an optional hard wall-clock timeout.

        When ``timeout_s`` is set the call runs in a helper thread so a hung
        network request can't stall a run forever. When it's unset (the mock
        default) we call directly to avoid per-call thread overhead.
        """
        if not self.timeout_s:
            return self._complete(prompt, context)
        with ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(self._complete, prompt, context)
            try:
                return fut.result(timeout=self.timeout_s)
            except FuturesTimeout as exc:
                raise TimeoutError(
                    f"{self.name}/{self.model} call exceeded {self.timeout_s}s"
                ) from exc

    def generate(self, prompt: str, context: str | None = None) -> ModelResponse:
        """Time the call and wrap the result. Shared by all providers.

        On a cache hit the stored text is returned with ``cost_usd=0.0`` (the
        tokens were already paid for the first time) and ``cached=True``.
        Real calls are retried with exponential backoff up to ``max_retries``
        times; after that a :class:`ProviderError` is raised.
        """
        key = self._cache_key(prompt, context)
        if self._use_cache:
            with self._cache_lock:
                hit = self._cache.get(key)
            if hit is not None:
                text, _original_cost = hit
                return ModelResponse(text=text, cost_usd=0.0, latency_ms=0.0, cached=True)

        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                text, cost = self._complete_guarded(prompt, context)
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised wrapped
                last_exc = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(self.backoff_base * (2 ** attempt))
                continue
            latency_ms = (time.perf_counter() - start) * 1000
            if self._use_cache:
                with self._cache_lock:
                    self._cache[key] = (text, cost)
            return ModelResponse(text=text, cost_usd=cost, latency_ms=latency_ms)

        raise ProviderError(
            f"{self.name}/{self.model} failed after {self.max_retries + 1} attempt(s): {last_exc}"
        ) from last_exc
