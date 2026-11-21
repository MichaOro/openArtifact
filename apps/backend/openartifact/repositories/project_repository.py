"""Persistence for :class:`~openartifact.models.Project`."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Project


class ProjectRepository:
    """Database access for projects. Receives an ``AsyncSession``; never creates its own."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str, description: str | None = None) -> Project:
        """Insert a project and flush so defaults (timestamps) are populated."""
        project = Project(id=str(uuid.uuid4()), name=name, description=description)
        self._session.add(project)
        await self._session.flush()
        return project

    async def get(self, project_id: str) -> Project | None:
        """Return the project or ``None``."""
        return await self._session.get(Project, project_id)

    async def list_all(self) -> Sequence[Project]:
        """Return all projects, newest first."""
        result = await self._session.execute(
            select(Project).order_by(Project.created_at.desc(), Project.id)
        )
        return result.scalars().all()

    async def delete(self, project: Project) -> None:
        """Delete a project (its work items are removed by the database cascade)."""
        await self._session.delete(project)
        await self._session.flush()
