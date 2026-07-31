"""Persist eval runs to SQLite so quality can be tracked over time.

This is what powers regression detection and the trend dashboard: each run's
aggregate metrics are stored with a timestamp, so you can compare the latest
run against the previous baseline.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .types import EvalRun

DEFAULT_DB = "llmqa_runs.db"


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
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
            n_cases    INTEGER NOT NULL,
            results_json TEXT
        )
        """
    )
    # Migrate older DBs that predate later columns.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    if "results_json" not in cols:
        conn.execute("ALTER TABLE runs ADD COLUMN results_json TEXT")
    if "label" not in cols:
        # Named baseline tag, e.g. "baseline" or "release-1.2", for pinned
        # regression comparisons instead of always comparing to the last run.
        conn.execute("ALTER TABLE runs ADD COLUMN label TEXT")
    conn.commit()
    return conn


def save_run(run: EvalRun, db_path: str | Path = DEFAULT_DB, label: str | None = None) -> int:
    conn = _connect(db_path)
    try:
        cur = conn.execute(
            "INSERT INTO runs (timestamp, provider, model, dataset, pass_rate, avg_score,"
            " cost_usd, n_cases, results_json, label) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                run.timestamp,
                run.provider,
                run.model,
                run.dataset,
                run.pass_rate,
                run.avg_score,
                run.total_cost_usd,
                len(run.results),
                run.model_dump_json(),
                label,
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def latest_run(db_path: str | Path = DEFAULT_DB, label: str | None = None) -> dict | None:
    """Return the most recent stored run summary, or None if the DB is empty.

    When ``label`` is given, return the most recent run tagged with that label
    (a pinned/named baseline) instead of the newest run overall.
    """
    if not Path(db_path).exists():
        return None
    conn = _connect(db_path)
    try:
        if label is not None:
            row = conn.execute(
                "SELECT timestamp, provider, model, pass_rate, avg_score"
                " FROM runs WHERE label = ? ORDER BY id DESC LIMIT 1",
                (label,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT timestamp, provider, model, pass_rate, avg_score"
                " FROM runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return {
        "timestamp": row[0], "provider": row[1], "model": row[2],
        "pass_rate": row[3], "avg_score": row[4],
    }


def list_runs(db_path: str | Path = DEFAULT_DB, limit: int = 50) -> list[dict]:
    """Return recent runs (newest first) as summary dicts for the dashboard."""
    if not Path(db_path).exists():
        return []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, timestamp, provider, model, dataset, pass_rate, avg_score, cost_usd, n_cases, label"
            " FROM runs ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.close()
    keys = ["id", "timestamp", "provider", "model", "dataset",
            "pass_rate", "avg_score", "cost_usd", "n_cases", "label"]
    return [dict(zip(keys, r, strict=False)) for r in rows]


def get_run(run_id: int, db_path: str | Path = DEFAULT_DB) -> dict | None:
    """Return one run's full detail (aggregates + per-case results_json)."""
    if not Path(db_path).exists():
        return None
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT id, timestamp, provider, model, dataset, pass_rate, avg_score,"
            " cost_usd, n_cases, results_json, label FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    detail = json.loads(row[9]) if row[9] else None
    return {
        "id": row[0], "timestamp": row[1], "provider": row[2], "model": row[3],
        "dataset": row[4], "pass_rate": row[5], "avg_score": row[6],
        "cost_usd": row[7], "n_cases": row[8], "detail": detail,
        "label": row[10] if len(row) > 10 else None,
    }
