"""What the model reads of the conversation of an agent node, as pure functions over the list of messages.

The node keeps the whole conversation (the prompts, what the model answered, every tool result up to the limit the step keeps,
16 KiB). Each request is made from a *view* of it, so the prompt does not grow from turn to turn by everything every tool ever
returned: a result is cut at ``result_chars`` for the model, and the results of the rounds before the last ``keep_rounds`` are
shortened to ``older_chars``. The step (the history of the run) always shows the full result, so nobody has to guess what the model
saw: the view is what it read, the step is what the tool returned.

A *round* is one answer of the model that called tools, with the results that followed it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: The rounds whose results the model still reads in full (up to the result limit); older ones are shortened.
KEEP_ROUNDS = 2
#: What remains of a result of an older round.
OLDER_RESULT_CHARS = 1500
#: The view for the final answer after a limit or a failed request: small, so the request can be answered at all.
WRAP_UP_RESULT_CHARS = 3000
WRAP_UP_OLDER_CHARS = 600


def _cut(content: str, keep: int, note: str) -> str:
    if len(content) <= keep:
        return content
    return (
        f"{content[:keep].rstrip()}\n[{note.format(rest=len(content) - keep, total=len(content))}]"
    )


def shape_messages(
    messages: list[dict[str, Any]],
    *,
    result_chars: int,
    older_chars: int = OLDER_RESULT_CHARS,
    keep_rounds: int = KEEP_ROUNDS,
    hints: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """The messages as the model reads them: tool results cut, older rounds shortened, a hint added to the results it is for
    (``hints`` by tool call id). Returns a new list; ``messages`` itself is not changed."""
    hints = hints or {}
    round_of: dict[int, int] = {}  # index of a tool message -> number of its round
    rounds = 0
    for index, message in enumerate(messages):
        if message.get("role") == "assistant" and message.get("tool_calls"):
            rounds += 1
        elif message.get("role") == "tool":
            round_of[index] = rounds
    shaped: list[dict[str, Any]] = []
    for index, message in enumerate(messages):
        if message.get("role") != "tool":
            shaped.append(message)
            continue
        content = str(message.get("content") or "")
        if rounds - round_of[index] >= keep_rounds:
            content = _cut(
                content,
                min(older_chars, result_chars),
                "shortened: an earlier result of {total} characters",
            )
        else:
            content = _cut(
                content,
                result_chars,
                "cut for the model: {rest} more characters; the step keeps the result as far as it is kept",
            )
        if hint := hints.get(str(message.get("tool_call_id"))):
            content = f"{content}\n[{hint}]"
        shaped.append({**message, "content": content})
    return shaped


def fingerprint(name: str, arguments: str) -> str:
    """What makes two calls the same: the tool and its arguments (the keys in any order, spaces ignored)."""
    import json

    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
        return f"{name}:{json.dumps(parsed, sort_keys=True, separators=(',', ':'), ensure_ascii=False)}"
    except ValueError:
        return f"{name}:{arguments.strip()}"
