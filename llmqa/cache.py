"""Response cache backends for providers.

The cache saves real money: identical provider calls (repeated dashboard runs,
regression compares, a judge re-asking the same prompt) return the stored
answer instead of re-spending tokens. Two backends are available:

- :class:`MemoryCache` - per-process, lost on restart (the default).
- :class:`SqliteCache`  - persisted to a file, shared across restarts and
  across worker processes, keyed by a content hash of the request.

Both are thread-safe so the concurrent runner can share one provider instance.
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path


def cache_key(name: str, model: str, prompt: str, context: str | None) -> str:
    """Stable content hash for a request. Same inputs -> same key across runs."""
    h = hashlib.sha256()
    for part in (name, model, prompt, context or ""):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class CacheBackend(ABC):
    @abstractmethod
    def get(self, key: str) -> tuple[str, float] | None:
        """Return (text, original_cost) for a hit, or None for a miss."""

    @abstractmethod
    def set(self, key: str, text: str, cost: float) -> None:
        ...

    @abstractmethod
    def clear(self) -> None:
        ...


class MemoryCache(CacheBackend):
    """In-process dict cache. Fast, ephemeral, thread-safe."""

    def __init__(self) -> None:
        self._d: dict[str, tuple[str, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> tuple[str, float] | None:
        with self._lock:
            return self._d.get(key)

    def set(self, key: str, text: str, cost: float) -> None:
        with self._lock:
            self._d[key] = (text, cost)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()


class SqliteCache(CacheBackend):
    """SQLite-backed cache that survives restarts and is shared across workers.

    A single connection with ``check_same_thread=False`` guarded by a lock is
    plenty for this workload (short key/value rows, read-mostly).
    """

    def __init__(self, path: str | Path) -> None:
        self._lock = threading.Lock()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS response_cache (
                key     TEXT PRIMARY KEY,
                text    TEXT NOT NULL,
                cost    REAL NOT NULL,
                created TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def get(self, key: str) -> tuple[str, float] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT text, cost FROM response_cache WHERE key = ?", (key,)
            ).fetchone()
        return (row[0], row[1]) if row else None

    def set(self, key: str, text: str, cost: float) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO response_cache (key, text, cost, created)"
                " VALUES (?, ?, ?, ?)",
                (key, text, cost, now),
            )
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM response_cache")
            self._conn.commit()


def build_cache(cache_path: str | Path | None) -> CacheBackend:
    """Persistent cache when a path is given, otherwise an in-memory one."""
    return SqliteCache(cache_path) if cache_path else MemoryCache()
