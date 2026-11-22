"""Encryption of stored secrets: AES-256-GCM with a key derived from ``OPENARTIFACT_SECRET_KEY``.

The key is HKDF-SHA256 of the configured secret key with a fixed ``info`` string, so the key that signs
the session cookie and the key that encrypts secrets are different keys. Every value gets a fresh random
96-bit nonce; the secret's name is the associated data, so a ciphertext copied to another row (another
name) does not decrypt. The stored form is ``version byte | nonce | ciphertext + tag``.

Limits: whoever has the secret key and the database can read every secret; a changed secret key makes
every stored secret unreadable (there is no re-encryption and no key rotation); the process holds the
derived key and the decrypted values in memory while it uses them. The values are not protected against
a Code node, which runs with the rights of the application and can read what the application can.
"""

from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

VERSION = b"\x01"
NONCE_BYTES = 12
HKDF_INFO = b"openartifact/secret-store/v1"


class SecretUnreadableError(Exception):
    """A stored value cannot be decrypted: the secret key changed or the data was altered."""


def derive_key(secret_key: str) -> bytes:
    """The 256-bit encryption key for ``secret_key``."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=HKDF_INFO).derive(
        secret_key.encode("utf-8")
    )


def encrypt(secret_key: str, name: str, value: str) -> bytes:
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(derive_key(secret_key)).encrypt(
        nonce, value.encode("utf-8"), name.encode("utf-8")
    )
    return VERSION + nonce + sealed


def decrypt(secret_key: str, name: str, blob: bytes) -> str:
    """The value, or :class:`SecretUnreadableError` (wrong key, other name, altered or short data)."""
    if len(blob) < 1 + NONCE_BYTES + 16 or blob[:1] != VERSION:
        raise SecretUnreadableError
    nonce, sealed = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
    try:
        return (
            AESGCM(derive_key(secret_key))
            .decrypt(nonce, sealed, name.encode("utf-8"))
            .decode("utf-8")
        )
    except (InvalidTag, UnicodeDecodeError) as error:
        raise SecretUnreadableError from error
