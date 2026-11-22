"""The credential store: named secrets, encrypted at rest, used by execution nodes by reference.

Values go in (``put``) and out to the executors only (``resolve``); nothing else reads them, and no
endpoint, log line, event or result carries one. Saving needs an API token and a secret key of the
operator's own (``security_problems`` makes the application refuse a token without a key): without a
token the application is open to everyone who can reach it, and a stored secret would be readable by
all of them through any node.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from openartifact.config import DEFAULT_SECRET_KEY, Settings
from openartifact.credentials.crypto import SecretUnreadableError, decrypt, encrypt
from openartifact.credentials.refs import REFERENCE, is_name, parse_name_lines
from openartifact.database import SessionOpener
from openartifact.exceptions import ArtifactError
from openartifact.graph.node_types import node_type
from openartifact.models import Graph, GraphNode, NodeKind, Secret
from openartifact.schemas_common import UtcDateTime

MAX_VALUE_BYTES = 8 * 1024
NOT_CONFIGURED = "Set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY first"


class SecretResolveError(Exception):
    """A secret a node needs cannot be provided; the message is safe to show (it holds a name only)."""


class SecretRead(BaseModel):
    """A secret as the API shows it: the name and the dates, never the value."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class SecretWrite(BaseModel):
    value: str = Field(min_length=1)


class SecretUse(BaseModel):
    """A node that refers to a secret, and where it sits (``pipelines``: those that call its action)."""

    node_id: str
    node_name: str
    kind: str
    graph_id: str
    graph_name: str
    graph_kind: str
    pipelines: list[dict[str, str]]


def _valid_name(name: str) -> str:
    if not is_name(name):
        raise ArtifactError(
            422, "A secret name has capitals, digits and underscores and starts with a letter"
        )
    return name


class SecretStore:
    """Reads and writes the ``secrets`` table; every method opens its own session."""

    def __init__(self, session: SessionOpener, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    @property
    def writable(self) -> bool:
        """Whether secrets may be saved: a token is set and the secret key is not the default."""
        key = self._settings.secret_key
        return bool(self._settings.api_token) and bool(key) and key != DEFAULT_SECRET_KEY

    async def names(self) -> list[SecretRead]:
        async with self._session() as session:
            rows = (await session.execute(select(Secret).order_by(Secret.name))).scalars().all()
            return [SecretRead.model_validate(r) for r in rows]

    async def put(self, name: str, value: str) -> tuple[SecretRead, bool]:
        """Create or replace; the flag says whether it was created. 409 without token and key."""
        _valid_name(name)
        if not self.writable:
            raise ArtifactError(409, NOT_CONFIGURED)
        if "\x00" in value or not value:
            raise ArtifactError(422, "The value must not be empty or contain NUL characters")
        if len(value.encode("utf-8")) > MAX_VALUE_BYTES:
            raise ArtifactError(422, f"The value is longer than {MAX_VALUE_BYTES // 1024} KiB")
        blob = encrypt(self._settings.secret_key, name, value)
        async with self._session() as session:
            row = (
                await session.execute(select(Secret).where(Secret.name == name))
            ).scalar_one_or_none()
            created = row is None
            if row is None:
                row = Secret(id=str(uuid.uuid4()), name=name, value=blob)
                session.add(row)
            else:
                row.value = blob
                row.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(row)
            return SecretRead.model_validate(row), created

    async def delete(self, name: str) -> None:
        _valid_name(name)
        async with self._session() as session:
            row = (
                await session.execute(select(Secret).where(Secret.name == name))
            ).scalar_one_or_none()
            if row is None:
                raise ArtifactError(404, "Secret not found")
            await session.delete(row)
            await session.commit()

    async def resolve(self, names: Sequence[str]) -> dict[str, str]:
        """The values of ``names``; raises :class:`SecretResolveError` for the first one that fails."""
        if not names:
            return {}
        async with self._session() as session:
            rows = {
                r.name: r.value
                for r in (
                    await session.execute(select(Secret).where(Secret.name.in_(list(names))))
                ).scalars()
            }
        values: dict[str, str] = {}
        for name in names:
            if name not in rows:
                raise SecretResolveError(f"Secret {name} does not exist")
            try:
                values[name] = decrypt(self._settings.secret_key, name, rows[name])
            except SecretUnreadableError as error:
                raise SecretResolveError(
                    f"Secret {name} cannot be read: the secret key changed"
                ) from error
        return values

    async def uses(self, name: str) -> list[SecretUse]:
        """The Code and HTTP nodes that refer to ``name``, with the pipelines that call their action."""
        _valid_name(name)
        async with self._session() as session:
            rows = (
                await session.execute(
                    select(GraphNode, Graph)
                    .join(Graph, Graph.id == GraphNode.graph_id)
                    .where(GraphNode.kind.in_([NodeKind.CODE.value, NodeKind.HTTP.value]))
                    .order_by(Graph.name, GraphNode.name)
                )
            ).all()
            found: list[SecretUse] = []
            for node, graph in rows:
                if name not in _referenced(node):
                    continue
                callers = (
                    await session.execute(
                        select(Graph)
                        .join(GraphNode, GraphNode.graph_id == Graph.id)
                        .where(GraphNode.kind == NodeKind.ACTION.value)
                        .where(GraphNode.definition_id == graph.id)
                        .distinct()
                        .order_by(Graph.name)
                    )
                ).scalars()
                found.append(
                    SecretUse(
                        node_id=node.id,
                        node_name=node.name,
                        kind=node.kind,
                        graph_id=graph.id,
                        graph_name=graph.name,
                        graph_kind=graph.kind,
                        pipelines=[{"id": p.id, "name": p.name} for p in callers],
                    )
                )
            return found


def _referenced(node: GraphNode) -> set[str]:
    """The secret names a node refers to (what is stored; malformed references are skipped)."""
    config: dict[str, Any] = node_type(node.kind).effective_config(node.config)
    if node.kind == NodeKind.CODE:
        try:
            return set(parse_name_lines(str(config.get("secrets") or "")))
        except ValueError:
            return set()
    text = "\n".join(str(config.get(k) or "") for k in ("url", "headers", "body"))
    return {m[1] for m in REFERENCE.finditer(text)}
