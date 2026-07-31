"""Render an EvalRun as a console table, a Markdown report, or JUnit XML."""
from __future__ import annotations

from xml.sax.saxutils import escape, quoteattr

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


def to_junit(run: EvalRun, suite_name: str = "llmqa") -> str:
    """Render the run as JUnit XML so CI systems show each case as a test.

    A failing case becomes a ``<testcase>`` with a ``<failure>`` child listing
    the per-metric scores and which metric gated the failure. This is the
    standard format GitHub Actions, GitLab, Jenkins, etc. ingest for test
    reporting.
    """
    n_failures = sum(1 for r in run.results if not r.passed)
    props = (
        f'<properties>'
        f'<property name="provider" value={quoteattr(run.provider)}/>'
        f'<property name="model" value={quoteattr(run.model)}/>'
        f'<property name="dataset" value={quoteattr(run.dataset)}/>'
        f'<property name="dataset_hash" value={quoteattr(run.dataset_hash or "")}/>'
        f'<property name="pass_rate" value="{run.pass_rate:.4f}"/>'
        f'<property name="avg_score" value="{run.avg_score:.4f}"/>'
        f'</properties>'
    )

    cases_xml = []
    for r in run.results:
        scores = " ".join(f"{m.metric}={m.score:.2f}" for m in r.metrics)
        attrs = (
            f'name={quoteattr(r.case_id)} classname={quoteattr(suite_name)} '
            f'time="{(r.latency_ms or 0) / 1000:.3f}"'
        )
        if r.passed:
            cases_xml.append(f"    <testcase {attrs}/>")
        else:
            gated = ", ".join(r.gate_metrics) if r.gate_metrics else "all metrics"
            msg = f"case failed (gated on: {gated})"
            body = escape(f"scores: {scores}")
            cases_xml.append(
                f"    <testcase {attrs}>\n"
                f"      <failure message={quoteattr(msg)}>{body}</failure>\n"
                f"    </testcase>"
            )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuites tests="{len(run.results)}" failures="{n_failures}">\n'
        f'  <testsuite name={quoteattr(suite_name)} tests="{len(run.results)}" '
        f'failures="{n_failures}">\n'
        f"    {props}\n" + "\n".join(cases_xml) + "\n"
        "  </testsuite>\n"
        "</testsuites>\n"
    )
