"""The shapes of a comment on its way in and out."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from openartifact.schemas_common import UtcDateTime

#: A comment is at most 64 KiB of text (the same bound as the run context).
BODY_MAX_LENGTH = 64 * 1024
AUTHOR_MAX_LENGTH = 64
AUTHOR_KINDS = ("user", "api", "mcp", "run", "system")

Author = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=AUTHOR_MAX_LENGTH)
]


def _body(value: str) -> str:
    """The text as written (line breaks and indentation kept); only an empty one is refused."""
    if not value.strip():
        raise ValueError("A comment cannot be empty")
    return value.strip("\r\n").replace("\r\n", "\n")


class CommentWrite(BaseModel):
    """Payload for adding a comment.

    ``author`` is honoured only for the administrative (environment) token: a managed token always writes under its
    own name and the browser as "You".
    """

    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=BODY_MAX_LENGTH)
    author: Author | None = None

    _check_body = field_validator("body")(_body)


class CommentUpdate(BaseModel):
    """Payload for changing the text of a comment."""

    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=BODY_MAX_LENGTH)

    _check_body = field_validator("body")(_body)


class CommentRead(BaseModel):
    """A comment as the API shows it."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    task_id: str
    body: str
    author_kind: str
    author: str
    execution_id: str | None
    created_at: UtcDateTime
    updated_at: UtcDateTime
