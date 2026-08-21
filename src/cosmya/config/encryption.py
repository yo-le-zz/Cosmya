"""Password-based encryption for Cosmya's stored API credentials.

Flow (see project spec):

    user password -> Argon2id -> derived key -> AES-256-GCM -> ciphertext

The user's password is NEVER persisted. Only:

* a random salt,
* Argon2id parameters,
* a password *verifier* (a value derived from the key, used only to check
  a candidate password is correct without ever storing the password or the
  encryption key itself),
* and AEAD ciphertext/nonces per provider

are written to disk.

Wrong-password handling: verification is checked before any decryption is
attempted, and failures return a dedicated exception without leaking any
timing- or content-based signal about the correct key.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cosmya.config.models import KdfParams

_KEY_LEN = 32  # AES-256
_NONCE_LEN = 12  # 96-bit GCM nonce, per NIST SP 800-38D recommendation
_SALT_LEN = 16
_VERIFIER_INFO = b"cosmya-credential-password-verifier-v1"


class WrongPasswordError(Exception):
    """Raised when a supplied password fails verification."""


def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))


def new_kdf_params() -> KdfParams:
    """Generate fresh Argon2id parameters with a new random salt."""
    salt = os.urandom(_SALT_LEN)
    return KdfParams(salt_b64=_b64e(salt))


def derive_key(password: str, kdf: KdfParams) -> bytes:
    """Derive a 32-byte AES-256 key from ``password`` using Argon2id.

    The raw derived key is used only in memory for this process's lifetime;
    it is never written to disk or logged.
    """
    salt = _b64d(kdf.salt_b64)
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=kdf.time_cost,
        memory_cost=kdf.memory_cost_kib,
        parallelism=kdf.parallelism,
        hash_len=_KEY_LEN,
        type=Type.ID,  # Argon2id
    )


def compute_password_verifier(key: bytes) -> str:
    """Derive a verifier value from the key (never the raw key itself).

    We use HMAC-SHA256 with a fixed info string as a one-way transform of
    the derived key, so the stored verifier cannot be used to recover the
    encryption key, yet still lets us confirm a candidate password derives
    the same key.
    """
    verifier = hmac.new(key, _VERIFIER_INFO, hashlib.sha256).digest()
    return _b64e(verifier)


def verify_password(password: str, kdf: KdfParams, expected_verifier_b64: str) -> bytes:
    """Verify ``password`` against a stored verifier.

    Returns the derived key on success. Raises :class:`WrongPasswordError`
    on failure. Uses a constant-time comparison to avoid leaking
    information through timing.
    """
    key = derive_key(password, kdf)
    candidate = compute_password_verifier(key)
    if not hmac.compare_digest(candidate, expected_verifier_b64):
        raise WrongPasswordError("The supplied password is incorrect.")
    return key


def encrypt_secret(key: bytes, plaintext: str) -> tuple[str, str]:
    """Encrypt ``plaintext`` with AES-256-GCM under ``key``.

    Returns ``(nonce_b64, ciphertext_b64)``. A fresh random nonce is used
    for every encryption call, as required for GCM safety.
    """
    aesgcm = AESGCM(key)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data=None)
    return _b64e(nonce), _b64e(ciphertext)


def decrypt_secret(key: bytes, nonce_b64: str, ciphertext_b64: str) -> str:
    """Decrypt and authenticate a stored secret. Raises on tampering."""
    aesgcm = AESGCM(key)
    nonce = _b64d(nonce_b64)
    ciphertext = _b64d(ciphertext_b64)
    try:
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data=None)
    except InvalidTag as exc:
        raise WrongPasswordError(
            "Credential could not be decrypted or authenticated."
        ) from exc
    return plaintext.decode("utf-8")
