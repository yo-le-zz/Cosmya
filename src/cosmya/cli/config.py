"""Implements `cosmya config`: the interactive configuration menu system.

Screen layout follows the spec:

    cosmya config
    -> 1. Providers  2. Model  3. Preferences  0. Exit

    Providers -> one colored, searchable entry per ProviderName (see
    providers_menu()), plus Back.

Every provider-configuring path is: clear screen -> explain -> collect API
key -> collect/verify protection password -> encrypt & store -> test
connectivity -> discover models -> show success/failure.

Both the provider list and the model list use questionary.Choice objects
carrying real values (a ProviderName / a ModelInfo) rather than parsed
strings, and colorize entries so a long list (now 13 providers, and
potentially many more models once several providers are configured) stays
readable instead of a flat wall of white text. Both lists also enable
type-to-filter search, since scrolling a long uncolored menu is exactly
what got complained about.
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
from cosmya.ai.openai_compatible import OMNIROUTE_AUTO_MODEL_LABELS
from cosmya.ai.registry import create_provider
from cosmya.config import manager, vault
from cosmya.config.encryption import WrongPasswordError
from cosmya.config.models import ProviderName, SelectedModel

console = Console()

# questionary.Choice(value=None) silently falls back to using the choice's
# *title* string as its resolved value -- None is not treated as "no
# selection", it's treated as "no value was set, use the title instead".
# A "Back" choice built with value=None therefore returns the string
# "Back" from .ask(), not None, which crashed configure_provider(provider)
# with `'str' object has no attribute 'display_label'` the moment anyone
# picked Back. This sentinel is guaranteed never equal to any real
# ProviderName/ModelInfo, so it can be checked for unambiguously alongside
# genuine None (Ctrl+C / cancelled prompt).
_BACK = object()

# A stable color per provider (indexed by declaration order in
# ProviderName), used to visually group a long model list by which
# provider each entry came from. Plain prompt_toolkit ANSI color names, so
# they render correctly in questionary's Choice titles (Rich markup does
# not apply here -- that's only for console.print/Table).
_COLOR_PALETTE = [
    "ansicyan",
    "ansimagenta",
    "ansiyellow",
    "ansigreen",
    "ansiblue",
    "ansired",
    "ansibrightcyan",
    "ansibrightmagenta",
    "ansibrightyellow",
    "ansibrightgreen",
    "ansibrightblue",
    "ansibrightred",
    "ansiwhite",
]


def _provider_color(provider: ProviderName) -> str:
    providers_in_order = list(ProviderName)
    index = providers_in_order.index(provider) % len(_COLOR_PALETTE)
    return _COLOR_PALETTE[index]


def clear_screen() -> None:
    console.clear()


def _provider_status_label(
    provider: ProviderName, configured_names: set[ProviderName]
) -> str:
    if not provider.requires_api_key:
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


def _provider_choice(provider: ProviderName, configured: set[ProviderName]) -> "questionary.Choice":
    if provider in configured:
        dot_color, suffix = "ansigreen", ""
    elif not provider.requires_api_key:
        dot_color, suffix = "ansiyellow", " (not checked)"
    else:
        dot_color, suffix = "ansibrightblack", " (not configured)"
    title = [
        (f"fg:{dot_color} bold", "\u25cf "),
        ("bold" if provider in configured else "", provider.display_label),
        ("fg:ansibrightblack", suffix),
    ]
    return questionary.Choice(title=title, value=provider)


def providers_menu() -> None:
    providers = list(ProviderName)
    while True:
        clear_screen()
        # Vault-backed providers (API-key ones) and keyless providers
        # (currently just Ollama) are tracked in two different places --
        # the encrypted vault vs. config.toml's configured_providers list
        # -- so the status set has to check both, or a keyless provider
        # would show "Not checked" forever even once verified reachable.
        config = manager.load_config()
        configured = set(vault.configured_providers()) | set(config.configured_providers)
        table = Table(title="Providers", show_header=False)
        table.add_column("Provider")
        table.add_column("Status")
        for provider in providers:
            table.add_row(
                provider.display_label, _provider_status_label(provider, configured)
            )
        console.print(table)

        choices = [_provider_choice(p, configured) for p in providers]
        choices.append(questionary.Choice(title=[("fg:ansired", "Back")], value=_BACK))
        provider = questionary.select(
            "Select a provider to configure (type to search):",
            choices=choices,
            use_search_filter=True,
            use_jk_keys=False,
        ).ask()

        if provider is None or provider is _BACK:
            clear_screen()
            return

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
        if provider is ProviderName.OMNIROUTE:
            _select_omniroute_auto_model()
    else:
        console.print(f"[red]Failed:[/red] {detail}")

    questionary.press_any_key_to_continue().ask()


def _select_omniroute_auto_model() -> None:
    """OmniRoute is meant to be Cosmya's default routing path: as soon as
    it's successfully verified, it becomes the active model (OmniRoute's
    own ``auto`` routing alias), so audits go through it without a
    separate trip to the Model menu. This can still be changed freely
    from Model afterwards.
    """
    config = manager.load_config()
    config.selected_model = SelectedModel(
        provider=ProviderName.OMNIROUTE,
        model_id="auto",
        display_name=OMNIROUTE_AUTO_MODEL_LABELS["auto"],
    )
    manager.save_config(config)
    console.print(
        "[cyan]Model set to OmniRoute's 'auto' routing -- audits will go through "
        "OmniRoute by default. Change this anytime via Model in the config menu.[/cyan]"
    )


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
    all_configured = set(configured) | {
        p for p in config.configured_providers if not p.requires_api_key
    }

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

    if ProviderName.OMNIROUTE in all_configured:
        models = _maybe_extend_with_omniroute_catalog(
            models, vault_password, free_only=config.preferences.free_models_only
        )

    if config.preferences.free_models_only:
        console.print(
            "[cyan]Filtering to free models only (change this in "
            "Preferences).[/cyan]"
        )
        models = [m for m in models if m.metadata.get("free") is True]

    if not models:
        if config.preferences.free_models_only:
            console.print(
                "[yellow]No confirmed-free models found among configured "
                "providers. Turn off 'free models only' in Preferences to "
                "see everything.[/yellow]"
            )
        else:
            console.print(
                "[yellow]No models could be discovered from any configured provider.[/yellow]"
            )
        questionary.press_any_key_to_continue().ask()
        return

    choices = _build_model_choices(models)
    choices.append(questionary.Choice(title=[("fg:ansired", "Back")], value=_BACK))
    selected = questionary.select(
        "Select a model (type to search):",
        choices=choices,
        use_search_filter=True,
        use_jk_keys=False,
    ).ask()
    if selected is None or selected is _BACK:
        return

    config = manager.load_config()
    config.selected_model = SelectedModel(
        provider=selected.provider,
        model_id=selected.id,
        display_name=selected.display_name,
    )
    manager.save_config(config)
    console.print(f"[green]Selected model:[/green] {selected.label()}")
    questionary.press_any_key_to_continue().ask()


def _maybe_extend_with_omniroute_catalog(
    models: list[ModelInfo], vault_password: str | None, *, free_only: bool
) -> list[ModelInfo]:
    """Offers to add OmniRoute's real upstream catalog to the model list,
    on top of the curated `auto` aliases already in `models` -- so picking
    a specific provider/model through OmniRoute is possible, not just
    `auto`. Declined by default (a fast Enter keeps the previous
    behavior). Whether the fetched catalog is restricted to free models is
    driven by the persisted "free models only" preference (see
    preferences_menu()), not asked here every time.
    """
    browse = questionary.confirm(
        "OmniRoute can also route to one specific provider/model instead of "
        "just 'auto'. Browse OmniRoute's own catalog?",
        default=False,
    ).ask()
    if not browse:
        return models

    api_key: str | None = None
    if vault_password:
        try:
            api_key = vault.get_api_key(ProviderName.OMNIROUTE, vault_password)
        except (KeyError, FileNotFoundError, WrongPasswordError):
            console.print("[red]Could not unlock OmniRoute credentials.[/red]")
            return models
    if api_key is None:
        console.print("[red]OmniRoute requires a credential password to browse its catalog.[/red]")
        return models

    omniroute = create_provider(ProviderName.OMNIROUTE, api_key)
    with console.status("Fetching OmniRoute's catalog..."):
        try:
            catalog_models = asyncio.run(
                omniroute.list_catalog_models(free_only=free_only)
            )
        except ProviderError as exc:
            console.print(f"[yellow]OmniRoute catalog: {exc}[/yellow]")
            return models

    if not catalog_models:
        console.print("[yellow]No matching OmniRoute models found.[/yellow]")
        return models

    existing_ids = {m.id for m in models if m.provider == ProviderName.OMNIROUTE}
    new_models = [m for m in catalog_models if m.id not in existing_ids]
    return models + new_models


def _build_model_choices(models: list[ModelInfo]) -> list["questionary.Choice"]:
    """Groups models by provider with a separator + a stable color per
    provider, so a long combined list (several providers, each possibly
    with many models) stays scannable instead of one flat undifferentiated
    list. Providers are visited in ProviderName declaration order for a
    stable, predictable grouping across runs.
    """
    grouped: dict[ProviderName, list[ModelInfo]] = {}
    for model in models:
        grouped.setdefault(model.provider, []).append(model)

    label_width = max((len(p.display_label) for p in grouped), default=0)
    choices: list[questionary.Choice] = []
    for provider in ProviderName:
        provider_models = grouped.get(provider)
        if not provider_models:
            continue
        color = _provider_color(provider)
        choices.append(questionary.Separator(f"── {provider.display_label} ──"))
        for model in provider_models:
            title = [
                (f"fg:{color} bold", f"{provider.display_label:<{label_width}}"),
                ("", f"  {model.display_name}"),
            ]
            choices.append(questionary.Choice(title=title, value=model))
    return choices


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

    console.print()
    console.print(
        "'Free models only' applies across every provider whenever you open "
        "Model: only models Cosmya can confirm are free are shown. Detection "
        "is best-effort (most providers don't expose pricing at all, so "
        "their models won't show up while this is on)."
    )
    free_models_only = questionary.confirm(
        "Show only free models in the Model menu?",
        default=config.preferences.free_models_only,
    ).ask()

    # Update in place rather than replacing config.preferences wholesale --
    # that used to silently wipe out any preference field not being edited
    # in this pass.
    if text:
        config.preferences.custom_instructions = text.strip()
    if free_models_only is not None:
        config.preferences.free_models_only = free_models_only
    manager.save_config(config)
    console.print("[green]Preferences saved.[/green]")
    questionary.press_any_key_to_continue().ask()
