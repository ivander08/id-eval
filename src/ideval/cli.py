from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__, reporting
from .calibrate import CalibrationReport
from .schema import suite_summaries

app = typer.Typer(help="id-eval: Indonesian LLM evaluation toolkit", no_args_is_help=True)


@app.command()
def list_suites() -> None:
    """List available eval suites."""
    reporting.print_suites(suite_summaries())


@app.command()
def run(suite: str, model: str = typer.Option(..., "--model", "-m"),
        judge: str | None = typer.Option(None, "--judge"),
        limit: int | None = typer.Option(None, "--limit"),
        out: Path | None = typer.Option(None, "--out")) -> None:
    """Run a suite against a model (e.g. --model ollama/qwen2.5:1.5b)."""
    from .runner import run_suite  # deferred: keeps list-suites dependency-free

    results = run_suite(suite, model, judge_model=judge, limit=limit, out=out)
    reporting.print_results(results)
    if out:
        console = reporting.console
        console.print(f"wrote {out}")


@app.command()
def calibrate(
    subject: list[str] = typer.Option(..., "--subject", "-m", help="subject model(s); repeatable"),
    judge: list[str] | None = typer.Option(None, "--judge", help="judge model(s); repeatable"),
    suite: list[str] | None = typer.Option(None, "--suite", help="suite(s); repeatable"),
    limit: int | None = typer.Option(None, "--limit"),
    out: Path | None = typer.Option(None, "--out"),
    update_readme: bool = typer.Option(False, "--update-readme"),
) -> None:
    """Measure judge agreement against exact-match ground truth (M2)."""
    from .calibrate import run_calibration  # deferred: keeps list-suites dependency-free

    judges = judge or ["kenari/deepseek-v4-1-flash"]
    suites = suite or ["factual", "factual_indommlu", "factual_tydiqa"]
    reports, pairs = run_calibration(suites, subject, judges, limit=limit)
    reporting.print_calibration(reports)
    if out:
        payload = {"config": {"suites": suites, "subjects": subject, "judges": judges, "limit": limit},
                   "reports": [r.model_dump() for r in reports],
                   "pairs": pairs}
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        reporting.console.print(f"wrote {out}")
    if update_readme:
        reporting.update_readme_table(Path("README.md"), reporting.actions_summary(reports))
        reporting.console.print("updated README.md calibration table")


@app.command()
def version() -> None:
    typer.echo(f"ideval {__version__}")


if __name__ == "__main__":
    app()
