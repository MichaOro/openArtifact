# Extending the application

The extension points that exist today are registries that the built-in parts use exactly as an extension
would ([ADR-014](../architecture/adr/014-building-blocks-and-extension-points.md)):

| Extension point | Registry | Section |
|-----------------|----------|---------|
| A kind of node | a manifest (`graph/nodes/*.yaml`, loaded into `NODE_TYPES` by `graph/node_types.py`), `EXECUTORS` (`engine/executors.py`) | [Add a kind of node](#add-a-kind-of-node) |
| A type of node setting | `Setting.validate` (server), `CONTROLS` (`static/js/editor/setting-controls.js`) | [Add a setting type](#add-a-setting-type) |
| A navigation entry | `SIDEBAR`, `ARTIFACT_RAIL` (`web/navigation.py`) | [Add a navigation entry](#add-a-navigation-entry) |
| A server-sent event | `EventBus.publish`, `EVENT_TYPES` (`static/js/tasks/events.js`) | [Add an event type](#add-an-event-type) |
| A dialog with fields | `form_modal` macro and `FormDialog` | [Add a dialog](#add-a-dialog) |

Loading third-party extensions (a plugin directory, entry points) is not built; these are the steps for a
change inside this repository. Wording: the UI says artifact, pipeline, stage and action; the code says
`task` for artifact and `graph` for how pipelines and action definitions are stored
([ADR-015](../architecture/adr/015-vocabulary-and-storage-names.md)). Never "workflow". The domain
vocabulary is in the [concepts guide](concepts.md).

All paths are below `openartifact/` unless stated.

## Add a kind of node

Worked examples in the code: the **timer** (`graph/nodes/timer.yaml`, migration `0016_timer_node.py`; its
setting is a column) and the **Code** and **HTTP** nodes (`graph/nodes/code.yaml`, `http.yaml`, `executors.py`,
`code_runner.py`, `http_runner.py`; their settings live in the `config` JSON). Use the second kind as the
model for anything new.

1. **Name the kind.** Add a member to `NodeKind` in `models/__init__.py`.
2. **Declare it as a manifest** (ADR-054): one file, `graph/nodes/<kind>.yaml`, and a line in `graph/nodes/_menu.yaml`
   (`kinds`, the order every list uses). The server loads it into a `NodeType` at start-up; a manifest that is not valid
   stops the start with its file name and what is wrong. See [A new kind is a manifest](#a-new-kind-is-a-manifest) below.
   `GET /api/node-types` then publishes the kind, and the repository, the connection rules, the settings validation, the "+"
   menu and the editor's card follow it. The editor needs no code for a kind of an existing behaviour.
3. **Migrate only if the schema changes.** Settings stored in `config` (`graph_nodes.config`, a JSON object
   merged and validated per key by `NodeType.merge_config`) need **no** migration. What does need one is the
   check constraint `ck_graph_nodes_kind` on `graph_nodes`, which lists the kinds: copy the pattern of
   `alembic/versions/0021_execution_nodes.py` (a batch alter that drops and recreates the constraint) and
   write the downgrade (it must remove nodes of the new kind, because the old constraint cannot hold them).
   Create migrations with `alembic revision -m "..."` (from the repository root). The model does not declare that
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
   `os.environ`. Keep new bounds once, in the manifest.
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

- A node that runs text it did not write needs the Execute Command node's safeguards or better: a bounded time, bounded
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

## Where a kind may be used: pipeline actions and guard actions

An action definition is for pipelines or for guards (ADR-067). A node manifest says in which: `purposes: [pipeline, guard]` (the
default, both), or `purposes: [guard]` for a kind that only a guard action may hold (a kind with access to internal data). The "+"
menu offers a kind only where it may be used, and the server refuses it anywhere else, so the manifest alone decides. `requires:
<right>` names the right a person needs to use the kind: a hook for planned per-person rights that nothing evaluates yet (today the personal settings decide what one sees and uses); set it when
a kind should be limited later, so the manifest does not have to change then.

### A data source for the SQLite node

The SQLite node reads **data sources** that the application registers by name (`Limits.data_sources`, `engine/sqlite_runner.py`
`DataSource`): a path, the **views a statement may read** (`readable`) and tables or columns it may never read (`denied`). There is no
field for a path in the node. An extension adds a source with its own views; a fixed floor (secrets, credentials, tokens, providers,
settings) holds for every source. List the choice in the manifest's `options` of the setting *Data source* (ADR-068).

## Where a setting goes in the node's dialog

Every setting says where it is shown (ADR-053); the dialog is drawn from that, so a new kind needs no layout code:

| Metadata | Values | Meaning |
|----------|--------|---------|
| `section` | `definition` (default), `behaviour` | The column: what the node *is* (left) or how it *runs* (right: timeouts, limits, failure handling). Two columns appear only when both have something, they stack when the dialog is narrow. |
| `level` | `core` (default), `optional`, `advanced` | How prominent: core is always shown; optional is shown once the node has a value and otherwise offered in *Add setting*; advanced is folded under *Advanced* and open while one of them has a value. A stored default is no configuration, so it does not keep an optional setting open. |
| `inherits` | `None` (default), `"agent"` | Only when a real parent supplies the value (today the agent): the row then shows *Inherited* / *Overridden* / *Not set*, an override is stored only when the user commits a value, and removing it restores inheritance. |
| `group` | any title | Settings of one group stay together: in *Definition* a group folds while unused (If conditions, Switch cases); in *Behaviour* it is a titled block (*Model & Generation*, *Execution limits*). |

Use `ON_FAILURE` for "If the node fails" (it is already `behaviour`; in a manifest `use: on_failure` takes the shared one), `GROUP_LIMITS` for timeouts and limits, and
`level="optional"` for anything most nodes of the kind never touch. A kind with something the shared layout cannot draw
(the Agent's choice of an agent and its input mapping) passes it as `extras` to `buildSettings`
(`static/js/editor/settings-layout.js`) and `skip`s those keys; it does not write a layout of its own.

## A new kind is a manifest

A manifest (`graph/nodes/<kind>.yaml`, `schema: 1`) *declares* a kind; it holds no code. `graph/manifest.py` is the schema
(pydantic) and the loader; `python -c "import json; from openartifact.graph.manifest import schema; print(json.dumps(schema(), indent=1))"`
prints its JSON Schema, which an editor can validate a file against.

| Field | Meaning |
|-------|---------|
| `kind`, `label`, `schema` | the `NodeKind` value, the name shown, the manifest version (1) |
| `behaviour` | how the kind connects and is drawn: `plain`, `flow` (a step of an action definition: On Pass / On Fail or branches), `tool`, and the structural `stage`, `action`, `pipeline`, `output`, `switch` |
| `scopes`, `fixed`, `addable`, `chain`, `ending`, `tool`, `links_to`, `default_size`, `reference_keys` | what the base `NodeType` knows (see the table of fields in ADR-054) |
| `guardable` | `true` for a kind that runs as a step of an action: a guard may be attached to such a node (ADR-060 addendum; the node's menu gets a *Guard* entry) |
| `menu` | `{group, order}`: the cluster of the "+" menu and the place in it (clusters and their order: `_menu.yaml`) |
| `ports` | `inputs` / `outputs` with `name`, `label`, `side`, `visible_when` (`{fn: ...}` or `{node: field}`), `label_from`, `repeat` |
| `menu_icon` | the glyph before the name in every menu that lists the kind (the "+" menus); without it the kind's `ui.icon` is used, and a kind must have one of the two (a test checks that it is an icon of `icons.html`). The card keeps its own look: a stage, a pipeline and a timer have no icon on their card but one in the menus |
| `ui` | `icon`, `size`, `port_labels`, `caption` (a template or a function), `block`, `size_fn`, `group_used_fn` |
| `settings` | the kind's settings: the fields of `Setting` (key, label, type, bounds, default, options, help, `stored_in`, `section`, `level`, `group`, `inherits`, `references`) and `check` |

What is *named*, not written:

- **Rules** (`check: <name>`): `graph/validators.py` (`VALIDATORS`): `url`, `status_spec`, `text_references`, `secret_names`,
  `not_secret`, `sql_query`, `repository`, ... A new rule is Python in `validators.py`, reviewed with the application.
- **Caption templates** (`ui.caption.template`): `{key}` (a setting), `{@field}` (a field of the node), `{key|filter}`,
  `{?flag:text}`; filters `default`, `trim`, `first_line`, `short`, `host_path`, `field_names` (`static/js/editor/caption.js`).
  `Postgres`: `"{?allow_write:changes · }{query|first_line|short|default:no query yet}"`.
- **Functions of the editor** (`static/js/editor/view-functions.js`, `CLIENT_FUNCTIONS` in `manifest.py`): captions, port
  visibility and labels, a size, which dialog groups are open. They exist for the If, Switch and Agent cards.

Two conveniences keep files short. `use: name` takes a setting from `graph/nodes/_shared.yaml` (the fields written beside it
win): `on_failure`, `operator`, `query`, ... A block `{repeat: N, settings: [...]}` (or a port with `repeat`) is written N
times with `{n}` for the number; `first:` holds what only the first copy has (a help text said once).

**A place held in the "+" menu.** Something that is not a kind of node but should already have an entry (*Guard*, before it
exists) is declared under `placeholders:` in `graph/nodes/_menu.yaml`, not as a manifest:

```yaml
placeholders:
- key: guard          # lower case; no kind and no other placeholder may have it
  label: Guard        # shown; a locale file may translate it: nodes.placeholders.guard.label
  icon: shield        # an icon of templates/components/icons.html
  group: Structure    # a cluster of `groups:` above
  order: 3            # its place in the cluster (Stage 1, Pipeline 2)
  scopes: [pipeline, action]   # in which editors it is offered
  soon: true          # shows the "Soon" tag
```

`manifest.read_placeholders()` validates the list (a bad entry is refused with `_menu.yaml` in the message). The editor page
carries it (`data-menu-placeholders`); `addableIn` still lists kinds only, so choosing a placeholder can never add a node: it
shows a notice. To build the feature later, give it a kind or a service of its own and remove the entry.

What a manifest cannot do: run code; add a kind that is not a `NodeKind` member and has no executor (kinds are rows of the
`graph_nodes.kind` constraint, ADR-054 §4); change how a structural behaviour connects. **Loading manifests from a directory
of the operator (for third-party kinds) is not enabled yet**: `node_types.load(directory)` already reads any directory, but
only the built-in one is loaded.

### A port that is there only with a setting

A port may carry `visible_when: {setting: on_failure, equals: error_output}`: it is shown, and the server accepts a connection at it, only
while the setting has that value (a setting that is not set counts as its default). This is how the error output of a kind works
([ADR-061](../architecture/adr/061-what-a-failure-does.md)): declare the setting once with `use: on_failure` and give the failure
output the `visible_when` above. A select may name the shown text of its options with `option_labels` (the stored value stays what
`options` says); a locale file overrides them with `nodes.<kind>.settings.<key>.options.<value>`.

### The card, the colour and what a node leaves behind

A new kind needs **no CSS and no editor code** to look like the others and to be found by the reference suggestions: the
manifest says it. The card's layout is keyed by the kind's `behaviour` (the editor sets `data-behaviour` on the card), not by
its name; its colour is `ui.color`, the name of a token `--node-<color>` in `static/css/tokens.css` (pick one that exists or add
yours there, built from the lane hues so both themes follow; `tests/test_node_manifests.py` fails for a colour without a token
or one that is a literal); its glyph is `ui.icon` (an icon of `icons.html`). Three more keys:

- `produces_result: true`: the node leaves `output` and `data` in the run context, so it is offered after `${(` in every
  reference field and in the mapping of an agent's inputs. A kind without it (a trigger, an output, a tool) has nothing to
  reference. `result_data: [comments, count]` lists keys of `data` it always leaves (offered as `${(Name).data.comments}`).
- `variables: {setting: sets_variables, format: lines}`: the run variables the node sets are read from that setting
  (`lines`: one name per line; `assignments`: the names before the `=` of `name = value` lines) and offered as `${var.name}`.
- `timed: true`: the flow panel of an execution shows how long a step of this kind took. `ui.step_icon` overrides the
  glyph of its step in the history when it should differ from the card's.

### The texts of a kind

The labels, helps, placeholders, options and ports of a manifest follow one short rule, kept by `tests/test_node_texts.py` for the
English text and for the German overrides (a language may be a quarter longer); the rule and its reasons are in the
[UI catalog](ui-catalog.md#texts-of-a-node). A text that needs more says why in `ALLOWED` of that test.

## Add a setting type

A setting is one `Setting(key, label, type, ...)` in a node type. The types are `integer`, `number` (whole or
decimal), `switch`, `text` (one line), `lines` (several lines), `code` (source code, monospace) and `select` (one of
`options`). Settings are bounded by `minimum` / `maximum` (integers and numbers), `max_length` (texts; the default is 2000 for `text` and 20000 for `lines` and `code`) and `options`; `check` is an extra validation function for a text (not sent to the editor;
raise `SettingError`); `placeholder` and `help` are shown in the inspector. `Setting.validate` is the one
place that decides whether a value fits. Using an existing type needs only the `Setting` entry.

A new type:

1. Add its branch to `Setting.validate` in `graph/node_types.py` (and the type to `SettingSpec.type` in `graph/manifest.py`) (and to `describe`, if it publishes more), and its
   default length to `_DEFAULT_MAX_LENGTH` if it is a text. There is no list of type names besides that: a type is
   what `validate` accepts.
2. Add a control class to `static/js/editor/setting-controls.js`: subclass `SettingControl` (or
   `LinesControl`), implement `createInput(value)` (and `read`, `parse`, `hint` if the value is not the
   input's text), and list it in `CONTROLS`. A type the browser does not know is shown as a text field.
3. Test the validation in `tests/test_execution_nodes.py` (or `tests/test_graphs.py`) and, if the control has
   behaviour, in an e2e flow.

## Add a management page

A page that lists definitions (pipelines, actions, agents, guards) is a page script and a manifest, not a new layout (ADR-069):

1. The template has one `<div data-management>` and the stylesheet `management.css` (see `graph_list.html`).
2. The script builds a `ManagementPage` (see the UI catalog, *Management pages*): what an entry is (`itemKey`, `search`, `tagsOf`, `sorts`), what
   a card shows, the chips and the tabs of the panel, and what open, edit and delete do. Selecting, the keys, cards or list, paging (the page size follows the room of the list, ADR-069 §12: a page passes
   no number of entries) and the sheet on a narrow screen come from the component.
3. A tab that is not built is `disabled: true` (greyed). The window that makes or changes an entry is a form manifest (`ui/forms/<name>.yaml`, ADR-065).
4. Show the picture of a graph in the panel (tab Graph) with `GraphPreview` and a scene from `sceneOfGraph(detail, isTool)`; give a new kind of picture a
   function that returns `{columns, links}` rather than a layout of its own.

## Add a navigation entry

Navigation entries are registered in the `NavigationRegistry` (see [ADR-066](../architecture/adr/066-modular-navigation.md)). The
application holds one at `app.state.navigation` (built by `build_registry()` in `web/navigation.py`); the pages draw it at every
request, so the sidebar, the rail of the artifact dialog and the active entry all come from it.

1. **Register the entry** with `registry.register(entry, parent=..., order=...)` (lower order = earlier):
   - Page: `NavLinkEntry(key, icon, href, paths=(), visible_when=None)`; `paths` are further path prefixes that belong to it
   - Runtime group: `NavGroupEntry(key, icon)`; artifact field: `NavFieldEntry(key, icon, dot=True)`; command:
     `NavActionEntry(key, icon, danger=False)`; line: `NavDividerEntry(key)`
   - `parent`: `SIDEBAR` (top level), the key of a link (`"pipeline"`, `"settings"`) or `"rail:fields"`, `"rail:custom"`, `"rail:actions"`
   - A key is registered once in the sidebar (and once per rail group): a duplicate raises. For a shipped entry add it to `build_registry()`.
2. **Texts.** `nav.<key>.label` and `nav.<key>.tooltip` in `i18n/locales/en.json` and `de.json`; the registry holds no texts.
3. **Icon.** An existing icon name, or add the SVG to `templates/components/icons.html` and its name to `icon_names`.
4. **Page.** A `NavLinkEntry` needs a route in `web/routes.py` that renders a template. Do **not** pass `active_nav`: the entry
   whose `href`/`paths` is the longest prefix of the path is active, derived by the registry. A page that has no entry fails
   `tests/test_navigation_modularity.py` unless it is listed there with a reason.
5. **Visibility.** Optional `visible_when=lambda context: ...` (a plain function of `{"path": ...}`; no expression string, no
   user, no rights). A predicate that raises hides the entry and is logged.
6. **Markup.** If the entry needs a new kind of markup, add it to `components/nav.html`; the `kind` of the entry picks the branch.
7. **Test it.** Register a fresh registry in a test (`build_registry()`), see `tests/test_navigation_modularity.py`; `tests/e2e/` for behaviour.

## Add an event type

The application pushes changes to every open browser through one stream (`GET /api/events`, server-sent
events, `events.py`). The bus is in-process and does not replay: a browser that reconnects loads the current
state from the REST API.

1. **Publish after the commit**, from the service or engine that changed the data:
   `bus.publish("thing.updated", {...})` with a JSON-serialisable payload (`model_dump(mode="json")`).
   The existing types are listed in the docstring of `stream_events` (`api/events.py`). Name events
   `noun.verb`, pass the name as a string literal or a module constant (the contract test reads it from the
   code), send enough data to update the view without a second request, and never put secrets or outputs
   in them.
2. **Subscribe in the browser.** Add the type to `EVENT_TYPES` in `static/js/tasks/events.js` (the client
   only listens to the types in that list; the browser drops any other name without a trace) and handle it
   in the `onEvent` callback of the page that cares (`tasks/main.js`, `executions/page.js`,
   `execution/flow-page.js`), comparing `type === "thing.updated"`. An event no page needs goes into
   `SERVER_ONLY` of `tests/test_event_contract.py` with the reason instead.
3. **Document it** in the docstring of `api/events.py` and in the arc42 chapter on the event stream.
4. **Test it.** `tests/test_event_contract.py` fails when a published name is missing from `EVENT_TYPES`,
   when `EVENT_TYPES` names something nothing publishes, or when a page handles a name that is not listened
   to. Server: the `published` fixture of `tests/conftest.py` records every published event; assert on it.
   Browser: wait for the effect, not for a time (see the [testing guide](testing.md#waiting)).

## Use the UI catalog

A control is picked from the catalog, not styled: buttons, icon buttons, chips, tabs, menus and the other building blocks are
listed in the [UI catalog](ui-catalog.md) with the tokens for both themes, and `tests/e2e/test_ui_catalog.py` fails for a
button that is not a catalog component or cannot be read ([ADR-059](../architecture/adr/059-one-catalog-of-ui-building-blocks.md)).

## Add a language or a text

Every text the interface shows is a key of `openartifact/i18n/locales/en.json` (`t(...)` in a template, `t(...)` from
`static/js/i18n.js` in a script); a new language is one more file. A new setting or kind of node needs no key: the manifest
is the English text and a locale file may override it. See [Languages](i18n.md) and
[ADR-056](../architecture/adr/056-internationalisation.md); `python3 tools/check_i18n.py` must stay clean.

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

## A configuration window is a manifest

**This is the rule for every new window and overlay that asks for something** ([ADR-065](../architecture/adr/065-every-window-is-a-form-manifest.md),
binding for people and AI agents alike): its form is a manifest, never hand-built markup. A handmade window is only allowed as a
named exception with a reason (a question, a display-only window, a picker or a name dialog); the exceptions are listed in
`tests/test_window_rule.py`, which fails for a window that is neither. Existing handmade windows move when they are touched.

The form of a window that configures something (a guard, a credential, later a provider, a retention rule) is data, like
a node kind ([ADR-062](../architecture/adr/062-configuration-windows-as-data.md)): you describe it in YAML and one
component draws it, in two columns where there is room, with the help in tooltips and the errors under the fields. The
frame around it (the title with the name renamed in place, "Used in N places", tabs, Save and Cancel) is yours. A question
("Delete it?") is not a form: use `confirm-dialog.js`.

**1. Describe the form** in `openartifact/ui/forms/<name>.yaml` (the file name is the form's name; a bad file stops the
start and names itself). The shipped example is `guard.yaml`:

```yaml
schema: 1
name: demo
columns: 2          # a wide window has two columns, a narrow one always one
width: 50           # rem: the form's width on a wide window (else the columns take what their content wants)
sections:
  - key: trigger
    title: Trigger
    column: 1       # 1, 2, auto (the column with less weight) or full (a row across the whole width)
    fields:
      - key: trigger.type          # a dotted path into the values: values.trigger.type
        widget: choice
        label: Trigger
        hide_label: true           # the section title says it; the label stays for screen readers, a help goes next to the title
        options: [{value: event, label: On an event}, {value: interval, label: Every few seconds}]
      - key: trigger.every_seconds
        widget: number
        label: Check every (seconds)
        min: 1
        default: 60
        help: One or two short sentences, shown in a tooltip.
        visible_when: {field: trigger.type, equals: interval}   # or in: [a, b]
      - key: trigger.cooldown_seconds
        widget: number
        label: Quiet after firing (seconds)
        advanced: true             # folded behind "More options"
```

| Part | Says |
|------|------|
| section `weight` | How much room it takes when `auto` sections are balanced between the columns (default: its visible fields) |
| field `required`, `min`, `max`, `step` | Checked by `form.validate()` for the fields that are there; the message sits under the field |
| field `config` | Free settings of the widget (`max_length`, `rows`; a rule tree names its schema); `depends_on: [key, ...]` draws the form again when one of those values changes |
| field `options` | The choices of `select`, `choice` and `chips`; `config: {options_from_code: name}` leaves them to the window (`overrides`) |

**2. Pick the widgets.** Built in (`components/form-widgets.js`): `text`, `number`, `textarea`, `select`, `choice` (one of
a few, as chips), `chips` (several, ticked), `switch`, `readonly`. What needs code is a **custom widget** registered
once, in the browser and on the server, so a manifest may name it:

```js
import { registerWidget } from "../components/form-widgets.js";
registerWidget("colour-picker", (ctx) => {
  // ctx.field (the manifest's field), ctx.value (a copy to edit), ctx.options, ctx.context (what the window handed over),
  // ctx.get(key) / ctx.set(value[, key]), ctx.id; return the element and the control the label belongs to (or null)
  const input = Object.assign(document.createElement("input"), { type: "color", value: ctx.value ?? "#000000" });
  input.addEventListener("input", () => ctx.set(input.value));
  return { el: input, control: input };
});
```

```python
from openartifact.ui import forms
forms.register_widget("colour-picker")   # before the manifests are read: a manifest naming it is valid
```

A test (`tests/test_forms.py`) checks that every widget a shipped manifest names is registered in the browser. The guard
form's three custom widgets (`rule-tree`, `escalation-steps`, `action-picker`) are in `guards/widgets.js`.

**3. Draw it in your window:**

```js
const manifest = await request("/api/forms/demo");          // in the language of the page
const form = new FormView(host, {
  manifest, values: state,                                  // the form edits `state` (nested keys by path)
  context: { ruleSchema, actions },                         // data for your custom widgets
  overrides: { consequence: { options: [...], help: "..." } }, // what the code decides for a field
  normalize: (values, key) => { /* keep values consistent after a change */ },
  onChange: () => scheduleAPreview(),
});
if (!form.validate()) return;                               // marks what breaks a limit
form.setErrors({ "trigger.events": "Choose one" });          // a message of the server under its field
```

**4. Texts and German.** The manifest is the English source. German (and any language) overrides single texts in
`locales/<language>.json` by key: `forms.demo.sections.trigger.title`, `forms.demo.fields.trigger.every_seconds.label` /
`.help` / `.placeholder`, `forms.demo.fields.trigger.type.options.event`. What a language does not name stays English.
`tests/test_forms.py` fails for an override that names nothing and for a text of a shipped form that German lacks.

**Migrated:** the guard editor (`guard.yaml`) and the credential window (`credential.yaml`: one field per field of every credential
type, declared with `visible_when` on the type; a secret is a `text` field with `config: {secret: true}` and a field that cannot change
has `config: {readonly: true}`; `tests/test_forms.py` keeps it the same as `credentials/types.py`).

**Windows that could move to a manifest** (the owner schedules them, or a change that rebuilds one moves it): the retention rule (small:
`rule-tree` and `select`; its title already carries the name), lane settings (small: `text` and `choice`), run limits (small:
numbers), the LLM provider dialog (medium: `text`, a credential chooser and a model list), the artifact fields dialog (medium: a `rows` widget
with add, remove and order), the *create artifact* dialog (medium: the artifact fields are dynamic). Not a form: the name
dialogs (*New*, *Rename*, *Add lane*: change them so the name is the title, binding rule 3) and the agent version view
(display only). The node settings dialog already has its own data (ADR-053/054); making it use `form-view.js` is a larger
step.

## Rearranging a window

A window whose form is a manifest (a form under `ui/forms/`, a node kind under `graph/nodes/`) can be rearranged by the
person who runs the application ([ADR-063](../architecture/adr/063-rearranging-manifest-windows.md)): the handle on the top
edge of the window opens a menu with *Edit layout*; the sections and fields can be dragged (or moved with the arrow keys),
the arrangement is saved for the whole instance and can be reset or exported. As the author of a window you need only this:

- **Give every section and field a stable key.** The layout refers to them by key; a key you rename or remove is ignored in
  a saved layout, a key you add appears where the manifest puts it (after the field before it). Never reuse a key for something else.
- **A `full` section stays full width**, and a **required field is never folded away**: a layout that tries is refused.
- **Nothing else changes with a layout:** no labels, no widgets, no visibility, no values. Those are the manifest's.
- **A node kind's window** has two areas, `definition` and `behaviour`, and the person who runs the application may add areas
  of their own. A setting may sit in any of them (only its place changes: its level, validation and inheritance are yours). The
  rows of one `group` move as one entry. A block the kind draws itself (the Agent's choice of agent and inputs) is *fixed*: list it
  in `static/js/editor/node-layout.js` (`OWN_BLOCKS`: its name and the setting keys it draws itself) **and** in `FIXED_BLOCKS` in
  `openartifact/ui/layout.py`, so the server refuses it in a layout.
- **Areas of one's own** are `custom_<id>` with a plain title (1 to 40 characters, at most 12 per window kind), only
  containers, and are stored in the layout layer. In a form manifest the same can be written as an ordinary section with a
  literal `title`; the manifests of node kinds know `definition` and `behaviour` only, so custom node areas stay in the layer.
- **To make an arrangement the default**, use *Export as YAML* in the layout menu (or `GET /api/ui-layouts/<kind>/<name>/export`)
  and copy the order into the manifest in the repository: sections in order with their `column`, fields in order, `advanced`
  as exported. A new window needs nothing: the form renderer and the settings dialog put the handle on every manifest
  window; a window that is not a manifest has none.

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
