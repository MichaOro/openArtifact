"""Settings users change at run time: ``/api/settings/run-limits`` for the browser and the same under
``/api/v1`` (ADR-039). A change publishes ``settings.changed`` and takes effect for executions that start
afterwards."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from openartifact import personal_settings
from openartifact.api.contract import GATED, errors
from openartifact.api.deps import ServiceDep, SessionDep
from openartifact.engine import history as history_module
from openartifact.engine import retention
from openartifact.engine.history import Changes
from openartifact.engine.limits import RunLimitsRead, RunLimitsWrite, load_limits, save_limits
from openartifact.engine.stop_switch import StopState

DESCRIPTION = (
    "``max_steps`` (10 to 100000, default 1000): steps one execution may take, the actions and the nodes of "
    "their definitions together; a pipeline that loops fails at it. ``time_limit_minutes`` (0 to 10080, "
    "default 0 = none): how long one execution may run; the node that runs then is stopped and the "
    "execution fails. An execution keeps the limits it started with. ``max_concurrent_runs`` is the "
    "operator's ``OPENARTIFACT_MAX_CONCURRENT_RUNS`` and read-only."
)

PERSONAL = (
    "Personal preferences of the user (a single-user system): ``mark_resolved_references`` (default off) marks the text "
    "a ``${card.x}`` reference stands for, in the artifact dialog and on the board's cards; ``show_stop_switch`` (default off) "
    "offers the emergency stop (``/settings/stop``), and cannot be switched off while the emergency stop is on. Which settings exist and "
    "their defaults are declared in the form manifest ``ui/forms/personal.yaml``. A change takes effect at once."
)


def _default(name: str) -> Any:
    """The default of a personal setting: the form manifest is the one place that declares it."""
    return personal_settings.defaults()[name]


class PersonalSettingsRead(BaseModel):
    """The personal settings; what was never set has the default of the manifest."""

    mark_resolved_references: bool = _default("mark_resolved_references")
    show_stop_switch: bool = _default("show_stop_switch")


class PersonalSettingsWrite(BaseModel):
    """A change of personal settings; a field that is left out keeps its value, a name nobody declared is refused."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mark_resolved_references: bool | None = None
    show_stop_switch: bool | None = None


class StopWrite(BaseModel):
    """Switch the emergency stop on (``true``) or off (``false``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    active: bool


STOP = (
    "The emergency stop (ADR-076): while ``active`` no execution starts from any source (browser, API, MCP) and every execution "
    "that runs is aborted when the switch goes on (``aborted`` counts them). A refused start is ``409`` with ``code`` "
    "``stopped``. The state is kept across restarts; a new system has it off. Switching on needs the personal setting "
    "``show_stop_switch`` (``available``), else ``409`` ``stop_unavailable``; switching off is always allowed. Cards, pipelines, "
    "actions, guards and the history keep working."
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

    # ── The emergency stop ──────────────────────────────────────────────────

    @router.get(
        "/stop",
        response_model=StopState,
        name=f"{tag}get_stop",
        summary="Get the emergency stop",
        description=STOP,
    )
    async def get_stop(service: ServiceDep) -> StopState:
        return await service.stop_switch_state()

    @router.put(
        "/stop",
        response_model=StopState,
        name=f"{tag}put_stop",
        summary="Switch the emergency stop on or off",
        description=STOP + " Publishes ``settings.changed`` with ``stop``.",
        responses=errors(409, 422, write=True, body=True),
    )
    async def put_stop(payload: StopWrite, service: ServiceDep) -> StopState:
        return await service.set_stop_switch(payload.active)

    # ── Personal settings ────────────────────────────────────────────────

    @router.get(
        "/personal",
        response_model=PersonalSettingsRead,
        name=f"{tag}get_personal",
        summary="Get personal settings",
        description=PERSONAL,
    )
    async def get_personal(session: SessionDep) -> PersonalSettingsRead:
        return PersonalSettingsRead(**await personal_settings.load(session))

    @router.put(
        "/personal",
        response_model=PersonalSettingsRead,
        name=f"{tag}put_personal",
        summary="Change personal settings",
        description=PERSONAL
        + " A field that is left out keeps its value. Publishes ``settings.changed``.",
        responses=errors(409, 422, write=True, body=True),
    )
    async def put_personal(
        payload: PersonalSettingsWrite, request: Request, session: SessionDep, service: ServiceDep
    ) -> PersonalSettingsRead:
        if payload.show_stop_switch is False:
            await service.refuse_hiding_active_stop()
        await personal_settings.save(session, payload.model_dump(exclude_unset=True))
        await session.commit()
        result = PersonalSettingsRead(**await personal_settings.load(session))
        bus = request.app.state.event_bus
        bus.publish("settings.changed", {"personal": result.model_dump(mode="json")})
        if payload.show_stop_switch is not None:
            # whether the emergency stop is offered changed with the setting: the pages that show it hear it
            state = await service.stop_switch_state()
            bus.publish("settings.changed", {"stop": state.model_dump(mode="json")})
        return result

    return router
