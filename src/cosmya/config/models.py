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
    """The AI providers Cosmya supports.

    OpenAI, Gemini, Claude, and Ollama have bespoke adapters (each provider's
    wire format differs). Everything else here exposes an OpenAI-compatible
    chat-completions + model-listing API and shares a single adapter --
    see ``ai/openai_compatible.py``.
    """

    OPENAI = "openai"
    GEMINI = "gemini"
    CLAUDE = "claude"
    OLLAMA = "ollama"
    GROQ = "groq"
    OPENROUTER = "openrouter"
    MISTRAL = "mistral"
    DEEPSEEK = "deepseek"
    XAI = "xai"
    TOGETHER = "together"
    FIREWORKS = "fireworks"
    CEREBRAS = "cerebras"
    OMNIROUTE = "omniroute"

    @property
    def display_label(self) -> str:
        return {
            ProviderName.OPENAI: "OpenAI",
            ProviderName.GEMINI: "Gemini",
            ProviderName.CLAUDE: "Claude",
            ProviderName.OLLAMA: "Ollama",
            ProviderName.GROQ: "Groq",
            ProviderName.OPENROUTER: "OpenRouter",
            ProviderName.MISTRAL: "Mistral",
            ProviderName.DEEPSEEK: "DeepSeek",
            ProviderName.XAI: "xAI",
            ProviderName.TOGETHER: "Together AI",
            ProviderName.FIREWORKS: "Fireworks AI",
            ProviderName.CEREBRAS: "Cerebras",
            ProviderName.OMNIROUTE: "OmniRoute",
        }[self]

    @property
    def requires_api_key(self) -> bool:
        # Ollama and OmniRoute are both local, self-hosted gateways that
        # work out of the box with no credential (OmniRoute: "Works the
        # second you install it -- no keys, no config"). OmniRoute does
        # optionally accept a bearer token for its own remote-mode auth,
        # which the provider adapter supports if one is configured, but it
        # is never required.
        return self not in (ProviderName.OLLAMA, ProviderName.OMNIROUTE)


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
