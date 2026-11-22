"""Artifact type routes (prefix ``/api/artifact-types``): the kinds of artifact and their parameters.

A type has a name and an ordered list of typed parameters (``text``, ``number``, ``boolean``,
``choice``). An artifact with a type carries values for them, checked when it is saved, and a run reads
them as ``${card.NAME}``. The integration API repeats the same operations under
``/api/v1/artifact-types``.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import TypesDep
from openartifact.artifact_types.schemas import ArtifactTypeRead, ArtifactTypeWrite

router = APIRouter(prefix="/api/artifact-types", tags=["artifact types"], responses=GATED)

WRITE_DESCRIPTION = (
    "``name`` is 1-60 characters, unique ignoring case (409). ``fields`` is the complete, ordered list "
    "(at most 30): ``name`` (``[a-z][a-z0-9_]{0,31}``), ``label``, ``kind`` (``text``, ``number``, "
    "``boolean``, ``choice``), ``required``, ``default``, for a choice ``options`` (2-20 values of at "
    "most 40 characters), for text ``max_length`` (default 200), for a number ``min_value``, "
    "``max_value`` and ``integer_only``. A wrong definition is 422, one sentence per problem starting "
    "with ``Field NAME:``. While artifacts use the type, a change that could make their stored values "
    "invalid (removing a parameter, changing its kind, removing an allowed value, narrowing a limit, a "
    "new required parameter without default) is 409. Publishes ``artifact_types.changed``."
)


@router.get("", response_model=list[ArtifactTypeRead], summary="List artifact types")
async def list_types(types: TypesDep) -> list[ArtifactTypeRead]:
    """The types by name with their parameters and ``artifact_count`` (how many artifacts use each)."""
    return await types.list_all()


@router.post(
    "",
    response_model=ArtifactTypeRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an artifact type",
    description=WRITE_DESCRIPTION,
    responses=errors(409, 422, write=True, body=True),
)
async def create_type(payload: ArtifactTypeWrite, types: TypesDep) -> ArtifactTypeRead:
    return await types.create(payload)


@router.get(
    "/{type_id}",
    response_model=ArtifactTypeRead,
    summary="Get an artifact type",
    responses=errors(404, 422),
)
async def get_type(type_id: str, types: TypesDep) -> ArtifactTypeRead:
    """One type by id (or name)."""
    return await types.get(type_id)


@router.put(
    "/{type_id}",
    response_model=ArtifactTypeRead,
    summary="Replace an artifact type",
    description="Replace the name and the whole parameter list. " + WRITE_DESCRIPTION,
    responses=errors(404, 409, 422, write=True, body=True),
)
async def replace_type(
    type_id: str, payload: ArtifactTypeWrite, types: TypesDep
) -> ArtifactTypeRead:
    return await types.replace(type_id, payload)


@router.delete(
    "/{type_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an artifact type",
    responses=errors(404, 409, 422, write=True),
)
async def delete_type(type_id: str, types: TypesDep) -> Response:
    """Delete a type with its parameters; 409 (with the count) while artifacts use it.
    Publishes ``artifact_types.changed``."""
    await types.delete(type_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
