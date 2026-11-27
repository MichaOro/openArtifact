"""Data storage (ADR-084): what the user may limit, what a cleaning pass does, and how the database file shrinks.

The principle is the owner's: **what a user can see or fetch (the interface, the API, MCP) is removed only by rules and limits the
user knows and has set** (Settings, Personal, *Data storage*, and the retention rules under Executions); only purely technical data,
which nobody can reach, may be cleaned without asking. Defaults change nothing: every limit is empty until the user sets it. Cards, their
comments and their activity are never touched here.

``VISIBLE_TABLES`` and ``TECHNICAL_TABLES`` classify every table (a test fails when a new table is in neither). The only technical things
that grow are the write-ahead log and free pages, which :func:`checkpoint_truncate` and :func:`shrink` deal with.

A pass is a :class:`Plan` made by :func:`plan` (the preview shows it) and carried out by :func:`clean` (it deletes exactly that):
1. executions beyond the number kept per artifact (the user's setting, else the operator's default) and executions the retention rules
   match, with their steps (``ExecutionHistory.remove``);
2. the *outputs and details of the steps* (and the run context) of finished executions older than N days: the execution and its steps
   stay, the heavy text goes and each step says so in ``data.data_pruned``;
3. the same for the oldest finished executions until the data of all executions fits the size limit;
4. a write-ahead log checkpoint with ``TRUNCATE`` (technical).
A running execution is never touched.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.comments.schemas import Author
from openartifact.engine import retention
from openartifact.engine.history import GUARD, RULES, Changes, ExecutionHistory, utcnow
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.models.enums import RunStatus
from openartifact.models.settings import AppSetting

logger = logging.getLogger(__name__)

#: Tables whose rows a user can read through the interface, the API or MCP (ADR-084): removed only by the user's own rules and limits.
VISIBLE_TABLES = frozenset(
    {
        "agent_versions",
        "agents",
        "app_settings",
        "artifact_fields",
        "credential_events",  # the history of a credential
        "credentials",
        "executions",
        "external_credentials",
        "graph_edges",
        "graph_nodes",
        "graph_versions",
        "graphs",
        "guard_attachments",
        "guard_definitions",
        "guard_versions",
        "internal_credentials",
        "internal_tokens",  # the managed tokens, listed on the credentials page
        "lanes",
        "llm_models",
        "llm_providers",
        "pipeline_runs",  # the state of a run
        "run_node_results",  # the steps of an execution
        "run_stages",
        "secrets",  # the names, listed by the API and by MCP
        "task_activity",
        "task_comments",
        "tasks",
    }
)
#: Tables nobody can reach: bookkeeping of the application itself. Nothing in them grows (one row each).
TECHNICAL_TABLES = frozenset({"alembic_version", "task_number_seq"})

#: The author of the executions deleted by the limit *Executions kept per artifact*.
STORAGE_LIMIT = Author("system", "storage limit")
#: The marker a step carries after its outputs were removed.
PRUNED_FLAG = "data_pruned"
#: Today's limits of a stored step output and of all outputs of one execution, in characters (``engine/runner.py``).
STEP_OUTPUT_CHARS = 256 * 1024
RUN_OUTPUT_CHARS = 1024 * 1024
_MIB = 1024 * 1024
#: What the page shows in a field the user has not set (the value stored then is ``None``), and the number a switch gives when it is
#: switched on. The first is what the engine does anyway (the operator's number of executions, today's limits), the second is a
#: suggestion the user changes.
ON_VALUES: dict[str, int] = {
    "storage_step_data_days": 30,
    "storage_run_data_mib": 1024,
    "storage_clean_interval_hours": 24,
    "storage_warn_mib": 1024,
}
_CHUNK = 500
#: ``length`` of a JSON column in bytes; ``null`` (the JSON value) counts as empty.
_DETAIL_BYTES = (
    "CASE WHEN r.detail IS NULL OR CAST(r.detail AS TEXT) = 'null' THEN 0 "
    "ELSE length(CAST(r.detail AS BLOB)) END"
)


# ── the policy: the user's limits ─────────────────────────────────────


@dataclass(frozen=True)
class StorageLimits:
    """What an execution freezes at its start about what it stores (like the run limits): the longest stored output of a step and the
    total of all stored outputs of the execution, in characters."""

    step_output_chars: int = STEP_OUTPUT_CHARS
    run_output_chars: int = RUN_OUTPUT_CHARS

    def to_data(self) -> dict[str, int]:
        return asdict(self)

    @classmethod
    def of_snapshot(cls, snapshot: Mapping[str, Any]) -> StorageLimits:
        """The limits a snapshot froze; an execution that started before they existed has today's."""
        raw = snapshot.get("storage")
        if not isinstance(raw, Mapping):
            return cls()
        step, run = raw.get("step_output_chars"), raw.get("run_output_chars")
        return cls(
            step if isinstance(step, int) and 0 < step <= STEP_OUTPUT_CHARS else STEP_OUTPUT_CHARS,
            run if isinstance(run, int) and 0 < run <= RUN_OUTPUT_CHARS else RUN_OUTPUT_CHARS,
        )


@dataclass(frozen=True)
class StoragePolicy:
    """The *Data storage* settings of the user; ``None`` is empty (the operator's default, today's limit, or off)."""

    keep_executions: int | None
    step_data_days: int | None
    run_data_bytes: int | None
    step_output_chars: int
    run_output_chars: int
    clean_interval_hours: int | None
    warn_bytes: int | None

    @classmethod
    def of(cls, values: Mapping[str, Any]) -> StoragePolicy:
        def number(name: str) -> int | None:
            value = values.get(name)
            return int(value) if isinstance(value, int) and not isinstance(value, bool) else None

        mib, kib = number("storage_run_data_mib"), number("storage_step_output_kib")
        run_kib, warn = number("storage_run_output_kib"), number("storage_warn_mib")
        return cls(
            keep_executions=number("storage_keep_executions"),
            step_data_days=number("storage_step_data_days"),
            run_data_bytes=mib * _MIB if mib else None,
            step_output_chars=min(kib * 1024, STEP_OUTPUT_CHARS) if kib else STEP_OUTPUT_CHARS,
            run_output_chars=min(run_kib * 1024, RUN_OUTPUT_CHARS) if run_kib else RUN_OUTPUT_CHARS,
            clean_interval_hours=number("storage_clean_interval_hours"),
            warn_bytes=warn * _MIB if warn else None,
        )

    def limits(self) -> StorageLimits:
        return StorageLimits(self.step_output_chars, self.run_output_chars)

    def keep(self, operator_default: int) -> int:
        """How many executions per artifact stay: the user's number, else the operator's default; ``0`` is all."""
        return operator_default if self.keep_executions is None else self.keep_executions


async def load_policy(session: AsyncSession) -> StoragePolicy:
    from openartifact import personal_settings

    return StoragePolicy.of(await personal_settings.load(session))


# ── cutting long text when it is stored ───────────────────────────────


def cut_detail(value: Any, limit: int) -> tuple[Any, int]:
    """``value`` (the JSON ``detail`` of a step) with every text longer than ``limit`` characters cut and marked; and how many were cut."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value, 0
        left = len(value) - limit
        return value[:limit] + f"\n[truncated: {left} characters left out]", 1
    if isinstance(value, list):
        out: list[Any] = []
        count = 0
        for item in value:
            cut, n = cut_detail(item, limit)
            out.append(cut)
            count += n
        return out, count
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            cut, n = cut_detail(item, limit)
            result[key] = cut
            count += n
        return result, count
    return value, 0


# ── what the data takes ───────────────────────────────────────────────


@dataclass
class _Row:
    id: str
    task_id: str
    number: int
    status: str
    started_at: datetime
    step_bytes: int
    context_bytes: int
    snapshot_bytes: int
    with_data: int  # steps that still hold an output or a detail


_ROWS = text(
    "SELECT e.id, e.task_id, e.number, e.status, e.started_at, "
    f"COALESCE((SELECT SUM(length(CAST(r.output AS BLOB)) + {_DETAIL_BYTES}) FROM run_node_results r WHERE r.execution_id = e.id), 0) AS step_bytes, "
    "length(CAST(e.context AS BLOB)) AS context_bytes, length(CAST(e.snapshot AS BLOB)) AS snapshot_bytes, "
    f"(SELECT COUNT(*) FROM run_node_results r WHERE r.execution_id = e.id AND (r.output != '' OR {_DETAIL_BYTES} > 0)) AS with_data "
    "FROM executions e"
)


async def _rows(session: AsyncSession) -> list[_Row]:
    result = await session.execute(_ROWS)
    return [
        _Row(
            r.id,
            r.task_id,
            r.number,
            r.status,
            r.started_at
            if isinstance(r.started_at, datetime)
            else datetime.fromisoformat(str(r.started_at)),
            int(r.step_bytes),
            int(r.context_bytes or 0),
            int(r.snapshot_bytes or 0),
            int(r.with_data),
        )
        for r in result
    ]


async def run_data_bytes(session: AsyncSession) -> int:
    """What the limit *Limit for the data of all executions* measures: outputs, details and contexts of all executions."""
    return sum(r.step_bytes + r.context_bytes for r in await _rows(session))


# ── the plan: the preview and the pass are the same thing ─────────────


@dataclass
class Category:
    key: str
    label: str
    entries: int = 0
    bytes: int = 0


@dataclass
class Plan:
    """What a pass does now: executions to delete (by artifact), executions whose step data is emptied, and what that frees."""

    by_keep: dict[str, list[str]] = field(default_factory=dict)
    by_rules: dict[str, list[str]] = field(default_factory=dict)
    by_age: list[str] = field(default_factory=list)
    by_size: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)

    @property
    def entries(self) -> int:
        return sum(c.entries for c in self.categories)

    @property
    def bytes(self) -> int:
        return sum(c.bytes for c in self.categories)

    def to_data(self) -> dict[str, Any]:
        return {
            "categories": [asdict(c) for c in self.categories],
            "entries": self.entries,
            "bytes": self.bytes,
        }


async def plan(
    session: AsyncSession, policy: StoragePolicy, operator_keep: int, now: datetime | None = None
) -> Plan:
    """What the user's rules and limits hit now (never a running execution)."""
    now = now or utcnow()
    rows = await _rows(session)
    by_id = {r.id: r for r in rows}
    result = Plan()
    # 1. executions beyond the number kept per artifact
    keep = policy.keep(operator_keep)
    doomed: set[str] = set()
    if keep > 0:
        per_task: dict[str, list[_Row]] = {}
        for row in sorted(rows, key=lambda r: r.number, reverse=True):
            per_task.setdefault(row.task_id, []).append(row)
        for task_id, listed in per_task.items():
            ids = [
                row.id
                for rank, row in enumerate(listed, start=1)
                if rank > keep and rank != 1 and row.status != RunStatus.RUNNING
            ]
            if ids:
                result.by_keep[task_id] = ids
                doomed.update(ids)
    # 2. executions the retention rules match (not those already doomed)
    rules = await retention.load_rules(session)
    for task_id, execution_id in await retention.matching_ids(session, rules, now):
        if execution_id not in doomed and by_id[execution_id].status != RunStatus.RUNNING:
            result.by_rules.setdefault(task_id, []).append(execution_id)
            doomed.add(execution_id)

    def total(ids: list[str]) -> int:
        return sum(
            by_id[i].step_bytes + by_id[i].context_bytes + by_id[i].snapshot_bytes for i in ids
        )

    kept = [r for r in rows if r.id not in doomed]
    # 3. step data of finished executions older than N days
    emptied: set[str] = set()
    if policy.step_data_days:
        cutoff = (now - timedelta(days=policy.step_data_days)).replace(tzinfo=None)
        for row in kept:
            if (
                row.status != RunStatus.RUNNING
                and row.started_at.replace(tzinfo=None) < cutoff
                and _heavy(row)
            ):
                result.by_age.append(row.id)
                emptied.add(row.id)
    # 4. step data of the oldest finished executions until all data fits the size limit
    if policy.run_data_bytes:
        current = sum(r.step_bytes + r.context_bytes for r in kept if r.id not in emptied) + sum(
            _EMPTY_CONTEXT for r in kept if r.id in emptied
        )
        for row in sorted(kept, key=lambda r: r.started_at):
            if current <= policy.run_data_bytes:
                break
            if row.id in emptied or row.status == RunStatus.RUNNING or not _heavy(row):
                continue
            result.by_size.append(row.id)
            emptied.add(row.id)
            current -= row.step_bytes + row.context_bytes - _EMPTY_CONTEXT
    for key, label, ids in (
        (
            "executions_keep",
            "Executions beyond the number kept per artifact",
            [i for v in result.by_keep.values() for i in v],
        ),
        (
            "executions_rules",
            "Executions matched by a retention rule",
            [i for v in result.by_rules.values() for i in v],
        ),
    ):
        result.categories.append(Category(key, label, len(ids), total(ids)))
    for key, label, ids in (
        ("step_data_age", "Step outputs and details older than the set days", result.by_age),
        ("step_data_size", "Step outputs and details over the size limit", result.by_size),
    ):
        result.categories.append(
            Category(
                key,
                label,
                len(ids),
                sum(by_id[i].step_bytes + by_id[i].context_bytes - _EMPTY_CONTEXT for i in ids),
            )
        )
    return result


#: ``"{}"``, what an emptied context holds.
_EMPTY_CONTEXT = 2


def _heavy(row: _Row) -> bool:
    """Whether emptying this execution frees something: a step still holds an output or detail, or the context is more than empty."""
    return row.with_data > 0 or row.context_bytes > _EMPTY_CONTEXT


# ── the pass ──────────────────────────────────────────────────────────


@dataclass
class Report:
    """What a pass did: the categories, how the file changed, and whether the write-ahead log is empty now."""

    plan: dict[str, Any]
    wal: dict[str, Any]
    before: dict[str, int]
    after: dict[str, int]
    at: str


async def empty_step_data(session: AsyncSession, execution_ids: list[str]) -> None:
    """Remove the outputs and details of the steps of these executions and their contexts; each step says so in ``data``."""
    for i in range(0, len(execution_ids), _CHUNK):
        chunk = execution_ids[i : i + _CHUNK]
        await session.execute(
            text(
                "UPDATE run_node_results SET output = '', detail = NULL, data = "
                "CASE WHEN data IS NULL OR CAST(data AS TEXT) = 'null' THEN json_object('data_pruned', json('true')) "
                "ELSE json_set(data, '$.data_pruned', json('true')) END "
                "WHERE execution_id IN :ids AND (output != '' OR detail IS NOT NULL AND CAST(detail AS TEXT) != 'null')"
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": chunk},
        )
        await session.execute(
            text("UPDATE executions SET context = '{}' WHERE id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": chunk},
        )


async def clean(
    session: AsyncSession,
    history: ExecutionHistory,
    policy: StoragePolicy,
    db_path: Path,
) -> Report:
    """Carry out :func:`plan` (one transaction), then truncate the write-ahead log. The caller commits nothing: this does."""
    before = file_sizes(db_path)
    made = await plan(session, policy, history.default_keep)
    changes = Changes()
    for task_id, ids in made.by_keep.items():
        await history.remove(
            session,
            task_id,
            ids,
            changes,
            STORAGE_LIMIT if policy.keep_executions is not None else GUARD,
        )
    for task_id, ids in made.by_rules.items():
        await history.remove(session, task_id, ids, changes, RULES)
    await empty_step_data(session, made.by_age + made.by_size)
    await session.commit()
    history.publish(changes)
    wal = await asyncio.to_thread(checkpoint_truncate, db_path)
    after = file_sizes(db_path)
    report = Report(made.to_data(), wal, before, after, utcnow().isoformat())
    logger.info(
        "Data storage pass: %d entries, %d bytes of data; executions deleted %d (limit %d, rules %d), step data emptied of %d; file %d -> %d bytes, wal truncated %s",
        made.entries,
        made.bytes,
        sum(len(v) for v in made.by_keep.values()) + sum(len(v) for v in made.by_rules.values()),
        sum(len(v) for v in made.by_keep.values()),
        sum(len(v) for v in made.by_rules.values()),
        len(made.by_age) + len(made.by_size),
        before["file_bytes"],
        after["file_bytes"],
        wal.get("truncated"),
    )
    return report


# ── the file: sizes, the log, shrinking ───────────────────────────────


def file_sizes(db_path: Path) -> dict[str, int]:
    """The size of the database file and of its write-ahead log in bytes."""
    wal = db_path.with_name(db_path.name + "-wal")
    return {
        "file_bytes": db_path.stat().st_size if db_path.exists() else 0,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
    }


def checkpoint_truncate(db_path: Path) -> dict[str, Any]:
    """Write the log back and cut the file to zero (``PRAGMA wal_checkpoint(TRUNCATE)``): technical, cheap, always allowed.

    ``truncated`` is false when a reader still holds the log (``busy``); the next pass tries again.
    """
    try:
        with sqlite3.connect(db_path, timeout=30) as conn:
            busy, log, checkpointed = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    except sqlite3.Error as error:
        return {"truncated": False, "error": str(error)}
    return {
        "truncated": busy == 0,
        "busy": busy,
        "log_pages": log,
        "checkpointed_pages": checkpointed,
    }


def info(db_path: Path, warn_bytes: int | None = None) -> dict[str, Any]:
    """The size of the file and the log, the pages, and the biggest tables (``dbstat`` when the SQLite build has it, else row counts)."""
    sizes = file_sizes(db_path)
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30) as conn:
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        pages = conn.execute("PRAGMA page_count").fetchone()[0]
        free = conn.execute("PRAGMA freelist_count").fetchone()[0]
        tables: list[dict[str, Any]]
        try:
            rows = conn.execute(
                "SELECT name, SUM(pgsize) AS bytes FROM dbstat WHERE aggregate = TRUE GROUP BY name "
                "HAVING name NOT LIKE 'sqlite_%' ORDER BY bytes DESC LIMIT 8"
            ).fetchall()
            tables = [{"name": n, "bytes": int(b), "rows": None} for n, b in rows]
            source = "dbstat"
        except sqlite3.Error:
            names = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            ]
            counted = [
                {
                    "name": n,
                    "bytes": None,
                    "rows": conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0],
                }
                for n in names
            ]
            tables = sorted(counted, key=lambda t: -int(t["rows"]))[:8]
            source = "rows"
    return {
        **sizes,
        "page_size": page_size,
        "pages": pages,
        "free_pages": free,
        "free_bytes": free * page_size,
        "tables": tables,
        "tables_by": source,
        "warn_bytes": warn_bytes,
        "over_warning": bool(warn_bytes and sizes["file_bytes"] > warn_bytes),
    }


def _vacuum(db_path: Path) -> None:
    with sqlite3.connect(db_path, timeout=120) as conn:
        conn.isolation_level = None
        conn.execute("VACUUM")


async def shrink(db_path: Path) -> dict[str, Any]:
    """``VACUUM`` the database (rewrites the file; the user asked for it): refused when the disk has less free space than the file
    and its log take, because VACUUM needs about that much; then the log is truncated."""
    sizes = file_sizes(db_path)
    needed = int((sizes["file_bytes"] + sizes["wal_bytes"]) * 1.1)
    free = shutil.disk_usage(db_path.parent).free
    if free < needed:
        raise ArtifactError(
            409,
            f"Shrinking needs about {needed // _MIB + 1} MiB of free disk space and {free // _MIB} MiB are free",
            code="not_enough_space",
        )
    await asyncio.to_thread(_vacuum, db_path)
    wal = await asyncio.to_thread(checkpoint_truncate, db_path)
    after = file_sizes(db_path)
    logger.info("Database shrunk: file %d -> %d bytes", sizes["file_bytes"], after["file_bytes"])
    return {"before": sizes, "after": after, "wal": wal}


# ── the service: preview, pass, shrink, status and the background cleaner ──

LAST_KEY = "storage.last_clean"
#: How often the background loop looks whether a pass is due (the interval itself is the user's setting).
LOOP_CHECK_SECONDS = 60


class Cleaner:
    """One cleaning pass at a time (a second request is ``409 busy``), the numbers the page shows, and the loop that runs a pass every
    *Clean automatically every N hours* (off when the setting is empty)."""

    def __init__(
        self,
        session_factory: Callable[[], Any],
        history: ExecutionHistory,
        db_path: Path,
        bus: EventBus | None = None,
        check_seconds: float = LOOP_CHECK_SECONDS,
    ) -> None:
        self._session = session_factory
        self.history = history
        self.db_path = db_path
        self._bus = bus
        self._lock = asyncio.Lock()
        self._check = check_seconds
        self._started = utcnow()

    async def preview(self) -> Plan:
        async with self._session() as session:
            return await plan(session, await load_policy(session), self.history.default_keep)

    async def clean(self) -> Report:
        if self._lock.locked():
            raise ArtifactError(409, "A cleaning pass is already running", code="busy")
        async with self._lock, self._session() as session:
            policy = await load_policy(session)
            report = await clean(session, self.history, policy, self.db_path)
            value = json.dumps(
                {"at": report.at, "entries": report.plan["entries"], "bytes": report.plan["bytes"]}
            )
            row = await session.get(AppSetting, LAST_KEY)
            if row is None:
                session.add(AppSetting(key=LAST_KEY, value=value))
            else:
                row.value = value
            await session.commit()
        if self._bus is not None:
            self._bus.publish(
                "storage.cleaned", {"at": report.at, "entries": report.plan["entries"]}
            )
        return report

    async def shrink(self) -> dict[str, Any]:
        if self._lock.locked():
            raise ArtifactError(409, "A cleaning pass is already running", code="busy")
        async with self._lock:
            return await shrink(self.db_path)

    async def status(self) -> dict[str, Any]:
        async with self._session() as session:
            policy = await load_policy(session)
            row = await session.get(AppSetting, LAST_KEY)
            data = await run_data_bytes(session)
        try:
            last = json.loads(row.value) if row is not None else None
        except ValueError:
            last = None
        interval = policy.clean_interval_hours
        since = self._started
        if last is not None:
            with contextlib.suppress(ValueError, KeyError, TypeError):
                since = datetime.fromisoformat(last["at"])
        return {
            "db": await asyncio.to_thread(info, self.db_path, policy.warn_bytes),
            "run_data_bytes": data,
            "last_clean": last,
            "interval_hours": interval,
            "next_clean_at": (since + timedelta(hours=interval)).isoformat() if interval else None,
            "defaults": {
                "storage_keep_executions": self.history.default_keep,
                "storage_step_output_kib": STEP_OUTPUT_CHARS // 1024,
                "storage_run_output_kib": RUN_OUTPUT_CHARS // 1024,
            },
            "on_values": dict(ON_VALUES),
        }

    async def due(self, now: datetime | None = None) -> bool:
        """Whether the interval the user set has passed since the last pass (or since the start)."""
        async with self._session() as session:
            policy = await load_policy(session)
            row = await session.get(AppSetting, LAST_KEY)
        if not policy.clean_interval_hours:
            return False
        last = self._started
        if row is not None:
            with contextlib.suppress(ValueError, KeyError):
                last = datetime.fromisoformat(json.loads(row.value)["at"])
        return (now or utcnow()) - last >= timedelta(hours=policy.clean_interval_hours)

    async def loop(self) -> None:
        """Run a pass whenever one is due; a failed pass is logged and tried again at the next check."""
        while True:
            await asyncio.sleep(self._check)
            try:
                if await self.due():
                    await self.clean()
            except Exception:  # a failed pass must not end the loop
                logger.exception("The data storage pass could not be done")
