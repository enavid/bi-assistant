"""Tests for CredentialCipher — at-rest credential encryption (TDD).

Verifies round-trip correctness, the encrypted-value marker, backward-compatible
passthrough for legacy plaintext, and wrong-key failure handling.
"""

from __future__ import annotations

import pytest

from app.core.crypto import (
    _ENC_PREFIX,
    CredentialCipher,
    CredentialDecryptionError,
)

_SECRET = "unit-test-secret-key"


def _cipher(secret: str = _SECRET) -> CredentialCipher:
    return CredentialCipher(secret)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_encrypt_then_decrypt_roundtrips():
    cipher = _cipher()
    secret = "p@ssw0rd!"
    token = cipher.encrypt(secret)
    assert cipher.decrypt(token) == secret


def test_encrypted_value_is_marked_and_differs_from_plaintext():
    cipher = _cipher()
    token = cipher.encrypt("hunter2")
    assert token.startswith(_ENC_PREFIX)
    assert "hunter2" not in token


def test_unicode_password_roundtrips():
    cipher = _cipher()
    secret = "گذرواژهٔ محرمانه ۱۲۳"
    assert cipher.decrypt(cipher.encrypt(secret)) == secret


def test_empty_string_roundtrips():
    cipher = _cipher()
    assert cipher.decrypt(cipher.encrypt("")) == ""


def test_same_plaintext_encrypts_to_different_tokens():
    # Fernet embeds a random IV/timestamp, so ciphertext must not be deterministic.
    cipher = _cipher()
    a = cipher.encrypt("same")
    b = cipher.encrypt("same")
    assert a != b
    assert cipher.decrypt(a) == cipher.decrypt(b) == "same"


# ---------------------------------------------------------------------------
# Backward compatibility (legacy plaintext passthrough)
# ---------------------------------------------------------------------------


def test_decrypt_legacy_plaintext_passthrough():
    cipher = _cipher()
    # A value without the marker is a pre-encryption legacy row; return it as-is.
    assert cipher.decrypt("legacy-plain-password") == "legacy-plain-password"


def test_is_encrypted_detection():
    cipher = _cipher()
    assert cipher.is_encrypted(cipher.encrypt("x")) is True
    assert cipher.is_encrypted("plain") is False
    assert cipher.is_encrypted("") is False


# ---------------------------------------------------------------------------
# Key handling
# ---------------------------------------------------------------------------


def test_wrong_key_cannot_decrypt():
    token = _cipher("key-one").encrypt("secret")
    with pytest.raises(CredentialDecryptionError):
        _cipher("key-two").decrypt(token)


def test_arbitrary_length_secret_is_accepted():
    # The cipher must accept any human-provided secret, not only 32-byte Fernet keys.
    for secret in ("x", "a" * 200, "short"):
        cipher = _cipher(secret)
        assert cipher.decrypt(cipher.encrypt("v")) == "v"
