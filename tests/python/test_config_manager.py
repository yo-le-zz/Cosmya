import pytest

from cosmya.config import manager
from cosmya.config.models import AppConfig, Preferences, ProviderName, SelectedModel


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def test_load_config_returns_defaults_when_missing():
    config = manager.load_config()
    assert config.selected_model is None
    assert config.preferences.custom_instructions == ""
    assert config.configured_providers == []


def test_save_and_load_config_roundtrip():
    config = AppConfig(
        selected_model=SelectedModel(
            provider=ProviderName.CLAUDE,
            model_id="claude-sonnet-5",
            display_name="Claude Sonnet 5",
        ),
        preferences=Preferences(custom_instructions="Be strict about security."),
        configured_providers=[ProviderName.CLAUDE],
    )
    manager.save_config(config)

    loaded = manager.load_config()
    assert loaded.selected_model is not None
    assert loaded.selected_model.model_id == "claude-sonnet-5"
    assert loaded.preferences.custom_instructions == "Be strict about security."
    assert loaded.configured_providers == [ProviderName.CLAUDE]


def test_config_path_uses_xdg_config_home(isolated_config_home):
    path = manager.config_path()
    assert str(path).startswith(str(isolated_config_home))
    assert path.name == "config.toml"


def test_save_config_is_atomic_no_partial_file_left(isolated_config_home):
    config = AppConfig()
    manager.save_config(config)
    cosmya_dir = isolated_config_home / "cosmya"
    leftover_tmp_files = list(cosmya_dir.glob(".*.tmp"))
    assert leftover_tmp_files == []
