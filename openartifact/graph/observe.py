"""The observe mode of a pipeline: the setting that goes live with a published version (ADR-088).

The setting is kept in the config of the pipeline's Trigger under a key with a leading underscore (like the mock, ADR-087, and the placement number,
ADR-082: it is no setting of the node and never appears in its form), and ``graph_of`` carries it as ``observe`` on the graph, so it is part of
every published version and of its fingerprint: observing starts and ends with a publication, with the consent the publish check asks for.
"""

from __future__ import annotations

from typing import Any

OBSERVE_KEY = "_observe"

MAX_DAYS = 365
MAX_RUNS = 100_000
_KEYS = {"enabled", "days", "runs"}


class ObserveError(ValueError):
    """The observe setting is not acceptable (the message says why, in plain words)."""


def _limit(value: Any, name: str, top: int) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObserveError(f"The limit in {name} is a whole number")
    if not 1 <= value <= top:
        raise ObserveError(f"The limit in {name} is between 1 and {top}")
    return value


def clean_observe(value: Any) -> dict[str, Any]:
    """The setting as it is stored: ``{"enabled": bool, "days": int | None, "runs": int | None}``; raises :class:`ObserveError`."""
    if not isinstance(value, dict):
        raise ObserveError("The observe mode is an object with enabled, days and runs")
    for key in value:
        if key not in _KEYS:
            raise ObserveError(f"The observe mode has no field '{key}'")
    enabled = value.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ObserveError("enabled is true or false")
    return {
        "enabled": enabled,
        "days": _limit(value.get("days"), "days", MAX_DAYS),
        "runs": _limit(value.get("runs"), "runs", MAX_RUNS),
    }


def stored_observe(trigger_config: dict[str, Any] | None) -> dict[str, Any] | None:
    """The setting held in a Trigger's config, or ``None`` when there is none."""
    found = (trigger_config or {}).get(OBSERVE_KEY)
    if not isinstance(found, dict):
        return None
    return {
        "enabled": bool(found.get("enabled")),
        "days": found.get("days"),
        "runs": found.get("runs"),
    }


def of_content(content: dict[str, Any] | None) -> dict[str, Any] | None:
    """The observe setting of a graph as ``graph_of`` or a published version holds it (``None``: the graph does not observe)."""
    found = (content or {}).get("observe")
    return found if isinstance(found, dict) and found.get("enabled") is True else None


def describe(setting: dict[str, Any] | None) -> str:
    """The setting in a few words, for the publish check and the log."""
    if not setting or not setting.get("enabled"):
        return "off"
    limits = []
    if setting.get("days"):
        limits.append(f"{setting['days']} days")
    if setting.get("runs"):
        limits.append(f"{setting['runs']} runs")
    return "on" + (f" for {' and '.join(limits)}" if limits else " until it is switched off")
