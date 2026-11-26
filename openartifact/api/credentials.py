"""Managed credentials (``/api/credentials``, ADR-051): internal tokens OpenArtifact makes and external values users give.

Every answer is metadata and state; a value or a hash never leaves. The one token of an internal credential is in the
answer to the request that made it (create, rotate), once. The same rules as the secrets API apply: nothing here works
without the API token (the gate), and storing an external value needs a secret key of the operator's own. The older
``/api/secrets`` stays as it is; its secrets appear here as generic external credentials.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status

from openartifact.api.contract import GATED, errors
from openartifact.credentials.schemas import (
    CredentialCreated,
    CredentialEventRead,
    CredentialRead,
    CredentialUse,
    Enabled,
    ExternalCreate,
    ExternalUpdate,
    InternalCreate,
    Rotate,
)
from openartifact.credentials.service import CredentialService
from openartifact.exceptions import ArtifactError

router = APIRouter(prefix="/api/credentials", tags=["credentials"], responses=GATED)


def get_credentials(request: Request) -> CredentialService:
    service: CredentialService = request.app.state.credentials
    return service


CredentialsDep = Annotated[CredentialService, Depends(get_credentials)]


@router.get("/types", summary="The credential types", response_model=list[dict[str, Any]])
async def credential_types(credentials: CredentialsDep) -> list[dict[str, object]]:
    """Each type with its category, fields, whether a connection test exists and what it can be used for."""
    return credentials.types()


@router.get(
    "", response_model=list[CredentialRead], summary="List credentials", responses=errors(422)
)
async def list_credentials(
    credentials: CredentialsDep, category: str | None = None
) -> list[CredentialRead]:
    """All credentials by name (``category``: ``internal`` or ``external``): metadata and state, never a value."""
    if category not in (None, "internal", "external"):
        raise ArtifactError(422, "category is internal or external")
    return await credentials.list_all(category)


@router.post(
    "/internal",
    response_model=CredentialCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Make an internal credential (a token)",
    responses=errors(409, 422, write=True, body=True),
)
async def create_internal(
    payload: InternalCreate, request: Request, credentials: CredentialsDep
) -> CredentialCreated:
    """Make an access token. It is in the answer once; only its hash is kept and it cannot be read again."""
    if not request.app.state.settings.api_token:
        raise ArtifactError(
            409, "Set OPENARTIFACT_API_TOKEN first: without it nothing asks for a token"
        )
    return await credentials.create_internal(
        payload.type, payload.name, payload.description, payload.expires_in_seconds
    )


@router.post(
    "/external",
    response_model=CredentialRead,
    status_code=status.HTTP_201_CREATED,
    summary="Store an external credential",
    responses=errors(409, 422, write=True, body=True),
)
async def create_external(payload: ExternalCreate, credentials: CredentialsDep) -> CredentialRead:
    """Store a value for another system (encrypted by the credential store). ``fields`` follow the type."""
    return await credentials.create_external(
        payload.type, payload.name, payload.description, payload.fields
    )


@router.get(
    "/{ref}", response_model=CredentialRead, summary="One credential", responses=errors(404, 422)
)
async def get_credential(ref: str, credentials: CredentialsDep) -> CredentialRead:
    return await credentials.get(ref)


@router.patch(
    "/{ref}",
    response_model=CredentialRead,
    summary="Change an external credential",
    responses=errors(404, 409, 422, write=True, body=True),
)
async def update_external(
    ref: str, payload: ExternalUpdate, credentials: CredentialsDep
) -> CredentialRead:
    """The description, the settings and, when given, the value (a secret field left empty keeps the stored one)."""
    return await credentials.update_external(ref, payload.description, payload.fields)


@router.put(
    "/{ref}/enabled",
    response_model=CredentialRead,
    summary="Switch a credential on or off",
    responses=errors(404, 409, 422, write=True, body=True),
)
async def set_enabled(ref: str, payload: Enabled, credentials: CredentialsDep) -> CredentialRead:
    """Off: a token fails at the next request, an external value is refused to nodes and providers."""
    return await credentials.set_enabled(ref, payload.enabled)


@router.post(
    "/{ref}/rotate",
    response_model=CredentialCreated,
    summary="Rotate an internal credential",
    responses=errors(404, 409, 422, write=True, body=True),
)
async def rotate(ref: str, payload: Rotate, credentials: CredentialsDep) -> CredentialCreated:
    """A new token (in the answer, once); the old one works for the grace period."""
    return await credentials.rotate(ref, payload.grace_seconds)


@router.post(
    "/{ref}/revoke",
    response_model=CredentialRead,
    summary="Revoke an internal credential",
    responses=errors(404, 422, write=True),
)
async def revoke(ref: str, credentials: CredentialsDep) -> CredentialRead:
    """End it for good: every token fails from the next request on."""
    return await credentials.revoke(ref)


@router.post(
    "/{ref}/test",
    response_model=CredentialRead,
    summary="Test an external credential",
    responses=errors(404, 409, 422, write=True),
)
async def test_credential(ref: str, credentials: CredentialsDep) -> CredentialRead:
    """A real request to the other system with the stored value; only types with a test have one."""
    return await credentials.test(ref)


@router.get(
    "/{ref}/uses",
    response_model=list[CredentialUse],
    summary="Where a credential is used",
    responses=errors(404, 422),
)
async def credential_uses(ref: str, credentials: CredentialsDep) -> list[CredentialUse]:
    """Nodes (with the pipelines that call their action) and providers that refer to an external credential."""
    return await credentials.uses(ref)


@router.get(
    "/{ref}/events",
    response_model=list[CredentialEventRead],
    summary="The audit trail of a credential",
    responses=errors(404, 422),
)
async def credential_events(ref: str, credentials: CredentialsDep) -> list[CredentialEventRead]:
    return await credentials.events(ref)


@router.delete(
    "/{ref}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a credential",
    responses=errors(404, 422, write=True),
)
async def delete_credential(ref: str, credentials: CredentialsDep) -> Response:
    """Delete it with its value or tokens; what still refers to an external one fails (see ``/uses``)."""
    await credentials.delete(ref)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
