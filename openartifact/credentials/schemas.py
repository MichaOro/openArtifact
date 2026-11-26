"""The models of the credentials API (ADR-051): metadata and state, never a value and never a hash.

The one exception is the token of an internal credential, in the answer to the request that made it (create, rotate):
it is shown that once and cannot be read again.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from openartifact.schemas_common import UtcDateTime


class TokenRead(BaseModel):
    """One token of an internal credential, by its public id (not the token)."""

    public_id: str
    created_at: UtcDateTime
    valid_until: UtcDateTime | None
    #: ``current`` (no end), ``grace`` (a rotation gave it an end that has not come), ``ended``.
    state: str


class InternalRead(BaseModel):
    expires_at: UtcDateTime | None
    revoked_at: UtcDateTime | None
    last_used_at: UtcDateTime | None
    tokens: list[TokenRead]


class ExternalRead(BaseModel):
    #: The fields of the type that are not secret.
    settings: dict[str, Any]
    last_test_at: UtcDateTime | None
    #: ``None`` while no test ran: never "ok" without one.
    last_test_ok: bool | None
    last_test_message: str | None


class CredentialRead(BaseModel):
    id: str
    name: str
    category: str
    type: str
    type_label: str
    description: str
    enabled: bool
    #: ``active``, ``disabled``, ``expired`` or ``revoked`` (the last two only for internal credentials).
    status: str
    created_at: UtcDateTime
    updated_at: UtcDateTime
    internal: InternalRead | None = None
    external: ExternalRead | None = None


class CredentialCreated(BaseModel):
    """The answer to creating or rotating an internal credential: it holds the token, once."""

    credential: CredentialRead
    token: str


class CredentialEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    action: str
    detail: str
    at: UtcDateTime


class CredentialUse(BaseModel):
    """Where a credential is referenced: a node of an action, or an LLM provider."""

    kind: str
    name: str
    where: str
    link: str | None
    pipelines: list[dict[str, str]] = Field(default_factory=list)


class InternalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    #: Seconds from now (``None``: it does not end).
    expires_in_seconds: int | None = Field(default=None, ge=60, le=10 * 365 * 24 * 3600)


class ExternalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    #: The fields of the type by name: the secret value and its settings.
    fields: dict[str, str] = Field(default_factory=dict)


class ExternalUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str | None = Field(default=None, max_length=500)
    #: Fields to change; a secret field left out or empty keeps the stored value.
    fields: dict[str, str] = Field(default_factory=dict)


class Rotate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: How long the old token still works (seconds); ``None``: the configured grace period.
    grace_seconds: int | None = Field(default=None, ge=0, le=30 * 24 * 3600)


class Enabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
