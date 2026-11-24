"""The inputs of an agent that come from the artifact the run belongs to (ADR-064).

The definition of the agent says which part of the artifact an input is (title, body, title and body, number or
comments); the action's node cannot map it. The title, the body and the number come from the copy of the card the run
holds (``card`` of the context, taken when the run started); the comments are read when the node runs. Nothing of the
artifact reaches the model unless a prompt of the agent contains the matching ``${input.NAME}``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from openartifact.engine.artifact_runner import CommentsGateway, comment_blocks
from openartifact.engine.context import CONTEXT_LIMIT_BYTES, ContextError, RunView, card_text
from openartifact.exceptions import ArtifactError

NO_ARTIFACT = "this agent needs an artifact, but the run has none"

#: Example values of a preview and of the Quick test (not specific to anything).
SAMPLE_BODY = "This is the body of the example artifact."
ARTIFACT_SAMPLES: dict[str, str] = {
    "title": "Example artifact",
    "body": SAMPLE_BODY,
    "title_body": f"#1 Example artifact\n\n{SAMPLE_BODY}",
    "number": "1",
    "comments": (
        "You (user), 2026-01-01 09:00: First comment\n\nAlice (user), 2026-01-01 09:05: Second comment"
    ),
}


class ArtifactInputError(ValueError):
    """An input of the artifact cannot be filled (the message is the reason the node fails with)."""


def _card_part(card: Mapping[str, Any], part: str) -> str:
    if part == "title_body":
        return card_text(card)
    value = card.get(part)
    return "" if value is None else str(value)


def too_large(name: str, text: str) -> ArtifactInputError | None:
    size = len(text.encode("utf-8"))
    if size > CONTEXT_LIMIT_BYTES:
        return ArtifactInputError(
            f"input '{name}' is {size // 1024 + 1} KiB, and the limit for one input is "
            f"{CONTEXT_LIMIT_BYTES // 1024} KiB: shorten the artifact or use fewer comments"
        )
    return None


async def artifact_values(
    specs: Sequence[Mapping[str, Any]], view: RunView, comments: CommentsGateway | None
) -> dict[str, str]:
    """The value of every artifact input of ``specs`` (by name), read from the run's card and its comments.

    :class:`ArtifactInputError` when the run has no artifact, the comments cannot be read, or a value is too large
    (nothing is ever cut).
    """
    values: dict[str, str] = {}
    for spec in specs:
        if spec.get("source") != "artifact":
            continue
        name, part = str(spec["name"]), str(spec.get("part") or "title_body")
        if part == "comments":
            if not view.task_id:
                raise ArtifactInputError(NO_ARTIFACT)
            if comments is None:
                raise ArtifactInputError("Comments are not available here")
            try:
                values[name] = comment_blocks(await comments.comments(view.task_id, None))
            except (ContextError, ArtifactError) as error:
                raise ArtifactInputError(
                    f"input '{name}': {getattr(error, 'message', str(error))}"
                ) from error
        else:
            card = view.context.card
            if not view.task_id and "title" not in card:
                raise ArtifactInputError(NO_ARTIFACT)
            values[name] = _card_part(card, part)
        if (problem := too_large(name, values[name])) is not None:
            raise problem
    return values
