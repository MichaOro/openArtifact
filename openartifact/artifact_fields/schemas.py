"""Schemas of the artifact fields API (``/api/artifact-fields``, ``/api/v1/artifact-fields``; ADR-044)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FieldBase(BaseModel):
    """One artifact field. Rules the schema cannot say are checked by the service (422, with
    ``Field NAME: ...`` sentences): the name is ``[a-z][a-z0-9_]{0,31}``, a choice has 1 to 20 allowed
    values of at most 40 characters, only a choice is ``multiple``, only text has ``max_length`` (1-1000,
    default 200), only a number has ``min_value``, ``max_value`` and ``integer_only``, the default must be a
    valid value (a list for a ``multiple`` choice)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(max_length=64)
    label: str = Field(max_length=200)
    #: ``text``, ``number``, ``boolean`` or ``choice``.
    kind: str = Field(max_length=16)
    #: Pre-fills new artifacts and stands in for a value that is not set.
    default: str | float | int | bool | list[str] | None = None
    options: list[str] = Field(default_factory=list, max_length=100)
    #: A choice that holds several of its values (multi select, ADR-050).
    multiple: bool = False
    max_length: int | None = None
    min_value: float | None = None
    max_value: float | None = None
    integer_only: bool = False


class FieldWrite(FieldBase):
    """A field as it is sent. ``renamed_options`` ({old: new}) says which allowed values of a choice were renamed,
    so the artifacts keep them; it is part of the change, not of the field (ADR-050)."""

    renamed_options: dict[str, str] = Field(default_factory=dict, max_length=100)


class FieldRead(FieldBase):
    """A field as stored, with how many artifacts have a value for it."""

    artifact_count: int = 0


class ArtifactFieldsWrite(BaseModel):
    """Body of the replace: the complete, ordered list of fields (at most 30)."""

    model_config = ConfigDict(extra="forbid")

    fields: list[FieldWrite] = Field(default_factory=list, max_length=100)


class ArtifactFieldsRead(BaseModel):
    """The fields in order."""

    fields: list[FieldRead]
