"""The schemas of the rule system (``/api/rules/schemas``, ADR-060): fields, operators and consequences per purpose,
for the rule builder."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from openartifact.api.contract import GATED, errors
from openartifact.rules.catalog import SCHEMAS


class RuleFieldRead(BaseModel):
    key: str
    kind: str
    operators: list[str]
    label: str
    options: list[str]
    minimum: float | None
    maximum: float | None
    prefix: str | None
    units: list[str]


class ConsequenceRead(BaseModel):
    key: str
    label: str
    available: bool
    needs: str | None


class RuleSchemaRead(BaseModel):
    """What a condition of this purpose may test and what its rule may do."""

    purpose: str
    fields: list[RuleFieldRead]
    consequences: list[ConsequenceRead]
    triggers: str
    planned: bool


router = APIRouter(prefix="/api/rules", tags=["rules"], responses=GATED)


@router.get(
    "/schemas", response_model=list[RuleSchemaRead], summary="The schemas of the rule system"
)
async def list_schemas() -> list[dict[str, Any]]:
    """Per purpose (``retention``, ``guard``, the planned ``lane``): the fields a condition may test (key, value
    kind, operators, options, bounds) and the consequences (``available: false`` with ``needs`` for one that is
    not built yet)."""
    return [schema.to_data() for schema in SCHEMAS.values()]


@router.get(
    "/schemas/{purpose}",
    response_model=RuleSchemaRead,
    summary="One schema of the rule system",
    responses=errors(404, 422),
)
async def get_schema(purpose: str) -> dict[str, Any]:
    """The schema of one purpose; 404 for an unknown one."""
    schema = SCHEMAS.get(purpose)
    if schema is None:
        raise HTTPException(status_code=404, detail="Unknown rule schema")
    return schema.to_data()
