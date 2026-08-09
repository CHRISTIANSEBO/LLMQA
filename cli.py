#!/usr/bin/env python3
"""LLMQA command-line interface.

Examples:
    python cli.py run --dataset datasets/qa_golden.yaml --provider mock
    python cli.py run --provider openai --judge-provider anthropic   # avoid self-judging
    python cli.py run --min-pass-rate 0.8                            # CI quality gate
    python cli.py run --min-tag-pass-rate rag=0.9 --max-avg-latency-ms 800
    python cli.py run --label baseline                               # pin a baseline
    python cli.py run --regression --regression-baseline baseline    # gate vs it
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env if present

from llmqa import __version__
from llmqa.catalog import resolve_cli_dataset
from llmqa.exceptions import LLMQAError
from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.report import to_console, to_junit, to_markdown
from llmqa.runner import run_eval
from llmqa.store import latest_run, save_run

log = logging.getLogger("llmqa")


def _configure_logging(verbose: bool) -> None:
    """Opt-in structured logging. Quiet by default so normal output is clean.

    ``--verbose`` (or ``LLMQA_LOG_LEVEL=DEBUG``) surfaces provider retries,
    cache hits, and timings on stderr; the report itself still goes to stdout.
    """
    import os

    level_name = "DEBUG" if verbose else os.environ.get("LLMQA_LOG_LEVEL", "WARNING")
    level = getattr(logging, level_name.upper(), logging.WARNING)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )


def _parse_kv(pairs: list[str] | None, *, kind: str) -> dict[str, float]:
    """Parse ``KEY=FLOAT`` CLI args into a dict, e.g. ``rag=0.9``."""
    out: dict[str, float] = {}
    for item in pairs or []:
        if "=" not in item:
            raise SystemExit(f"--{kind} expects KEY=VALUE, got {item!r}")
        key, _, val = item.partition("=")
        try:
            out[key.strip()] = float(val)
        except ValueError:
            raise SystemExit(f"--{kind} value must be a number, got {val!r}") from None
    return out


def cmd_run(args: argparse.Namespace) -> int:
    _configure_logging(getattr(args, "verbose", False))
    log.debug("starting run: provider=%s dataset=%s", args.provider, args.dataset)
    provider = get_provider(
        args.provider,
        use_cache=not args.no_cache,
        cache_path=args.cache_path,
        max_retries=args.retries,
        timeout_s=args.timeout,
    )

    # Judge for LLM-based metrics. Defaults to the provider under test, but a
    # separate --judge-provider avoids the model grading its own output
    # (self-judging bias/circularity).
    if args.judge_provider:
        judge = get_provider(args.judge_provider, use_cache=not args.no_cache)
    else:
        judge = provider

    metrics = []
    for name in args.metrics:
        if name == "llm_judge":
            metrics.append(build_metric(name, judge=judge, samples=args.judge_samples))
        elif name == "hallucination":
            metrics.append(build_metric(name, judge=judge))
        else:
            metrics.append(build_metric(name))

    baseline = (
        latest_run(args.db, label=args.regression_baseline)
        if args.regression
        else None
    )

    dataset_path = resolve_cli_dataset(args.dataset)
    run = run_eval(
        dataset_path, provider, metrics, tags=args.tags,
        concurrency=args.concurrency, max_cost_usd=args.max_cost,
    )
    print(to_console(run))

    if run.stopped_early:
        print(f"\n⚠ Run stopped early: {run.stopped_reason}")

    if args.markdown:
        Path(args.markdown).write_text(to_markdown(run))
        print(f"\nMarkdown report -> {args.markdown}")

    if args.junit:
        Path(args.junit).write_text(to_junit(run))
        print(f"JUnit XML -> {args.junit}")

    # GitHub Actions annotations: surface each failing case inline on the PR.
    if args.github_annotations:
        for r in run.results:
            if not r.passed:
                gated = ", ".join(r.gate_metrics) if r.gate_metrics else "all metrics"
                scores = " ".join(f"{m.metric}={m.score:.2f}" for m in r.metrics)
                print(f"::error title=LLMQA::{r.case_id} failed (gated on {gated}) — {scores}")

    if not args.no_store:
        run_id = save_run(run, args.db, label=args.label)
        tag = f" [label={args.label}]" if args.label else ""
        print(f"Saved run #{run_id} to {args.db}{tag}")

    return _evaluate_gates(run, args, baseline)


def _evaluate_gates(run, args, baseline) -> int:
    """Apply every configured gate; return 0 if all pass, 1 if any fail."""
    failures: list[str] = []
    oks: list[str] = []

    # 1) Absolute pass-rate gate.
    if args.min_pass_rate is not None:
        if run.pass_rate < args.min_pass_rate:
            failures.append(
                f"pass rate {run.pass_rate:.0%} < required {args.min_pass_rate:.0%}"
            )
        else:
            oks.append(f"pass rate {run.pass_rate:.0%} >= {args.min_pass_rate:.0%}")

    # 2) Per-tag pass-rate gates.
    if args.min_tag_pass_rate:
        by_tag = run.pass_rate_by_tag()
        for tag, need in _parse_kv(args.min_tag_pass_rate, kind="min-tag-pass-rate").items():
            got = by_tag.get(tag)
            if got is None:
                failures.append(f"tag {tag!r} not present in run")
            elif got < need:
                failures.append(f"tag {tag!r} pass rate {got:.0%} < {need:.0%}")
            else:
                oks.append(f"tag {tag!r} pass rate {got:.0%} >= {need:.0%}")

    # 3) Per-metric average-score gates.
    if args.min_metric_score:
        by_metric = run.score_by_metric()
        for metric, need in _parse_kv(args.min_metric_score, kind="min-metric-score").items():
            got = by_metric.get(metric)
            if got is None:
                failures.append(f"metric {metric!r} not scored in run")
            elif got < need:
                failures.append(f"metric {metric!r} avg {got:.2f} < {need:.2f}")
            else:
                oks.append(f"metric {metric!r} avg {got:.2f} >= {need:.2f}")

    # 4) Latency budget (average or p95).
    if args.max_avg_latency_ms is not None and run.avg_latency_ms > args.max_avg_latency_ms:
        failures.append(f"avg latency {run.avg_latency_ms:.0f}ms > {args.max_avg_latency_ms:.0f}ms")
    if args.max_p95_latency_ms is not None and run.p95_latency_ms > args.max_p95_latency_ms:
        failures.append(f"p95 latency {run.p95_latency_ms:.0f}ms > {args.max_p95_latency_ms:.0f}ms")

    # 5) Cost budget.
    if args.max_cost_budget is not None and run.total_cost_usd > args.max_cost_budget:
        failures.append(f"cost ${run.total_cost_usd:.4f} > budget ${args.max_cost_budget:.4f}")

    # 6) Regression gate vs baseline.
    if baseline:
        drop = baseline["avg_score"] - run.avg_score
        if drop > args.regression_tolerance:
            failures.append(
                f"regression: avg score dropped {drop:.2f} "
                f"({baseline['avg_score']:.2f} -> {run.avg_score:.2f}), "
                f"tolerance {args.regression_tolerance:.2f}"
            )
        else:
            oks.append(
                f"no regression vs baseline ({baseline['avg_score']:.2f} -> {run.avg_score:.2f})"
            )

    # Surface any provider errors that were captured per case.
    errored = [r.case_id for r in run.results if getattr(r, "error", None)]
    if errored:
        failures.append(f"provider errors on: {', '.join(errored)}")

    for msg in oks:
        print(f"\n\u2705 {msg}")
    for msg in failures:
        print(f"\n\u274c GATE FAILED: {msg}")

    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmqa", description="LLM Quality Assurance harness")
    p.add_argument("--version", action="version", version=f"llmqa {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run an evaluation")
    r.add_argument("-v", "--verbose", action="store_true",
                   help="Verbose logging on stderr (retries, cache hits, timings)")
    r.add_argument("--dataset", default="qa_golden.yaml",
                   help="A dataset file path, or a name in the packaged datasets/ dir")
    r.add_argument("--provider", default="mock",
                   help="mock | mock-strong | mock-lite | mock-legacy | anthropic | openai | xai")
    r.add_argument("--judge-provider", default=None,
                   help="Separate provider for llm_judge/hallucination (avoids self-judging)")
    r.add_argument("--metrics", nargs="+",
                   default=["exact_match", "similarity", "llm_judge", "hallucination"])
    r.add_argument("--tags", nargs="*", help="Only run cases with these tags")

    # Execution / resilience.
    r.add_argument("--concurrency", type=int, default=1,
                   help="Run this many cases in parallel (I/O-bound provider calls)")
    r.add_argument("--timeout", type=float, default=None,
                   help="Per-call hard timeout in seconds for a provider request")
    r.add_argument("--retries", type=int, default=2,
                   help="Retries per provider call on failure (exponential backoff)")
    r.add_argument("--judge-samples", type=int, default=1,
                   help="Poll the LLM judge N times and take the majority grade "
                        "(self-consistency; denoises a flaky judge)")
    r.add_argument("--max-cost", type=float, default=None,
                   help="Stop the run once accumulated cost (USD) reaches this ceiling")

    # Gating.
    r.add_argument("--min-pass-rate", type=float, help="Fail (exit 1) below this pass rate")
    r.add_argument("--min-tag-pass-rate", nargs="*", metavar="TAG=RATE",
                   help="Per-tag pass-rate gates, e.g. rag=0.9 adversarial=0.8")
    r.add_argument("--min-metric-score", nargs="*", metavar="METRIC=SCORE",
                   help="Per-metric average-score gates, e.g. llm_judge=0.7")
    r.add_argument("--max-avg-latency-ms", type=float, help="Fail if avg case latency exceeds this")
    r.add_argument("--max-p95-latency-ms", type=float, help="Fail if p95 case latency exceeds this")
    r.add_argument("--max-cost-budget", type=float,
                   help="Gate: fail (exit 1) if total run cost (USD) exceeds this budget")

    # Regression / baselines.
    r.add_argument("--regression", action="store_true", help="Compare to a stored baseline run")
    r.add_argument("--regression-baseline", default=None, metavar="LABEL",
                   help="Compare to the latest run with this label (default: latest run overall)")
    r.add_argument("--regression-tolerance", type=float, default=0.05)
    r.add_argument("--label", default=None, help="Tag this stored run with a label (e.g. baseline)")

    # Storage / output.
    r.add_argument("--db", default="llmqa_runs.db")
    r.add_argument("--no-store", action="store_true", help="Do not persist this run")
    r.add_argument("--no-cache", action="store_true",
                   help="Disable the response cache (forces a fresh call per case)")
    r.add_argument("--cache-path", default=None,
                   help="Persist the response cache to this SQLite file "
                        "(survives restarts and is shared across runs)")
    r.add_argument("--markdown", help="Write a Markdown report to this path")
    r.add_argument("--junit", help="Write a JUnit XML report to this path (for CI test reporting)")
    r.add_argument("--github-annotations", action="store_true",
                   help="Emit ::error:: annotations for failing cases (GitHub Actions)")
    r.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except LLMQAError as exc:
        # User-fixable problems (bad dataset, missing key, bad config): show a
        # clean one-line message, not a traceback. Use --verbose for the stack.
        print(f"error: {exc}", file=sys.stderr)
        if getattr(args, "verbose", False):
            raise
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
