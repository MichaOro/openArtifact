"""The board tools of the MCP server (ADR-079): the tools to tidy up, read and change many cards, and their rules."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from openartifact.api.board_tools import BOARD_TOOLS, BULK_MAX, READ_TOOLS, WRITE_TOOLS
from tests.helpers import slow_pipeline
from tests.test_integration import _content, _create, _mcp, _text, _tool, api  # noqa: F401


def _lane(client: TestClient, number: int) -> str:
    return str(client.get(f"/api/v1/artifacts/{number}").json()["status"])


def _ok(result: dict[str, Any]) -> Any:
    assert not result.get("isError"), result
    return _content(result)


def _parents(client: TestClient) -> dict[int, int | None]:
    return {c["number"]: c["parent"] for c in _content(_tool(client, "list_artifacts", brief=True))}


def _by_number(answer: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {r["artifact"]: r for r in answer["results"]}


def test_the_server_offers_every_board_tool_and_none_that_deletes(api: TestClient) -> None:  # noqa: F811
    names = {t["name"] for t in _mcp(api, "tools/list")["result"]["tools"]}
    assert set(BOARD_TOOLS) <= names
    assert set(READ_TOOLS).isdisjoint(WRITE_TOOLS)
    assert not [n for n in names if any(word in n for word in ("delete", "remove", "purge"))]


def test_a_card_is_archived_and_taken_out_again_with_the_reason_of_a_refusal(
    api: TestClient,  # noqa: F811
) -> None:
    _create(api, title="Old", status="in_progress")
    archived = _ok(_tool(api, "archive_artifact", artifact="#1"))
    assert archived["archived_at"] is not None and archived["archived_from_status"] == "in_progress"
    assert _content(_tool(api, "list_artifacts")) == []
    assert [c["number"] for c in _content(_tool(api, "list_artifacts", archived="only"))] == [1]

    twice = _tool(api, "archive_artifact", artifact="1")
    assert twice["isError"] and "archived" in _text(twice)

    back = _ok(_tool(api, "unarchive_artifact", artifact="1"))
    assert back["archived_at"] is None and back["status"] == "in_progress"
    again = _tool(api, "unarchive_artifact", artifact="1")
    assert again["isError"] and "not archived" in _text(again)


def test_a_card_that_is_processed_is_not_archived(api: TestClient) -> None:  # noqa: F811
    slow_pipeline(api)
    _tool(api, "create_artifact", title="Item", pipeline="Flow")
    _tool(api, "start_processing", artifact="1")
    refused = _tool(api, "archive_artifact", artifact="1")
    assert refused["isError"] and "being processed" in _text(refused)
    assert _content(_tool(api, "get_artifact", artifact="1"))["processing"] is True


def test_cards_are_moved_in_one_call_and_each_says_why_it_was_refused(
    api: TestClient,  # noqa: F811
) -> None:
    slow_pipeline(api)
    for title in ("A", "B", "C"):
        _create(api, title=title, status="backlog")
    _tool(api, "create_artifact", title="D", pipeline="Flow")
    _tool(api, "archive_artifact", artifact="2")
    _tool(api, "start_processing", artifact="4")

    answer = _ok(
        _tool(api, "move_artifacts", artifacts=["1", "#2", "3", "4", "9", "3"], lane="done")
    )
    first = {r["artifact"]: r for r in answer["results"][:5]}
    assert first[1]["ok"] and first[3]["ok"]
    assert first[2]["ok"] is False and "archived" in first[2]["reason"]
    assert first[4]["ok"] is False and "being processed" in first[4]["reason"]
    assert first["9"]["ok"] is False and "not found" in first["9"]["reason"].lower()
    assert answer["results"][5] == {
        "artifact": 3,
        "ok": False,
        "reason": "named twice in this call",
    }
    assert (answer["ok"], answer["failed"]) == (2, 4)
    assert (_lane(api, 1), _lane(api, 3), _lane(api, 4)) == ("done", "done", "backlog")


def test_a_dry_run_says_what_would_happen_and_changes_nothing(api: TestClient) -> None:  # noqa: F811
    _create(api, title="A", status="backlog")
    _create(api, title="B", status="backlog")
    _tool(api, "archive_artifact", artifact="2")
    moved = _ok(_tool(api, "move_artifacts", artifacts=["1", "2"], lane="done", dry_run=True))
    assert moved["dry_run"] is True and (moved["ok"], moved["failed"]) == (1, 1)
    archived = _ok(_tool(api, "archive_artifacts", artifacts=["1", "2"], dry_run=True))
    assert _by_number(archived)[2]["ok"] is False
    assert _lane(api, 1) == "backlog"
    assert _content(_tool(api, "list_artifacts", brief=True))[0]["archived"] is False


def test_a_bulk_call_has_a_cap_and_a_known_lane(api: TestClient) -> None:  # noqa: F811
    _create(api, title="A")
    too_many = _tool(api, "archive_artifacts", artifacts=[str(n) for n in range(BULK_MAX + 1)])
    assert too_many["isError"] and f"At most {BULK_MAX} cards" in _text(too_many)
    empty = _tool(api, "move_artifacts", artifacts=[], lane="done")
    assert empty["isError"] and "at least one card" in _text(empty)
    unknown = _tool(api, "move_artifacts", artifacts=["1"], lane="sideways")
    assert unknown["isError"] and "Unknown lane 'sideways'. Available: " in _text(unknown)
    assert _lane(api, 1) == "backlog"


def test_cards_are_archived_in_one_call(api: TestClient) -> None:  # noqa: F811
    for title in ("A", "B"):
        _create(api, title=title)
    answer = _ok(_tool(api, "archive_artifacts", artifacts=["1", "2", "7"]))
    assert (answer["ok"], answer["failed"]) == (2, 1)
    assert [c["number"] for c in _content(_tool(api, "list_artifacts", archived="only"))] == [2, 1]
    again = _ok(_tool(api, "archive_artifacts", artifacts=["1"]))
    assert (
        again["results"][0]["ok"] is False
        and "already in the archive" in again["results"][0]["reason"]
    )


def test_the_list_pages_filters_and_can_be_brief(api: TestClient) -> None:  # noqa: F811
    parent = _create(api, title="Epic", status="backlog")
    for index in range(3):
        _create(api, title=f"Story {index}", status="in_progress", parent_id=parent["id"])
    _tool(api, "archive_artifact", artifact="4")

    brief = _content(_tool(api, "list_artifacts", brief=True))
    assert sorted(c["number"] for c in brief) == [1, 2, 3]
    brief = sorted(brief, key=lambda c: c["number"])
    assert set(brief[1]) == {
        "number",
        "title",
        "lane",
        "parent",
        "archived",
        "archived_at",
        "created_at",
        "updated_at",
        "processing",
    }
    assert (brief[1]["lane"], brief[1]["parent"], brief[0]["parent"]) == ("in_progress", 1, None)
    children = _content(_tool(api, "list_artifacts", parent="#1", brief=True))
    assert sorted(c["number"] for c in children) == [2, 3]
    whole = _content(_tool(api, "list_artifacts", brief=True))
    page = _content(_tool(api, "list_artifacts", limit=1, offset=1, brief=True))
    assert page == whole[1:2]
    everything = _content(_tool(api, "list_artifacts", archived="include", brief=True))
    assert {c["number"]: c["archived"] for c in everything} == {
        1: False,
        2: False,
        3: False,
        4: True,
    }
    assert _content(_tool(api, "count_artifacts")) == {
        "total": 3,
        "lane": None,
        "archived": "exclude",
    }
    assert (
        _content(_tool(api, "count_artifacts", lane="in_progress", archived="include"))["total"]
        == 3
    )
    assert _content(_tool(api, "count_artifacts", archived="only"))["total"] == 1
    bad = _tool(api, "list_artifacts", limit=0)
    assert bad["isError"] and "limit must be 1 to 500" in _text(bad)


def test_cards_are_found_by_title_text_and_number(api: TestClient) -> None:  # noqa: F811
    _create(api, title="Notaus", body="a switch for everything")
    _create(api, title="Other", body="the NOTAUS is described elsewhere in this long text")
    _create(api, title="Unrelated")
    found = _content(_tool(api, "search_artifacts", query="notaus"))
    assert [(c["number"], c["match"]) for c in found] == [(1, "title"), (2, "body")]
    assert "NOTAUS is described" in found[1]["snippet"] and "snippet" not in found[0]
    assert [c["match"] for c in _content(_tool(api, "search_artifacts", query="#3"))] == ["number"]
    short = _tool(api, "search_artifacts", query="n")
    assert short["isError"] and "at least 2 characters" in _text(short)
    _tool(api, "archive_artifact", artifact="1")
    assert [c["number"] for c in _content(_tool(api, "search_artifacts", query="notaus"))] == [2]
    assert [
        c["number"]
        for c in _content(_tool(api, "search_artifacts", query="notaus", archived="include"))
    ] == [1, 2]


def test_several_cards_are_read_at_once_with_their_comments(api: TestClient) -> None:  # noqa: F811
    _create(api, title="Long", body="x" * 500)
    parent = _create(api, title="Epic")
    _create(api, title="Child", parent_id=parent["id"])
    for text in ("one", "two", "three"):
        _tool(api, "add_comment", artifact="1", text=text)

    read = _content(
        _tool(
            api,
            "get_artifacts",
            artifacts=["1", "#3", "99"],
            with_comments=True,
            comments_limit=2,
            body_chars=100,
        )
    )
    assert [r.get("number") for r in read] == [1, 3, None]
    assert [c["body"] for c in read[0]["comments"]] == ["two", "three"]
    assert len(read[0]["body"]) == 100 and read[0]["body_truncated"] is True
    assert read[1]["parent"] == 2 and read[0]["parent"] is None and read[1]["comments"] == []
    assert read[2]["artifact"] == "99" and "not found" in read[2]["error"].lower()
    plain = _content(_tool(api, "get_artifacts", artifacts=["1"]))
    assert len(plain[0]["body"]) == 500 and "comments" not in plain[0]
    too_many = _tool(api, "get_artifacts", artifacts=[str(n) for n in range(21)])
    assert too_many["isError"] and "At most 20 cards" in _text(too_many)


def test_parents_are_set_and_taken_away_for_many_cards(api: TestClient) -> None:  # noqa: F811
    for title in ("Epic", "A", "B"):
        _create(api, title=title)
    done = _ok(_tool(api, "set_parent", artifacts=["2", "3"], parent="#1"))
    assert (done["ok"], done["failed"]) == (2, 0)
    assert _parents(api) == {1: None, 2: 1, 3: 1}
    assert _by_number(done)[2]["parent"] == 1

    cycle = _ok(_tool(api, "set_parent", artifacts=["1", "2"], parent="3"))
    results = _by_number(cycle)
    assert results[1]["ok"] is False and "own ancestor" in results[1]["reason"]
    assert results[2]["ok"] is True  # a sibling may become a child of its sibling
    own = _by_number(_ok(_tool(api, "set_parent", artifacts=["1"], parent="1")))
    assert own[1]["reason"] == "A card cannot be its own parent"

    cleared = _ok(_tool(api, "set_parent", artifacts=["2", "3"]))
    assert (cleared["ok"], cleared["failed"]) == (2, 0)
    assert _parents(api) == {1: None, 2: None, 3: None}
    dry = _ok(_tool(api, "set_parent", artifacts=["2"], parent="1", dry_run=True))
    assert dry["ok"] == 1 and _content(_tool(api, "get_artifact", artifact="2"))["parent"] is None


def test_field_values_are_set_on_many_cards_and_a_value_that_does_not_fit_is_named(
    api: TestClient,  # noqa: F811
) -> None:
    api.put(
        "/api/artifact-fields",
        json={"fields": [{"name": "points", "label": "Points", "kind": "number"}]},
    ).raise_for_status()
    _create(api, title="A")
    _create(api, title="B")
    done = _ok(_tool(api, "set_fields", artifacts=["1", "2"], fields={"points": 5}))
    assert (done["ok"], done["failed"]) == (2, 0)
    assert _content(_tool(api, "get_artifact", artifact="2"))["fields"]["points"] == 5

    wrong = _ok(_tool(api, "set_fields", artifacts=["1"], fields={"points": "many"}))
    assert wrong["failed"] == 1 and "points" in wrong["results"][0]["reason"]
    unknown = _tool(api, "set_fields", artifacts=["1"], fields={"nope": 1})
    assert unknown["isError"] and "Unknown field nope. Available: points" in _text(unknown)
    nothing = _tool(api, "set_fields", artifacts=["1"], fields={})
    assert nothing["isError"] and "Give the fields to set" in _text(nothing)


def test_one_comment_goes_to_many_cards_but_not_to_an_archived_one(api: TestClient) -> None:  # noqa: F811
    for title in ("A", "B", "C"):
        _create(api, title=title)
    _tool(api, "archive_artifact", artifact="3")
    answer = _ok(_tool(api, "add_comments", artifacts=["1", "2", "3"], text="Bundled into #9"))
    results = _by_number(answer)
    assert (results[1]["ok"], results[2]["ok"], results[3]["ok"]) == (True, True, False)
    assert "archived" in results[3]["reason"]
    comments = _content(_tool(api, "list_comments", artifact="1"))
    assert [(c["body"], c["author_kind"]) for c in comments] == [("Bundled into #9", "mcp")]
    empty = _tool(api, "add_comments", artifacts=["1"], text="  ")
    assert empty["isError"] and "cannot be empty" in _text(empty)
