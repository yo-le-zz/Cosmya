"""Typed data models for Cosmya's configuration and encrypted credential store.

Two files are kept strictly separate on disk:

* ``config.toml``      -- non-secret settings (selected model, preferences).
* ``credentials.json``  -- Argon2id/AEAD-protected provider API keys.

Nothing in this module ever holds a plaintext secret longer than necessary,
and secrets are never included in a model's ``repr``/``str``.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, SecretStr

CONFIG_SCHEMA_VERSION = 1
CREDENTIAL_SCHEMA_VERSION = 1


class ProviderName(str, Enum):
    """The four AI providers Cosmya supports."""

    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"
    OLLAMA = "ollama"

    @property
    def display_label(self) -> str:
        return {
            ProviderName.OPENAI: "OpenAI",
            ProviderName.GEMINI: "Gemini",
            ProviderName.CLAUDE: "Claude",
            ProviderName.OLLAMA: "Ollama",
        }[self]

    @property
    def requires_api_key(self) -> bool:
        return self is not ProviderName.OLLAMA


class SelectedModel(BaseModel):
    """The model chosen by the user, persisted by provider + stable id."""

    provider: ProviderName
    model_id: str
    display_name: str


class Preferences(BaseModel):
    """User-provided free-text instructions injected into audit prompts.

    This content is treated as inert prompt *data*, never as instructions
    that can alter Cosmya's own system prompt or tool behavior.
    """

    custom_instructions: str = ""


class AppConfig(BaseModel):
    """Non-secret configuration persisted to ``config.toml``."""

    schema_version: int = CONFIG_SCHEMA_VERSION
    selected_model: SelectedModel | None = None
    preferences: Preferences = Field(default_factory=Preferences)
    configured_providers: list[ProviderName] = Field(default_factory=list)


class KdfParams(BaseModel):
    """Argon2id parameters used to derive the credential encryption key."""

    algorithm: str = "argon2id"
    time_cost: int = 3
    memory_cost_kib: int = 65536  # 64 MiB
    parallelism: int = 4
    salt_b64: str


class EncryptedCredential(BaseModel):
    """A single provider's API key, stored only in encrypted form."""

    provider: ProviderName
    nonce_b64: str
    ciphertext_b64: str
    algorithm: str = "aes-256-gcm"


class CredentialStore(BaseModel):
    """The full on-disk encrypted credential file."""

    schema_version: int = CREDENTIAL_SCHEMA_VERSION
    kdf: KdfParams
    password_verifier_b64: str
    credentials: dict[ProviderName, EncryptedCredential] = Field(default_factory=dict)


class PlaintextApiKey(BaseModel):
    """In-memory only. Never serialized to disk."""

    provider: ProviderName
    api_key: SecretStr

    def __repr__(self) -> str:  # pragma: no cover - defensive
        return f"PlaintextApiKey(provider={self.provider!r}, api_key=**redacted**)"
