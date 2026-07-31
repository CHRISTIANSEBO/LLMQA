"""Dataset catalog: discovery, safe resolution, and content versioning.

The web UI lets you pick among the datasets shipped in ``datasets/``. To keep
that safe, a name coming from an HTTP request is resolved *only* against that
directory (no path traversal). Each run also records a short content hash of
the dataset file so the trend view can tell when two runs used different data.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = REPO_ROOT / "datasets"
DEFAULT_DATASET_NAME = "qa_golden.yaml"


def list_datasets(directory: str | Path = DATASETS_DIR) -> list[str]:
    """Available dataset file names (e.g. ``qa_golden.yaml``), sorted."""
    return sorted(p.name for p in Path(directory).glob("*.yaml"))


def resolve_dataset_name(name: str | None, directory: str | Path = DATASETS_DIR) -> str:
    """Resolve an untrusted dataset *name* to a full path inside ``directory``.

    Only a bare file name that actually exists in the datasets directory is
    honored; anything else (missing, a path with separators, traversal) falls
    back to the default dataset. Safe to call with request-supplied input.
    """
    directory = Path(directory)
    default = str(directory / DEFAULT_DATASET_NAME)
    if not name:
        return default
    # Reject anything that isn't a plain file name in the directory.
    if "/" in name or "\\" in name or name != Path(name).name:
        return default
    candidate = directory / name
    return str(candidate) if candidate.is_file() else default


def dataset_hash(path: str | Path) -> str:
    """Short, stable content hash of a dataset file (``sha256:<12 hex>``)."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest[:12]}"
