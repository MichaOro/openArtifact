"""Async repository layer.

Repositories encapsulate all database access for a single aggregate.
They receive an ``AsyncSession`` from the service layer — they never create
their own engine or session.

This keeps the HTTP layer (API routes) free of SQL concerns and the
business logic (services) free of persistence details.
"""

from __future__ import annotations

from openartifact.repositories.project_repository import ProjectRepository
from openartifact.repositories.work_item_repository import WorkItemRepository

__all__ = ["ProjectRepository", "WorkItemRepository"]
