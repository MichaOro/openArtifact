"""Schemas of the artifact types API (``/api/artifact-types``, ``/api/v1/artifact-types``)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from openartifact.schemas_common import UtcDateTime

TYPE_NAME_MAX = 60
MAX_TYPES = 100

TypeName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=TYPE_NAME_MAX)
]


class FieldWrite(BaseModel):
    """One parameter of a type. Rules the schema cannot say are checked by the service (422, with
    ``Field NAME: ...`` sentences): the name is ``[a-z][a-z0-9_]{0,31}``, a choice has 2 to 20 allowed
    values of at most 40 characters, only text has ``max_length`` (1-1000, default 200), only a number
    has ``min_value``, ``max_value`` and ``integer_only``, the default must be a valid value."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)
    label: str = Field(max_length=200)
    #: ``text``, ``number``, ``boolean`` or ``choice``.
    kind: str = Field(max_length=16)
    required: bool = False
    default: str | float | int | bool | None = None
    options: list[str] = Field(default_factory=list, max_length=100)
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    integer_only: bool = False


class FieldRead(FieldWrite):
    """A parameter as stored."""


class ArtifactTypeWrite(BaseModel):
    """Body of create and replace: the name and the complete, ordered list of parameters (at most 30)."""

    model_config = ConfigDict(extra="forbid")

    name: TypeName
    fields: list[FieldWrite] = Field(default_factory=list, max_length=100)


class ArtifactTypeRead(BaseModel):
    """An artifact type with its parameters in order; ``artifact_count`` is how many artifacts use it."""

    id: str
    name: str
    fields: list[FieldRead]
    artifact_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime
