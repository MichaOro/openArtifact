"""Persistence for :class:`~openartifact.models.WorkItem`."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import WorkItem, WorkItemStatus


class WorkItemRepository:
    """Database access for work items. Receives an ``AsyncSession``; never creates its own."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        project_id: str,
        title: str,
        description: str | None = None,
        status: WorkItemStatus = WorkItemStatus.BACKLOG,
    ) -> WorkItem:
        """Insert a work item at the end of its lane."""
        item = WorkItem(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=title,
            description=description,
            status=status,
            position=await self._next_position(project_id, status),
        )
        self._session.add(item)
        await self._session.flush()
        return item

    async def get(self, item_id: str) -> WorkItem | None:
        """Return the work item or ``None``."""
        return await self._session.get(WorkItem, item_id)

    async def list_for_project(
        self, project_id: str, status: WorkItemStatus | None = None
    ) -> Sequence[WorkItem]:
        """Return a project's work items in board order (lane, then position)."""
        query = select(WorkItem).where(WorkItem.project_id == project_id)
        if status is not None:
            query = query.where(WorkItem.status == status)
        result = await self._session.execute(query.order_by(WorkItem.status, WorkItem.position))
        return result.scalars().all()

    async def move(self, item: WorkItem, status: WorkItemStatus) -> WorkItem:
        """Move an item to the end of another lane."""
        item.position = await self._next_position(item.project_id, status)
        item.status = status
        await self._session.flush()
        return item

    async def delete(self, item: WorkItem) -> None:
        """Delete a work item."""
        await self._session.delete(item)
        await self._session.flush()

    async def _next_position(self, project_id: str, status: WorkItemStatus) -> int:
        result = await self._session.execute(
            select(func.max(WorkItem.position)).where(
                WorkItem.project_id == project_id, WorkItem.status == status
            )
        )
        highest = result.scalar()
        return 0 if highest is None else int(highest) + 1
