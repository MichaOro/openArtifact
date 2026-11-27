"""The number of a placement (ADR-082): the same action definition placed more than once in a pipeline is told apart as "Name #1", "#2", "#3".

A placement is an action node of a pipeline that runs a definition. Its number is **kept** in the node (``config["_number"]``, not a setting the
user sees): a new placement takes the **lowest free** number of its definition in that pipeline, a gap left by a deleted one is filled and the
others keep theirs. The number is shown only while the definition is placed more than once there; a single placement has none. It is a label
for people: references name a node by its id and never by its number.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

#: Where a placement keeps its number in the node's config.
KEY = "_number"


def lowest_free(taken: Iterable[Any]) -> int:
    """The smallest whole number from 1 that is not in ``taken``."""
    used = {n for n in taken if isinstance(n, int) and not isinstance(n, bool) and n >= 1}
    number = 1
    while number in used:
        number += 1
    return number


def numbers_of(nodes: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """The number of every placement that has one, by node id: the action nodes of ``nodes`` that run a definition that more than one of
    them runs. A node says its kept number as ``number``; one without it (or with a number another node has) gets the lowest free number,
    in the order of ``nodes``, so a pipeline from before numbers reads the same way every time."""
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for node in nodes:
        if node.get("kind") == "action" and node.get("definition_id"):
            groups[str(node["definition_id"])].append(node)
    result: dict[str, int] = {}
    for placed in groups.values():
        if len(placed) < 2:
            continue
        taken: set[int] = set()
        for node in placed:
            kept = node.get("number")
            if (
                isinstance(kept, int)
                and not isinstance(kept, bool)
                and kept >= 1
                and kept not in taken
            ):
                result[str(node["id"])] = kept
                taken.add(kept)
        for node in placed:
            if str(node["id"]) not in result:
                number = lowest_free(taken)
                result[str(node["id"])] = number
                taken.add(number)
    return result
