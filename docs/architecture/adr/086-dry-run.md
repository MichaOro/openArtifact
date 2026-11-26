# ADR-086: The dry run: a run under real conditions that skips what writes, with every node declaring its effect

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-054](054-node-kinds-as-yaml-manifests.md) (the manifest gets an `effect` block), [ADR-070](070-versions-of-actions-and-pipelines.md) (a run may take the draft), [ADR-076](076-stop-switch.md) (the stop also blocks a dry run)  
**Amended by:** —  
**Implemented in:** `static/js/editor/dry-run-panel.js` and `dry-run-model.js` (the Dry run tab), `api/runs.py` (`dry-run/check`, `placements`), `engine/runner.py` (`check_start`), `graph/effects.py`, `graph/manifest.py` (`EffectSpec`), `graph/nodes/*.yaml` (`effect:`), `engine/dry_run.py` (the skipped step), `engine/runner.py` (`start`, `_entry_inputs`, the skip), `engine/context.py` (`bind_given`, the missing-result rule, `RunView.dry_run`), `engine/executors.py` (the timer, the agent), `engine/snapshot.py` and `graph/publishing.py` (`draft`), `agents/tools.py` (`Tool.writes`), `agents/local_tools.py`, `agents/mcp_client.py`, `agents/board_toolbox.py`, `engine/history_query.py` (filter and counters), `engine/guard_views.py`, migration `0066_dry_run.py`, `static/js/executions/`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [execution history](../../guides/execution-history.md), [api reference](../../guides/api-reference.md)

## 1. Context

A pipeline that writes (comments, HTTP calls, scripts, GitHub, Postgres) cannot be tried without doing what it does. Authors need a test run that follows the
real conditions (the branches, the inputs, the reads) but changes nothing, and they need to know which nodes would have changed something.

## 2. Decision

- **Every node kind declares its effect** in its manifest (`effect:`): `none` (it only decides or shapes data), `read`, `write`, or `mixed` (only the Agent and the tool
  kinds whose tools decide). The declaration may follow a setting (`setting` and the values that `reading` lists: the HTTP method, the operation of GitHub and of the
  Artifact node) or a switch (`flag` and `flag_true`: Postgres *Allow changes*, Execute Command *Read only*, the tools' write switches). **What is not declared, an
  unknown value and an unknown kind count as writing.** Execute Command is writing unless its new setting *Read only* is ticked.
- **A run has a persisted `dry_run` flag** (`pipeline_runs`, `executions`; migration 0066, existing rows are real runs). The engine decides per step: a node whose effect is
  `write` is not executed; its step is recorded as passed with `reason` and `data` (`dry_run: true`, `would_have`) saying what it would have done. Its inputs are
  still resolved first, so a wrong reference fails as it would for real. Nodes that read or decide run as always: conditions, branches, reads and calls of called pipelines
  are real.
- **A skipped node has no result.** What it leaves is the fact that it was skipped (`success`, `data.dry_run`, `data.would_have`). A later node that asks for something it
  would have produced (`.output`, `.exit_code`, another `data` field) fails with a message naming the node and pointing at mock data (card #140) instead of working with
  an invented value.
- **Timers do not wait.** The step passes at once and records the wait it skipped (`skipped_seconds`). **Guards take part**: their actions and views see the same flag
  (`v_guard_runs.dry_run`). **An agent runs**, but the tools it calls that change something are answered with "Dry run: ... was not executed", as a normal answer, so the
  model goes on. A tool counts as changing by the same declaration (MCP tools by the server's `readOnlyHint`; a tool that is not announced as read only is changing).
- **The emergency stop blocks a dry run** like any start (ADR-076).
- **The version:** `version` is `draft` or `published`. The editor's start defaults to the draft (it tests what is being edited), the Integration API and the MCP tool to the
  published version. The snapshot of the run is built from that version for the pipeline and everything it calls. `inputs` and `version` without `dry_run` are 422.
- **Inputs:** with an `action_id` the values are for the declared inputs of that action's Trigger (checked like a mapping, ADR-083, used once); without it they are for the
  pipeline's own Trigger. The values are taken as text: they are **never read for `${...}`** (`bind_given`), so a value cannot reach a secret.
- **The artifact stays as it is.** A dry run does not move the artifact's pipeline, stage and action, and its stage states do not count when a real run starts later.
  Execution numbers continue; retention treats a dry run like any execution.
- **History:** `dry_run` is in the list and the detail, the rows show a chip (*Dry run*, *Testlauf*), the list filters by `dry_run=only|exclude`, and the counters
  *failed* and *done in 24 hours* count real runs only (a dry run is no failure of a pipeline); *running* and *total* count every execution.

## 3. Consequences

- A new node kind has to declare its effect or it is skipped in every dry run (the safe side); the manifest test checks the declaration.
- A step of a dry run proves the conditions and the reads, not the result of a write; the missing-result rule makes that visible instead of hiding it.
- Not decided here: mock data for skipped nodes (card #140).

## 4. Addendum: the Dry run tab of the Trigger window

The editor starts a dry run from the window of the **Trigger** of a pipeline and of an action definition (a double click on the node). The window has two tabs with the
shared tab list (`components/tabs.js`): *Inputs* (the settings as before) and *Dry run* (*Testlauf*). The **Output** node has no such tab: it only gives data out. A graph
for guards has none either: its actions run on their own, not on a card. The tab chosen stays chosen while the window is drawn again and when it is opened again (kept
in the editor of the page, like the tab of the settings page it follows, but not in the address: the window itself is not an address).

The tab (`editor/dry-run-panel.js`, the pure part `editor/dry-run-model.js`):

1. **The test card:** a searchable list (the combobox component) of the cards of the board that are not archived, by number and title with the lane beside it. The card last
   chosen is remembered **per graph in the browser** (`localStorage`, key `oa-dry-run-card-<graph id>`), nothing on the server.
2. **The inputs:** one control per input the Trigger declares, by its type: text, number (a text field that takes a decimal), true or false (a pick with *Not set*), a choice (a
   pick), a list (lines). A required input is marked; an empty field uses the declared default, which sits in the field faintly (as in a placement). Only what is filled
   in is sent. A graph without inputs shows a note and sends none.
3. **The version:** *Draft* (the default: it tests what is being edited) or *Published*. With *Published* the form is made from the contract of the version that runs
   (`GET .../contract`), with *Draft* from the Trigger as edited.
4. **The check before the start,** in plain words, asked of the server: `POST /api/tasks/{id}/dry-run/check` with the body of the start returns `{"problems": [...]}` and
   starts nothing. It runs the same choice of the start and the same check of the inputs as the start, the size check of the card, and for the draft the check before
   publishing (ADR-082) of every graph the run would use. The values given for the entry action stand in for what its placement maps. The browser holds no second copy of
   these rules; it asks again, after a short pause, whenever the card, an input, the version or the place changes, and shows only the last answer. The check informs, it
   does not block: the start itself is the last word and its refusal (409, 422) is shown in the window in plain words.
5. **The start** (*Start dry run* / *Testlauf starten*) sends `dry_run: true` with `inputs`, `version` and the start (`stage_id`, `action_id` for an action). It is locked, with
   the reason as its tooltip and as text, while the emergency stop is on (the state of `stop-state.js`), while no card is chosen, while a dry run is in progress, and for an
   action that no pipeline places.
6. **The result:** under the form a status line with the *Dry run* mark and the status of the run and a short list of its steps (name, how it ended, and for a skipped writing
   step what it would have done), from `GET /api/runs/{id}/results` and live from the `run.updated` events. The Trigger and a passing Output are not listed. *Open in
   history* links to the execution (`/artifacts/<number>/executions/<id>`), where the run stands with its mark (the flow page shows it beside the status). The window does
   not draw the flow again.

**An action definition** is run through a pipeline: a dry run starts at a place a pipeline puts it. `GET /api/actions/{id}/placements` lists those places (pipeline, stage, the
action node in it) by the version that runs; the window uses the first (the one chosen last) and offers a pick when there are several. An action that no pipeline places
cannot run alone: the tab says *Place this action in a pipeline to run it* and the start stays locked.

Accessibility: the tabs follow the ARIA tab pattern (arrow keys, Home, End), the check and the result are live regions, the error is an alert, every control has its label,
the order of the tab key is the order of the form. On a narrow screen the form is stacked and does not scroll sideways.
