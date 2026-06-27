"""Symmetric encryption for credentials at rest (Fernet / AES-128-CBC + HMAC).

Stored values are prefixed with :data:`_ENC_PREFIX`. A value without the prefix
is treated as legacy plaintext and returned unchanged by :meth:`decrypt`, so the
feature can be rolled out without a blocking data migration: existing rows keep
working and are upgraded to ciphertext the next time they are written.
"""

from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_ENC_PREFIX = "enc:v1:"


class CredentialDecryptionError(Exception):
    """Raised when a marked ciphertext cannot be decrypted (wrong key or corruption)."""


class CredentialCipher:
    """Encrypts/decrypts credential strings with a key derived from a secret."""

    def __init__(self, secret: str) -> None:
        if not secret:
            raise ValueError("CredentialCipher requires a non-empty secret")
        self._fernet = Fernet(self._derive_key(secret))

    @staticmethod
    def _derive_key(secret: str) -> bytes:
        # Accept any human-provided secret and derive a 32-byte url-safe Fernet key.
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    @staticmethod
    def is_encrypted(stored: str) -> bool:
        return bool(stored) and stored.startswith(_ENC_PREFIX)

    def encrypt(self, plaintext: str) -> str:
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return _ENC_PREFIX + token

    def decrypt(self, stored: str) -> str:
        if not self.is_encrypted(stored):
            # Legacy plaintext written before encryption was enabled.
            return stored
        token = stored[len(_ENC_PREFIX) :]
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            logger.error("Credential decryption failed: wrong key or corrupt ciphertext")
            raise CredentialDecryptionError("credential could not be decrypted") from exc


_cipher: CredentialCipher | None = None


def get_credential_cipher() -> CredentialCipher:
    """Return the process-wide credential cipher.

    Uses ``settings.db_credential_secret`` when set; otherwise derives the key
    from the app database password (always present) so encryption is on by
    default. A dedicated secret should be configured in production.
    """
    global _cipher
    if _cipher is None:
        from app.core.config import settings

        secret = settings.db_credential_secret or settings.db_password
        if not settings.db_credential_secret:
            logger.warning(
                "db_credential_secret is not set; deriving credential key from db_password. "
                "Set a dedicated DB_CREDENTIAL_SECRET in production."
            )
        _cipher = CredentialCipher(secret)
    return _cipher
