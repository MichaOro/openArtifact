# ADR-071: Card rules

**Status:** Accepted  
**Date:** 2026-11-25  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-036](036-ui-conventions-and-lane-settings.md) (the lane style *finished* becomes a rule), [ADR-052](052-retention-rules-and-rule-builder.md) and [ADR-060](060-guards.md) (the same rule model, a third and fourth use)  
**Implemented in:** `tasks/card_rules.py`, `tasks/card_sweeper.py`, `rules/catalog.py` (`lane`, `board`), `tasks/service.py`, `api/card_rules.py`, `models/board.py` (`Task.archived_at`), migration `0058`  
**Affected chapters:** guides [api-reference](../../guides/api-reference.md), [concepts](../../guides/concepts.md)

## 1. Context

A lane could only be switched to *finished* (its cards struck through). The owner wants what the retention rules do for executions, for
cards: *when* a condition holds, *then* something happens to the card, at a lane and for the whole board: set a card as done, hide it
after a time, delete what has been hidden for weeks, give it a label (like the chip *Draft*) or a colour by how long it has been in a lane
or how long nothing happened to it.

## 2. Decision

- **One rule model.** A rule is `{when, action, name, enabled, params}`; `when` is the condition tree of ADR-052/060 (`rules/tree.py`),
  the fields and actions are described by `GET /api/rules/schemas` (purposes `lane` and `board`). The actions are a small registry
  (`ACTIONS`): `set_done` (lane only), `archive` (lane, board), `delete` (board only), `label` (`text` 1 to 24 characters, `tone`) and `colour`
  (`tone`, `mode` `fill` or `border`). Tones are the semantic ones green, red, yellow, blue, neutral, never a free colour. A new condition or
  action is one entry in the catalog and one in the registry.
- **Conditions:** lane, time in the lane, time since the last activity, age of the card, time since archived, title, text, has a parent,
  artifact fields (`field.<name>`). Durations are seconds in the API.
- **Time in the lane** comes from the history (`task_activity`): the newest entry of kind `lane` or `created` of the card. No new column and
  no backfill: the history is already there for every card. A card whose entries were pruned (more than 500 per card) falls back to its creation.
  **Last activity** is the newest of the card's activity, its comments and its last change (`updated_at`), except the sweeper's own entry
  `archived` and the archiving itself, which are no sign of life.
- **Marks are derived, not stored.** Every read of a card (`marks` on `GET /api/tasks`, one card, `/api/v1/artifacts`, the events) computes
  `{done, labels, colour}` from the rules and the facts of the moment. All cards are looked at in one pass: three grouped queries for the
  facts, however many cards there are (a test counts the statements for 60 cards). While no rule is on, nothing is queried.
- **Archive and delete change data** and are done by a sweeper: every `OPENARTIFACT_CARD_SWEEP_INTERVAL_SECONDS` (default 900, `0` only on
  saving) and at once when rules are saved or `POST /api/board/rules/sweep` is called. Archiving sets `tasks.archived_at` (migration 0058)
  and `tasks.archived_from_status` (the lane it was in) and writes the activity entry `archived`; the card's `updated_at` stays. A card with a
  running run is never archived (by hand: 409; by a rule: skipped).
- **The archive is the set of cards with `archived_at`.** `POST /api/tasks/{id}/archive` and `.../unarchive` (also `/api/v1/artifacts/{ref}/...`)
  do it by hand. *Unarchive* puts the card back into `archived_from_status` at the very top (smallest position minus one; the first lane when that
  lane is gone), clears both columns and writes the activity entry `unarchived`, from which the time in the lane counts again. A lane that holds
  archived cards cannot be deleted (they count as its cards). **An archived card is read-only on the server:** a change, a field, a comment (add,
  edit, delete), a move, a delete by the user and a run are 409 `archived`; only *unarchive* is allowed (and the delete of a board rule). Archiving a
  parent archives only that card: its children stay on the board and keep their parent link to the archived card.
- **Lists:** `GET /api/tasks?archived=exclude|include|only` (default `exclude`: the board), `sort=archived_at|title`, `order=asc|desc`
  (`only` defaults to newest archived first), `limit` (1 to 500) and `offset`, header `X-Total-Count` (same for `/api/v1/artifacts`); the MCP
  tool `list_artifacts` takes `include_archived`. One card by id or number, its comments and its history stay readable. A card carries
  `archived_at`, `archived_from_status` and `archived_from_lane` (that lane's title now, `null` if gone).
- **Delete is the dangerous action** and is fenced: only for the board; only for cards that are already archived (so *archive* and
  *delete* are two steps with a wait between); it needs a condition and a `delete` rule is **off until switched on**; a card with children
  or with a running run is never deleted (they are *spared*, and the preview says why); the deletion goes through `ArtifactService.delete` (the
  same path as a delete by hand, which publishes `task.deleted`); every deletion is logged (the last 100 under `GET /api/board/rules/deletions`
  and the application log); `POST /api/board/rules/preview` and `POST /api/board/rules/sweep?dry_run=true` say what *would* happen.
- **Conflicts:** `set_done` and `archive` hold when any rule holds; labels add up (the same text and tone once); the first matching colour
  wins, the rules of the card's lane before those of the board, each in the order of its list.
- **A rule without a condition holds for every card of its place.** This differs on purpose from the retention rules, where a rule without a
  condition does nothing: a lane that looked finished is the rule *Set card as done* without a condition. `delete` refuses it.
- **Storage:** one row `cards.rules` in `app_settings` (`{"lanes": {key: [rule]}, "board": [rule]}`, at most 20 rules per place); a stored
  rule that no longer fits makes the whole row count as empty, rather than act on a guess.
- **The lane style follows the rules:** `PUT /api/lanes/{status}` with `style` adds or removes the unconditional `set_done` rule, and
  saving the rules sets `style` to `finished` while that rule is there, so the old API and the new one agree. Migration 0058 turns every lane
  with the style `finished` into that rule.
- **API:** `GET/PUT /api/lanes/{status}/rules`, `GET/PUT /api/board/rules`, previews, sweep, deletion log; events `cards.rules.changed`,
  `board.updated` (`{archived, deleted}`), `board.resync`, `board.lanes`.

## 3. Consequences

- The board page (card #119) draws `marks`: strikethrough for `done`, chips for labels, fill or border for the colour, and a *Show hidden
  cards* switch for `include_archived`; the lane menu and the board menu get the rule list like the retention window.
- A colour that depends on time changes while nobody saves anything: the page asks again when it reads (the list is read on load and on
  `board.resync`), there is no push at the moment a threshold is passed.
- Time in the lane is as good as the history: cards moved before the history existed (ADR-058) count from their creation.
- Delete cannot be undone; the safeguards above are the only protection, so the owner has to switch it on.
