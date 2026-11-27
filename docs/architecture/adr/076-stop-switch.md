# ADR-076: The emergency stop: one global switch that blocks every execution

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-062](062-configuration-windows-as-data.md) (a second personal setting), [ADR-028](028-global-executions-page-and-keyset-paging.md) (a running row has the stop button where the trash is)  
**Implemented in:** `engine/stop_switch.py`, `engine/runner.py` (`set_stop`, `stop_active`, the check in `start` and `_start`), `tasks/service.py` (`stop_switch_state`, `set_stop_switch`), `api/settings.py` (`/settings/stop`), `api/mcp.py` (`get_stop_switch`, `set_stop_switch`), `exceptions.py` (`code`), `ui/forms/personal.yaml` (`show_stop_switch`), `static/js/components/stop-state.js`, `stop-switch.js`, `stop-banner.js`, `tasks/events.js` (one shared connection)  
**Affected chapters:** guides [api-reference](../../guides/api-reference.md), [execution-history](../../guides/execution-history.md), [concepts](../../guides/concepts.md), [ui-catalog](../../guides/ui-catalog.md)

## 1. Context

An execution can be stopped one by one, on the card and in the list, and a guard can pause or abort the run it watches
([ADR-060](060-guards.md)). What neither does: stop *everything*, and keep anything from starting again (a loop, a script or an agent that
starts runs through the API or MCP). Card #123 asked for an emergency stop for writing actions. That needs every kind of node to say whether it
writes (the effect declaration of card #125); the owner decided on the smaller version that covers the real case, a run that goes wrong: one
switch, for execution as a whole.

## 2. Decision

- **One switch, `STOP`, off by default, kept across restarts.** The state is one row of `app_settings` (`execution.stop`, `{"active", "since"}`);
  a new system has no row, which means off, and what was set stays set when the server restarts. The pseudo code of the owner: *if stop, return,
  else process.*
- **While it is on, nothing starts and nothing runs.** Switching it on **aborts every running execution at once** (the same stop as by hand: the
  processes and agent steps end, the state is `stopped`, the note says `EMERGENCY STOP`, a wait between the tries of a retry ends too) and
  **refuses every start from every source**: browser, API, MCP, anything automatic. All of them go through `RunEngine.start`, so there is one place.
  A refused start is `409` with `code: "stopped"` and a plain message; the MCP tool says `stopped: ...`; nothing is half started (no run row, no
  execution). Everything else keeps working: cards, pipelines, actions, guards, editing, reading.
- **Race safe.** A start that is on its way when the switch goes on either sees it before it commits (it reads the state in its own transaction and
  raises, so nothing is written) or is a run that `set_stop` aborts, because `set_stop` writes the state, makes the process remember it, waits for
  the starts that are on their way and only then looks for runs. A test with many starts at once (in the event loop and from threads) fails without
  that order.
- **Who can set it:** the browser, the REST API (`GET`/`PUT /api/settings/stop`, also under `/api/v1`) and the MCP server (`get_stop_switch`,
  `set_stop_switch`), with the rules of their other write calls. Abuse is not this switch's concern.
- **The personal setting `show_stop_switch` offers the feature** (default off: not everyone has the case). Off, switching **on** is refused (`409`
  `stop_unavailable`, naming the setting) for the API and MCP too, and the button is not drawn. Switching **off** is always allowed, so a stop can
  never get stuck behind a hidden switch. The setting itself cannot be switched off while the emergency stop is on (`409` `stop_active`).
- **The error carries a stable word.** `ArtifactError` has an optional `code`; the handler adds it to the body (`{"detail": ..., "code": ...}`), the
  client's `ApiError.code` reads it, the MCP error text starts with it. The existing refusals keep their body.
- **UI.** On the Executions page the switch sits next to *Retention*: the switch of the catalog in its red form (`ge-switch--danger`: off it is the
  neutral switch, on it takes the red of the trash button), labelled `STOP`. Switching on asks in the page's confirm dialog and names how many
  executions run and will be aborted; switching off asks nothing. A **banner at the top centre of every page** says *Pipeline processing is
  stopped* while the emergency stop is on, with a button that switches it off when the switch is offered. The state is read on page load and follows
  `settings.changed` with a `stop` part, so every open tab shows the same. A card's *Start processing* is greyed while the emergency stop is on (see Addendum 1).
- **A running row has the stop button where the trash is.** The trash is not drawn on a running row (a running execution cannot be deleted
  anyway) and the red square takes its place; any other row shows the trash. This replaces the greyed trash of
  [ADR-028](028-global-executions-page-and-keyset-paging.md) Addendum 1 in the global list.
- **One event connection per page.** Every page now listens for the banner, and a browser keeps six connections per host open across all tabs, so
  `connectEvents` shares one `EventSource` per page for the default URL (a caller that joins late is told at once that it is open or that it was
  refused). A custom URL still gets its own.

## 3. Consequences

- A new system keeps working as before; the switch costs nothing until it is offered and switched on.
- STOP is a blunt instrument by design: it does not distinguish reading from writing. That needs the effect declaration (card #125); then a
  finer mode can build on the same state.
- The abort uses the stop that exists, so what a stop does to a running Execute Command (the process group ends) or an agent step is what it did.
- A restart while the emergency stop is on keeps it on: the executions that were running are closed as `stopped` with the note `Interrupted by restart` as always, and nothing starts until somebody
  switches the emergency stop off.

## Addendum 1 (2026-11-26): the name, the greyed Start, the stored note

The owner tested the switch and asked for two things.

- **The name is *emergency stop*** (German *Notaus*) in every visible text: the question, the banner and its button, the tooltips, the
  messages of the API and MCP (the codes `stopped`, `stop_unavailable` and `stop_active` stay), the personal setting *Show the emergency stop*
  and the guides. The switch keeps its short visible label `STOP`; its accessible name and its tooltip are *Emergency stop*. The note of an
  execution the switch aborted reads `EMERGENCY STOP`.
- **Start processing is greyed while the emergency stop is on.** `ProcessingPanel` (`tasks/processing.js`) subscribes to the same state as the
  banner (`components/stop-state.js`), so no second mechanism: the button is disabled with the tooltip *Emergency stop is on: processing is stopped*,
  also in a dialog that is already open when the switch flips, and it is enabled again when the switch goes off. The server's `409 stopped` stays the
  safety net (a direct API or MCP start, or a click before the page knows the state). A running card keeps its *Stop processing* button.
- **Stored notes.** Rows written by the first version say `STOP switch`. A note is text that the list, the history, the API and MCP show as stored,
  so a display mapping would have left the API and MCP with the old text. Migration `0061` rewrites exactly that note in `pipeline_runs.note` and
  `executions.note` once (the downgrade writes it back); every other note is untouched.
