"""Artifact field routes (prefix ``/api/artifact-fields``): the one list of fields every artifact has (ADR-044).

An artifact carries values for them (``fields`` of an artifact), checked when it is saved, and a run reads
them as ``${card.NAME}``. The integration API repeats the same operations under ``/api/v1/artifact-fields``.
"""

from __future__ import annotations

from fastapi import APIRouter

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import FieldsDep
from openartifact.artifact_fields.schemas import ArtifactFieldsRead, ArtifactFieldsWrite

router = APIRouter(prefix="/api/artifact-fields", tags=["artifact fields"], responses=GATED)

WRITE_DESCRIPTION = (
    "``fields`` is the complete, ordered list (at most 30): ``name`` (``[a-z][a-z0-9_]{0,31}``, what "
    "pipelines read as ``${card.NAME}``), ``label``, ``kind`` (``text``, ``number``, ``boolean``, "
    "``choice``), ``default`` (pre-fills new artifacts, stands in for a value that is not set), for a "
    "choice ``options`` (2-20 values of at most 40 characters), for text ``max_length`` (default 200), "
    "for a number ``min_value``, ``max_value`` and ``integer_only``. A wrong definition is 422, one "
    "sentence per problem starting with ``Field NAME:``. A field left out is removed with its values; a "
    "changed field whose stored values no longer fit is 409, naming the field and how many artifacts. "
    "Publishes ``artifact_fields.changed``."
)


@router.get("", response_model=ArtifactFieldsRead, summary="List the artifact fields")
async def list_fields(fields: FieldsDep) -> ArtifactFieldsRead:
    """The fields in order, each with ``artifact_count`` (how many artifacts have a value for it)."""
    return await fields.list_fields()


@router.put(
    "",
    response_model=ArtifactFieldsRead,
    summary="Replace the artifact fields",
    description=WRITE_DESCRIPTION,
    responses=errors(409, 422, write=True, body=True),
)
async def replace_fields(payload: ArtifactFieldsWrite, fields: FieldsDep) -> ArtifactFieldsRead:
    return await fields.replace(payload)
