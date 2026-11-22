"""The credential store API (``/api/secrets``): names and dates, never values.

``PUT`` creates or replaces a secret (only when an API token and a secret key are set, otherwise 409),
``DELETE`` removes it (nodes that still refer to it then fail with "Secret NAME does not exist";
``GET .../uses`` lists them so that a user can be warned first). The integration API repeats the
same operations under ``/api/v1/secrets``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from openartifact.secret_store import SecretRead, SecretStore, SecretUse, SecretWrite

router = APIRouter(prefix="/api/secrets", tags=["secrets"])


def get_secret_store(request: Request) -> SecretStore:
    store: SecretStore = request.app.state.secret_store
    return store


StoreDep = Annotated[SecretStore, Depends(get_secret_store)]


@router.get("", response_model=list[SecretRead])
async def list_secrets(store: StoreDep) -> list[SecretRead]:
    """The names of the stored secrets with their dates."""
    return await store.names()


@router.put("/{name}", response_model=SecretRead)
async def put_secret(
    name: str, payload: SecretWrite, store: StoreDep, response: Response
) -> SecretRead:
    """Create or replace a secret (201 when created); the value is encrypted and never returned."""
    read, created = await store.put(name, payload.value)
    if created:
        response.status_code = status.HTTP_201_CREATED
    return read


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(name: str, store: StoreDep) -> Response:
    await store.delete(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/uses", response_model=list[SecretUse])
async def secret_uses(name: str, store: StoreDep) -> list[SecretUse]:
    """The nodes that refer to the secret, and the pipelines that call them."""
    return await store.uses(name)
