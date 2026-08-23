import pytest

from cosmya.ai.models import ModelInfo
from cosmya.config.models import ProviderName


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def _sample_models() -> list[ModelInfo]:
    return [
        ModelInfo(id="gpt-5", display_name="gpt-5", provider=ProviderName.OPENAI),
        ModelInfo(id="gpt-4o", display_name="gpt-4o", provider=ProviderName.OPENAI),
        ModelInfo(
            id="auto",
            display_name="Auto (balanced default)",
            provider=ProviderName.OMNIROUTE,
        ),
        ModelInfo(
            id="auto/coding",
            display_name="Auto — coding-optimized",
            provider=ProviderName.OMNIROUTE,
        ),
    ]


def test_build_model_choices_groups_by_provider_with_separators():
    from cosmya.cli.config import _build_model_choices

    choices = _build_model_choices(_sample_models())
    kinds = [type(c).__name__ for c in choices]
    # Expect: Separator(OpenAI), Choice, Choice, Separator(OmniRoute), Choice, Choice
    assert kinds == ["Separator", "Choice", "Choice", "Separator", "Choice", "Choice"]


def test_build_model_choices_preserves_every_model_as_a_choice_value():
    import questionary

    from cosmya.cli.config import _build_model_choices

    models = _sample_models()
    choices = _build_model_choices(models)
    choice_values = [c.value for c in choices if type(c) is questionary.Choice]
    assert sorted(m.id for m in choice_values) == sorted(m.id for m in models)


def test_build_model_choices_respects_provider_declaration_order():
    """Providers must group in ProviderName enum order regardless of the
    order models happen to arrive in, for a stable, predictable menu."""
    from cosmya.cli.config import _build_model_choices

    # OmniRoute model listed before OpenAI's, but OpenAI comes first in
    # ProviderName's declaration order.
    models = [
        ModelInfo(id="auto", display_name="Auto", provider=ProviderName.OMNIROUTE),
        ModelInfo(id="gpt-5", display_name="gpt-5", provider=ProviderName.OPENAI),
    ]
    choices = _build_model_choices(models)
    separator_titles = [c.title for c in choices if type(c).__name__ == "Separator"]
    assert "OpenAI" in separator_titles[0]
    assert "OmniRoute" in separator_titles[1]


def test_model_menu_select_call_is_constructible(monkeypatch):
    """Regression test for a real bug: `questionary.select(...,
    use_search_filter=True)` raises ValueError at construction time unless
    `use_jk_keys=False` is also passed. A fully-mocked `questionary.select`
    can't catch that -- only letting the real constructor run does."""
    import cosmya.cli.config as config_module
    from cosmya.config import manager, vault
    from cosmya.config.models import ProviderName as PN

    monkeypatch.setenv("COSMYA_VAULT_PASSWORD", "pw")
    vault.store_api_key(PN.OPENAI, "sk-test", "pw")
    config = manager.load_config()
    config.configured_providers.append(PN.OPENAI)
    manager.save_config(config)

    async def fake_discover(providers, password):
        return _sample_models()

    monkeypatch.setattr(config_module, "_discover_all_models", fake_discover)

    real_select = config_module.questionary.select

    def select_but_stub_ask(*args, **kwargs):
        question = real_select(*args, **kwargs)  # must not raise
        monkeypatch.setattr(question, "ask", lambda: None)
        return question

    monkeypatch.setattr(config_module.questionary, "select", select_but_stub_ask)
    monkeypatch.setattr(config_module.console, "clear", lambda: None)
    monkeypatch.setattr(config_module.console, "print", lambda *a, **k: None)
    monkeypatch.setattr(
        config_module.console,
        "status",
        lambda *a, **k: __import__("contextlib").nullcontext(),
    )

    config_module.model_menu()  # must not raise
