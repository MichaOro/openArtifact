"""Settings users change at run time: ``/api/settings/run-limits`` for the browser and the same under
``/api/v1`` (ADR-039). A change publishes ``settings.changed`` and takes effect for executions that start
afterwards."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, model_validator

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
    "their defaults are declared in the form manifest ``ui/forms/personal.yaml``. A change takes effect at once. The ``storage_*`` "
    "settings are the *Data storage* limits (ADR-084): all default to ``null`` (the operator's default or the limit of today, or off), "
    "and ``null`` clears one."
)


#: The *Data storage* settings with their bounds and what they are called in an error (ADR-084); ``None`` clears one.
STORAGE_BOUNDS: dict[str, tuple[int, int, str]] = {
    "storage_keep_executions": (0, 100000, "Executions kept per artifact (0 keeps all)"),
    "storage_step_data_days": (1, 36500, "Empty step outputs after (days)"),
    "storage_run_data_mib": (1, 1000000, "Limit for the data of all executions (MiB)"),
    "storage_step_output_kib": (1, 256, "Longest stored output of a step (KiB)"),
    "storage_run_output_kib": (1, 1024, "Longest stored output of an execution (KiB)"),
    "storage_clean_interval_hours": (1, 8760, "Clean automatically every (hours)"),
    "storage_warn_mib": (1, 10000000, "Warn when the database is larger than (MiB)"),
}


def _default(name: str) -> Any:
    """The default of a personal setting: the form manifest is the one place that declares it."""
    return personal_settings.defaults()[name]


class PersonalSettingsRead(BaseModel):
    """The personal settings; what was never set has the default of the manifest."""

    mark_resolved_references: bool = _default("mark_resolved_references")
    show_stop_switch: bool = _default("show_stop_switch")
    storage_keep_executions: int | None = _default("storage_keep_executions")
    storage_step_data_days: int | None = _default("storage_step_data_days")
    storage_run_data_mib: int | None = _default("storage_run_data_mib")
    storage_step_output_kib: int | None = _default("storage_step_output_kib")
    storage_run_output_kib: int | None = _default("storage_run_output_kib")
    storage_clean_interval_hours: int | None = _default("storage_clean_interval_hours")
    storage_warn_mib: int | None = _default("storage_warn_mib")


class PersonalSettingsWrite(BaseModel):
    """A change of personal settings; a field that is left out keeps its value, a name nobody declared is refused."""

    model_config = ConfigDict(extra="forbid", strict=True)

    mark_resolved_references: bool | None = None
    show_stop_switch: bool | None = None
    storage_keep_executions: int | None = None
    storage_step_data_days: int | None = None
    storage_run_data_mib: int | None = None
    storage_step_output_kib: int | None = None
    storage_run_output_kib: int | None = None
    storage_clean_interval_hours: int | None = None
    storage_warn_mib: int | None = None

    @model_validator(mode="after")
    def _bounds(self) -> PersonalSettingsWrite:
        """The limits of the *Data storage* settings, in plain words (``None`` clears a setting)."""
        for name, (low, high, what) in STORAGE_BOUNDS.items():
            value = getattr(self, name)
            if value is not None and not low <= value <= high:
                raise ValueError(f"{what}: use a number from {low} to {high}, or leave it empty")
        return self


class StopWrite(BaseModel):
    """Switch the emergency stop on (``true``) or off (``false``)."""

    model_config = ConfigDict(extra="forbid", strict=True)

    active: bool


class StorageCategoryRead(BaseModel):
    """What one kind of limit would delete or empty: how many entries and how many bytes."""

    key: str
    label: str
    entries: int
    bytes: int


class StoragePlanRead(BaseModel):
    """What a cleaning pass does now (the preview is exactly this)."""

    categories: list[StorageCategoryRead]
    entries: int
    bytes: int


class StorageTableRead(BaseModel):
    name: str
    bytes: int | None
    rows: int | None


class StorageInfoRead(BaseModel):
    """The database file: its size and the log's, the pages, the biggest tables."""

    file_bytes: int
    wal_bytes: int
    page_size: int
    pages: int
    free_pages: int
    free_bytes: int
    tables: list[StorageTableRead]
    tables_by: str
    warn_bytes: int | None
    over_warning: bool


class StorageStatusRead(BaseModel):
    db: StorageInfoRead
    run_data_bytes: int
    last_clean: dict[str, Any] | None
    interval_hours: int | None
    #: When the background cleaner runs next (``None`` while it is off).
    next_clean_at: str | None = None
    #: What a field the user has not set stands for (the settings key to a number): the engine's own value.
    defaults: dict[str, int] = {}
    #: The number a switch of a limit that is off gives when it is switched on.
    on_values: dict[str, int] = {}


class StorageReportRead(BaseModel):
    """What a pass did: the plan it carried out, the file before and after, and whether the write-ahead log is empty now."""

    plan: StoragePlanRead
    wal: dict[str, Any]
    before: dict[str, int]
    after: dict[str, int]
    at: str


class ShrinkRead(BaseModel):
    before: dict[str, int]
    after: dict[str, int]
    wal: dict[str, Any]


STORAGE = (
    "Data storage (ADR-084). Limits are the personal settings ``storage_*``; all are empty by default and then change nothing. "
    "What a user can see or fetch is removed only by those limits and the retention rules; cards, comments and activity never. "
    "A running execution is never touched."
)


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

    # ── Data storage ─────────────────────────────────────────────────────

    @router.get(
        "/storage",
        response_model=StorageStatusRead,
        name=f"{tag}get_storage",
        summary="Get the size of the database and the state of the cleaner",
        description=STORAGE
        + " The size of the file and of its write-ahead log, the free pages, the biggest tables, the data of all executions, the "
        "last pass and the interval of the background cleaner.",
    )
    async def get_storage(request: Request) -> StorageStatusRead:
        return StorageStatusRead(**await request.app.state.storage.status())

    @router.post(
        "/storage/preview",
        response_model=StoragePlanRead,
        name=f"{tag}preview_storage",
        summary="Preview a cleaning pass",
        description=STORAGE
        + " What a pass would delete or empty now, per kind, in entries and bytes; nothing is changed.",
        responses=errors(write=True),
    )
    async def preview_storage(request: Request) -> StoragePlanRead:
        return StoragePlanRead(**(await request.app.state.storage.preview()).to_data())

    @router.post(
        "/storage/clean",
        response_model=StorageReportRead,
        name=f"{tag}clean_storage",
        summary="Clean now",
        description=STORAGE
        + " Carries out exactly what the preview shows, then truncates the write-ahead log. ``409`` ``busy`` while a pass runs.",
        responses=errors(409, write=True),
    )
    async def clean_storage(request: Request) -> StorageReportRead:
        report = await request.app.state.storage.clean()
        return StorageReportRead(
            plan=StoragePlanRead(**report.plan),
            wal=report.wal,
            before=report.before,
            after=report.after,
            at=report.at,
        )

    @router.post(
        "/storage/shrink",
        response_model=ShrinkRead,
        name=f"{tag}shrink_storage",
        summary="Shrink the database",
        description=STORAGE
        + " Rewrites the file (VACUUM): it needs about as much free disk space as the file and its log take and holds the database "
        "for a moment; take a backup first. ``409`` ``not_enough_space`` when the disk has less free, ``409`` ``busy`` while a pass runs.",
        responses=errors(409, write=True),
    )
    async def shrink_storage(request: Request) -> ShrinkRead:
        return ShrinkRead(**await request.app.state.storage.shrink())

    return router
