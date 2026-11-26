"""What an execution node returns: the outcome and the text, numbers and data behind it.

The **result contract** (ADR-072): whatever the kind, the run context holds for every node that ran the same core, so a later node can ask
any of them the same questions: ``success`` (true when the outcome is ``pass``: the engine sets it, a kind does not have to), ``outcome``
(``pass`` or ``fail``), ``reason``, ``output``, ``data`` (the extras of the kind), ``attempts`` (how many tries it took, 1 without *Retry
on fail*) and ``duration_ms`` (wall time of the step, waits between tries included). ``exit_code`` stays where a kind has one.
"""

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
    #: What only the step shows (an agent's prompts and attempts): stored with the step, never copied
    #: into the run context.
    detail: dict[str, Any] | None = None
    #: How many tries the node took (*Retry on fail*, ADR-072): the engine sets it; 1 for a node that ran once.
    attempts: int = 1
    #: Wall time of the step in milliseconds, all tries and the waits between them: the engine measures it (a kind need not).
    duration_ms: int | None = None
    #: How many bytes of ``output`` the run context keeps for later nodes (the step keeps all); ``None``: the context's own limit for a node
    #: (4 KiB). The Build Context node asks for the size of its package (ADR-078).
    keep_bytes: int | None = None

    @property
    def success(self) -> bool:
        """The node succeeded: the one boolean a later node asks (``${(Node).success}``); derived from ``outcome``, never set apart."""
        return self.outcome == "pass"

    def __post_init__(self) -> None:
        if self.reason is not None:
            self.reason = self.reason[:REASON_MAX_CHARS]


def failed(reason: str, **extra: Any) -> NodeResult:
    """A failed result with a reason (a node that could not even start)."""
    return NodeResult("fail", reason=reason, **extra)
