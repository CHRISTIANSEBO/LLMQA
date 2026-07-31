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


def resolve_cli_dataset(name_or_path: str, directory: str | Path = DATASETS_DIR) -> str:
    """Resolve a CLI ``--dataset`` value to a path.

    Unlike :func:`resolve_dataset_name` (which is for untrusted web input), the
    CLI is trusted: an existing file path is used as-is, otherwise the value is
    treated as a name in the packaged datasets directory. Raises if neither
    resolves, so a typo fails loudly instead of silently evaluating the wrong
    data.
    """
    p = Path(name_or_path)
    if p.is_file():
        return str(p)
    candidate = Path(directory) / Path(name_or_path).name
    if candidate.is_file():
        return str(candidate)
    raise FileNotFoundError(
        f"Dataset {name_or_path!r} not found (looked for a file at that path and "
        f"for that name in {directory}). Available: {', '.join(list_datasets(directory)) or 'none'}"
    )


def dataset_hash(path: str | Path) -> str:
    """Short, stable content hash of a dataset file (``sha256:<12 hex>``)."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"sha256:{digest[:12]}"
