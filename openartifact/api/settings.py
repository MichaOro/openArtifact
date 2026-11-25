"""Settings users change at run time: ``/api/settings/run-limits`` for the browser and the same under
``/api/v1`` (ADR-039). A change publishes ``settings.changed`` and takes effect for executions that start
afterwards."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.engine import history as history_module
from openartifact.engine import retention
from openartifact.engine.history import Changes
from openartifact.engine.limits import RunLimitsRead, RunLimitsWrite, load_limits, save_limits
from openartifact.models.settings import AppSetting
from sqlalchemy import select

DESCRIPTION = (
    "``max_steps`` (10 to 100000, default 1000): steps one execution may take, the actions and the nodes of "
    "their definitions together; a pipeline that loops fails at it. ``time_limit_minutes`` (0 to 10080, "
    "default 0 = none): how long one execution may run; the node that runs then is stopped and the "
    "execution fails. An execution keeps the limits it started with. ``max_concurrent_runs`` is the "
    "operator's ``OPENARTIFACT_MAX_CONCURRENT_RUNS`` and read-only."
)

PERSONAL = (
    "Personal preferences of the signed-in user (single-user system). Each setting is a switch or a choice; "
    "changes take effect immediately and publish ``settings.changed``. Unknown keys are ignored for forward "
    "compatibility. Default values are defined in the form manifest (``ui/forms/personal.yaml``)."
)

RETENTION = (
    "What happens to finished executions, for all artifacts: a list of rules, each ``when`` a tree of groups "
    "(``mode`` ``all`` or ``any``) holding conditions on ``status`` (done, failed, stopped), ``started_by``, "
    "``pipeline`` (name, ignoring case), ``age`` (``older_than`` seconds) and ``position`` (``beyond`` the newest "
    "N of the artifact), ``then`` an ``action`` (``delete``: for good, with the steps). A running execution is "
    "never touched and a rule without conditions does nothing. The rules are checked whenever an execution is "
    "added or finishes."
)


def build_settings_router(
    prefix: str, tags: Sequence[str], dependencies: Sequence[Any] = ()
) -> APIRouter:
    router = APIRouter(
        prefix=f"{prefix}/settings",
        tags=list(tags),
        dependencies=list(dependencies),
        responses=GATED,
    )
    tag = "v1_" if "v1" in prefix else ""

    async def read(request: Request, session: SessionDep) -> RunLimitsRead:
        limits, changed = await load_limits(session)
        return RunLimitsRead(
            max_steps=limits.max_steps,
            time_limit_minutes=limits.time_limit_minutes,
            max_concurrent_runs=request.app.state.settings.max_concurrent_runs,
            updated_at=changed,
        )

    @router.get(
        "/run-limits",
        response_model=RunLimitsRead,
        name=f"{tag}get_run_limits",
        summary="Get the run limits",
        description=DESCRIPTION,
    )
    async def get_run_limits(request: Request, session: SessionDep) -> RunLimitsRead:
        return await read(request, session)

    @router.put(
        "/run-limits",
        response_model=RunLimitsRead,
        name=f"{tag}put_run_limits",
        summary="Change the run limits",
        description=DESCRIPTION
        + " A field that is left out keeps its value. Publishes ``settings.changed``.",
        responses=errors(422, write=True, body=True),
    )
    async def put_run_limits(
        payload: RunLimitsWrite, request: Request, session: SessionDep
    ) -> RunLimitsRead:
        await save_limits(session, payload)
        await session.commit()
        result = await read(request, session)
        request.app.state.event_bus.publish(
            "settings.changed", {"run_limits": result.model_dump(mode="json")}
        )
        return result

    class RulesRead(retention.Rules):
        """The retention rules as stored."""

    class RulesSaved(retention.Rules):
        """The rules and how many executions saving them deleted."""

        deleted: int

    class RulesPreview(BaseModel):
        matching: int
        per_rule: list[int]

    @router.get(
        "/retention",
        response_model=RulesRead,
        name=f"{tag}get_retention",
        summary="Get the retention rules",
        description=RETENTION,
    )
    async def get_retention(session: SessionDep) -> retention.Rules:
        return await retention.load_rules(session)

    @router.put(
        "/retention",
        response_model=RulesSaved,
        name=f"{tag}put_retention",
        summary="Change the retention rules",
        description=RETENTION
        + " Saving applies them to the executions that exist: the finished ones the rules match are deleted at once.",
        responses=errors(422, write=True, body=True),
    )
    async def put_retention(
        payload: retention.Rules, request: Request, session: SessionDep
    ) -> dict[str, Any]:
        await retention.save_rules(session, payload)
        changes = Changes()
        history = request.app.state.engine.history
        deleted = await history.apply_rules(session, changes)
        await session.commit()
        history.publish(changes)
        request.app.state.event_bus.publish(
            "settings.changed", {"retention": payload.model_dump(mode="json")}
        )
        return {**payload.model_dump(mode="json"), "deleted": deleted}

    @router.post(
        "/retention/preview",
        response_model=RulesPreview,
        name=f"{tag}preview_retention",
        summary="How many executions rules would delete",
        description="Counts the finished executions these rules match now; nothing is stored or deleted.",
        responses=errors(422, write=True, body=True),
    )
    async def preview_retention(payload: retention.Rules, session: SessionDep) -> RulesPreview:
        now = history_module.utcnow()
        found = await retention.matching_ids(session, payload, now)
        return RulesPreview(
            matching=len(found), per_rule=await retention.count_per_rule(session, payload, now)
        )

    # ── Personal Settings ────────────────────────────────────────────────

    class PersonalSettingsRead(BaseModel):
        """Personal settings as read by the client."""

        mark_resolved_references: bool = False
        # future settings will be added here

    class PersonalSettingsWrite(BaseModel):
        """Personal settings write payload (partial updates allowed)."""

        mark_resolved_references: bool | None = None
        # future settings will be added here

    @router.get(
        "/personal",
        response_model=PersonalSettingsRead,
        name=f"{tag}get_personal",
        summary="Get personal settings",
        description=PERSONAL,
    )
    async def get_personal(session: SessionDep) -> PersonalSettingsRead:
        result = await session.execute(select(AppSetting).where(AppSetting.key.like("personal.%")))
        settings = {row.key: row.value for row in result.scalars().all()}
        return PersonalSettingsRead(
            mark_resolved_references=settings.get("personal.mark_resolved_references") == "true",
        )

    @router.put(
        "/personal",
        response_model=PersonalSettingsRead,
        name=f"{tag}put_personal",
        summary="Change personal settings",
        description=PERSONAL
        + " A field that is left out keeps its value. Publishes ``settings.changed``.",
        responses=errors(422, write=True, body=True),
    )
    async def put_personal(payload: PersonalSettingsWrite, request: Request, session: SessionDep) -> PersonalSettingsRead:
        data = payload.model_dump(exclude_unset=True)
        for key, value in data.items():
            setting_key = f"personal.{key}"
            setting_value = "true" if value is True else "false" if value is False else str(value)
            existing = await session.get(AppSetting, setting_key)
            if existing:
                existing.value = setting_value
            else:
                session.add(AppSetting(key=setting_key, value=setting_value))
        await session.commit()
        result = await get_personal(session)
        request.app.state.event_bus.publish(
            "settings.changed", {"personal": result.model_dump(mode="json")}
        )
        return result

    return router
