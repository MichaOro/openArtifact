# ADR-090: A lane has an id and a name; the key it was made from says nothing

**Status:** Accepted  
**Date:** 2026-11-27  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-011](011-board-interactions-sse-and-pointer-dnd.md) (lanes are rows; the key stays the storage value), [ADR-036](036-ui-conventions-and-lane-settings.md) (MCP `list_lanes`)  
**Implemented in:** migration 0069 (`lanes.uuid`), `tasks/lanes.py` (`pick_lane`, `resolve_lane`, `require_lane`), `tasks/service.py` (`lane`, `lane_name`/`lane_id` on a card), `api/board_tools.py` (the board tools of MCP), `tasks/schemas.py`  
**Affected chapters:** guides [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md)

## 1. Context

Lanes are the owner's: they are added, renamed and deleted freely. A lane's `key` (the value `tasks.status` holds) is made once from the first title
(`Code Review` becomes `code_review`) and never changes. On the owner's board the lane made as `in_progress` is now called *Must have*, `done` is *MVP*,
a lane called *DONE* got the key `done_2`, `backlog` is *Optional*: **the keys no longer mean what they say.**

The MCP tools spoke in keys. `list_lanes` showed `status` (`in_progress`) and `key` (`in-progress`, the form the web page uses), the cards showed
`lane: done`, the filters compared `status == lane` and an unknown value gave an **empty answer**. An agent that listed the lanes took the `key`, got
0 cards for *Must have* (the board holds 40) and for *DONE*, reported them as empty, and read `done` as "finished" although it is the owner's *MVP* lane.
That is not a mistake of the agent: the interface gave it a name that lies and then answered a wrong question with silence.

## 2. Decision

- **A lane has an id and a name.** The **id** is a uuid (`lanes.uuid`, unique): it never changes, says nothing and survives a rename. The **name** is
  the title the user typed (unique ignoring case, changeable). Interfaces for people and agents address a lane by its name or its id.
- **The key stays storage.** `tasks.status` keeps the key, so nothing is migrated and the web page works as before. The key appears in no interface for
  agents (MCP). In REST it stays where it was (`status` of a card and of a lane, the path of `/api/lanes/{status}`) because the web page and existing
  scripts use it; REST gains `id` on a lane and `lane_id` and `lane_name` on a card, additively.
- **One resolver** (`resolve_lane` in `tasks/lanes.py`) turns what a caller gives into a lane. A value that fits more than one lane is taken in this
  order (corrected 2026-11-27, see addendum 1): a **title exactly as typed**, the **old key** exactly as stored, the **id**, a **title with trimming and case
  ignored**. An unknown value is an error that lists the lanes **by name**:
  `Unknown lane 'in-progress'. Lanes: Optional, Must have, MVP, DONE, Platform` (422 in REST, an error text in MCP), never an empty answer.
  The old key is accepted everywhere the resolver is used, so no script that sends a key breaks; the tools do not show it any more.
- **MCP speaks names and ids.** `list_lanes` answers `name`, `id`, `style`, `artifact_count`, `position`, `deletable` (no `status`, no `key`, no `hue`). A card
  record (`list_artifacts` brief and full, `get_artifact`, `create_artifact`, `update_artifact`) has `lane` (the **name**) and `lane_id`; the storage
  key (`status`, `archived_from_status`) is not shown. `list_artifacts`, `count_artifacts`, `search_artifacts`, `create_artifact`, `update_artifact` and
  `move_artifacts` take a lane by name or id (`lane`); `count_artifacts` answers the lane's name.
- **Where a lane is named in REST** (a card's `status` on create and update, the lane in `/api/lanes/{status}`, `/api/lanes/{status}/rules`, the
  preview of a rule) the same resolver is used: a name, an id or a key.
- **The web page never shows an id.** A lane is drawn by its title; the id is for interfaces.
- **Audit: nothing in the application reads a lane's meaning from its key.** The key is an identity only: the foreign key of `tasks.status`, the key of the
  card rules table, the lane of an archived card (`archived_from_status`), the first lane by position (the default of a new card and the home of a hidden
  card), the `finished` look by the `style` column. The one place that still names lanes by key is the guards' view (`v_guard_lanes`, `v_guard_artifacts.lane`
  and the facts `lane.<key>`): it is an interface written by the user, not by an agent, and stays as it is until the guards get their own decision.

## 3. Consequences

- An agent that renames nothing gets the same cards as the owner sees. A lane renamed at noon is found by its new name at once.
- A typo in a lane name is a clear error with the names to choose from, in every tool.
- A card in a REST answer says two things about its lane, the storage key (`status`, for the page) and the lane (`lane_name`, `lane_id`).
- An MCP client that read `status` from a card or `list_lanes` gets `lane` and `name` now; the old key still works as an input.

## 4. Not in this decision

Changing the web page's `data-lane` (the key stays its DOM address), making the guards address lanes by name or id, and removing the key from REST.

## Addendum 1: a key is not a lookalike title (2026-11-27)

The first order put a title (case ignored) before the old key. The board's lanes are `Optional` (key `backlog`), `Must have`, `MVP` (key `done`) and `DONE`
(key `done_2`): the web page sends the key of the lane a card is dropped on, so dropping a card on *MVP* sent `done`, which matched the **title** *DONE* and the
card landed in the wrong lane. Now an exact title wins, then an exact key, then the id, then a title with another case: `done` (as the page sends it) is MVP,
`DONE` (as typed) is the lane titled DONE, `must have` still finds *Must have*. A test covers it (`test_a_key_the_web_page_sends_is_not_taken_for_another_lanes_title`).
