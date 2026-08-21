"""High-level API for storing and retrieving encrypted provider credentials.

This is the module the rest of Cosmya should use -- it never exposes raw
Argon2id/AES-GCM primitives to callers, only "give me the key for provider X
given this password" / "store this key under this password".
"""

from __future__ import annotations

from cosmya.config import manager
from cosmya.config.encryption import (
    WrongPasswordError,
    compute_password_verifier,
    decrypt_secret,
    derive_key,
    encrypt_secret,
    new_kdf_params,
    verify_password,
)
from cosmya.config.models import CredentialStore, EncryptedCredential, ProviderName

__all__ = [
    "WrongPasswordError",
    "get_api_key",
    "remove_api_key",
    "store_api_key",
    "vault_exists",
]


def vault_exists() -> bool:
    return manager.load_credential_store() is not None


def _unlock(password: str) -> tuple[CredentialStore, bytes]:
    """Load the store and verify the password, returning the derived key."""
    store = manager.load_credential_store()
    if store is None:
        raise FileNotFoundError("No credentials have been configured yet.")
    key = verify_password(password, store.kdf, store.password_verifier_b64)
    return store, key


def store_api_key(provider: ProviderName, api_key: str, password: str) -> None:
    """Encrypt and persist ``api_key`` for ``provider`` under ``password``.

    If this is the first credential ever stored, a new Argon2id salt and
    password verifier are created and the password becomes the vault's
    master password. Subsequent calls must supply the same password.
    """
    store = manager.load_credential_store()
    if store is None:
        kdf = new_kdf_params()
        key = derive_key(password, kdf)
        store = CredentialStore(
            kdf=kdf,
            password_verifier_b64=compute_password_verifier(key),
        )
    else:
        key = verify_password(password, store.kdf, store.password_verifier_b64)

    nonce_b64, ciphertext_b64 = encrypt_secret(key, api_key)
    store.credentials[provider] = EncryptedCredential(
        provider=provider,
        nonce_b64=nonce_b64,
        ciphertext_b64=ciphertext_b64,
    )
    manager.save_credential_store(store)


def get_api_key(provider: ProviderName, password: str) -> str:
    """Decrypt and return the API key for ``provider``.

    Raises :class:`WrongPasswordError` on an incorrect password and
    :class:`KeyError` if no credential is stored for that provider.
    """
    store, key = _unlock(password)
    credential = store.credentials.get(provider)
    if credential is None:
        raise KeyError(f"No credential stored for provider {provider.value!r}.")
    return decrypt_secret(key, credential.nonce_b64, credential.ciphertext_b64)


def remove_api_key(provider: ProviderName, password: str) -> None:
    store, _key = _unlock(password)
    store.credentials.pop(provider, None)
    manager.save_credential_store(store)


def configured_providers() -> list[ProviderName]:
    store = manager.load_credential_store()
    if store is None:
        return []
    return list(store.credentials.keys())
