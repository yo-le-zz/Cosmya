"""Implements `cosmya config`: the interactive configuration menu system.

Screen layout follows the spec exactly:

    cosmya config
    -> 1. Providers  2. Model  3. Preferences  0. Exit

    Providers -> 1. OpenAI 2. Gemini 3. Claude 4. Ollama 0. Back

Every provider-configuring path is: clear screen -> explain -> collect API
key -> collect/verify protection password -> encrypt & store -> test
connectivity -> discover models -> show success/failure.
"""

from __future__ import annotations

import asyncio
import os

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cosmya.ai.errors import ProviderError
from cosmya.ai.models import ModelInfo
from cosmya.ai.registry import create_provider
from cosmya.config import manager, vault
from cosmya.config.encryption import WrongPasswordError
from cosmya.config.models import Preferences, ProviderName, SelectedModel

console = Console()


def clear_screen() -> None:
    console.clear()


def _provider_status_label(
    provider: ProviderName, configured_names: set[ProviderName]
) -> str:
    if provider is ProviderName.OLLAMA:
        return (
            "[green]●[/green] Available"
            if provider in configured_names
            else "[yellow]●[/yellow] Not checked"
        )
    if provider in configured_names:
        return "[green]●[/green] Configured"
    return "[grey62]○[/grey62] Not configured"


def config_main_menu() -> None:
    while True:
        clear_screen()
        console.print(Panel("Cosmya Configuration", style="bold"))
        choice = questionary.select(
            "Select a section:",
            choices=[
                "1. Providers",
                "2. Model",
                "3. Preferences",
                "0. Exit",
            ],
        ).ask()

        if choice is None or choice.startswith("0"):
            clear_screen()
            return
        if choice.startswith("1"):
            providers_menu()
        elif choice.startswith("2"):
            model_menu()
        elif choice.startswith("3"):
            preferences_menu()


def providers_menu() -> None:
    while True:
        clear_screen()
        configured = set(vault.configured_providers())
        table = Table(title="Providers", show_header=False)
        table.add_column("Provider")
        table.add_column("Status")
        for provider in ProviderName:
            table.add_row(
                provider.display_label, _provider_status_label(provider, configured)
            )
        console.print(table)

        choice = questionary.select(
            "Select a provider to configure:",
            choices=[
                "1. OpenAI",
                "2. Gemini",
                "3. Claude",
                "4. Ollama",
                "0. Back",
            ],
        ).ask()

        if choice is None or choice.startswith("0"):
            clear_screen()
            return

        provider = {
            "1": ProviderName.OPENAI,
            "2": ProviderName.GEMINI,
            "3": ProviderName.CLAUDE,
            "4": ProviderName.OLLAMA,
        }[choice[0]]
        configure_provider(provider)


def configure_provider(provider: ProviderName) -> None:
    clear_screen()
    console.print(Panel(f"Configuring {provider.display_label}", style="bold cyan"))

    api_key: str | None = None
    password: str | None = None

    if provider.requires_api_key:
        console.print(
            f"{provider.display_label} requires an API key. It will be encrypted "
            "with a password before being stored -- the key is never written "
            "to disk in plaintext."
        )
        api_key = questionary.password("API key:").ask()
        if not api_key:
            console.print("[yellow]No API key entered. Cancelled.[/yellow]")
            questionary.press_any_key_to_continue().ask()
            return

        is_first_credential = not vault.vault_exists()
        prompt = (
            "Create a protection password for your stored credentials:"
            if is_first_credential
            else "Enter your existing credential protection password:"
        )
        password = questionary.password(prompt).ask()
        if not password:
            console.print("[yellow]No password entered. Cancelled.[/yellow]")
            questionary.press_any_key_to_continue().ask()
            return

        try:
            vault.store_api_key(provider, api_key, password)
        except WrongPasswordError:
            console.print(
                "[red]Incorrect password. Your existing credentials were not changed.[/red]"
            )
            questionary.press_any_key_to_continue().ask()
            return

    console.print("[cyan]Testing provider connectivity...[/cyan]")
    with console.status("Contacting provider..."):
        ok, detail, models = asyncio.run(
            _test_and_discover(provider, api_key, password)
        )

    if ok:
        console.print(f"[green]Success:[/green] {provider.display_label} is reachable.")
        if models:
            console.print(f"Discovered {len(models)} model(s).")
        _mark_provider_configured(provider)
    else:
        console.print(f"[red]Failed:[/red] {detail}")

    questionary.press_any_key_to_continue().ask()


async def _test_and_discover(
    provider: ProviderName, api_key: str | None, password: str | None
) -> tuple[bool, str, list[ModelInfo]]:
    resolved_key = api_key
    if resolved_key is None and provider.requires_api_key and password:
        try:
            resolved_key = vault.get_api_key(provider, password)
        except (KeyError, FileNotFoundError, WrongPasswordError):
            resolved_key = None

    adapter = create_provider(provider, resolved_key)
    try:
        models = await adapter.list_models()
        return True, "", models
    except ProviderError as exc:
        return False, str(exc), []


def _mark_provider_configured(provider: ProviderName) -> None:
    config = manager.load_config()
    if provider not in config.configured_providers:
        config.configured_providers.append(provider)
        manager.save_config(config)


def model_menu() -> None:
    clear_screen()
    configured = vault.configured_providers()
    config = manager.load_config()
    all_configured = set(configured) | (
        {ProviderName.OLLAMA}
        if ProviderName.OLLAMA in config.configured_providers
        else set()
    )

    if not all_configured:
        console.print(
            Panel(
                "No providers are configured yet. Go to Providers first.",
                style="yellow",
            )
        )
        questionary.press_any_key_to_continue().ask()
        return

    # The vault password is asked for here, BEFORE the async event loop
    # below starts: questionary's synchronous .ask() drives its own
    # internal asyncio.run(), which raises RuntimeError if called while
    # another event loop (the one driving model discovery) is already
    # running. Asking once up front also avoids fighting Rich's live
    # status spinner for terminal control, and since one password unlocks
    # the whole credential vault, it only needs to be asked once here
    # rather than per provider.
    vault_password: str | None = os.environ.get("COSMYA_VAULT_PASSWORD")
    if vault_password is None and any(p.requires_api_key for p in all_configured):
        vault_password = questionary.password(
            "Enter your credential password to load provider models:"
        ).ask()

    console.print(Panel("Discovering available models...", style="bold"))
    with console.status("Querying configured providers..."):
        models = asyncio.run(_discover_all_models(list(all_configured), vault_password))

    if not models:
        console.print(
            "[yellow]No models could be discovered from any configured provider.[/yellow]"
        )
        questionary.press_any_key_to_continue().ask()
        return

    choice = questionary.select(
        "Select a model:",
        choices=[m.label() for m in models] + ["0. Back"],
    ).ask()
    if choice is None or choice == "0. Back":
        return

    selected = next(m for m in models if m.label() == choice)
    config = manager.load_config()
    config.selected_model = SelectedModel(
        provider=selected.provider,
        model_id=selected.id,
        display_name=selected.display_name,
    )
    manager.save_config(config)
    console.print(f"[green]Selected model:[/green] {selected.label()}")
    questionary.press_any_key_to_continue().ask()


async def _discover_all_models(
    providers: list[ProviderName], vault_password: str | None
) -> list[ModelInfo]:
    results: list[ModelInfo] = []
    for provider in providers:
        api_key = None
        if provider.requires_api_key:
            if not vault_password:
                continue
            try:
                api_key = vault.get_api_key(provider, vault_password)
            except (KeyError, FileNotFoundError, WrongPasswordError):
                console.print(
                    f"[red]Could not unlock credentials for {provider.display_label}.[/red]"
                )
                continue
        adapter = create_provider(provider, api_key)
        try:
            results.extend(await adapter.list_models())
        except ProviderError as exc:
            console.print(f"[yellow]{provider.display_label}: {exc}[/yellow]")
    return results


def preferences_menu() -> None:
    clear_screen()
    config = manager.load_config()
    console.print(Panel("Preferences", style="bold"))
    console.print("Custom instructions given to the AI for every audit.")
    if config.preferences.custom_instructions:
        console.print(
            Panel(config.preferences.custom_instructions, title="Current preferences")
        )

    text = questionary.text(
        "Enter your custom instructions (leave blank to keep current):",
        multiline=True,
    ).ask()
    if text:
        config.preferences = Preferences(custom_instructions=text.strip())
        manager.save_config(config)
        console.print("[green]Preferences saved.[/green]")
    questionary.press_any_key_to_continue().ask()
