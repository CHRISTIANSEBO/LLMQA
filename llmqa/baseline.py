"""Committed baseline snapshots for regression detection in ephemeral CI.

The SQLite regression store works locally, but CI runners are ephemeral: there
is no "previous run" to compare against. A **baseline file** solves this the way
snapshot testing does — you commit a small JSON file capturing the expected
per-case scores, and the gate compares each run against it. The file is diffable
and reviewable in a PR, so a change in expected quality is an explicit, visible
edit rather than invisible state in a database.

Workflow::

    llmqa run --provider mock --baseline baselines/qa.json --update-baseline   # record
    # ... commit baselines/qa.json ...
    llmqa run --provider mock --baseline baselines/qa.json --check-baseline     # gate

The check reuses the significance-aware :func:`paired_regression_verdict`, so it
fails only on a real, confident drop — not noise.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .exceptions import DatasetError
from .stats import RegressionVerdict, paired_regression_verdict
from .types import EvalRun

BASELINE_VERSION = 1


def build_baseline(run: EvalRun) -> dict:
    """Serialize the parts of a run needed to detect future regressions."""
    return {
        "version": BASELINE_VERSION,
        "dataset": run.dataset,
        "dataset_hash": run.dataset_hash,
        "provider": run.provider,
        "model": run.model,
        "created": run.timestamp,
        "pass_rate": round(run.pass_rate, 6),
        "avg_score": round(run.avg_score, 6),
        "n_cases": len(run.results),
        "metric_scores": {k: round(v, 6) for k, v in run.score_by_metric().items()},
        "case_scores": {k: round(v, 6) for k, v in run.case_scores().items()},
    }


def write_baseline(run: EvalRun, path: str | Path) -> dict:
    """Write a baseline snapshot for ``run`` to ``path`` (pretty JSON). Returns it."""
    data = build_baseline(run)
    p = Path(path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return data


def load_baseline(path: str | Path) -> dict:
    """Load and lightly validate a baseline file, raising a friendly error."""
    p = Path(path)
    try:
        data = json.loads(p.read_text())
    except FileNotFoundError as exc:
        raise DatasetError(
            f"Baseline file not found: {p}. Create one with "
            f"`llmqa run --baseline {p} --update-baseline`."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise DatasetError(f"Could not read baseline {p}: {exc}") from exc
    if not isinstance(data, dict) or "case_scores" not in data:
        raise DatasetError(f"{p} is not a valid LLMQA baseline (missing case_scores).")
    return data


@dataclass
class BaselineComparison:
    """Result of comparing a run to a committed baseline snapshot."""

    verdict: RegressionVerdict | None
    hash_changed: bool
    added_cases: list[str] = field(default_factory=list)
    removed_cases: list[str] = field(default_factory=list)
    baseline_hash: str = ""
    current_hash: str = ""

    @property
    def is_regression(self) -> bool:
        return bool(self.verdict and self.verdict.is_regression)

    @property
    def comparable(self) -> bool:
        return self.verdict is not None

    def lines(self) -> list[tuple[str, str]]:
        """Human-readable status lines as ``(level, message)`` where level is
        one of ``ok`` / ``warn`` / ``fail``. The CLI maps these to markers.
        """
        out: list[tuple[str, str]] = []
        if self.hash_changed:
            out.append((
                "warn",
                f"dataset changed since baseline (baseline {self.baseline_hash or '?'} "
                f"vs current {self.current_hash or '?'}); comparison may be apples-to-oranges",
            ))
        if self.removed_cases:
            out.append(("warn", f"cases missing vs baseline: {', '.join(self.removed_cases)}"))
        if self.added_cases:
            out.append(("warn", f"new cases not in baseline: {', '.join(self.added_cases)}"))
        if self.verdict is None:
            out.append(("fail", "no overlapping cases with baseline; cannot compare"))
        elif self.verdict.is_regression:
            out.append(("fail", f"regression vs baseline (significant): {self.verdict.summary()}"))
        elif self.verdict.observed_drop > self.verdict.tolerance:
            out.append((
                "ok",
                f"avg score dropped {self.verdict.observed_drop:.3f} but not statistically "
                f"significant \u2014 {self.verdict.summary()}",
            ))
        else:
            out.append(("ok", f"no regression vs baseline \u2014 {self.verdict.summary()}"))
        return out


def compare_to_baseline(
    run: EvalRun,
    baseline: dict,
    *,
    tolerance: float = 0.05,
    confidence: float = 0.95,
) -> BaselineComparison:
    """Compare ``run`` against a loaded ``baseline`` dict, significance-aware."""
    base_scores: dict[str, float] = baseline.get("case_scores", {})
    cur_scores = run.case_scores()
    common = sorted(set(base_scores) & set(cur_scores))
    added = sorted(set(cur_scores) - set(base_scores))
    removed = sorted(set(base_scores) - set(cur_scores))

    verdict: RegressionVerdict | None = None
    if common:
        verdict = paired_regression_verdict(
            [base_scores[c] for c in common],
            [cur_scores[c] for c in common],
            tolerance=tolerance,
            confidence=confidence,
        )

    baseline_hash = baseline.get("dataset_hash", "") or ""
    current_hash = run.dataset_hash or ""
    hash_changed = bool(baseline_hash and current_hash and baseline_hash != current_hash)

    return BaselineComparison(
        verdict=verdict,
        hash_changed=hash_changed,
        added_cases=added,
        removed_cases=removed,
        baseline_hash=baseline_hash,
        current_hash=current_hash,
    )
