"""Persist eval runs to SQLite so quality can be tracked over time.

This is what powers regression detection and the trend dashboard: each run's
aggregate metrics are stored with a timestamp, so you can compare the latest
run against the previous baseline.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from .types import EvalRun

DEFAULT_DB = "llmqa_runs.db"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp  TEXT NOT NULL,
            provider   TEXT NOT NULL,
            model      TEXT NOT NULL,
            dataset    TEXT NOT NULL,
            pass_rate  REAL NOT NULL,
            avg_score  REAL NOT NULL,
            cost_usd   REAL NOT NULL,
            n_cases    INTEGER NOT NULL
        )
        """
    )
    return conn


def save_run(run: EvalRun, db_path: str | Path = DEFAULT_DB) -> int:
    conn = _connect(db_path)
    cur = conn.execute(
        "INSERT INTO runs (timestamp, provider, model, dataset, pass_rate, avg_score, cost_usd, n_cases)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            run.timestamp,
            run.provider,
            run.model,
            run.dataset,
            run.pass_rate,
            run.avg_score,
            run.total_cost_usd,
            len(run.results),
        ),
    )
    conn.commit()
    run_id = cur.lastrowid
    conn.close()
    return run_id


def last_run(db_path: str | Path = DEFAULT_DB) -> dict | None:
    """Return the most recent run before the current one, for baseline comparison."""
    if not Path(db_path).exists():
        return None
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT timestamp, provider, model, pass_rate, avg_score FROM runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "timestamp": row[0], "provider": row[1], "model": row[2],
        "pass_rate": row[3], "avg_score": row[4],
    }
