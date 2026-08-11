"""Tests for the statistics helpers and the significance-aware regression gate."""
from __future__ import annotations

from llmqa.stats import (
    bootstrap_mean_ci,
    paired_regression_verdict,
)


def test_bootstrap_ci_brackets_the_mean():
    vals = [0.2, 0.4, 0.6, 0.8, 1.0]
    lo, hi = bootstrap_mean_ci(vals, seed=1)
    mean = sum(vals) / len(vals)
    assert lo <= mean <= hi
    assert lo < hi  # a spread of values yields a non-degenerate interval


def test_bootstrap_ci_degenerate_inputs():
    assert bootstrap_mean_ci([]) == (0.0, 0.0)
    assert bootstrap_mean_ci([0.7]) == (0.7, 0.7)


def test_bootstrap_ci_is_deterministic():
    vals = [0.1, 0.5, 0.9, 0.3, 0.7]
    assert bootstrap_mean_ci(vals, seed=42) == bootstrap_mean_ci(vals, seed=42)


def test_large_consistent_drop_is_a_significant_regression():
    baseline = [1.0] * 12
    current = [0.4] * 12
    v = paired_regression_verdict(baseline, current, tolerance=0.05)
    assert v.observed_drop > 0.05
    assert v.significant
    assert v.is_regression
    assert v.mean_diff < 0


def test_tiny_noisy_drop_is_not_a_regression():
    # A drop within tolerance should never be flagged even if "significant".
    baseline = [0.80, 0.82, 0.79, 0.81]
    current = [0.79, 0.81, 0.78, 0.80]  # ~0.01 lower
    v = paired_regression_verdict(baseline, current, tolerance=0.05)
    assert v.observed_drop < 0.05
    assert not v.is_regression


def test_noisy_data_with_no_confidence_is_not_flagged():
    # Same means but high variance and mixed signs => CI includes 0 => not significant.
    baseline = [0.2, 0.9, 0.5, 0.1, 0.8]
    current = [0.9, 0.2, 0.1, 0.8, 0.5]
    v = paired_regression_verdict(baseline, current, tolerance=0.01)
    assert not v.significant or not v.is_regression


def test_improvement_is_not_a_regression():
    v = paired_regression_verdict([0.5] * 10, [0.9] * 10, tolerance=0.05)
    assert v.mean_diff > 0
    assert not v.is_regression


def test_verdict_summary_is_readable():
    v = paired_regression_verdict([1.0] * 6, [0.5] * 6, tolerance=0.05)
    s = v.summary()
    assert "avg score" in s and "CI" in s and "n=6" in s
