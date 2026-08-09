"""Typed exceptions for LLMQA.

A small hierarchy so callers (and the CLI) can distinguish user-fixable
configuration/input problems from unexpected internal errors, and so the CLI can
print a friendly one-line message instead of a raw traceback.

This module imports nothing from the rest of the package, so any module
(including ``providers.base``) can import these without a circular import.
"""
from __future__ import annotations


class LLMQAError(Exception):
    """Base class for all LLMQA errors the user might reasonably hit."""


class DatasetError(LLMQAError):
    """A dataset file is missing, unreadable, malformed, or fails validation."""


class ConfigError(LLMQAError):
    """Invalid CLI/config combination (bad provider, metric, or option value)."""


class MissingAPIKeyError(ConfigError, RuntimeError):
    """A real provider was selected but its API key environment var is unset.

    Also subclasses ``RuntimeError`` for backwards compatibility with callers
    (and tests) that caught the previous ``RuntimeError``.
    """


class ProviderError(LLMQAError, RuntimeError):
    """A provider call failed after exhausting its retries.

    Carries the underlying exception as ``__cause__`` so callers can inspect the
    root cause (rate limit, timeout, auth, etc.). Also subclasses ``RuntimeError``
    for backwards compatibility with existing ``except RuntimeError`` callers.
    """


__all__ = [
    "LLMQAError",
    "DatasetError",
    "ConfigError",
    "MissingAPIKeyError",
    "ProviderError",
]
