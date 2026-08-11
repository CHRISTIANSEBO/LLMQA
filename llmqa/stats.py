"""Lightweight statistics for quantifying evaluation uncertainty.

A pass rate of 88% over 12 cases and 88% over 1,200 cases are very different
claims, and "avg score dropped 0.02" between two runs is often just noise. These
helpers put **confidence intervals** on aggregate scores and decide whether a
regression versus a baseline is **statistically significant** rather than random
variation — so the CI regression gate stops firing (or staying silent) on noise.

Implemented with the standard library only (percentile bootstrap): a QA harness
core should install without numpy/scipy. Every function is deterministic given
its ``seed`` so CI output and gate decisions are reproducible.
"""
from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass

DEFAULT_RESAMPLES = 2000
DEFAULT_CONFIDENCE = 0.95
DEFAULT_SEED = 1234


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence (q in [0,1])."""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    idx = q * (len(sorted_vals) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = idx - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_mean_ci(
    values: Sequence[float],
    *,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> tuple[float, float]:
    """Percentile-bootstrap confidence interval for the mean of ``values``.

    Returns ``(low, high)``. Degenerate inputs are handled gracefully: an empty
    sequence yields ``(0.0, 0.0)`` and a single value yields ``(v, v)``.
    """
    vals = list(values)
    if not vals:
        return (0.0, 0.0)
    if len(vals) == 1:
        return (vals[0], vals[0])
    rng = random.Random(seed)
    n = len(vals)
    means = sorted(sum(vals[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_resamples))
    tail = (1 - confidence) / 2
    return (_percentile(means, tail), _percentile(means, 1 - tail))


@dataclass
class RegressionVerdict:
    """Outcome of comparing a run's per-case scores against a baseline's.

    ``mean_diff`` is ``mean(current) - mean(baseline)`` (negative = worse than
    baseline). ``ci_low``/``ci_high`` bound that difference. ``significant`` is
    True when the whole CI sits below zero (we are confident the change is a real
    drop). ``is_regression`` requires BOTH a drop larger than ``tolerance`` in
    the point estimate AND significance — the combination is what kills noise.
    """

    n_pairs: int
    baseline_mean: float
    current_mean: float
    mean_diff: float
    ci_low: float
    ci_high: float
    observed_drop: float
    tolerance: float
    confidence: float
    significant: bool
    is_regression: bool

    def summary(self) -> str:
        pct = int(round(self.confidence * 100))
        return (
            f"avg score {self.baseline_mean:.3f} -> {self.current_mean:.3f} "
            f"(Δ {self.mean_diff:+.3f}, {pct}% CI [{self.ci_low:+.3f}, {self.ci_high:+.3f}], "
            f"n={self.n_pairs})"
        )


def paired_regression_verdict(
    baseline_scores: Sequence[float],
    current_scores: Sequence[float],
    *,
    tolerance: float = 0.05,
    confidence: float = DEFAULT_CONFIDENCE,
    n_resamples: int = DEFAULT_RESAMPLES,
    seed: int = DEFAULT_SEED,
) -> RegressionVerdict:
    """Decide whether ``current`` is a significant regression versus ``baseline``.

    ``baseline_scores`` and ``current_scores`` are equal-length, index-aligned
    per-case scores (align them on shared case ids before calling). The mean of
    the paired differences is bootstrapped to get a CI; a regression is reported
    only when the point-estimate drop exceeds ``tolerance`` *and* the CI confirms
    the drop is real (its upper bound is below zero).
    """
    if len(baseline_scores) != len(current_scores):
        raise ValueError("baseline_scores and current_scores must be the same length")
    n = len(baseline_scores)
    diffs = [c - b for b, c in zip(baseline_scores, current_scores, strict=True)]
    baseline_mean = sum(baseline_scores) / n if n else 0.0
    current_mean = sum(current_scores) / n if n else 0.0
    mean_diff = sum(diffs) / n if n else 0.0
    ci_low, ci_high = bootstrap_mean_ci(
        diffs, confidence=confidence, n_resamples=n_resamples, seed=seed
    )
    observed_drop = baseline_mean - current_mean
    significant = ci_high < 0.0  # entire CI below zero => confident real drop
    is_regression = significant and observed_drop > tolerance
    return RegressionVerdict(
        n_pairs=n,
        baseline_mean=baseline_mean,
        current_mean=current_mean,
        mean_diff=mean_diff,
        ci_low=ci_low,
        ci_high=ci_high,
        observed_drop=observed_drop,
        tolerance=tolerance,
        confidence=confidence,
        significant=significant,
        is_regression=is_regression,
    )
