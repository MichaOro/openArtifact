"""What the Build Context node reads of the cards and their history (ADR-078): parent, children, siblings, comment count, past executions.

A small read-only gateway on its own sessions, so the engine does not import the artifact service (which imports the engine). Archived
cards are left out of the related cards (they are off the board); a deleted parent is no parent.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import SessionOpener
from openartifact.engine.context_builder import CardInfo, PastExecution
from openartifact.models import Execution, Lane, RunNodeResult, Task, TaskComment

#: Steps whose output is no result worth showing for an earlier execution (they only start or end an action).
_NO_RESULT_KINDS = ("trigger", "output", "stage", "action", "pipeline", "complete")


def _info(task: Task, lane: str | None) -> CardInfo:
    return CardInfo(task.number, task.title, task.body or "", lane)


class SqlCardsGateway:
    """The cards and executions of the application's own database."""

    def __init__(self, session: SessionOpener) -> None:
        self._session = session

    @staticmethod
    async def _lanes(session: AsyncSession, keys: set[str]) -> dict[str, str]:
        if not keys:
            return {}
        rows = await session.execute(select(Lane.key, Lane.title).where(Lane.key.in_(keys)))
        return {key: title for key, title in rows.all()}

    async def parent(self, task_id: str) -> CardInfo | None:
        async with self._session() as session:
            task = await session.get(Task, task_id)
            if task is None or task.parent_id is None:
                return None
            parent = await session.get(Task, task.parent_id)
            if parent is None or parent.archived_at is not None:
                return None
            return _info(parent, (await self._lanes(session, {parent.status})).get(parent.status))

    async def _related(
        self, parent_id: str | None, exclude: str | None, limit: int
    ) -> tuple[list[CardInfo], int]:
        if parent_id is None:
            return [], 0
        query = select(Task).where(Task.parent_id == parent_id, Task.archived_at.is_(None))
        if exclude is not None:
            query = query.where(Task.id != exclude)
        async with self._session() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(query.subquery())) or 0
            )
            rows = (await session.scalars(query.order_by(Task.number, Task.id).limit(limit))).all()
            lanes = await self._lanes(session, {r.status for r in rows})
            return [_info(r, lanes.get(r.status)) for r in rows], total

    async def children(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        return await self._related(task_id, None, limit)

    async def siblings(self, task_id: str, limit: int) -> tuple[list[CardInfo], int]:
        async with self._session() as session:
            task = await session.get(Task, task_id)
        return await self._related(task.parent_id if task else None, task_id, limit)

    async def comment_count(self, task_id: str) -> int:
        async with self._session() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(TaskComment)
                    .where(TaskComment.task_id == task_id)
                )
                or 0
            )

    async def executions(
        self, task_id: str, exclude: str | None, newest: int
    ) -> tuple[list[PastExecution], int]:
        query = select(Execution).where(Execution.task_id == task_id, Execution.status != "running")
        if exclude is not None:
            query = query.where(Execution.id != exclude)
        async with self._session() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(query.subquery())) or 0
            )
            rows = (
                await session.scalars(query.order_by(Execution.number.desc()).limit(newest))
            ).all()
            found: list[PastExecution] = []
            for row in reversed(rows):
                step = (
                    await session.execute(
                        select(RunNodeResult.node_name, RunNodeResult.output)
                        .where(
                            RunNodeResult.execution_id == row.id,
                            RunNodeResult.output != "",
                            RunNodeResult.kind.not_in(_NO_RESULT_KINDS),
                        )
                        .order_by(RunNodeResult.seq.desc())
                        .limit(1)
                    )
                ).first()
                found.append(
                    PastExecution(
                        row.number,
                        row.status,
                        row.note,
                        row.started_by,
                        row.pipeline_name,
                        row.started_at,
                        step[0] if step else None,
                        step[1] if step else "",
                    )
                )
            return found, total
