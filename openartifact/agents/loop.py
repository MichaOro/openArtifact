"""The turn loop of an agent node: ask the model, run the tools its answer calls, send the results back, ask again.

This is the engine of an agent node, apart from the node itself (``agents/runtime.py`` resolves the inputs and the prompts and hands
the engine a ``NodeResult``) and from the single request (``agents/completion.py``: time limits and retries). It is driven by the
two stand-ins the tests use (``complete`` and ``sleep``) and by a :class:`Budget`; it knows neither the event bus nor the database.

**The limits are a loose safety net, not the way an agent is held in check** (the guards judge its health, ADR-060). A limit that
is reached - the iterations, the time of the node, the token budget - or a run that makes no progress (:data:`STALL_AFTER` identical
calls with identical results in a row) does not fail the node: the agent gets **one more request without tools** to write its answer
from what it has found (:func:`_wrap_up`), and the step passes with a note that the answer may be incomplete. The same happens when
a request fails for good after tools have run (a model that could not answer a large prompt in time): the last request is made from
a much shorter conversation. Only when that request fails too, the node fails, and says so.

**What the model reads** is a view of the conversation (``agents/context_window.py``): a tool result is cut at the node's
*tool result* limit, older rounds are shortened, so the prompt does not grow by everything every tool returned. The step keeps the
full result (up to 16 KiB).

**A call made over and over** gets a note on its result for the model (:data:`REPEAT_HINT_AFTER` identical calls in a row). Whether
that is healthy (a web search of ten different pages is not a repetition, ten times the same file is) is the guard's to judge.

While it runs the loop tells what happens through ``signal(event, data)`` - ``tool_call`` (a call of a tool node started and ended)
and ``turn`` (a request started and ended, with the start of the answer text and the tokens) - names, counts and states, never
arguments or results.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openartifact.agents.client import Completion, Endpoint
from openartifact.agents.completion import Complete, Sleep, run_completion
from openartifact.agents.context_window import (
    WRAP_UP_OLDER_CHARS,
    WRAP_UP_RESULT_CHARS,
    fingerprint,
    shape_messages,
)
from openartifact.agents.schemas import TOOL_RESULT_DEFAULT
from openartifact.agents.tools import Toolbox
from openartifact.engine.context import NODE_OUTPUT_LIMIT_BYTES
from openartifact.engine.results import NodeResult, failed

#: What the loop tells while it runs: ``signal(event, data)``; the engine hands it on to the event bus.
Signal = Callable[[str, dict[str, Any]], None]

#: Identical calls (same tool, same arguments) in a row after which the result carries a note for the model.
REPEAT_HINT_AFTER = 3
#: Identical calls with identical results in a row after which the agent is asked to answer (no progress).
STALL_AFTER = 8
#: The most seconds one tool call may take (the time of the node, when less is left): a tool that does not answer becomes an error
#: text for the model, it does not hold the run until the time limit of the node.
TOOL_CALL_SECONDS = 300.0
#: What the final request may take beyond the time limit of the node (seconds, or the request timeout when that is less).
WRAP_UP_GRACE_SECONDS = 120.0
#: How much of the answer text a ``turn`` event carries.
EVENT_TEXT_CHARS = 300

WRAP_UP_PROMPT = (
    "You have reached {reason}. Do not call any tool now. Answer with what you have found so far, "
    "and say clearly what is still missing or uncertain."
)
FAILED_PROMPT = (
    "The last request could not be answered ({error}). Do not call any tool now. Answer with what you have found so far, "
    "and say clearly what is still missing or uncertain."
)
REPEAT_NOTE = (
    "Note: this is the same call with the same arguments as the {count} before; the result will be the same. "
    "Use what you have, or try something else."
)


def tools_used(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What each tool node was asked, from the turns of a run: ``[{"node": id, "name": ..., "calls": n, "errors": m}]`` in the order
    the nodes were first used. Calls of records without a tool node (before this was kept) are left out."""
    found: dict[str, dict[str, Any]] = {}
    for turn in turns:
        for call in turn.get("tool_calls") or []:
            node = str(call.get("node_id") or "")
            if not node:
                continue
            entry = found.setdefault(
                node, {"node": node, "name": call.get("node_name") or "", "calls": 0, "errors": 0}
            )
            entry["calls"] += 1
            entry["errors"] += 1 if call.get("error") else 0
    return list(found.values())


def summed(
    total: dict[str, int | None] | None, usage: dict[str, int | None]
) -> dict[str, int | None]:
    """Usage of all turns: a number the provider never sent stays ``None``."""
    if total is None:
        return dict(usage)
    return {
        key: None
        if total.get(key) is None and value is None
        else (total.get(key) or 0) + (value or 0)
        for key, value in usage.items()
    }


@dataclass
class Budget:
    """The limits of one node run. ``reason`` says which one is reached, in words for the note and the step."""

    total_seconds: float
    iterations: int
    tokens: int | None
    started: float

    def left(self) -> float:
        return self.total_seconds - (time.monotonic() - self.started)

    def reason(self, turns: int, tokens_used: int) -> str | None:
        """The limit that is reached after ``turns`` requests and ``tokens_used`` tokens, or ``None``."""
        if turns >= self.iterations:
            return f"the limit of {self.iterations} iterations"
        if self.left() <= 0:
            return f"the time limit of {self.total_seconds:g} s"
        if self.tokens is not None and tokens_used >= self.tokens:
            return f"the token budget of {self.tokens} tokens"
        return None


def _clip(text: str | None, size: int = EVENT_TEXT_CHARS) -> str:
    cleaned = " ".join((text or "").split())
    return cleaned if len(cleaned) <= size else cleaned[: size - 1].rstrip() + "…"


async def run_turns(
    started: float,
    endpoint: Endpoint,
    model: str,
    messages: list[dict[str, Any]],
    settings: dict[str, Any],
    box: Toolbox,
    data: dict[str, Any],
    detail: dict[str, Any],
    *,
    complete: Complete,
    sleep: Sleep,
    signal: Signal | None = None,
) -> NodeResult:
    """The turns of the node (see the module docstring). ``messages`` is the whole conversation and grows; ``detail`` and ``data``
    are filled for the step."""
    total = float(settings["total_timeout_seconds"])
    budget = Budget(
        total,
        int(settings["max_iterations"]) if box else 1,
        settings.get("token_budget"),
        started,
    )
    result_chars = int(settings.get("tool_result_chars") or TOOL_RESULT_DEFAULT)
    schemas = box.schemas() if box else None
    attempts: list[dict[str, Any]] = []
    hints: dict[str, str] = {}
    notes: list[str] = []
    state = {"last": None, "repeats": 0, "same_result": 0, "last_result": None}

    def tell(event: str, payload: dict[str, Any]) -> None:
        if signal is not None:
            signal(event, payload)

    def finish(result: NodeResult) -> NodeResult:
        detail["attempts"] = attempts
        detail["duration_ms"] = round((time.monotonic() - started) * 1000)
        data["attempts"] = len(attempts)
        data["iterations"] = len(detail["turns"])
        if used := tools_used(detail["turns"]):
            data["tools"] = (
                used  # the step says which tool nodes were used and how often (the flow shows their state)
            )
        result.duration = time.monotonic() - started
        return result

    def fail(reason: str) -> NodeResult:
        return finish(failed(reason, data=data, detail=detail))

    def used_tokens() -> int:
        return int((data["usage"] or {}).get("total_tokens") or 0)

    async def ask(
        view: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
        allowed: float,
        limit: float,
        wrap_up: str | None = None,
    ) -> Completion | None:
        """One request (one turn of the step); ``None`` when it failed, the error is in the turn."""
        number = len(detail["turns"]) + 1
        tell(
            "turn",
            {"state": "started", "turn": number, **({"wrap_up": wrap_up} if wrap_up else {})},
        )
        outcome = await run_completion(
            endpoint,
            model,
            view,
            temperature=settings["temperature"],
            max_tokens=settings["max_tokens"],
            request_timeout=settings["request_timeout_seconds"],
            total_timeout=max(allowed, 0.0),
            limit=limit,
            retries=settings["retries"],
            complete=complete,
            sleep=sleep,
            tools=tools,
        )
        turn: dict[str, Any] = {
            "attempts": [a.to_data() for a in outcome.attempts],
            "text": None,
            "finish_reason": None,
            "tool_calls": [],
        }
        if wrap_up:
            turn["wrap_up"] = wrap_up
        detail["turns"].append(turn)
        attempts.extend(turn["attempts"])
        if outcome.completion is None:
            data["status"] = outcome.http_status
            turn["error"] = outcome.error or "The request failed"
            tell("turn", {"state": "finished", "turn": number, "error": _clip(turn["error"], 200)})
            return None
        done = outcome.completion
        turn["text"], turn["finish_reason"] = done.text, done.finish_reason
        data["usage"] = detail["usage"] = summed(data["usage"], done.usage())
        data["finish_reason"] = detail["finish_reason"] = done.finish_reason
        tell(
            "turn",
            {
                "state": "finished",
                "turn": number,
                "text": _clip(done.text),
                "finish_reason": done.finish_reason,
                "tokens": done.usage().get("total_tokens"),
                "total_tokens": data["usage"].get("total_tokens") if data["usage"] else None,
                "tool_calls": len(done.tool_calls),
            },
        )
        return done

    async def wrap_up(reason: str, failure: str | None = None) -> NodeResult:
        """The final request without tools, from a shortened conversation: the agent answers from what it has found. ``reason`` is
        the limit that was reached; ``failure`` is the error of a request that could not be answered (then there is no limit)."""
        view = shape_messages(
            messages,
            result_chars=min(result_chars, WRAP_UP_RESULT_CHARS),
            older_chars=WRAP_UP_OLDER_CHARS,
            hints=None,
        )
        asked = (
            FAILED_PROMPT.format(error=_clip(failure, 200))
            if failure
            else WRAP_UP_PROMPT.format(reason=reason)
        )
        view.append({"role": "user", "content": asked})
        grace = min(float(settings["request_timeout_seconds"]), WRAP_UP_GRACE_SECONDS)
        allowed = max(budget.left(), grace)
        what = "a failed request" if failure else reason
        done = await ask(view, tools=None, allowed=allowed, limit=allowed, wrap_up=what)
        cause = (
            f"A request failed ({_clip(failure, 200)})"
            if failure
            else f"{reason[:1].upper()}{reason[1:]} was reached"
        )
        if done is None:
            last = detail["turns"][-1].get("error") or "the request failed"
            return fail(f"{cause}, and the final answer could not be written: {last}")
        if not done.text.strip():
            return fail(f"{cause}, and the model wrote no final answer")
        notes.append(
            f"{cause[:1].lower()}{cause[1:]}: this answer was written without tools from what the agent had found by then and may be incomplete"
        )
        return conclude(done)

    def conclude(done: Completion) -> NodeResult:
        if not done.text.strip():
            return fail(
                "The model returned no text"
                + (f" (finish reason: {done.finish_reason})" if done.finish_reason else "")
            )
        if done.finish_reason == "length":
            notes.append("the model stopped at its token limit, the answer may be incomplete")
        if len(done.text.encode("utf-8")) > NODE_OUTPUT_LIMIT_BYTES:
            notes.append(
                f"the answer is longer than the {NODE_OUTPUT_LIMIT_BYTES // 1024} KiB the run context "
                "keeps: later nodes read its beginning, the step keeps all of it"
            )
        return finish(
            NodeResult(
                "pass",
                output=done.text,
                reason=("Note: " + "; ".join(notes)) if notes else None,
                data=data,
                detail=detail,
            )
        )

    def watch(call_id: str, name: str, arguments: str, result: str) -> str | None:
        """Count a call that repeats; the reason when the run makes no progress."""
        key = fingerprint(name, arguments)
        if key == state["last"]:
            state["repeats"] += 1
            state["same_result"] = state["same_result"] + 1 if result == state["last_result"] else 0
        else:
            state.update(last=key, repeats=1, same_result=0)
        state["last_result"] = result
        if state["repeats"] >= REPEAT_HINT_AFTER:
            hints[call_id] = REPEAT_NOTE.format(count=state["repeats"] - 1)
        if state["same_result"] + 1 >= STALL_AFTER:
            return (
                f"no progress: the same call with the same result {state['repeats']} times in a row"
            )
        return None

    while True:
        done = await ask(
            shape_messages(messages, result_chars=result_chars, hints=hints),
            tools=schemas,
            allowed=budget.left(),
            limit=total,
        )
        if done is None:
            error = detail["turns"][-1]["error"]
            if any(t["tool_calls"] for t in detail["turns"][:-1]):
                # tools have run: do not lose what they found, write the answer from a shorter conversation
                return await wrap_up("a request that failed", failure=error)
            return fail(error)
        if not done.tool_calls:
            return conclude(done)
        if len(detail["turns"]) >= budget.iterations:
            return await wrap_up(
                budget.reason(len(detail["turns"]), used_tokens()) or "the iteration limit"
            )
        messages.append(
            {
                "role": "assistant",
                "content": done.text or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": c.arguments},
                    }
                    for c in done.tool_calls
                ],
            }
        )
        turn = detail["turns"][-1]
        stalled: str | None = None
        for call in done.tool_calls:
            node_id, node_name = box.node_of(call.name)
            number = len(detail["turns"])
            base = {
                "tool_node_id": node_id,
                "tool_node_name": node_name,
                "tool": call.name,
                "turn": number,
            }
            if node_id:
                tell("tool_call", {"state": "started", **base})
            record = await box.call_within(
                call.id, call.name, call.arguments, min(max(budget.left(), 0.0), TOOL_CALL_SECONDS)
            )
            if node_id:
                tell(
                    "tool_call",
                    {
                        "state": "finished",
                        **base,
                        "ok": not record.error,
                        "duration_ms": record.duration_ms,
                    },
                )
            turn["tool_calls"].append(record.to_data())
            messages.append({"role": "tool", "tool_call_id": call.id, "content": record.result})
            stalled = watch(call.id, call.name, call.arguments, record.result) or stalled
        reason = stalled or budget.reason(len(detail["turns"]), used_tokens())
        if reason:
            return await wrap_up(reason)
