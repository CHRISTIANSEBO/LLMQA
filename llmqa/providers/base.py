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


class Provider(ABC):
    name: str = "base"
    model: str = "unknown"

    @abstractmethod
    def _complete(self, prompt: str, context: str | None = None) -> tuple[str, float]:
        """Return (text, cost_usd). Implemented per provider."""

    def generate(self, prompt: str, context: str | None = None) -> ModelResponse:
        """Time the call and wrap the result. Shared by all providers."""
        start = time.perf_counter()
        text, cost = self._complete(prompt, context)
        latency_ms = (time.perf_counter() - start) * 1000
        return ModelResponse(text=text, cost_usd=cost, latency_ms=latency_ms)
