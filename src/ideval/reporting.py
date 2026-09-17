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
    table.add_column("subject")
    table.add_column("suite")
    table.add_column("n", justify="right")
    table.add_column("kappa", justify="right")
    table.add_column("pabak", justify="right")
    table.add_column("retest", justify="right")
    table.add_column("frame", justify="right")
    table.add_column("prec", justify="right")
    table.add_column("recall", justify="right")
    table.add_column("spearman", justify="right")
    table.add_column("err", justify="right")
    table.add_column("flags")
    for r in reports:
        fmt = lambda v: "-" if v is None else format(v, ".3f")  # noqa: E731
        table.add_row(r.judge, r.subject, r.suite, str(r.n), fmt(r.kappa), fmt(r.pabak),
                      fmt(r.test_retest), fmt(r.framing_agreement),
                      fmt(r.precision), fmt(r.recall), fmt(r.spearman), str(r.errors),
                      ", ".join(r.flags))
    console.print(table)


CALIBRATION_START = "<!-- calibration:start -->"
CALIBRATION_END = "<!-- calibration:end -->"


def update_readme_table(path: Path, markdown: str) -> None:
    """Replace the content between the calibration markers in `path`."""
    text = path.read_text(encoding="utf-8")
    if CALIBRATION_START not in text or CALIBRATION_END not in text:
        raise ValueError(f"{path} is missing calibration markers")
    head, rest = text.split(CALIBRATION_START, 1)
    _, tail = rest.split(CALIBRATION_END, 1)
    path.write_text(f"{head}{CALIBRATION_START}\n{markdown}\n{CALIBRATION_END}{tail}", encoding="utf-8")


def actions_summary(reports: list[CalibrationReport]) -> str:
    """Markdown for GitHub Actions job summaries."""
    lines = ["| judge | subject | suite | n | kappa | pabak | retest | frame | precision | recall | spearman | err | flags |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in reports:
        fmt = lambda v: "-" if v is None else format(v, ".3f")  # noqa: E731
        lines.append(f"| {r.judge} | {r.subject} | {r.suite} | {r.n} | {fmt(r.kappa)} | {fmt(r.pabak)} | "
                     f"{fmt(r.test_retest)} | {fmt(r.framing_agreement)} | {fmt(r.precision)} | "
                     f"{fmt(r.recall)} | {fmt(r.spearman)} | {r.errors} | {', '.join(r.flags)} |")
    return "\n".join(lines)
