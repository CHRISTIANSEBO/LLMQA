#!/usr/bin/env python3
"""LLMQA command-line interface.

Examples:
    python cli.py run --dataset datasets/qa_golden.yaml --provider mock
    python cli.py run --provider anthropic --metrics exact_match similarity llm_judge
    python cli.py run --min-pass-rate 0.8        # exit 1 if below threshold (CI gate)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env if present

from llmqa.metrics import build_metric
from llmqa.providers import get_provider
from llmqa.report import to_console, to_markdown
from llmqa.runner import run_eval
from llmqa.store import save_run, last_run


def cmd_run(args: argparse.Namespace) -> int:
    provider = get_provider(args.provider)

    # LLM-based metrics use the same provider as judge unless it's mock.
    judge = provider
    metrics = []
    for name in args.metrics:
        if name in ("llm_judge", "hallucination"):
            metrics.append(build_metric(name, judge=judge))
        else:
            metrics.append(build_metric(name))

    baseline = last_run(args.db) if args.regression else None

    run = run_eval(args.dataset, provider, metrics, tags=args.tags)
    print(to_console(run))

    if args.markdown:
        Path(args.markdown).write_text(to_markdown(run))
        print(f"\nMarkdown report -> {args.markdown}")

    if not args.no_store:
        run_id = save_run(run, args.db)
        print(f"Saved run #{run_id} to {args.db}")

    exit_code = 0

    # Quality gate: absolute threshold.
    if args.min_pass_rate is not None and run.pass_rate < args.min_pass_rate:
        print(f"\n❌ GATE FAILED: pass rate {run.pass_rate:.0%} < required {args.min_pass_rate:.0%}")
        exit_code = 1

    # Regression gate: compare to previous baseline.
    if baseline:
        drop = baseline["avg_score"] - run.avg_score
        if drop > args.regression_tolerance:
            print(
                f"\n❌ REGRESSION: avg score dropped {drop:.2f} "
                f"({baseline['avg_score']:.2f} → {run.avg_score:.2f}), "
                f"tolerance {args.regression_tolerance:.2f}"
            )
            exit_code = 1
        else:
            print(f"\n✅ No regression vs baseline ({baseline['avg_score']:.2f} → {run.avg_score:.2f})")

    return exit_code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="llmqa", description="LLM Quality Assurance harness")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("run", help="Run an evaluation")
    r.add_argument("--dataset", default="datasets/qa_golden.yaml")
    r.add_argument("--provider", default="mock",
                   help="mock | mock-strong | mock-lite | mock-legacy | anthropic | openai")
    r.add_argument("--metrics", nargs="+",
                   default=["exact_match", "similarity", "llm_judge", "hallucination"])
    r.add_argument("--tags", nargs="*", help="Only run cases with these tags")
    r.add_argument("--min-pass-rate", type=float, help="Fail (exit 1) below this pass rate")
    r.add_argument("--regression", action="store_true", help="Compare to last stored run")
    r.add_argument("--regression-tolerance", type=float, default=0.05)
    r.add_argument("--db", default="llmqa_runs.db")
    r.add_argument("--no-store", action="store_true", help="Do not persist this run")
    r.add_argument("--markdown", help="Write a Markdown report to this path")
    r.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
