"""Implements `cosmya audit <path>`: runs a full agent-driven audit."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import questionary
from rich.console import Console

from cosmya.agent.engine import AgentTurnLimitError, run_audit
from cosmya.agent.tools import NativeExtensionMissingError
from cosmya.ai.errors import ProviderError
from cosmya.ai.registry import create_provider
from cosmya.audit.report import render_report
from cosmya.audit.schema import InvalidAuditResponseError
from cosmya.config import manager, vault
from cosmya.config.encryption import WrongPasswordError

console = Console()


def run_audit_command(project_path: str) -> None:
    resolved = Path(project_path).expanduser().resolve()
    if not resolved.is_dir():
        console.print(f"[red]Not a directory:[/red] {resolved}")
        raise SystemExit(1)

    config = manager.load_config()
    if config.selected_model is None:
        console.print(
            "[yellow]No model selected. Run `cosmya config` and choose a "
            "provider and model first.[/yellow]"
        )
        raise SystemExit(1)

    selected = config.selected_model
    api_key: str | None = None
    if selected.provider.requires_api_key:
        password = (
            os.environ.get("COSMYA_VAULT_PASSWORD")
            or questionary.password("Credential password:").ask()
        )
        if not password:
            console.print("[red]A credential password is required.[/red]")
            raise SystemExit(1)
        try:
            api_key = vault.get_api_key(selected.provider, password)
        except WrongPasswordError:
            console.print("[red]Incorrect password.[/red]")
            raise SystemExit(1)
        except (KeyError, FileNotFoundError):
            console.print(
                f"[red]No credential stored for {selected.provider.display_label}.[/red]"
            )
            raise SystemExit(1)

    provider = create_provider(selected.provider, api_key)

    console.print(
        f"Auditing [bold]{resolved}[/bold] with {selected.display_name} "
        f"({selected.provider.display_label})"
    )

    with console.status("Inspecting project...", spinner="dots") as status:

        def on_progress(message: str) -> None:
            status.update(message)

        try:
            result = asyncio.run(
                run_audit(
                    provider=provider,
                    model_id=selected.model_id,
                    project_root=str(resolved),
                    project_label=str(resolved),
                    custom_instructions=config.preferences.custom_instructions,
                    on_progress=on_progress,
                )
            )
        except NativeExtensionMissingError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(1)
        except (ProviderError, InvalidAuditResponseError, AgentTurnLimitError) as exc:
            console.print(f"[red]Audit failed:[/red] {exc}")
            raise SystemExit(1)

    console.print()
    render_report(result.audit, console=console)
