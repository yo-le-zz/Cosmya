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


def test_providers_menu_passes_selected_provider_through(monkeypatch):
    """providers_menu() now uses questionary.Choice objects carrying the
    real ProviderName as `value` (instead of a numbered string that had to
    be parsed back into an index -- a previous version of this parsing had
    a bug at index 10+). With structured values there's no parsing left to
    regress on; this just checks the selection is wired through correctly,
    including for a provider past index 9."""
    import cosmya.cli.config as config_module

    assert list(ProviderName)[9] == ProviderName.TOGETHER

    calls = iter(
        [
            _FakeQuestion(ProviderName.TOGETHER),  # pick provider #10 directly
            _FakeQuestion(None),  # then Back / cancel, exiting the loop
        ]
    )
    monkeypatch.setattr(config_module.questionary, "select", lambda *a, **k: next(calls))

    recorded: list[ProviderName] = []
    monkeypatch.setattr(
        config_module, "configure_provider", lambda provider: recorded.append(provider)
    )
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: None)

    config_module.providers_menu()

    assert recorded == [ProviderName.TOGETHER]


def test_keyless_provider_status_reflects_config_after_being_configured(monkeypatch):
    """Regression test: Ollama (the only keyless provider) never appears in
    vault.configured_providers() (it stores no credential), so the status
    table must also check config.configured_providers -- otherwise it
    would show "Not checked" forever even once verified reachable."""
    import cosmya.cli.config as config_module
    from cosmya.config import manager
    from cosmya.config.models import AppConfig

    manager.save_config(AppConfig(configured_providers=[ProviderName.OLLAMA]))

    monkeypatch.setattr(
        config_module.questionary, "select", lambda *a, **k: _FakeQuestion(None)
    )

    printed: list[object] = []
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: printed.append(a))

    config_module.providers_menu()

    # The Table object itself was printed; render it to check its content.
    import io

    from rich.console import Console

    render_console = Console(file=io.StringIO(), width=120)
    for call_args in printed:
        for arg in call_args:
            if hasattr(arg, "columns"):  # a rich.table.Table
                render_console.print(arg)
    rendered = render_console.file.getvalue()
    assert "Available" in rendered


def test_omniroute_requires_api_key_like_cloud_providers():
    """Confirmed by real-world use: unlike Ollama, OmniRoute's gateway
    does gate access behind an API key, so it follows the normal
    vault-backed credential flow rather than the keyless one."""
    assert ProviderName.OMNIROUTE.requires_api_key is True


def test_providers_menu_select_call_is_constructible(monkeypatch):
    """Regression test for a real bug: `questionary.select(...,
    use_search_filter=True)` raises ValueError at construction time unless
    `use_jk_keys=False` is also passed (j/k would otherwise collide with
    search-filter typing). A test that fully mocks `questionary.select`
    itself can't catch that -- only monkeypatching the final `.ask()` and
    letting the real `select()` constructor run does."""
    import cosmya.cli.config as config_module

    real_select = config_module.questionary.select

    def select_but_stub_ask(*args, **kwargs):
        question = real_select(*args, **kwargs)  # must not raise
        monkeypatch.setattr(question, "ask", lambda: None)
        return question

    monkeypatch.setattr(config_module.questionary, "select", select_but_stub_ask)
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: None)

    config_module.providers_menu()  # must not raise
