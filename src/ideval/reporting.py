from __future__ import annotations

from rich.console import Console
from rich.table import Table

from .calibrate import CalibrationReport
from .schema import EvalResult, SuiteSummary

console = Console()


def print_suites(summaries: list[SuiteSummary]) -> None:
    table = Table(title="id-eval suites")
    table.add_column("suite")
    table.add_column("cases", justify="right")
    table.add_column("exact-match", justify="right")
    table.add_column("rubric", justify="right")
    for s in summaries:
        table.add_row(s.name, str(s.count), str(s.scoreable), str(s.rubric))
    console.print(table)


def print_results(results: list[EvalResult]) -> None:
    scored = [r for r in results if r.score is not None]
    table = Table(title=f"results ({len(scored)}/{len(results)} scored)")
    table.add_column("case")
    table.add_column("score", justify="right")
    table.add_column("error")
    for r in results:
        table.add_row(r.case_id, "-" if r.score is None else f"{r.score:.2f}", r.error or "")
    console.print(table)
    if scored:
        avg = sum(r.score for r in scored) / len(scored)
        console.print(f"average score: {avg:.3f}")


def print_calibration(reports: list[CalibrationReport]) -> None:
    table = Table(title="judge calibration vs exact-match ground truth")
    table.add_column("judge")
    table.add_column("suite")
    table.add_column("n", justify="right")
    table.add_column("kappa", justify="right")
    table.add_column("prec", justify="right")
    table.add_column("recall", justify="right")
    table.add_column("spearman", justify="right")
    for r in reports:
        fmt = lambda v: "-" if v is None else format(v, ".3f")  # noqa: E731
        table.add_row(r.judge, r.suite, str(r.n), fmt(r.kappa), fmt(r.precision), fmt(r.recall), fmt(r.spearman))
    console.print(table)


def actions_summary(reports: list[CalibrationReport]) -> str:
    """Markdown for GitHub Actions job summaries."""
    lines = ["| judge | suite | n | kappa | precision | recall | spearman |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for r in reports:
        fmt = lambda v: "-" if v is None else format(v, ".3f")  # noqa: E731
        lines.append(f"| {r.judge} | {r.suite} | {r.n} | {fmt(r.kappa)} | "
                     f"{fmt(r.precision)} | {fmt(r.recall)} | {fmt(r.spearman)} |")
    return "\n".join(lines)
