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
def calibrate(suite: str = "factual", judges: str = "openrouter/openai/gpt-4o-mini",
              limit: int | None = None, out_json: Path | None = None) -> None:
    """Measure judge agreement against exact-match ground truth (M2)."""
    typer.echo("calibrate: wired to real runs in M2 (statistics implemented and tested)")


@app.command()
def version() -> None:
    typer.echo(f"ideval {__version__}")


if __name__ == "__main__":
    app()
