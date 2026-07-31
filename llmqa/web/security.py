"""Security controls for the public dashboard API.

The dashboard is deployable as a public service, and can be configured with
real (paid) provider keys. Without guards, an anonymous visitor could burn the
operator's API budget or read arbitrary files via a custom dataset path. This
module centralizes three cheap, dependency-free protections:

1. Optional bearer-token auth on mutating endpoints (``LLMQA_API_TOKEN``).
2. A gate that blocks real (paid) providers unless explicitly enabled
   (``LLMQA_ALLOW_REAL_PROVIDERS``).
3. An in-memory per-IP rate limiter on mutating endpoints.

(Untrusted dataset names are resolved safely by ``catalog.resolve_dataset_name``,
which only honors bare file names inside the packaged ``datasets/`` directory.)

All limits are env-configurable and default to safe values.
"""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# Providers that cost real money and therefore need explicit opt-in.
REAL_PROVIDERS = frozenset({"anthropic", "openai", "xai", "grok"})


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


# --- Auth -------------------------------------------------------------------
def require_auth(request: Request) -> None:
    """Enforce a bearer token on mutating endpoints when one is configured.

    No-op when ``LLMQA_API_TOKEN`` is unset (open demo mode). When set, callers
    must send ``Authorization: Bearer <token>`` or ``X-API-Token: <token>``.
    """
    token = os.environ.get("LLMQA_API_TOKEN")
    if not token:
        return
    header = request.headers.get("authorization", "")
    presented = ""
    if header.lower().startswith("bearer "):
        presented = header[7:].strip()
    if not presented:
        presented = request.headers.get("x-api-token", "").strip()
    if presented != token:
        raise HTTPException(status_code=401, detail="Missing or invalid API token.")


# --- Real-provider gate -----------------------------------------------------
def real_providers_allowed() -> bool:
    return _truthy(os.environ.get("LLMQA_ALLOW_REAL_PROVIDERS"))


def check_provider_allowed(name: str) -> None:
    """Block real (paid) providers unless the operator explicitly enabled them.

    This protects the API budget on a public deployment: even if keys are set
    for the operator's own use, anonymous run requests can't spend them unless
    ``LLMQA_ALLOW_REAL_PROVIDERS`` is truthy.
    """
    if name.lower() in REAL_PROVIDERS and not real_providers_allowed():
        raise HTTPException(
            status_code=403,
            detail=(
                f"Real provider {name!r} is disabled on this server. "
                "Set LLMQA_ALLOW_REAL_PROVIDERS=1 to enable paid providers, "
                "or use a mock provider."
            ),
        )


# --- Rate limiting ----------------------------------------------------------
class RateLimiter:
    """A simple thread-safe sliding-window rate limiter keyed by client IP."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        if self.limit <= 0:  # 0/negative disables limiting
            return
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window_s:
                q.popleft()
            if len(q) >= self.limit:
                retry = max(1, int(self.window_s - (now - q[0])))
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Slow down.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)


_LIMITER: RateLimiter | None = None
_LIMITER_LOCK = threading.Lock()


def _limiter() -> RateLimiter:
    global _LIMITER
    # Double-checked locking so concurrent first requests can't each build a
    # separate limiter (which would silently split the rate budget).
    if _LIMITER is None:
        with _LIMITER_LOCK:
            if _LIMITER is None:
                limit = int(os.environ.get("LLMQA_RATE_LIMIT", "30"))
                window = float(os.environ.get("LLMQA_RATE_WINDOW_S", "60"))
                _LIMITER = RateLimiter(limit, window)
    return _LIMITER


def _client_ip(request: Request) -> str:
    # Honor a single proxy hop (Railway/most PaaS) via X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    _limiter().check(_client_ip(request))


def guard_mutation(request: Request, provider: str | None = None) -> None:
    """Run all per-request guards for a mutating endpoint, in order."""
    require_auth(request)
    rate_limit(request)
    if provider is not None:
        check_provider_allowed(provider)
