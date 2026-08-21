import pytest

from cosmya.config import vault
from cosmya.config.encryption import WrongPasswordError
from cosmya.config.models import ProviderName


@pytest.fixture(autouse=True)
def isolated_config_home(tmp_path, monkeypatch):
    """Redirect XDG_CONFIG_HOME so tests never touch the real user config."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    yield tmp_path


def test_vault_does_not_exist_initially():
    assert vault.vault_exists() is False


def test_store_and_retrieve_api_key():
    vault.store_api_key(ProviderName.OPENAI, "sk-test-key-123", "my-password")
    assert vault.vault_exists() is True
    retrieved = vault.get_api_key(ProviderName.OPENAI, "my-password")
    assert retrieved == "sk-test-key-123"


def test_wrong_password_raises():
    vault.store_api_key(ProviderName.OPENAI, "sk-test-key-123", "correct-password")
    with pytest.raises(WrongPasswordError):
        vault.get_api_key(ProviderName.OPENAI, "wrong-password")


def test_second_provider_reuses_same_master_password():
    vault.store_api_key(ProviderName.OPENAI, "openai-key", "shared-password")
    vault.store_api_key(ProviderName.CLAUDE, "claude-key", "shared-password")

    assert vault.get_api_key(ProviderName.OPENAI, "shared-password") == "openai-key"
    assert vault.get_api_key(ProviderName.CLAUDE, "shared-password") == "claude-key"


def test_second_provider_with_wrong_master_password_fails():
    vault.store_api_key(ProviderName.OPENAI, "openai-key", "shared-password")
    with pytest.raises(WrongPasswordError):
        vault.store_api_key(ProviderName.CLAUDE, "claude-key", "different-password")


def test_missing_provider_credential_raises_key_error():
    vault.store_api_key(ProviderName.OPENAI, "openai-key", "pw")
    with pytest.raises(KeyError):
        vault.get_api_key(ProviderName.CLAUDE, "pw")


def test_get_api_key_with_no_vault_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        vault.get_api_key(ProviderName.OPENAI, "any-password")


def test_remove_api_key():
    vault.store_api_key(ProviderName.OPENAI, "openai-key", "pw")
    vault.remove_api_key(ProviderName.OPENAI, "pw")
    with pytest.raises(KeyError):
        vault.get_api_key(ProviderName.OPENAI, "pw")


def test_configured_providers_lists_stored_keys():
    assert vault.configured_providers() == []
    vault.store_api_key(ProviderName.OPENAI, "k1", "pw")
    vault.store_api_key(ProviderName.GEMINI, "k2", "pw")
    providers = vault.configured_providers()
    assert set(providers) == {ProviderName.OPENAI, ProviderName.GEMINI}


def test_credentials_file_never_contains_plaintext_key(isolated_config_home):
    secret = "sk-super-duper-secret-value-xyz"
    master_password = "correct-horse-battery-staple"
    vault.store_api_key(ProviderName.OPENAI, secret, master_password)
    cred_file = isolated_config_home / "cosmya" / "credentials.json"
    assert cred_file.exists()
    content = cred_file.read_text(encoding="utf-8")
    assert secret not in content
    assert master_password not in content


def test_credential_file_permissions_are_restrictive(isolated_config_home):
    import stat

    vault.store_api_key(ProviderName.OPENAI, "secret", "pw")
    cred_file = isolated_config_home / "cosmya" / "credentials.json"
    mode = stat.S_IMODE(cred_file.stat().st_mode)
    assert mode == 0o600


def test_config_dir_permissions_are_restrictive(isolated_config_home):
    import stat

    vault.store_api_key(ProviderName.OPENAI, "secret", "pw")
    cosmya_dir = isolated_config_home / "cosmya"
    mode = stat.S_IMODE(cosmya_dir.stat().st_mode)
    assert mode == 0o700
