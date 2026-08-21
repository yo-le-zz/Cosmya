import pytest

from cosmya.config.encryption import (
    WrongPasswordError,
    compute_password_verifier,
    decrypt_secret,
    derive_key,
    encrypt_secret,
    new_kdf_params,
    verify_password,
)


def _fast_kdf_params():
    """Argon2id params with reduced cost so tests run quickly."""
    params = new_kdf_params()
    params.time_cost = 1
    params.memory_cost_kib = 8192
    params.parallelism = 1
    return params


def test_derive_key_is_deterministic_for_same_password_and_salt():
    kdf = _fast_kdf_params()
    key1 = derive_key("correct horse battery staple", kdf)
    key2 = derive_key("correct horse battery staple", kdf)
    assert key1 == key2
    assert len(key1) == 32


def test_derive_key_differs_for_different_passwords():
    kdf = _fast_kdf_params()
    key1 = derive_key("password-one", kdf)
    key2 = derive_key("password-two", kdf)
    assert key1 != key2


def test_derive_key_differs_for_different_salts():
    kdf1 = _fast_kdf_params()
    kdf2 = _fast_kdf_params()
    assert kdf1.salt_b64 != kdf2.salt_b64
    key1 = derive_key("same-password", kdf1)
    key2 = derive_key("same-password", kdf2)
    assert key1 != key2


def test_verify_password_succeeds_with_correct_password():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    verifier = compute_password_verifier(key)
    recovered_key = verify_password("hunter2", kdf, verifier)
    assert recovered_key == key


def test_verify_password_rejects_wrong_password():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    verifier = compute_password_verifier(key)
    with pytest.raises(WrongPasswordError):
        verify_password("wrong-password", kdf, verifier)


def test_verifier_does_not_reveal_key():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    verifier = compute_password_verifier(key)
    # The verifier must not simply be the key (or a trivial encoding of it).
    assert verifier != key
    import base64

    assert base64.b64encode(key).decode() != verifier


def test_encrypt_decrypt_roundtrip():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    nonce_b64, ciphertext_b64 = encrypt_secret(key, "sk-super-secret-api-key")
    plaintext = decrypt_secret(key, nonce_b64, ciphertext_b64)
    assert plaintext == "sk-super-secret-api-key"


def test_encrypt_uses_fresh_nonce_each_time():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    nonce1, ct1 = encrypt_secret(key, "same-secret")
    nonce2, ct2 = encrypt_secret(key, "same-secret")
    assert nonce1 != nonce2
    assert ct1 != ct2  # GCM output differs due to different nonce


def test_decrypt_fails_with_wrong_key():
    kdf = _fast_kdf_params()
    key1 = derive_key("password-one", kdf)
    key2 = derive_key("password-two", kdf)
    nonce_b64, ciphertext_b64 = encrypt_secret(key1, "top-secret")
    with pytest.raises(WrongPasswordError):
        decrypt_secret(key2, nonce_b64, ciphertext_b64)


def test_decrypt_fails_on_tampered_ciphertext():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    nonce_b64, ciphertext_b64 = encrypt_secret(key, "top-secret")
    tampered = ciphertext_b64[:-4] + (
        "AAAA" if ciphertext_b64[-4:] != "AAAA" else "BBBB"
    )
    with pytest.raises(WrongPasswordError):
        decrypt_secret(key, nonce_b64, tampered)


def test_decrypt_fails_on_tampered_nonce():
    kdf = _fast_kdf_params()
    key = derive_key("hunter2", kdf)
    nonce_b64, ciphertext_b64 = encrypt_secret(key, "top-secret")
    tampered_nonce = nonce_b64[:-4] + ("AAAA" if nonce_b64[-4:] != "AAAA" else "BBBB")
    with pytest.raises((WrongPasswordError, Exception)):
        decrypt_secret(key, tampered_nonce, ciphertext_b64)
