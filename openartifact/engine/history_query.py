"""The global execution list: filters, the keyset cursor and the query behind ``GET /api/executions``.

Order is ``started_at`` descending, then ``id`` descending (the tie-breaker), which the index
``ix_executions_started_at`` serves. A page is continued with a cursor holding the last row's
``(started_at, id)``, so rows inserted or deleted meanwhile neither repeat nor skip rows of the pages
that follow (an offset would). The filters, all optional and combined with AND:

* ``status`` and ``started_by``: comma separated lists of values, any of which may match.
* ``pipeline``: matches an execution whose ``pipeline_id`` equals the text, or whose stored
  ``pipeline_name`` contains it (case-insensitive). The name is the copy taken at the start, so it
  still works after the pipeline was renamed or deleted.
* ``q``: case-insensitive substring of the artifact's title, the pipeline name or the note; if it is a
  number (``12`` or ``#12``) the artifact with that number matches too.
* ``since`` / ``until``: ISO 8601 times on ``started_at``, both inclusive; a time without an offset is UTC.
* ``dry_run``: ``only`` (the dry runs, ADR-086), ``exclude`` (the real runs) or left out (both).
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    SQLColumnExpression,
    and_,
    exists,
    func,
    literal,
    or_,
    select,
    tuple_,
)
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.engine.schemas import (
    ExecutionOverview,
    ExecutionRead,
    ExecutionsPage,
    ExecutionsSummary,
    ExecutionTaskRef,
)
from openartifact.exceptions import ArtifactError
from openartifact.models import Execution, Graph, RunStatus, StartedBy, Task
from openartifact.schemas_common import as_utc

MAX_LIMIT = 200
DEFAULT_LIMIT = 50


def _choice(text: str | None, allowed: type[RunStatus] | type[StartedBy], name: str) -> list[str]:
    if not text:
        return []
    values = [v.strip().lower() for v in text.split(",") if v.strip()]
    valid = {m.value for m in allowed}
    bad = [v for v in values if v not in valid]
    if bad:
        raise ArtifactError(
            422, f"{name}: unknown {', '.join(bad)} (use {', '.join(sorted(valid))})"
        )
    return values


def _time(text: str | None, name: str) -> datetime | None:
    if not text:
        return None
    try:
        value = datetime.fromisoformat(text.strip())
    except ValueError as error:
        raise ArtifactError(
            422, f"{name} must be an ISO 8601 time, e.g. 2026-11-22T10:00:00Z"
        ) from error
    return as_utc(value)


def _contains(column: SQLColumnExpression[str], text: str) -> ColumnElement[bool]:
    """Case-insensitive substring match; ``%``, ``_`` and the escape character in ``text`` are literal."""
    escaped = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return func.lower(column).like(f"%{escaped}%", escape="\\")


@dataclass(frozen=True)
class ExecutionFilter:
    statuses: list[str]
    started_by: list[str]
    pipeline: str | None
    q: str | None
    since: datetime | None
    until: datetime | None
    #: ``True``: only dry runs, ``False``: only real runs, ``None``: both.
    dry_run: bool | None = None

    @classmethod
    def parse(
        cls,
        *,
        status: str | None = None,
        started_by: str | None = None,
        pipeline: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
        dry_run: str | None = None,
    ) -> ExecutionFilter:
        """The filter from the raw query values; a value that makes no sense is a 422."""
        wanted = (dry_run or "").strip().lower()
        if wanted not in ("", "only", "exclude"):
            raise ArtifactError(422, "dry_run: use only or exclude")
        return cls(
            statuses=_choice(status, RunStatus, "status"),
            started_by=_choice(started_by, StartedBy, "started_by"),
            pipeline=(pipeline or "").strip() or None,
            q=(q or "").strip() or None,
            since=_time(since, "since"),
            until=_time(until, "until"),
            dry_run={"only": True, "exclude": False}.get(wanted),
        )

    def conditions(self) -> list[ColumnElement[bool]]:
        found: list[ColumnElement[bool]] = []
        if self.statuses:
            found.append(Execution.status.in_(self.statuses))
        if self.started_by:
            found.append(Execution.started_by.in_(self.started_by))
        if self.pipeline:
            found.append(
                or_(
                    Execution.pipeline_id == self.pipeline,
                    _contains(Execution.pipeline_name, self.pipeline),
                )
            )
        if self.q:
            options = [
                _contains(Task.title, self.q),
                _contains(Execution.pipeline_name, self.q),
                _contains(func.coalesce(Execution.note, ""), self.q),
            ]
            digits = self.q.removeprefix("#")
            if digits.isascii() and digits.isdigit():
                options.append(Task.number == int(digits))
            found.append(or_(*options))
        if self.dry_run is not None:
            found.append(Execution.dry_run.is_(self.dry_run))
        if self.since is not None:
            found.append(Execution.started_at >= self.since.astimezone(UTC).replace(tzinfo=None))
        if self.until is not None:
            found.append(Execution.started_at <= self.until.astimezone(UTC).replace(tzinfo=None))
        return found


def encode_cursor(started_at: datetime, execution_id: str) -> str:
    raw = json.dumps([as_utc(started_at).isoformat(), execution_id]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, str]:
    """The ``(started_at, id)`` a cursor holds (naive UTC, as stored); anything else is a 422."""
    try:
        text, execution_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        if not isinstance(text, str) or not isinstance(execution_id, str):
            raise ValueError
        return as_utc(datetime.fromisoformat(text)).replace(tzinfo=None), execution_id
    except (ValueError, TypeError, binascii.Error) as error:
        raise ArtifactError(422, "cursor is not valid") from error


def _base() -> Select[Execution, int, str, bool]:
    pipeline_exists = exists().where(Graph.id == Execution.pipeline_id).correlate(Execution)
    return select(Execution, Task.number, Task.title, pipeline_exists).join(
        Task, Task.id == Execution.task_id
    )


async def summary(session: AsyncSession, now: datetime) -> ExecutionsSummary:
    """The counters of the strip above the list (see :class:`ExecutionsSummary`). *Running* and *total* count every execution;
    *failed* and *done in the last 24 hours* count the real runs only: a dry run (ADR-086) is no failure of a pipeline."""
    since = (now - timedelta(hours=24)).astimezone(UTC).replace(tzinfo=None)

    def count(status: str, recent: bool = False) -> ColumnElement[int]:
        cond = Execution.status == status
        if recent:
            cond = and_(cond, Execution.started_at >= since, Execution.dry_run.is_(False))
        return func.coalesce(func.sum(cond.cast(Integer)), 0)

    row = (
        await session.execute(
            select(
                func.count(),
                count(RunStatus.RUNNING),
                count(RunStatus.FAILED, True),
                count(RunStatus.DONE, True),
            ).select_from(Execution)
        )
    ).one()
    return ExecutionsSummary(running=row[1], failed_24h=row[2], done_24h=row[3], total=row[0])


async def list_executions(
    session: AsyncSession,
    flt: ExecutionFilter,
    *,
    limit: int,
    cursor: str | None,
    now: datetime,
) -> ExecutionsPage:
    """One page of the executions of all artifacts that match the filter, newest first."""
    if not 1 <= limit <= MAX_LIMIT:
        raise ArtifactError(422, f"limit must be between 1 and {MAX_LIMIT}")
    conditions = flt.conditions()
    after = decode_cursor(cursor) if cursor else None
    page = _base().where(*conditions)
    if after is not None:
        page = page.where(
            tuple_(Execution.started_at, Execution.id)
            < tuple_(literal(after[0], Execution.started_at.type), literal(after[1]))
        )
    rows = (
        await session.execute(
            page.order_by(Execution.started_at.desc(), Execution.id.desc()).limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    total = await session.scalar(
        select(func.count())
        .select_from(Execution)
        .join(Task, Task.id == Execution.task_id)
        .where(*conditions)
    )
    items = [
        ExecutionOverview(
            **ExecutionRead.of(row).model_dump(),
            task=ExecutionTaskRef(id=row.task_id, number=number, title=title),
            pipeline_exists=bool(exists_),
        )
        for row, number, title, exists_ in rows
    ]
    last = rows[-1][0] if more else None
    return ExecutionsPage(
        items=items,
        next_cursor=None if last is None else encode_cursor(last.started_at, last.id),
        total=total or 0,
        summary=await summary(session, now),
    )
