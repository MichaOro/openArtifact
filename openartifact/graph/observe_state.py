"""The observe mode at run time (``graph/observe.py`` holds the setting): who is observed, when an observation ends, and what the owner decides then (ADR-088).

The setting (``graph/observe.py``) lives in the published version of a pipeline. What changes while it is observed lives here, in
``graphs.observe_state`` outside every version: the runs counted, the day it began, a release, a renewal and a short record of those decisions.
A new publication that changes the setting starts a new observation.

The rules, in one place:

* A run that starts at a pipeline whose published version has the mode on is an **observed run**: a dry run (ADR-086) that nobody asked for by hand.
* The observation **ends** after the days or the runs of the setting. From then on every start is refused (409, ``observation_ended``) until the owner
  decides: *observe again* (a new limit, counted from now) or *release* (the pipeline runs for real, until a publication changes the mode).
* A pipeline that another one calls follows the outer run; its own mode is not read then (``admit`` is asked at the start of the outermost run only).
* A manual dry run is never refused for an ended observation and is not counted: it changes nothing.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.exceptions import ArtifactError
from openartifact.graph.observe import describe, of_content
from openartifact.graph.versions import current_version
from openartifact.models import Graph

logger = logging.getLogger(__name__)

CODE = "observation_ended"
KEPT_EVENTS = 20


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _parse(text: Any) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


async def published_setting(session: AsyncSession, graph: Graph) -> dict[str, Any] | None:
    """The observe mode of the version that runs, ``None`` while it is off or nothing is published (a draft is never observed)."""
    version = await current_version(session, graph)
    return of_content(json.loads(version.content)) if version else None


def _event(state: dict[str, Any], action: str, by: str, note: str = "") -> None:
    events = list(state.get("events") or [])
    events.append({"at": _iso(_now()), "action": action, "by": by, "note": note})
    state["events"] = events[-KEPT_EVENTS:]


def _fresh(setting: dict[str, Any], events: list[Any] | None = None) -> dict[str, Any]:
    return {
        "setting": setting,
        "started_at": _iso(_now()),
        "runs": 0,
        "released": False,
        "limits": None,
        "events": list(events or []),
    }


async def on_publication(session: AsyncSession, graph: Graph, via: str) -> None:
    """Called when a version was published: a changed mode starts a new observation (counters from zero, a release forgotten); the same
    mode in a later version leaves the observation as it is (editing a node does not restart the clock)."""
    setting = await published_setting(session, graph)
    state = dict(graph.observe_state or {})
    if setting is None:
        if state:
            events = state.get("events") or []
            graph.observe_state = {"events": events[-KEPT_EVENTS:]} if events else None
            if graph.observe_state is not None:
                _event(graph.observe_state, "off", via, "published without the observe mode")
        return
    if state.get("setting") == setting:
        return
    fresh = _fresh(setting, state.get("events"))
    _event(fresh, "on", via, f"published: observe mode {describe(setting)}")
    graph.observe_state = fresh


def limits_of(setting: dict[str, Any], state: dict[str, Any]) -> tuple[int | None, int | None]:
    """The days and the runs that count now: the owner's renewal if there is one, else the setting's."""
    own = state.get("limits")
    if isinstance(own, dict):
        return own.get("days"), own.get("runs")
    return setting.get("days"), setting.get("runs")


def status_of(
    graph: Graph, setting: dict[str, Any] | None, now: datetime | None = None
) -> dict[str, Any]:
    """The state of the observation of a pipeline, for the API (everything a person or a remote tool needs to decide)."""
    now = now or _now()
    state = graph.observe_state or {}
    out: dict[str, Any] = {
        "enabled": setting is not None,
        "observing": False,
        "ended": False,
        "released": False,
        "days": None,
        "runs": None,
        "runs_done": 0,
        "started_at": None,
        "ends_at": None,
        "reason": None,
        "events": list(state.get("events") or []),
    }
    if setting is None:
        return out
    days, runs = limits_of(setting, state)
    started = _parse(state.get("started_at"))
    done = int(state.get("runs") or 0)
    out.update(days=days, runs=runs, runs_done=done, started_at=state.get("started_at"))
    if started and days:
        out["ends_at"] = _iso(started + timedelta(days=days))
    if state.get("released"):
        out["released"] = True
        return out
    why = None
    if runs and done >= runs:
        why = f"{done} of {runs} runs were observed"
    elif started and days and now >= started + timedelta(days=days):
        why = f"the {days} days are over (since {started:%Y-%m-%d})"
    if why:
        out["ended"] = True
        out["reason"] = (
            f"Observation of the pipeline '{graph.name}' has ended: {why}. "
            "Decide: observe it again or release it to run for real."
        )
    else:
        out["observing"] = True
    return out


async def admit(session: AsyncSession, graph: Graph) -> bool:
    """Decide for a run that starts at this pipeline (not a manual dry run): ``True`` when it is observed (and counted), ``False`` when the
    pipeline runs for real; raises :class:`ArtifactError` (409, ``observation_ended``) while an ended observation waits for the owner."""
    setting = await published_setting(session, graph)
    if setting is None:
        return False
    state = dict(graph.observe_state or {})
    if state.get("setting") != setting or not state.get("started_at"):
        fresh = _fresh(setting, state.get("events"))
        graph.observe_state = state = (
            fresh  # a version from before the state existed: it counts from this run
        )
    found = status_of(graph, setting)
    if found["released"]:
        return False
    if found["ended"]:
        raise ArtifactError(409, str(found["reason"]), CODE)
    graph.observe_state = {**state, "runs": int(state.get("runs") or 0) + 1}
    return True


async def release(session: AsyncSession, graph: Graph, by: str) -> dict[str, Any]:
    """Release the pipeline: it runs for real from now on, whatever the published mode says, until a publication changes the mode. Immediate
    and recorded; works whether the observation has ended or not. 409 when the pipeline is not observed."""
    setting = await published_setting(session, graph)
    if setting is None:
        raise ArtifactError(409, "The pipeline is not observed: there is nothing to release")
    state = dict(graph.observe_state or {})
    if state.get("setting") != setting:
        state = _fresh(setting, state.get("events"))
    if state.get("released"):
        raise ArtifactError(409, "The pipeline is released already")
    state["released"] = True
    _event(state, "release", by, "the pipeline runs for real")
    graph.observe_state = state
    logger.info("Observe mode of pipeline %s released by %s", graph.id, by)
    return status_of(graph, setting)


async def observe_again(
    session: AsyncSession, graph: Graph, by: str, days: int | None, runs: int | None
) -> dict[str, Any]:
    """Observe again from now: the counters start from zero, a release is taken back, the limit is the one given (or the setting's when none is
    given). Immediate and recorded. 409 when no published version has the mode on (that takes a publication: the publish check names it)."""
    setting = await published_setting(session, graph)
    if setting is None:
        raise ArtifactError(
            409,
            "The published version has no observe mode: switch it on in the draft and publish",
        )
    state = _fresh(setting, (graph.observe_state or {}).get("events"))
    if days is not None or runs is not None:
        state["limits"] = {"days": days, "runs": runs}
    shown_days, shown_runs = limits_of(setting, state)
    _event(
        state,
        "again",
        by,
        f"observed again, {describe({'enabled': True, 'days': shown_days, 'runs': shown_runs})}",
    )
    graph.observe_state = state
    logger.info("Observe mode of pipeline %s started again by %s", graph.id, by)
    return status_of(graph, setting)
