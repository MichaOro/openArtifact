"""Tests for the project and work item repositories (real SQLite via migrations)."""

from __future__ import annotations

import pytest

from alembic import command
from openartifact.config import Settings
from openartifact.database import db_session_context
from openartifact.models import WorkItemStatus
from openartifact.repositories import ProjectRepository, WorkItemRepository
from tests.test_tasks import _alembic_config


@pytest.fixture
def migrated(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointing at a temp database with all migrations applied."""
    monkeypatch.setenv("OPENARTIFACT_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("OPENARTIFACT_DATABASE_FILENAME", settings.database_filename)
    command.upgrade(_alembic_config(), "head")
    return settings


async def test_project_create_get_list_delete(migrated: Settings) -> None:
    async with db_session_context(migrated) as session:
        repo = ProjectRepository(session)
        first = await repo.create("First", "desc")
        second = await repo.create("Second")
        assert first.description == "desc"
        assert second.description is None
        assert first.created_at is not None

        assert await repo.get(first.id) is first
        assert await repo.get("missing") is None
        assert {p.name for p in await repo.list_all()} == {"First", "Second"}

        await repo.delete(first)
        assert [p.name for p in await repo.list_all()] == ["Second"]


async def test_work_items_get_increasing_positions_per_lane(migrated: Settings) -> None:
    async with db_session_context(migrated) as session:
        project = await ProjectRepository(session).create("P")
        repo = WorkItemRepository(session)
        a = await repo.create(project.id, "a")
        b = await repo.create(project.id, "b")
        c = await repo.create(project.id, "c", status=WorkItemStatus.REVIEW)
        assert (a.position, b.position, c.position) == (0, 1, 0)


async def test_list_for_project_orders_and_filters(migrated: Settings) -> None:
    async with db_session_context(migrated) as session:
        projects = ProjectRepository(session)
        mine, other = await projects.create("mine"), await projects.create("other")
        repo = WorkItemRepository(session)
        first = await repo.create(mine.id, "first")
        second = await repo.create(mine.id, "second")
        await repo.create(other.id, "foreign")
        review = await repo.create(mine.id, "review", status=WorkItemStatus.REVIEW)

        listed = await repo.list_for_project(mine.id)
        assert [i.id for i in listed] == [first.id, second.id, review.id]
        only_review = await repo.list_for_project(mine.id, WorkItemStatus.REVIEW)
        assert [i.id for i in only_review] == [review.id]


async def test_move_appends_to_target_lane(migrated: Settings) -> None:
    async with db_session_context(migrated) as session:
        project = await ProjectRepository(session).create("P")
        repo = WorkItemRepository(session)
        todo = await repo.create(project.id, "t", status=WorkItemStatus.TODO)
        item = await repo.create(project.id, "x")
        moved = await repo.move(item, WorkItemStatus.TODO)
        assert moved.status == WorkItemStatus.TODO
        assert moved.position == todo.position + 1


async def test_delete_work_item(migrated: Settings) -> None:
    async with db_session_context(migrated) as session:
        project = await ProjectRepository(session).create("P")
        repo = WorkItemRepository(session)
        item = await repo.create(project.id, "x")
        await repo.delete(item)
        assert await repo.get(item.id) is None
