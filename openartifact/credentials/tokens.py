"""Tokens OpenArtifact makes (ADR-051): ``oa_<public id>_<secret>``.

The public id is the lookup key (one indexed query instead of a comparison with every token); the secret is 256
random bits. Such a token is not a password a person chose, so it needs no slow, salted hash: SHA-256 of the whole
token is enough (nothing can be guessed or looked up in a table of common values), is fast on every request and does not
depend on the secret key (changing it does not end the tokens). Only the hash is stored; the token itself is shown
once, when it is made, and cannot be read again.
"""

from __future__ import annotations

import hashlib
import secrets

PREFIX = "oa_"
_ID_LENGTH = 12


def new_token() -> tuple[str, str, str]:
    """``(token, public_id, hash)`` of a fresh token."""
    public_id = secrets.token_hex(_ID_LENGTH // 2)
    token = f"{PREFIX}{public_id}_{secrets.token_urlsafe(32)}"
    return token, public_id, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def public_id_of(token: str) -> str | None:
    """The public id of something that looks like one of our tokens, else ``None`` (nothing is looked up)."""
    if not token.startswith(PREFIX):
        return None
    public_id, _, rest = token[len(PREFIX) :].partition("_")
    if (
        len(public_id) != _ID_LENGTH
        or not rest
        or any(c not in "0123456789abcdef" for c in public_id)
    ):
        return None
    return public_id


def matches(token: str, stored_hash: str) -> bool:
    """Constant-time comparison of a presented token with a stored hash."""
    return secrets.compare_digest(hash_token(token), stored_hash)
