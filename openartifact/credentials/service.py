"""Managed credentials (ADR-051): the one service for tokens OpenArtifact makes and values users give.

* **Internal** credentials (``api_access_token``, ``mcp_access_token``): a token is made, shown once and kept as a
  SHA-256 hash with a public id (``credentials/tokens.py``); they can expire, be switched off, revoked for good and
  rotated (the old token lives on for a grace period). They never touch the secret store.
* **External** credentials: the value is kept by the credential store (encrypted, unchanged), the service adds the type,
  the non-secret settings, the state, the last connection test and where it is used. The credential's name is the
  secret's name, so ``${secret:NAME}`` and every ``secret`` setting keep working; a secret that was made without the
  service is adopted the first time it is listed.

Where the value of an external credential lives is a :class:`SecretBackend`; the credential store is the only one so far.
Every change leaves an event (without any value) in the audit trail.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.config import Settings
from openartifact.credentials import tokens
from openartifact.credentials.refs import is_name
from openartifact.credentials.schemas import (
    CredentialCreated,
    CredentialEventRead,
    CredentialRead,
    CredentialUse,
    ExternalRead,
    InternalRead,
    TokenRead,
)
from openartifact.credentials.store import SecretResolveError, SecretStore
from openartifact.credentials.testing import test_connection
from openartifact.credentials.types import (
    EXTERNAL,
    INTERNAL,
    CredentialType,
    credential_type,
    of_category,
)
from openartifact.database import SessionOpener
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models import (
    Credential,
    CredentialEvent,
    ExternalCredential,
    Graph,
    InternalCredential,
    InternalToken,
    LlmProvider,
    Secret,
)

logger = logging.getLogger(__name__)

BACKEND = "secret_store"
LAST_USED_EVERY = timedelta(minutes=1)  # a token is not written to the database on every request
SCOPE_API, SCOPE_MCP = "api", "mcp"
#: Which scopes a type of token opens: an MCP token opens the MCP server only.
SCOPES = {"api_access_token": {SCOPE_API, SCOPE_MCP}, "mcp_access_token": {SCOPE_MCP}}
CHANGED = "credentials.changed"


class SecretBackend(Protocol):
    """Where the value of an external credential lives (the credential store, later perhaps a vault)."""

    async def put(self, name: str, value: str) -> object: ...
    async def delete(self, name: str) -> None: ...
    async def resolve(self, names: list[str]) -> dict[str, str]: ...


def _now() -> datetime:
    """Now as the database keeps it: UTC without a zone."""
    return datetime.now(UTC).replace(tzinfo=None)


class CredentialService:
    def __init__(
        self, session: SessionOpener, backend: SecretStore, settings: Settings, bus: EventBus
    ) -> None:
        self._session = session
        self._store = backend
        self._backends: dict[str, SecretBackend] = {BACKEND: backend}
        self._settings = settings
        self._bus = bus

    # ── reading ──────────────────────────────────────────────────────

    @staticmethod
    def types() -> list[dict[str, object]]:
        return [t.describe() for t in (*of_category(INTERNAL), *of_category(EXTERNAL))]

    async def _adopt(self, session: AsyncSession) -> None:
        """Secrets made without the service (the older API) become external credentials of the generic type."""
        known = set(
            await session.scalars(
                select(Credential.backend_ref).where(Credential.category == EXTERNAL)
            )
        )
        for secret in await session.scalars(select(Secret)):
            if secret.name in known:
                continue
            session.add(
                Credential(
                    id=secret.id,
                    name=secret.name,
                    category=EXTERNAL,
                    type="generic_api_key",
                    backend=BACKEND,
                    backend_ref=secret.name,
                )
            )
            session.add(ExternalCredential(credential_id=secret.id))
        await session.commit()

    async def _read(self, session: AsyncSession, credential: Credential) -> CredentialRead:
        found = credential_type(credential.type)
        base: dict[str, Any] = {
            "id": credential.id,
            "name": credential.name,
            "category": credential.category,
            "type": credential.type,
            "type_label": found.label if found else credential.type,
            "description": credential.description,
            "enabled": credential.enabled,
            "created_at": credential.created_at,
            "updated_at": credential.updated_at,
        }
        now = _now()
        if credential.category == INTERNAL:
            life = await session.get(InternalCredential, credential.id)
            rows = (
                await session.scalars(
                    select(InternalToken)
                    .where(InternalToken.credential_id == credential.id)
                    .order_by(InternalToken.created_at.desc())
                )
            ).all()
            status = (
                "revoked"
                if life and life.revoked_at
                else "expired"
                if life and life.expires_at and life.expires_at <= now
                else "active"
                if credential.enabled
                else "disabled"
            )
            return CredentialRead(
                **base,
                status=status,
                internal=InternalRead(
                    expires_at=life.expires_at if life else None,
                    revoked_at=life.revoked_at if life else None,
                    last_used_at=life.last_used_at if life else None,
                    tokens=[
                        TokenRead(
                            public_id=t.public_id,
                            created_at=t.created_at,
                            valid_until=t.valid_until,
                            state="current"
                            if t.valid_until is None
                            else "grace"
                            if t.valid_until > now
                            else "ended",
                        )
                        for t in rows
                    ],
                ),
            )
        meta = await session.get(ExternalCredential, credential.id)
        return CredentialRead(
            **base,
            status="active" if credential.enabled else "disabled",
            external=ExternalRead(
                settings=json.loads(meta.settings) if meta else {},
                last_test_at=meta.last_test_at if meta else None,
                last_test_ok=meta.last_test_ok if meta else None,
                last_test_message=meta.last_test_message if meta else None,
            ),
        )

    async def _find(self, session: AsyncSession, ref: str) -> Credential:
        found = await session.get(Credential, ref)
        if found is None:
            found = await session.scalar(select(Credential).where(Credential.name == ref.strip()))
        if found is None:
            raise ArtifactError(404, "Credential not found")
        return found

    async def list_all(self, category: str | None = None) -> list[CredentialRead]:
        async with self._session() as session:
            await self._adopt(session)
            query = select(Credential).order_by(Credential.name)
            if category:
                query = query.where(Credential.category == category)
            return [await self._read(session, c) for c in await session.scalars(query)]

    async def get(self, ref: str) -> CredentialRead:
        async with self._session() as session:
            await self._adopt(session)
            return await self._read(session, await self._find(session, ref))

    async def events(self, ref: str, limit: int = 50) -> list[CredentialEventRead]:
        async with self._session() as session:
            credential = await self._find(session, ref)
            rows = await session.scalars(
                select(CredentialEvent)
                .where(CredentialEvent.credential_id == credential.id)
                .order_by(CredentialEvent.at.desc())
                .limit(limit)
            )
            return [CredentialEventRead.model_validate(r) for r in rows]

    async def uses(self, ref: str) -> list[CredentialUse]:
        """Where an external credential is referenced: nodes (with the pipelines that call their action) and providers."""
        async with self._session() as session:
            credential = await self._find(session, ref)
            if credential.category != EXTERNAL or not credential.backend_ref:
                return []
            name = credential.backend_ref
        found: list[CredentialUse] = []
        node_uses = await self._store.uses(name)
        async with self._session() as session:
            slugs = {
                g.id: g.slug
                for g in await session.scalars(
                    select(Graph).where(Graph.id.in_({u.graph_id for u in node_uses} or {""}))
                )
            }
            for use in node_uses:
                found.append(
                    CredentialUse(
                        kind=use.kind,
                        name=use.node_name,
                        where=use.graph_name,
                        link=f"/{'actions' if use.graph_kind == 'action' else 'pipelines'}/{slugs.get(use.graph_id, '')}?select={use.node_id}",
                        pipelines=use.pipelines,
                    )
                )
            for provider in await session.scalars(
                select(LlmProvider)
                .where(LlmProvider.secret_name == name)
                .order_by(LlmProvider.name)
            ):
                found.append(
                    CredentialUse(
                        kind="provider",
                        name=provider.name,
                        where="LLM provider",
                        link="/settings/providers",
                    )
                )
        return found

    # ── events ───────────────────────────────────────────────────────

    def _event(
        self, session: AsyncSession, credential: Credential, action: str, detail: str = ""
    ) -> None:
        session.add(
            CredentialEvent(
                id=str(uuid.uuid4()),
                credential_id=credential.id,
                name=credential.name,
                action=action,
                detail=detail[:300],
            )
        )

    def _changed(self, credential: Credential, action: str) -> None:
        self._bus.publish(CHANGED, {"id": credential.id, "name": credential.name, "action": action})

    async def _free_name(self, session: AsyncSession, name: str) -> None:
        if await session.scalar(select(Credential.id).where(Credential.name == name)):
            raise ArtifactError(409, f'A credential named "{name}" exists already')

    # ── internal ─────────────────────────────────────────────────────

    @staticmethod
    def _internal_type(type_id: str) -> CredentialType:
        found = credential_type(type_id)
        if found is None or found.category != INTERNAL:
            raise ArtifactError(422, f"Unknown internal credential type: {type_id[:40]}")
        return found

    async def create_internal(
        self, type_id: str, name: str, description: str = "", expires_in_seconds: int | None = None
    ) -> CredentialCreated:
        """Make an internal credential and its first token; the token is in the answer, once."""
        self._internal_type(type_id)
        name = name.strip()
        if not name or "\x00" in name:
            raise ArtifactError(422, "A name is needed")
        token, public_id, digest = tokens.new_token()
        async with self._session() as session:
            await self._free_name(session, name)
            credential = Credential(
                id=str(uuid.uuid4()),
                name=name,
                category=INTERNAL,
                type=type_id,
                description=description.strip(),
            )
            session.add(credential)
            await session.flush()
            session.add(
                InternalCredential(
                    credential_id=credential.id,
                    expires_at=_now() + timedelta(seconds=expires_in_seconds)
                    if expires_in_seconds
                    else None,
                )
            )
            session.add(
                InternalToken(
                    id=str(uuid.uuid4()),
                    credential_id=credential.id,
                    public_id=public_id,
                    token_hash=digest,
                )
            )
            self._event(session, credential, "created", type_id)
            await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "created")
        return CredentialCreated(credential=read, token=token)

    async def _internal(
        self, session: AsyncSession, ref: str
    ) -> tuple[Credential, InternalCredential]:
        credential = await self._find(session, ref)
        life = (
            await session.get(InternalCredential, credential.id)
            if credential.category == INTERNAL
            else None
        )
        if life is None:
            raise ArtifactError(422, "This is not an internal credential")
        return credential, life

    async def rotate(self, ref: str, grace_seconds: int | None = None) -> CredentialCreated:
        """A new token; the old ones keep working for the grace period (0: they end at once)."""
        grace = (
            self._settings.credentials_rotation_grace_seconds
            if grace_seconds is None
            else grace_seconds
        )
        token, public_id, digest = tokens.new_token()
        async with self._session() as session:
            credential, life = await self._internal(session, ref)
            if life.revoked_at:
                raise ArtifactError(409, "A revoked credential cannot be rotated: make a new one")
            now = _now()
            end = now + timedelta(seconds=grace)
            for old in await session.scalars(
                select(InternalToken).where(InternalToken.credential_id == credential.id)
            ):
                if old.valid_until is None or old.valid_until > end:
                    old.valid_until = end
            session.add(
                InternalToken(
                    id=str(uuid.uuid4()),
                    credential_id=credential.id,
                    public_id=public_id,
                    token_hash=digest,
                )
            )
            credential.updated_at = now
            self._event(session, credential, "rotated", f"the old token works for {grace} s")
            await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "rotated")
        return CredentialCreated(credential=read, token=token)

    async def revoke(self, ref: str) -> CredentialRead:
        """End it for good: every token fails from the next request on. The history stays."""
        async with self._session() as session:
            credential, life = await self._internal(session, ref)
            if life.revoked_at is None:
                now = _now()
                life.revoked_at = now
                credential.updated_at = now
                self._event(session, credential, "revoked")
                await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "revoked")
        return read

    async def verify(self, token: str, scope: str) -> str | None:
        """The credential's name if this token opens ``scope`` (``api`` or ``mcp``) right now, else ``None``: it
        exists, its credential is on, not revoked, not expired and the token itself not past its grace period.
        Nothing here says why it fails. The name is who the caller is (comments are written under it)."""
        public_id = tokens.public_id_of(token)
        if public_id is None:
            return None
        async with self._session() as session:
            row = (
                await session.execute(
                    select(InternalToken, Credential, InternalCredential)
                    .join(Credential, Credential.id == InternalToken.credential_id)
                    .join(InternalCredential, InternalCredential.credential_id == Credential.id)
                    .where(InternalToken.public_id == public_id)
                )
            ).first()
            if row is None:
                tokens.matches(token, "0" * 64)  # about the same work for an unknown id
                return None
            stored, credential, life = row
            if not tokens.matches(token, stored.token_hash):
                return None
            now = _now()
            if (
                not credential.enabled
                or life.revoked_at is not None
                or (life.expires_at is not None and life.expires_at <= now)
                or (stored.valid_until is not None and stored.valid_until <= now)
                or scope not in SCOPES.get(credential.type, set())
            ):
                return None
            if life.last_used_at is None or now - life.last_used_at > LAST_USED_EVERY:
                life.last_used_at = now
                await session.commit()
            return credential.name

    # ── external ─────────────────────────────────────────────────────

    @staticmethod
    def _external_type(type_id: str) -> CredentialType:
        found = credential_type(type_id)
        if found is None or found.category != EXTERNAL:
            raise ArtifactError(422, f"Unknown credential type: {type_id[:40]}")
        return found

    @staticmethod
    def _check_fields(
        found: CredentialType, fields: dict[str, str], *, creating: bool
    ) -> dict[str, str]:
        """The fields of the type, trimmed; unknown names and missing required ones are refused (422, one line each)."""
        names = {f.name for f in found.fields}
        problems = [
            f"Field {name[:40]}: not a field of {found.label}"
            for name in fields
            if name not in names
        ]
        clean: dict[str, str] = {}
        for field in found.fields:
            raw = str(fields.get(field.name, "")).strip()
            if not raw:
                if field.required and creating:
                    problems.append(f"Field {field.name}: a value is needed")
                continue
            if "\x00" in raw:
                problems.append(f"Field {field.name}: must not contain NUL characters")
            clean[field.name] = raw
        value = clean.get("value", "")
        if (
            found.id == "postgres_connection"
            and value
            and not value.lower().startswith(("postgres://", "postgresql://"))
        ):
            problems.append("Field value: a connection URL starts with postgresql://")
        if clean.get("base_url") and not clean["base_url"].lower().startswith(
            ("http://", "https://")
        ):
            problems.append("Field base_url: an address starts with http:// or https://")
        if problems:
            raise ArtifactError(422, "\n".join(problems))
        return clean

    async def create_external(
        self, type_id: str, name: str, description: str, fields: dict[str, str]
    ) -> CredentialRead:
        found = self._external_type(type_id)
        name = name.strip()
        if not is_name(name):
            raise ArtifactError(
                422,
                "A name has capitals, digits and underscores and starts with a letter (it is what ${secret:NAME} says)",
            )
        clean = self._check_fields(found, fields, creating=True)
        async with self._session() as session:
            await self._adopt(session)
            await self._free_name(session, name)
        value = clean.pop("value")
        await self._store.put(name, value)  # 409 without token and key, 422 for a bad value
        async with self._session() as session:
            secret_id = await session.scalar(select(Secret.id).where(Secret.name == name))
            credential = Credential(
                id=secret_id or str(uuid.uuid4()),
                name=name,
                category=EXTERNAL,
                type=type_id,
                description=description.strip(),
                backend=BACKEND,
                backend_ref=name,
            )
            session.add(credential)
            await session.flush()
            session.add(ExternalCredential(credential_id=credential.id, settings=json.dumps(clean)))
            self._event(session, credential, "created", type_id)
            await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "created")
        return read

    async def _external(
        self, session: AsyncSession, ref: str
    ) -> tuple[Credential, ExternalCredential]:
        await self._adopt(session)
        credential = await self._find(session, ref)
        meta = (
            await session.get(ExternalCredential, credential.id)
            if credential.category == EXTERNAL
            else None
        )
        if meta is None or not credential.backend_ref:
            raise ArtifactError(422, "This is not an external credential")
        return credential, meta

    async def update_external(
        self, ref: str, description: str | None, fields: dict[str, str]
    ) -> CredentialRead:
        """Change the description, the settings and, when one is given, the value; a changed value or address makes
        the last test stale (it is cleared)."""
        async with self._session() as session:
            credential, meta = await self._external(session, ref)
            found = self._external_type(credential.type)
            clean = self._check_fields(found, fields, creating=False)
            name = credential.backend_ref or credential.name
            settings = json.loads(meta.settings)
            changed = False
            value = clean.pop("value", None)
            if value is not None:
                await self._backends[credential.backend or BACKEND].put(name, value)
                changed = True
            for field in found.fields:
                if (
                    not field.secret
                    and field.name in fields
                    and clean.get(field.name, "") != settings.get(field.name, "")
                ):
                    if clean.get(field.name):
                        settings[field.name] = clean[field.name]
                    else:
                        settings.pop(field.name, None)
                    changed = True
            if description is not None:
                credential.description = description.strip()
            meta.settings = json.dumps(settings)
            if changed:
                meta.last_test_at = meta.last_test_ok = meta.last_test_message = None
            credential.updated_at = _now()
            self._event(
                session, credential, "updated", "value changed" if value is not None else ""
            )
            await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "updated")
        return read

    async def set_enabled(self, ref: str, enabled: bool) -> CredentialRead:
        """Switch a credential on or off. Off: an internal token fails at the next request, an external value is
        refused to every node and provider ("Secret NAME is disabled"). A revoked credential stays revoked."""
        async with self._session() as session:
            await self._adopt(session)
            credential = await self._find(session, ref)
            life = (
                await session.get(InternalCredential, credential.id)
                if credential.category == INTERNAL
                else None
            )
            if life and life.revoked_at:
                raise ArtifactError(409, "A revoked credential cannot be switched on again")
            if credential.enabled != enabled:
                credential.enabled = enabled
                credential.updated_at = _now()
                self._event(session, credential, "enabled" if enabled else "disabled")
                await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "enabled" if enabled else "disabled")
        return read

    async def delete(self, ref: str) -> None:
        """Delete a credential with its value or tokens. What still refers to an external one then fails (``uses``
        says what that is; the page asks before). The audit trail keeps what happened."""
        async with self._session() as session:
            await self._adopt(session)
            credential = await self._find(session, ref)
            backend_ref, backend = credential.backend_ref, credential.backend
            self._event(session, credential, "deleted")
            await session.execute(
                delete(InternalToken).where(InternalToken.credential_id == credential.id)
            )
            await session.execute(
                delete(InternalCredential).where(InternalCredential.credential_id == credential.id)
            )
            await session.execute(
                delete(ExternalCredential).where(ExternalCredential.credential_id == credential.id)
            )
            await session.delete(credential)
            await session.commit()
        if credential.category == EXTERNAL and backend_ref:
            try:
                await self._backends[backend or BACKEND].delete(backend_ref)
            except ArtifactError as error:
                if error.status != 404:
                    raise
        self._changed(credential, "deleted")

    async def test(self, ref: str) -> CredentialRead:
        """Test the connection of an external credential with its type's test. Types without a test are refused: a
        credential is never shown as tested when no test ran."""
        async with self._session() as session:
            credential, meta = await self._external(session, ref)
            found = self._external_type(credential.type)
            if not found.testable:
                raise ArtifactError(422, f"There is no connection test for {found.label}")
            name, settings = credential.backend_ref or credential.name, json.loads(meta.settings)
            enabled = credential.enabled
        if not enabled:
            raise ArtifactError(409, "Switch the credential on to test it")
        try:
            value = (await self._backends[BACKEND].resolve([name]))[name]
        except SecretResolveError as error:
            raise ArtifactError(409, str(error)) from error
        ok, message = await test_connection(
            credential.type,
            value,
            settings,
            allow_private=self._settings.http_allow_private_networks,
        )
        async with self._session() as session:
            credential, meta = await self._external(session, ref)
            meta.last_test_at, meta.last_test_ok, meta.last_test_message = _now(), ok, message[:300]
            self._event(session, credential, "tested", "passed" if ok else "failed")
            await session.commit()
            read = await self._read(session, credential)
        self._changed(credential, "tested")
        return read
