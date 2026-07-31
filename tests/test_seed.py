"""Seeding populates an empty DB with a realistic historical trend."""
from __future__ import annotations

from pathlib import Path

from llmqa.seed import seed_if_empty
from llmqa.store import list_runs

DATASET = str(Path(__file__).resolve().parent.parent / "datasets" / "qa_golden.yaml")


def test_seed_if_empty_inserts_then_noop(tmp_path):
    db = str(tmp_path / "seed.db")
    inserted = seed_if_empty(DATASET, db)
    assert inserted > 0
    runs = list_runs(db)
    assert len(runs) == inserted
    # Providers span the mock tiers, so the trend isn't flat.
    providers = {r["provider"] for r in runs}
    assert providers  # at least one tier present

    # Second call is a no-op because the DB already has rows.
    assert seed_if_empty(DATASET, db) == 0


def test_seed_force_reseeds(tmp_path):
    db = str(tmp_path / "seed2.db")
    first = seed_if_empty(DATASET, db)
    again = seed_if_empty(DATASET, db, force=True)
    assert again == first
    assert len(list_runs(db, limit=1000)) == first * 2
