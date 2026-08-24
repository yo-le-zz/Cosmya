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


class _FakeQuestion:
    def __init__(self, answer):
        self._answer = answer

    def ask(self):
        return self._answer


def test_maybe_extend_declines_by_default_returns_original_models(monkeypatch):
    import cosmya.cli.config as config_module

    monkeypatch.setattr(
        config_module.questionary, "confirm", lambda *a, **k: _FakeQuestion(False)
    )
    models = _sample_models()
    result = config_module._maybe_extend_with_omniroute_catalog(models, "pw", free_only=False)
    assert result == models


def test_maybe_extend_appends_free_catalog_models(monkeypatch):
    import cosmya.cli.config as config_module
    from cosmya.config.models import ProviderName as PN

    monkeypatch.setattr(
        config_module.questionary, "confirm", lambda *a, **k: _FakeQuestion(True)  # browse=True
    )
    monkeypatch.setattr(config_module.vault, "get_api_key", lambda provider, password: "fake-key")

    captured_free_only = {}

    class FakeOmniRoute:
        async def list_catalog_models(self, *, free_only):
            captured_free_only["value"] = free_only
            return [
                ModelInfo(
                    id="oc/free-model",
                    display_name="oc/free-model \U0001f193",
                    provider=PN.OMNIROUTE,
                )
            ]

    monkeypatch.setattr(config_module, "create_provider", lambda name, key: FakeOmniRoute())

    models = _sample_models()
    result = config_module._maybe_extend_with_omniroute_catalog(models, "pw", free_only=True)

    assert captured_free_only["value"] is True
    ids = [m.id for m in result]
    assert "oc/free-model" in ids
    assert len(result) == len(models) + 1


def test_maybe_extend_confirm_calls_are_constructible(monkeypatch):
    """Same category of bug as the select() regression test: let the real
    questionary.confirm(...) constructor run (only stubbing .ask()), so an
    invalid kwarg combination can't silently pass a fully-mocked suite."""
    import cosmya.cli.config as config_module

    real_confirm = config_module.questionary.confirm
    answers = iter([False])  # decline browsing -- short-circuits before any network use

    def confirm_but_stub_ask(*args, **kwargs):
        question = real_confirm(*args, **kwargs)  # must not raise
        monkeypatch.setattr(question, "ask", lambda: next(answers))
        return question

    monkeypatch.setattr(config_module.questionary, "confirm", confirm_but_stub_ask)

    models = _sample_models()
    result = config_module._maybe_extend_with_omniroute_catalog(models, "pw", free_only=False)
    assert result == models


def test_maybe_extend_deduplicates_models_already_present(monkeypatch):
    """If the catalog happens to include a model id already covered by the
    curated auto aliases, it must not be added twice."""
    import cosmya.cli.config as config_module
    from cosmya.config.models import ProviderName as PN

    models = _sample_models()  # already includes id "auto" for OMNIROUTE

    class FakeOmniRoute:
        async def list_catalog_models(self, *, free_only):
            return [
                ModelInfo(id="auto", display_name="Auto (dup)", provider=PN.OMNIROUTE),
                ModelInfo(id="oc/new-model", display_name="oc/new-model", provider=PN.OMNIROUTE),
            ]

    answers = iter([_FakeQuestion(True), _FakeQuestion(False)])
    monkeypatch.setattr(config_module.questionary, "confirm", lambda *a, **k: next(answers))
    monkeypatch.setattr(config_module, "create_provider", lambda name, key: FakeOmniRoute())
    monkeypatch.setattr(config_module.vault, "get_api_key", lambda provider, password: "fake-key")

    result = config_module._maybe_extend_with_omniroute_catalog(models, "pw", free_only=False)

    ids = [m.id for m in result]
    assert ids.count("auto") == 1
    assert "oc/new-model" in ids
