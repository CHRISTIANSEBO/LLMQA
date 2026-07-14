"""Seed the DB with historical mock runs so the dashboard shows a live trend
chart from day one instead of an empty table on a fresh deploy.

Each seed run uses a different mock provider tier (legacy → lite → strong)
and is timestamped to the past so the trend chart shows a realistic improving
quality curve. Runs are only inserted when the DB is empty; subsequent
restarts are no-ops.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .metrics import REGISTRY, build_metric
from .runner import run_eval
from .store import list_runs, save_run

# (provider_name, days_ago) — oldest first so the chart reads left → right.
# Three tiers spread across two weeks gives a clear improving trend.
_SEED_PLAN = [
    ("mock-legacy", 14),
    ("mock-legacy", 12),
    ("mock-lite",   10),
    ("mock-lite",    8),
    ("mock-lite",    6),
    ("mock-strong",  4),
    ("mock-strong",  2),
    ("mock-strong",  0),
]


def seed_if_empty(dataset_path: str, db_path: str, *, force: bool = False) -> int:
    """Seed the DB with mock historical runs if it currently has no rows.

    Returns the number of runs inserted (0 when the DB already had data).
    Pass ``force=True`` to re-seed even when the DB is not empty (useful for
    testing or resetting a local instance).
    """
    if not force and list_runs(db_path, limit=1):
        return 0  # Already has data — nothing to do.

    # Import here so provider deps are resolved lazily (mirrors get_provider).
    from .providers import get_provider

    all_metric_names = list(REGISTRY)
    now = datetime.now(timezone.utc)
    inserted = 0

    for provider_name, days_ago in _SEED_PLAN:
        provider = get_provider(provider_name, use_cache=False)
        # Build a fresh metric list per run (metrics may hold per-run state).
        metrics = []
        for name in all_metric_names:
            if name in ("llm_judge", "hallucination"):
                metrics.append(build_metric(name, judge=provider))
            else:
                metrics.append(build_metric(name))

        run = run_eval(dataset_path, provider, metrics)
        run.timestamp = (now - timedelta(days=days_ago)).isoformat(timespec="seconds")
        save_run(run, db_path)
        inserted += 1

    return inserted
