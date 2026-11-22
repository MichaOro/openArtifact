# Extending the application

The extension points that exist today are registries that the built-in parts use exactly as an extension
would ([ADR-014](../architecture/adr/014-building-blocks-and-extension-points.md)):

| Extension point | Registry | Section |
|-----------------|----------|---------|
| A kind of node | `NODE_TYPES` (`graph/node_types.py`), `EXECUTORS` (`engine/executors.py`), `VIEWS` (`static/js/editor/node-types.js`) | [Add a kind of node](#add-a-kind-of-node) |
| A type of node setting | `SETTING_TYPES` (server), `CONTROLS` (`static/js/editor/setting-controls.js`) | [Add a setting type](#add-a-setting-type) |
| A navigation entry | `SIDEBAR`, `ARTIFACT_RAIL` (`web/navigation.py`) | [Add a navigation entry](#add-a-navigation-entry) |
| A server-sent event | `EventBus.publish`, `EVENT_TYPES` (`static/js/tasks/events.js`) | [Add an event type](#add-an-event-type) |
| A dialog with fields | `form_modal` macro and `FormDialog` | [Add a dialog](#add-a-dialog) |

Loading third-party extensions (a plugin directory, entry points) is not built; these are the steps for a
change inside this repository. Wording: the UI says artifact, pipeline, stage and action; the code says
`task` for artifact and `graph` for how pipelines and action definitions are stored
([ADR-015](../architecture/adr/015-vocabulary-and-storage-names.md)). Never "workflow". The domain
vocabulary is in the [concepts guide](concepts.md).

All paths are below `apps/backend/openartifact/` unless stated.

## Add a kind of node

Worked examples in the code: the **timer** (`TimerType`, `TimerView`, migration `0016_timer_node.py`; its
setting is a column) and the **Code** and **HTTP** nodes (`CodeType`, `HttpType`, `executors.py`,
`code_runner.py`, `http_runner.py`; their settings live in the `config` JSON). Use the second kind as the
model for anything new.

1. **Name the kind.** Add a member to `NodeKind` in `models/__init__.py`.
2. **Describe it on the server.** In `graph/node_types.py` add a subclass of `NodeType` and add an instance
   to the registration list at the end of the file (`register(...)`):
   - `kind`, `label`;
   - `scopes`: `PIPELINE`, `ACTION_DEFINITION` or both;
   - `fixed` (comes with every new graph and cannot be deleted) or `addable` (offered in the "+" menu);
   - `chain` (a step of the main line; new nodes are placed after these), `ending` (the end of the main line);
   - `inputs` / `outputs`: tuples of `Port(name, label)`; use the names of `Ports` (`in`, `out`, `pass`,
     `fail`, ...) so the engine and the rules agree;
   - `settings`: tuples of `Setting(...)`, see [Add a setting type](#add-a-setting-type); put new ones in
     `config` (`stored_in="config"`);
   - `links_to` if the node points at another graph (`definition_id`);
   - override `connect_error` only where the connection rule differs from the common one in the base class.

   `GET /api/node-types` now publishes the kind, and the repository, the connection rules, the settings
   validation and the "+" menu follow the registry.
3. **Migrate only if the schema changes.** Settings stored in `config` (`graph_nodes.config`, a JSON object
   merged and validated per key by `NodeType.merge_config`) need **no** migration. What does need one is the
   check constraint `ck_graph_nodes_kind` on `graph_nodes`, which lists the kinds: copy the pattern of
   `alembic/versions/0021_execution_nodes.py` (a batch alter that drops and recreates the constraint) and
   write the downgrade (it must remove nodes of the new kind, because the old constraint cannot hold them).
   Create migrations with `cd apps/backend && alembic revision -m "..."`. The model does not declare that
   constraint, so `alembic check` (run by `tests/test_migrations.py`) will not tell you about a missing
   one: the node-creation test for the new kind will. A setting as a column of its own (the way `seconds`
   and `fail_enabled` work) additionally needs a field on `NodeUpdate` / `NodeRead` in `graph/schemas.py`
   and a model change; avoid it.
4. **Execute it.** Only kinds inside action definitions have an executor; the walk through stages and
   pipelines (`RunEngine._walk`) belongs to the engine itself, and a new kind of the main line would need an
   engine change and an ADR. For an action-definition kind, in `engine/executors.py` write

   ```python
   async def _mykind(node: dict[str, Any], limits: Limits) -> NodeResult: ...

   register_executor(NodeKind.MYKIND, _mykind)            # leaves by On Pass / On Fail
   register_executor(NodeKind.TIMER, _timer, by_outcome=False)  # leaves by the single Next output
   register_executor(NodeKind.IF, _if, by_outcome=False)         # leaves by the port the result names
   ```

   `node` is the frozen node of the run's snapshot: `node["config"]` holds every config setting (defaults
   filled in by `effective_config`), `node["seconds"]` the column setting. Return a `NodeResult`
   (`engine/results.py`): `outcome` (`"pass"` or `"fail"`), optional `exit_code`, `output` (text),
   `reason` (a sentence for people, cut at 1000 characters), `data` (a JSON object) and `duration`; use
   `failed("reason")` for a node that could not even start. The engine stores the result as a step, picks
   the port from the outcome (or the one the result names: set `NodeResult.port` to an output of the kind, as the If and Switch
   nodes do, and declare those outputs in the node type; a settings group and `references` on a `Setting` shape the inspector) and carries on; a kind without an executor passes at once through `out` and
   leaves a step without output. Limits the executor needs go through `Limits` (built from `Settings` in
   `Limits.from_settings`): add the setting in `config.py` (with bounds) and a field there, never read
   `os.environ`. Keep new bounds once, in `node_types.py`.
5. **Handle secrets and foreign input safely** if the node runs foreign code, calls the network or uses
   credentials (checklist below). Wrap the work in `_with_secrets(names, limits, run)`; it resolves the
   secrets, registers them for log masking, turns an exception into a plain failure and masks every form of
   the values in `output`, `reason` and `data`.
6. **Draw it in the browser.** In `static/js/editor/node-types.js` add a `NodeView` subclass with
   `static kind` equal to the server's value (and `static icon`, `static size`, `static portLabels` where
   needed) and add it to the list that is passed to `registerView` at the end of the file. Override only what
   differs: `caption(node)` (the line under the name), `portLocal`, `isVisible`, `canFeed` (a mirror of the
   server's `connect_error`), `sections` (the inspector blocks, see `static/js/editor/inspector.js`). A kind
   without a view class uses the base `NodeView`. The inspector draws the settings from the server's
   description, one control per setting type.
7. **Icons only through `templates/components/icons.html`.** Add the SVG to the `icon` macro and the name to
   `icon_names` (base.html renders every icon once into `<template id="icons">`;
   `static/js/components/icons.js` clones from there). No other file contains icon paths. If the kind should
   have an icon in the step list of the history, add it to `KIND_ICONS` in `static/js/tasks/history-step.js`.
8. **Test it.**
   - Server: `tests/test_graphs.py` (create, connect, refuse a wrong connection, settings bounds),
     `tests/test_engine.py` and `tests/test_execution_nodes.py` (a run goes through the node; both outcomes).
     Put the executor's own logic in a module of its own (as `code_runner.py`, `http_runner.py`) with a
     test file of its own.
   - Browser: a flow in `tests/e2e/test_editor.py` or `tests/e2e/test_execution_nodes.py` if the kind has
     its own inspector block.
   - A schema change: `tests/test_migrations.py`.
9. **Document it.** The glossary (arc42 chapter 12), the [execution nodes guide](execution-nodes.md) for
   user-visible behaviour, and an ADR if the engine behaviour is new
   ([ADR-021](../architecture/adr/021-execution-nodes-as-executors.md) and
   [ADR-022](../architecture/adr/022-node-settings-as-json-config.md) describe the current model).

### Checklist for nodes that run foreign code, call the network or use credentials

- A node that runs text it did not write needs the Code node's safeguards or better: a bounded time, bounded
  output, bounded resources, a clean environment (never the application's settings), the process group
  killed on timeout and on cancel. See `engine/code_runner.py` and [Security](security.md).
- A node that calls out must vet the address it connects to, not the one it was given (resolve once, check,
  connect to the checked address), refuse redirects by default and never follow the environment's proxy
  settings. See `engine/http_runner.py`.
- Secrets are referenced by name in the node, resolved at run time by the executor and never stored in a
  snapshot, a log line, an event or a result. Everything the node returns passes through masking.
  See [Credentials](credentials.md).
- Everything the node returns is untrusted text that ends up in the history and in agents' prompts: it is
  rendered with `textContent`, never as HTML.
- A new node that needs the API token or a secret key must state so in its `help` text and refuse to run
  without it.

## Add a setting type

A setting is one `Setting(key, label, type, ...)` in a node type. The types are `integer`, `switch`, `text`
(one line), `lines` (several lines), `code` (source code, monospace) and `select` (one of `options`). Settings
are bounded by `minimum` / `maximum` (integers), `max_length` (texts; the default is 2000 for `text` and 20000 for `lines` and `code`) and `options`; `check` is an extra validation function for a text (not sent to the editor;
raise `SettingError`); `placeholder` and `help` are shown in the inspector. `Setting.validate` is the one
place that decides whether a value fits. Using an existing type needs only the `Setting` entry.

A new type:

1. Add its name to `SETTING_TYPES` and its default length (if a text) to `_DEFAULT_MAX_LENGTH` in
   `graph/node_types.py`; add its branch to `Setting.validate` (and `describe`, if it publishes more).
2. Add a control class to `static/js/editor/setting-controls.js`: subclass `SettingControl` (or
   `LinesControl`), implement `createInput(value)` (and `read`, `parse`, `hint` if the value is not the
   input's text), and list it in `CONTROLS`. A type the browser does not know is shown as a text field.
3. Test the validation in `tests/test_execution_nodes.py` (or `tests/test_graphs.py`) and, if the control has
   behaviour, in an e2e flow.

## Add a navigation entry

Entries are objects in `web/navigation.py`; two navigations exist, `SIDEBAR` and `ARTIFACT_RAIL` (the rail of
the artifact dialog), and `components/nav.html` renders both.

1. **Add the object** to the navigation: `NavLink(key, label, icon, href=...)` (a page; `children=(...)`
   makes a section), `NavField` (a value of the open artifact chosen from a list), `NavAction` (a command),
   or a `NavDivider`. Entries are added with `.add(item, group)`.
2. **Icon.** Use an existing icon name, or add the SVG to `templates/components/icons.html` and its name to
   `icon_names` (see above).
3. **Page.** A `NavLink` needs a route in `web/routes.py` that renders a template and passes
   `active_nav=<key>` (the Executions page is an example: `/executions`, key `executions`). A `NavField` or
   `NavAction` of the rail needs its handler in the dialog script (`static/js/tasks/`), selected by
   `data-card-field` / `data-card-action`.
4. **Markup.** If the entry needs a new kind of markup, add it to `components/nav.html`; the `kind` of the
   entry picks the branch.
5. **Test it.** `tests/test_web.py` for the route and the rendered entry; `tests/e2e/` for behaviour in the
   dialog or sidebar.

## Add an event type

The application pushes changes to every open browser through one stream (`GET /api/events`, server-sent
events, `events.py`). The bus is in-process and does not replay: a browser that reconnects loads the current
state from the REST API.

1. **Publish after the commit**, from the service or engine that changed the data:
   `bus.publish("thing.updated", {...})` with a JSON-serialisable payload (`model_dump(mode="json")`).
   The existing types are `task.created`, `task.updated`, `task.moved`, `task.deleted`, `board.resync`,
   `run.updated`, `execution.updated` and `execution.deleted`. Name events `noun.verb`, send enough data to
   update the view without a second request, and never put secrets or outputs in them.
2. **Subscribe in the browser.** Add the type to `EVENT_TYPES` in `static/js/tasks/events.js` (the client
   only listens to the types in that list) and handle it in the `onEvent` callback of the page that cares
   (`tasks/main.js`, `executions/page.js`, `execution/flow-page.js`).
3. **Document it** in the docstring of `api/events.py` and in the arc42 chapter on the event stream.
4. **Test it.** Server: the `published` fixture of `tests/conftest.py` records every published event;
   assert on it. Browser: wait for the effect, not for a time (see the [testing guide](testing.md#waiting)).

## Add a dialog

Every dialog with input fields is a `FormDialog` over a `form_modal` ([ADR-010](../architecture/adr/010-frontend-without-htmx.md) describes the dialog system; there is no separate ADR for it yet).

1. **Markup.** In the page template import the macro and render the dialog once:
   `{% from "components/form_modal.html" import form_modal %}` and
   `{{ form_modal("my-modal", "Title", fields, submit="Create") }}`. `fields` is a list of
   `{name, label, kind: "text" | "textarea", required, maxlength, rows, placeholder, hint}`; `NAME_FIELDS` is
   the ready-made single "Name" field. No inline scripts.
2. **Behaviour.**

   ```js
   const dialog = new FormDialog(new Modal(document.getElementById("my-modal")));
   dialog.open({
     title: "Rename pipeline",
     values: { name: current },          // optional start values by field name
     submitLabel: "Save",                // optional
     onSubmit: async ({ name }) => { await rename(name); },   // returns a promise
   });
   ```

   `onSubmit(values)` decides where the result goes. The dialog checks required fields, blocks double
   submits and closing while the request runs, closes on success and shows a failure: an error with
   `fieldErrors` marks the field, one with `detail` or a message shows a form error. Throw (or let
   `request()` from `static/js/http.js` throw) rather than catching and swallowing. For a yes/no question use
   `ConfirmDialog` (`confirm_modal.html`).
3. **Test it** in `tests/e2e/test_dialog.py` or next to the page's other flows.

## Extend the history detail and the flow view

The History tab of the artifact dialog and the page of one execution share the markup and rendering of a
step (`static/js/tasks/history-step.js`, template `components/history_step_template.html`). Everything a
step shows comes from what ran, so it is set with `textContent` only.

- **A new fact on a step.** Add the column to `RunNodeResult` (migration), the field to `ExecutionStepRead`
  (`engine/schemas.py`) and fill it in `RunEngine._record`; then show it in `stepFacts` or the template.
  Steps are written by the engine as the run proceeds, so older executions will lack the value: the field
  must be optional.
- **A new fact on an execution.** Same for the `Execution` model and `ExecutionRead`; the list, the History
  tab, the global page and the MCP tool read the same schema. If it should be filterable on the global page,
  extend `engine/history_query.py` (and its index, see migration 0025) and `static/js/executions/filters.js`.
- **The flow view.** The path through the pipelines is not stored: `engine/flow.py` replays it over the
  frozen snapshot with the engine's rules, and `static/js/execution/` draws it on the editor's canvas. A
  change of how the engine walks (a new kind of main-line node) must be mirrored in `flow.py`
  (`tests/test_execution_flow.py` runs real pipelines and checks the replayed path). New node kinds in action definitions
  need nothing here except the step icon.
- **Snapshots are frozen.** What the replay and the view need from a node must be in the snapshot
  (`engine/snapshot.py`); executions frozen earlier lack new fields, so `flow.py` fills in defaults
  (`_graphs`). Never read the live graph to explain an old execution.
- **Retention** is in `engine/history.py` (one place); see the [execution history guide](execution-history.md).

## Rules for any change

- Server rule and browser mirror are written once each; keep them in step (`canFeed` mirrors `connect_error`).
- Colours only as tokens (`static/css/tokens.css`); class prefix `ge-` for the graph editor.
- No inline scripts in templates: the default Content-Security-Policy is `script-src 'self'`.
- Unused code is quarantined, not left behind (`quarantine.json`, see [CONTRIBUTING](../../.github/CONTRIBUTING.md)).
- Run `ruff`, `mypy` and `pytest` ([testing guide](testing.md)) before the change is done; run the browser
  tests before a push.
