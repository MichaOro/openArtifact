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

## Addendum 1 (2026-11-26): the rules editor (card #119)

- **One window for both places.** `card-rules-modal` (`tasks/card-rules-dialog.js`) replaces the old lane settings window. It has the frame
  of the retention rules: the rule list (switch, sentence, chevron, bin, *Add rule*) and, after a click, one rule with *If* (rule builder)
  and *Then* (the action with its settings). The lane menu's *Settings* opens it for the lane (title `Lane settings`, the lane as a chip),
  the board menu gets a new *Settings* entry for the board's rules (title `Board settings`). The components are the shared ones
  (`RuleList`, `RuleEditor`, `RuleBuilder`); the editor learned the settings of an action (`schema.actions[].params`, `defaults`,
  `startsOff`) and the list keeps a rule's `params`.
- **The schema comes from the server** (`GET /api/rules/schemas/lane|board`); `tasks/card-rules-schema.js` adds the texts and, for the
  board, the lanes as the choices of the field *Lane* (a list value, which the server's `is` accepts). *Set card as done* exists for a lane
  only; the board offers archive, delete, label and colour.
- **The preview is the card itself.** `tasks/card-sample.js` copies the board's card template and `card-marks.js` draws on it what the rule
  would do (strikethrough and dimming, label chip, colour as fill or border, a dashed outline for archive). It is shown beside the open
  rule, and in a small window while a rule of the list is hovered or focused, with the number of cards the rule touches now
  (`POST …/rules/preview`, asked once per rule).
- **Marks replace `lanes.style` in the browser.** The board's cards and the card dialog (title, label chips, colour frame) draw the
  server's `marks`; the CSS of `.lane--finished` is gone (the server still sends `style` for the old API). The board reloads on
  `cards.rules.changed`, `board.updated` and `board.resync`.
- **A rule that deletes** starts switched off, must name at least one condition, and asks before it is saved on: Save shows how many
  archived cards it would delete, and only a second click on *Save and delete* saves. The board's window also has *Preview now* (a dry run
  of the pass: `POST /api/board/rules/sweep?dry_run=true`) and the log of what rules deleted.
- The old `LaneSettingsDialog` stays in the quarantine (`quarantine.json`) for one cycle.

## Addendum 2: the archive in the board page

The archive has a view on the board page (`tasks/archive-view.js`, built on `ManagementPage` with the new option `readOnly`: no pencil, no bin).

- **Entry:** the board's menu (the "more" button next to *Add lane*) has one entry whose text changes: *Show archive* / *Hide archive*. The view
  takes the place of the lanes; *Add lane* is hidden while it is shown. It reads `GET /api/tasks?archived=only&sort=archived_at&order=desc&limit=500`
  and follows `board.updated`, `task.updated` and `task.deleted`.
- **Tiles and panel:** two thirds tiles, one third panel. Order: the time of entry into the archive (newest first by default; oldest first,
  A–Z and Z–A can be chosen). Panel tabs: *Details* (text, archived and created time), *Comments*, *History*, *Context* (the lane the card came
  from, the parent, the artifact fields that are set; pipeline, stage and action are left out). Everything is read only.
- **The one change:** *Remove from archive* (Details tab) calls `POST /api/tasks/{id}/unarchive`; the card goes on top of the lane it came from.
- **By hand:** the rail of the artifact dialog has an *Archive* action (above *Delete*) that calls `POST /api/tasks/{id}/archive`. Events of an
  archived card (`task.updated` with `archived_at`) take it off the board and close its open dialog.
- **History:** the entries `archived` and `unarchived` read "moved it to the archive" and "took it out of the archive, back to {lane}".

## Addendum 3 (2026-11-26): a rule can be "always"

The server already treats a rule without a condition as *holds for every card of its place* and derives the marks at every read, so a
card that leaves the lane loses the state at once. What was missing was saying so in the editor (*If all of these* with *No conditions
yet* looked unfinished). No data change, no migration.

- **The choice.** In the rules window of a lane and of the board, a rule has *Always (every card in this lane)* / *(every card on the
  board)* or *Only when…* above its conditions. *Always* hides the condition tree; *Only when…* shows it. A new rule starts as *Always*;
  going back to *Always* clears the tree. There is no *always false*: a rule that never holds is a rule that is switched off.
- **Stored as before.** An empty `when` group is *always*. The choice is a flag of the open window (`rule.conditional`, dropped by
  `kept()`, never saved); a rule that has conditions reads as *only when*. *Only when…* with no condition yet keeps Save off, because
  it would be saved as *always*.
- **A rule that deletes** needs a condition (as before, the server refuses it): *Always* is disabled for it, and choosing the action
  switches the rule to *Only when…*.
- **The list** tells a rule without a condition as *Always: Set card as done*.
- **Opt-in.** The shared `RuleEditor` and `rule-list-model` offer the choice only for a schema with `always` (`buildSchema(…, {scope})`
  of the card rules). The retention rules and the guards keep their meaning: an empty rule does nothing.
- Design: [2026-11-26-optional-rule-condition-design.md](../../superpowers/specs/2026-11-26-optional-rule-condition-design.md).

## Addendum 4 (2026-11-26): an archived card in the dialog of the board, read only

- **"Show more"** of the text in the archive panel (Details tab) no longer unfolds the text in the narrow panel: it opens the card in the
  same `ArtifactDialog` a card of the board opens in (`ClampedText` got the opt-in option `onMore`; `ArchiveView` has `onOpen`, `main.js`
  `showArchived`). The panel keeps its own *Remove from archive* button.
- **Read only is a mode of that window, not a copy** (`openView(…, { readOnly: true })`, off for every other opening). It hides what writes:
  Edit, Run, the comment box with its Send and the menus of the comments (`[data-readonly]` in `task-dialog.css`), and switches off the rail's
  Lane, Parent, Pipeline, Stage and Action and the artifact fields; the lane chip under the title is switched off too. Tabs, the references in
  the text and the history stay as they are. The server's 409 `archived` stays the rule behind it.
- **The rail:** Archive and Delete are gone; *Remove from archive* (`nav.unarchive`, registered in `web/navigation.py` after Delete) takes
  the place of Delete, the last entry. Archive keeps its row as an invisible gap, so no other entry moves. It calls the same
  `POST /api/tasks/{id}/unarchive` as the panel (`ArchiveView.restore`), closes the window and takes the tile out of the archive.
- **Events:** the event that archives a card closes its dialog on the board, but not the read-only one (that is where it is looked at); the
  read-only window closes when the card leaves the archive elsewhere or is deleted.
