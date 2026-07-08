"""Render an EvalRun as a console table and a shareable Markdown report."""
from __future__ import annotations

from .types import EvalRun


def to_console(run: EvalRun) -> str:
    lines = [
        f"LLMQA run — {run.provider}/{run.model}  ({run.timestamp})",
        f"dataset: {run.dataset}",
        "-" * 64,
    ]
    for r in run.results:
        mark = "PASS" if r.passed else "FAIL"
        metric_bits = " ".join(f"{m.metric}={m.score:.2f}" for m in r.metrics)
        lines.append(f"[{mark}] {r.case_id:<22} {metric_bits}")
    lines += [
        "-" * 64,
        f"pass rate : {run.pass_rate:.0%}  ({sum(1 for r in run.results if r.passed)}/{len(run.results)})",
        f"avg score : {run.avg_score:.2f}",
        f"by metric : " + ", ".join(f"{k}={v:.2f}" for k, v in run.score_by_metric().items()),
        f"cost      : ${run.total_cost_usd:.4f}",
    ]
    return "\n".join(lines)


def to_markdown(run: EvalRun) -> str:
    md = [
        f"# LLMQA Report — {run.provider}/{run.model}",
        "",
        f"- **Dataset:** `{run.dataset}`",
        f"- **Timestamp:** {run.timestamp}",
        f"- **Pass rate:** {run.pass_rate:.0%}",
        f"- **Average score:** {run.avg_score:.2f}",
        f"- **Cost:** ${run.total_cost_usd:.4f}",
        "",
        "| Case | Result | " + " | ".join(run.score_by_metric().keys()) + " |",
        "|------|--------|" + "|".join(["------"] * len(run.score_by_metric())) + "|",
    ]
    metric_names = list(run.score_by_metric().keys())
    for r in run.results:
        by_name = {m.metric: m.score for m in r.metrics}
        row = " | ".join(f"{by_name.get(n, 0):.2f}" for n in metric_names)
        md.append(f"| {r.case_id} | {'✅' if r.passed else '❌'} | {row} |")
    return "\n".join(md)
