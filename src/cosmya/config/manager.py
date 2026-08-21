"""Persistence layer for Cosmya configuration and encrypted credentials.

Locations follow the XDG Base Directory spec on Linux:

    $XDG_CONFIG_HOME/cosmya/config.toml       (default: ~/.config/cosmya/)
    $XDG_CONFIG_HOME/cosmya/credentials.json

Directories are created with ``0700`` and files with ``0600`` so that only
the owning user can read stored (encrypted) credentials.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib  # Python >= 3.11 stdlib
from pathlib import Path

import tomli_w

from cosmya.config.models import AppConfig, CredentialStore

_APP_DIR_NAME = "cosmya"
_CONFIG_FILENAME = "config.toml"
_CREDENTIALS_FILENAME = "credentials.json"

_DIR_MODE = 0o700
_FILE_MODE = 0o600


def config_home() -> Path:
    """Return the Cosmya config directory, creating it if necessary."""
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    app_dir = base / _APP_DIR_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    _restrict_permissions(app_dir, _DIR_MODE)
    return app_dir


def config_path() -> Path:
    return config_home() / _CONFIG_FILENAME


def credentials_path() -> Path:
    return config_home() / _CREDENTIALS_FILENAME


def _restrict_permissions(path: Path, mode: int) -> None:
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != mode:
            path.chmod(mode)
    except OSError:
        # Best-effort: some filesystems (e.g. certain container overlays)
        # do not support chmod. We do not fail configuration for this.
        pass


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically with restrictive permissions."""
    directory = path.parent
    fd, tmp_name = tempfile.mkstemp(
        dir=directory, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.chmod(tmp_name, _FILE_MODE)
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    return AppConfig.model_validate(raw)


def save_config(config: AppConfig) -> None:
    # TOML has no representation for "null", so omit unset optional fields
    # (e.g. selected_model before a model has ever been chosen).
    data = tomli_w.dumps(config.model_dump(mode="json", exclude_none=True)).encode(
        "utf-8"
    )
    _atomic_write(config_path(), data)


def load_credential_store() -> CredentialStore | None:
    path = credentials_path()
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return CredentialStore.model_validate(raw)


def save_credential_store(store: CredentialStore) -> None:
    data = json.dumps(store.model_dump(mode="json"), indent=2).encode("utf-8")
    _atomic_write(credentials_path(), data)
