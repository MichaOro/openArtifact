"""The Artifact node (ADR-055): reads or writes the comments of the artifact the run belongs to, and of no other.

"Get comments" turns the newest comments into a readable transcript (the node output, at most the node's own limits) and
into ``data.comments`` (``author``, ``kind``, ``body``, ``at``); "Add comment" writes one under the node's name, marked as
written by a run, with the execution it came from. The artifact is never a setting: a node cannot reach another card.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from openartifact.comments.schemas import BODY_MAX_LENGTH, CommentRead
from openartifact.engine.context import NODE_OUTPUT_LIMIT_BYTES, ContextError, RunView
from openartifact.engine.results import NodeResult, failed
from openartifact.exceptions import ArtifactError

GET = "Get comments"
ADD = "Add comment"
CUT_MARK = "…[cut]"
#: The transcript stays under the node's output limit (4 KiB) with room for the cut mark.
TRANSCRIPT_BYTES = NODE_OUTPUT_LIMIT_BYTES - 96


class CommentsGateway(Protocol):
    """What the node needs of the comment service (a protocol: the service imports the engine)."""

    async def comments(self, ref: str, newest: int | None = None) -> list[CommentRead]: ...

    async def add(self, ref: str, body: str, author: Any) -> CommentRead: ...


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - len(CUT_MARK), 0)] + CUT_MARK


def _at(comment: CommentRead) -> str:
    return comment.created_at.strftime("%Y-%m-%d %H:%M")


def comment_blocks(comments: list[CommentRead]) -> str:
    """All the comments, oldest first, one block each: ``<author> (<kind>), <date time>: <text>`` (an agent's input
    of the part Comments, ADR-064); no limit of its own, the caller refuses a text that is too large."""
    return "\n\n".join(
        f"{c.author} ({c.author_kind}), {_at(c)}: {c.body.strip()}" for c in comments
    )


def transcript(
    comments: list[CommentRead], max_chars: int, max_total: int
) -> tuple[str, list[dict[str, str]], int]:
    """The newest comments that fit, as text and as data (oldest first), and how many older ones were left out.

    Every body is cut to ``max_chars``; the transcript (headers included) is at most ``max_total`` characters and
    ``TRANSCRIPT_BYTES`` bytes, and the newest comment is kept before an older one.
    """
    blocks: list[tuple[str, dict[str, str]]] = []
    used = 0
    for comment in reversed(comments):
        body = _cut(comment.body.strip(), max_chars)
        block = f"[{_at(comment)}] {comment.author} ({comment.author_kind}):\n{body}"
        size = len(block) + 2
        if blocks and (used + size > max_total or len((block).encode()) + used > TRANSCRIPT_BYTES):
            break
        if not blocks and size > max_total:
            block = _cut(block, max_total)
        blocks.append(
            (
                block,
                {
                    "author": comment.author,
                    "kind": comment.author_kind,
                    "body": body,
                    "at": comment.created_at.isoformat(),
                },
            )
        )
        used += size
    blocks.reverse()
    text = "\n\n".join(b for b, _ in blocks)
    raw = text.encode()
    if len(raw) > TRANSCRIPT_BYTES:
        text = raw[:TRANSCRIPT_BYTES].decode("utf-8", errors="ignore") + CUT_MARK
    return text, [d for _, d in blocks], len(comments) - len(blocks)


async def run_artifact(
    config: Mapping[str, Any],
    *,
    node_name: str,
    view: RunView,
    gateway: CommentsGateway | None,
    author_factory: Any,
) -> NodeResult:
    """Do what the node's operation says on the comments of the run's own artifact."""
    if gateway is None or not view.task_id:
        return failed("Comments are not available here")
    operation = str(config.get("operation") or GET)
    try:
        if operation == ADD:
            text = view.render(str(config.get("text") or "")).strip("\r\n")
            if not text.strip():
                return failed("The comment is empty")
            if len(text) > BODY_MAX_LENGTH:
                return failed(f"The comment is too long (at most {BODY_MAX_LENGTH} characters)")
            made = await gateway.add(
                view.task_id, text, author_factory("run", node_name, view.execution_id)
            )
            return NodeResult("pass", output=f"Comment added as {node_name}", data={"id": made.id})
        if operation != GET:
            return failed(f"Unknown operation: {operation[:60]}")
        limit = int(config.get("limit") or 20)
        found = await gateway.comments(view.task_id, limit)
    except ContextError as error:
        return failed(str(error))
    except ArtifactError as error:
        return failed(error.message)
    text, data, left_out = transcript(
        found, int(config.get("max_chars") or 800), int(config.get("max_total") or 3500)
    )
    note = (
        f"({left_out} older comment{'s' if left_out != 1 else ''} left out)\n" if left_out else ""
    )
    return NodeResult(
        "pass",
        output=(note + text) if found else "No comments yet",
        data={"comments": data, "count": len(data), "left_out": left_out},
    )
