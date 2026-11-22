"""The rule that decides which pipeline, stage and action a task update asks for (no database)."""

from __future__ import annotations

from typing import Any

import pytest

from openartifact.models import Task
from openartifact.tasks.schemas import TaskUpdate
from openartifact.tasks.service import requested_target

CURRENT = Task(pipeline_id="p1", stage_id="s1", action_id="a1")


def _target(**sent: Any) -> tuple[str | None, str | None, str | None]:
    return requested_target(CURRENT, TaskUpdate(**sent))


def test_a_field_that_is_not_sent_keeps_the_tasks_value() -> None:
    assert _target(action_id="a2") == ("p1", "s1", "a2")


def test_a_new_pipeline_resets_stage_and_action() -> None:
    assert _target(pipeline_id="p2") == ("p2", None, None)


def test_the_same_pipeline_changes_nothing_else() -> None:
    assert _target(pipeline_id="p1") == ("p1", "s1", "a1")


def test_a_new_stage_resets_the_action() -> None:
    assert _target(stage_id="s2") == ("p1", "s2", None)


def test_what_is_sent_wins_over_the_reset() -> None:
    assert _target(pipeline_id="p2", stage_id="s9", action_id="a9") == ("p2", "s9", "a9")


def test_a_null_pipeline_clears_all_three() -> None:
    assert _target(pipeline_id=None) == (None, None, None)


@pytest.mark.parametrize("sent", [{"stage_id": None}, {"action_id": None}])
def test_a_null_stage_or_action_is_asked_for_as_null(sent: dict[str, Any]) -> None:
    pipeline, stage, action = _target(**sent)
    assert pipeline == "p1"
    assert (stage, action) == ((None, None) if "stage_id" in sent else ("s1", None))
