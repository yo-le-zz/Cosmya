import sys
import types

import pytest

from cosmya.config.models import ProviderName


class _FakeQuestion:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def test_providers_menu_selects_correct_provider_past_index_nine(monkeypatch):
    """Regression test: with only 4 providers, `choice[0]` on a string like
    "10. Together AI" would read "1" and either KeyError or silently select
    the wrong provider. providers_menu() must parse the full number before
    the first '.' instead."""
    import cosmya.cli.config as config_module

    # Index 10 in the (1-based, enumerate-generated) menu is Together AI --
    # see the ProviderName declaration order in config/models.py:
    # OpenAI, Gemini, Claude, Ollama, Groq, OpenRouter, Mistral, DeepSeek,
    # xAI, Together AI, Fireworks AI, Cerebras.
    assert list(ProviderName)[9] == ProviderName.TOGETHER

    calls = iter(
        [
            _FakeQuestion("10. Together AI"),  # pick provider #10
            _FakeQuestion("0. Back"),  # then exit the loop
        ]
    )
    monkeypatch.setattr(
        config_module.questionary, "select", lambda *a, **k: next(calls)
    )

    recorded: list[ProviderName] = []
    monkeypatch.setattr(
        config_module, "configure_provider", lambda provider: recorded.append(provider)
    )
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: None)

    config_module.providers_menu()

    assert recorded == [ProviderName.TOGETHER]


def test_keyless_provider_status_reflects_config_after_being_configured(monkeypatch):
    """Regression test: Ollama/OmniRoute never appear in
    vault.configured_providers() (they store no credential), so the status
    table must also check config.configured_providers -- otherwise a
    successfully-configured keyless provider shows "Not checked" forever."""
    import cosmya.cli.config as config_module
    from cosmya.config import manager
    from cosmya.config.models import AppConfig

    manager.save_config(AppConfig(configured_providers=[ProviderName.OMNIROUTE]))

    calls = iter([_FakeQuestion("0. Back")])
    monkeypatch.setattr(config_module.questionary, "select", lambda *a, **k: next(calls))

    printed: list[object] = []
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: printed.append(a))

    config_module.providers_menu()

    # The Table object itself was printed; render it to check its content.
    from rich.console import Console

    render_console = Console(file=__import__("io").StringIO(), width=120)
    for call_args in printed:
        for arg in call_args:
            if hasattr(arg, "columns"):  # a rich.table.Table
                render_console.print(arg)
    rendered = render_console.file.getvalue()
    assert "Available" in rendered
