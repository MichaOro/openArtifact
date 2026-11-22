"""What an execution node returns: the outcome and the text, numbers and data behind it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

#: Longest ``reason`` kept; reasons are text for people, never the input of anything.
REASON_MAX_CHARS = 1000


@dataclass
class NodeResult:
    """The result of one execution node: ``outcome`` is the port it leaves by (On Pass / On Fail)."""

    outcome: Literal["pass", "fail"]
    exit_code: int | None = None
    output: str = ""
    reason: str | None = None
    data: dict[str, Any] | None = None
    duration: float = 0.0
    #: Variables the node sets in the run context (a Code node's ``"vars"``); only a passing node's count.
    variables: dict[str, Any] | None = None
    #: The output the node leaves by, for kinds that choose it themselves (If, Switch); ``None``: by outcome.
    port: str | None = None

    def __post_init__(self) -> None:
        if self.reason is not None:
            self.reason = self.reason[:REASON_MAX_CHARS]


def failed(reason: str, **extra: Any) -> NodeResult:
    """A failed result with a reason (a node that could not even start)."""
    return NodeResult("fail", reason=reason, **extra)
