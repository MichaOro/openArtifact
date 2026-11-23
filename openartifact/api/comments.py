"""Comment routes (ADR-055): the same four operations for the browser (``/api/tasks/{ref}/comments``) and the
integration API (``/api/v1/artifacts/{ref}/comments``). Only the channel differs: it decides, together with the
token, who the author is (``comments.service.author_of``)."""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Response, status

from openartifact.api.contract import errors
from openartifact.api.deps import CommentsDep
from openartifact.comments.schemas import CommentRead, CommentUpdate, CommentWrite
from openartifact.comments.service import author_of

LIST_DESCRIPTION = (
    "The comments of the artifact, oldest first. A comment is plain text; ``author_kind`` is ``user`` (the browser), "
    "``api``, ``mcp``, ``run`` (a pipeline node, with its ``execution_id``) or ``system``, ``author`` the name."
)
ADD_DESCRIPTION = (
    "Add a comment (plain text, 1 to 65536 characters, line breaks are kept). It is written under the name of the "
    "managed token that made the request and cannot be changed by the caller; only the administrative token may pass "
    "``author`` (1 to 64 characters), else the author is the channel's name. Publishes ``comment.created``."
)


def build_comments_router(prefix: str, channel: str, tags: list[str | Enum]) -> APIRouter:
    """The comment routes under ``prefix`` (``{ref}``: the id or the number of the artifact) for a channel (``user``,
    ``api``)."""
    router = APIRouter(prefix=prefix, tags=tags)

    @router.get(
        "/{ref}/comments",
        response_model=list[CommentRead],
        summary="List the comments of an artifact",
        description=LIST_DESCRIPTION,
        responses=errors(404, 422),
    )
    async def list_comments(ref: str, service: CommentsDep) -> list[CommentRead]:
        return await service.comments(ref)

    @router.post(
        "/{ref}/comments",
        response_model=CommentRead,
        status_code=status.HTTP_201_CREATED,
        summary="Add a comment to an artifact",
        description=ADD_DESCRIPTION,
        responses=errors(404, 422, write=True, body=True),
    )
    async def add_comment(ref: str, payload: CommentWrite, service: CommentsDep) -> CommentRead:
        return await service.add(ref, payload.body, author_of(channel, payload.author))

    @router.patch(
        "/{ref}/comments/{comment_id}",
        response_model=CommentRead,
        summary="Change the text of a comment",
        responses=errors(404, 422, write=True, body=True),
    )
    async def update_comment(
        ref: str, comment_id: str, payload: CommentUpdate, service: CommentsDep
    ) -> CommentRead:
        """Replace the text; ``updated_at`` then differs from ``created_at`` (the UI says "edited"). Any comment may be
        changed. Publishes ``comment.updated``."""
        return await service.update(ref, comment_id, payload.body)

    @router.delete(
        "/{ref}/comments/{comment_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        summary="Delete a comment",
        responses=errors(404, 422, write=True),
    )
    async def delete_comment(ref: str, comment_id: str, service: CommentsDep) -> Response:
        """Delete a comment. Publishes ``comment.deleted``."""
        await service.delete(ref, comment_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
