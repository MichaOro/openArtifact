"""Persistence for board tasks. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import Task
from openartifact.tasks.schemas import TaskCreate, TaskUpdate

# Below this distance between two neighbours the lane is renumbered before inserting between them.
MIN_POSITION_GAP = 1e-6


class PlacementError(ValueError):
    """The requested position refers to a task that is not in the target lane."""


class ParentError(ValueError):
    """The requested parent does not exist or would create a cycle."""


@dataclass
class UpdateResult:
    """Outcome of :meth:`TaskRepository.update`."""

    changed: set[str] = field(default_factory=set)
    #: True when other tasks of the lane got new positions (clients must resync).
    renumbered: bool = False


class TaskRepository:
    """Database access for :class:`~openartifact.models.Task`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: TaskCreate) -> Task:
        """Insert a task at the top of its lane and flush so defaults are populated."""
        task = Task(
            id=str(uuid.uuid4()),
            title=data.title,
            body=data.body,
            status=data.status.value,
            position=await self._top_position(data.status.value),
        )
        self._session.add(task)
        await self._session.flush()
        return task

    async def list_all(self) -> Sequence[Task]:
        """Return all tasks in board order: by lane, then position (ties: newest first)."""
        result = await self._session.execute(
            select(Task).order_by(Task.status, Task.position, Task.created_at.desc(), Task.id)
        )
        return result.scalars().all()

    async def get(self, task_id: str) -> Task | None:
        """Return the task or ``None``."""
        return await self._session.get(Task, task_id)

    async def update(self, task: Task, data: TaskUpdate) -> UpdateResult:
        """Apply the sent fields and, if requested, move/reorder the task.

        Placement rules:

        * ``before_id`` set: put the task right before that task (which must be in the
          target lane);
        * ``before_id`` explicitly ``null``: put it at the end of the target lane;
        * lane changed without ``before_id``: put it at the top of the target lane.

        ``updated_at`` is only refreshed when something changed.
        """
        sent = data.model_fields_set
        result = UpdateResult()

        if "parent_id" in sent and data.parent_id != task.parent_id:
            await self._check_parent(task, data.parent_id)
            result.changed.add("parent_id")

        new_values: dict[str, str | None] = {}
        if "title" in sent and data.title is not None:
            new_values["title"] = data.title
        if "body" in sent:
            new_values["body"] = data.body
        if "status" in sent and data.status is not None:
            new_values["status"] = data.status.value
        for name, value in new_values.items():
            if getattr(task, name) != value:
                result.changed.add(name)

        target = new_values.get("status", task.status) or task.status
        lane_changed = target != task.status
        if "before_id" in sent or lane_changed:
            await self._place(task, target, data, result)

        for name in result.changed - {"position", "parent_id"}:
            setattr(task, name, new_values[name])
        if "parent_id" in result.changed:
            task.parent_id = data.parent_id
        if result.changed or result.renumbered:
            await self._session.flush()
        return result

    async def delete(self, task: Task) -> int:
        """Delete a task. Its children lose their parent (they are not deleted).

        Returns the number of children that were detached.
        """
        children = (
            (await self._session.execute(select(Task).where(Task.parent_id == task.id)))
            .scalars()
            .all()
        )
        for child in children:
            child.parent_id = None
        await self._session.delete(task)
        await self._session.flush()
        return len(children)

    async def _check_parent(self, task: Task, parent_id: str | None) -> None:
        """A parent must exist and must not be the task itself or one of its descendants."""
        if parent_id is None:
            return
        if parent_id == task.id:
            raise ParentError("An artifact cannot be its own parent")
        seen: set[str] = set()
        current: str | None = parent_id
        while current is not None:
            if current == task.id:
                raise ParentError("The parent must not be a descendant of this artifact")
            if current in seen:  # defensive: a pre-existing cycle must not hang the request
                break
            seen.add(current)
            node = await self.get(current)
            if node is None:
                raise ParentError("Parent artifact not found")
            current = node.parent_id

    # ── ordering ──────────────────────────────────────────────────────

    async def _lane(self, status: str, *, exclude: str | None = None) -> list[Task]:
        query = select(Task).where(Task.status == status)
        if exclude is not None:
            query = query.where(Task.id != exclude)
        result = await self._session.execute(
            query.order_by(Task.position, Task.created_at.desc(), Task.id)
        )
        return list(result.scalars().all())

    async def _top_position(self, status: str) -> float:
        lowest = (
            await self._session.execute(
                select(func.min(Task.position)).where(Task.status == status)
            )
        ).scalar()
        return 0.0 if lowest is None else float(lowest) - 1.0

    async def _place(self, task: Task, target: str, data: TaskUpdate, result: UpdateResult) -> None:
        others = await self._lane(target, exclude=task.id)
        before_id = data.before_id if "before_id" in data.model_fields_set else None
        explicit_end = "before_id" in data.model_fields_set and before_id is None

        if before_id is not None:
            index = next((i for i, t in enumerate(others) if t.id == before_id), None)
            if index is None:
                raise PlacementError("before_id must reference another task in the target lane")
            new_order = [t.id for t in others[:index]] + [task.id] + [t.id for t in others[index:]]
        elif explicit_end:
            new_order = [t.id for t in others] + [task.id]
        else:  # lane changed, no explicit position: top
            new_order = [task.id] + [t.id for t in others]

        if target == task.status:
            current = [t.id for t in await self._lane(target)]
            if current == new_order:
                return  # already exactly there

        index = new_order.index(task.id)
        prev = others[index - 1] if index > 0 else None
        nxt = others[index] if index < len(others) else None
        if prev is not None and nxt is not None and nxt.position - prev.position < MIN_POSITION_GAP:
            for i, other in enumerate(others):  # no room left between the neighbours
                other.position = float(i)
            result.renumbered = True
        if prev is None and nxt is None:
            position = 0.0
        elif prev is None:
            assert nxt is not None
            position = nxt.position - 1.0
        elif nxt is None:
            position = prev.position + 1.0
        else:
            position = (prev.position + nxt.position) / 2.0

        task.position = position
        result.changed.add("position")
