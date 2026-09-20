from __future__ import annotations

import json
from pathlib import Path

import typer

from . import __version__, reporting
from .calibrate import CalibrationReport
from .schema import suite_summaries

app = typer.Typer(help="id-eval: Indonesian LLM evaluation toolkit", no_args_is_help=True)

JUDGE_BACKENDS = ("native", "deepeval")


def _check_backend(backend: str) -> None:
    """Fail loudly on a typo instead of silently falling back to the native path."""
    if backend not in JUDGE_BACKENDS:
        raise typer.BadParameter(f"unknown judge backend '{backend}'; expected one of {', '.join(JUDGE_BACKENDS)}",
                                 param_hint="--judge-backend")


@app.command()
def list_suites() -> None:
    """List available eval suites."""
    reporting.print_suites(suite_summaries())


@app.command()
def run(suite: str, model: str = typer.Option(..., "--model", "-m"),
        judge: str | None = typer.Option(None, "--judge"),
        limit: int | None = typer.Option(None, "--limit"),
        out: Path | None = typer.Option(None, "--out"),
        judge_backend: str = typer.Option("native", "--judge-backend",
                                          help="judge implementation: native | deepeval")) -> None:
    """Run a suite against a model (e.g. --model ollama/qwen2.5:1.5b)."""
    from .runner import run_suite  # deferred: keeps list-suites dependency-free

    _check_backend(judge_backend)
    results = run_suite(suite, model, judge_model=judge, limit=limit, out=out,
                        judge_backend=judge_backend)
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
    repeats: int = typer.Option(1, "--repeats", help="judge draws per case; >1 enables test-retest"),
    out: Path | None = typer.Option(None, "--out"),
    annotations: Path | None = typer.Option(None, "--annotations",
                                            help="rubric ground-truth labels (JSONL); "
                                                 "turns the rubric suites into judge-vs-truth rows"),
    update_readme: bool = typer.Option(False, "--update-readme"),
    judge_backend: str = typer.Option("native", "--judge-backend",
                                      help="judge implementation: native | deepeval"),
) -> None:
    """Measure judge agreement against exact-match ground truth (M2)."""
    from .calibrate import load_labels, run_calibration  # deferred: keeps list-suites dependency-free

    _check_backend(judge_backend)
    judges = judge or ["kenari/deepseek-v4-1-flash"]
    suites = suite or ["factual", "factual_indommlu", "factual_tydiqa"]
    labels = load_labels(annotations) if annotations else None
    reports, pairs = run_calibration(suites, subject, judges, limit=limit, repeats=repeats,
                                     judge_backend=judge_backend, labels=labels)
    reporting.print_calibration(reports)
    if out:
        payload = {"config": {"suites": suites, "subjects": subject, "judges": judges,
                              "limit": limit, "repeats": repeats,
                              "judge_backend": judge_backend,
                              "annotations": str(annotations) if annotations else None},
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
