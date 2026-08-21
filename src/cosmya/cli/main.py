"""Cosmya's Typer CLI application."""

from __future__ import annotations

import typer
from rich.console import Console

from cosmya import __author__, __license__, __repository__, __version__, __website__
from cosmya.cli.audit import run_audit_command
from cosmya.cli.config import config_main_menu

app = typer.Typer(
    name="cosmya",
    help="Cosmya -- an AI-powered, read-only code auditor.",
    add_completion=False,
    no_args_is_help=True,
)

console = Console()


def _print_version() -> None:
    console.print(f"[bold]Cosmya[/bold] version {__version__}")
    console.print(f"Author: {__author__}")
    console.print(f"License: {__license__}")
    console.print(f"Repository: {__repository__}")
    console.print(f"Website: {__website__}")


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v", help="Show Cosmya's version and exit.", is_eager=True
    ),
) -> None:
    if version:
        _print_version()
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@app.command(name="config")
def config_command() -> None:
    """Open the interactive configuration menu (providers, model, preferences)."""
    config_main_menu()


@app.command(name="audit")
def audit_command(
    path: str = typer.Argument(..., help="Path to the project directory to audit."),
) -> None:
    """Run a read-only AI audit of a project directory."""
    run_audit_command(path)
