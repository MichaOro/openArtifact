# Research and Design Proposal: One Configuration Experience for Every Node

**Date:** 2026-11-23  
**Status:** Approved and implemented as [ADR-053](architecture/adr/053-canonical-node-configuration.md) (see there for the deviations from this proposal). This document is the research baseline.  
**Scope:** The settings dialog of a node (Agent, If, Switch, HTTP request, Code, Edit Fields, GitHub, Postgres, the tools), the schema behind it, and what the Agent mockup (two columns, progressive disclosure, inheritance) can become for all of them.  
**Vocabulary:** The task text says *Action*. In this repository an **action** is an action *definition* (a graph of nodes); the things with settings are **nodes** (`graph/node_types.py`: `NodeType`, `Setting`). This document uses *node* where the code does and *action* only for the definition.

How to read the labels: **[Fact]** is confirmed in the repository (with a path), **[Proposal]** is a design decision proposed here, **[Recommendation]** is advice where the evidence leaves room, **[Open]** needs the owner.

---

## A. Executive Summary

1. **There is already a canonical schema, and it is the right one to extend.** A node's settings are declared once on the server as `Setting` objects of a `NodeType` (ADR-022), validated there, sent to the browser by `GET /api/node-types`, and drawn by `setting-controls.js`. The browser contains no list of fields. **[Recommendation]** Do not introduce a second schema or a generic form engine: add three small pieces of metadata to `Setting` (where it goes, how prominent it is, what it inherits from).
2. **What is missing is not a schema but a shared *shape*.** Today the dialog is one column; nodes with settings render them as a flat list (`blocks.settings`, `editor/inspector.js:70`), the Agent node has its own renderer with its own override rows (`editor/agent-inspector.js`), and every other kind decides alone how much it shows. The mockup's value for the rest of the system is: *definition on the left, behaviour on the right, optional things behind "Add", inherited things shown as inherited*.
3. **Inheritance exists in exactly one place today: the Agent node inherits from its agent** (`agents/resolve.py`, ADR-046). No other node kind has a parent that supplies defaults (Run limits, ADR-039, are global limits of an execution, not defaults of a node). So "inherited / overridden" is a *capability of a setting* (`inherits`), not a universal state every field has. **[Recommendation]** Build the shared override row for it, use it for the Agent now, and let other kinds adopt it only when they get a real parent.
4. **The two-column layout is right for a few kinds and wrong for most.** Agent, HTTP request and Code have both a definition and enough behavioural settings to fill a right column. If, Switch, Timer, Edit Fields have almost no behaviour settings and a left column that is long and repetitive. **[Proposal]** The layout is *derived from the data*: a right column exists only when at least one setting belongs to the `behaviour` section; otherwise one column. Narrow dialogs stack.
5. **Four things in the mockup conflict with repository decisions and should not be copied:** a *Save changes* button (settings are saved as they are changed, ADR-022 and `editor.js`), a solid red *Delete* button (ADR-036: solid red only confirms inside a confirmation dialog), an *Add input* button in the node (a node maps the inputs its agent declares; it cannot declare them), and override rows that copy the parent's value (ADR-046: a set value is explicit, and removing means *not set*). Details in section G.
6. **Smallest sensible path:** (1) metadata on `Setting`, no visible change; (2) a generic two-column renderer in `InspectorBlocks.settings` with the existing single-column fallback; (3) one shared override row replacing `ag-override` and reusing `SettingsGroup`; (4) move HTTP/Code optional settings behind *Add setting*. Each step ships and is tested on its own; none needs a migration.

---

## B. Current State Analysis

### B.1 What is generic already

| Concern | Where | Fact |
|---|---|---|
| Declaration of a node kind | `openartifact/graph/node_types.py` `NodeType` (kind, label, `scopes`, `fixed`, `addable`, `chain`, `tool`, ports, `settings`, `links_to`, `reference_keys`) | **[Fact]** One class per kind, registered with `register()`; `describe()` is what the editor loads. |
| A setting | same file, `Setting` (`key`, `label`, `type` integer/number/switch/text/lines/code/select, bounds, `options`, `default`, `placeholder`, `help`, `stored_in` column/config, `check`, `group`, `references`) | **[Fact]** Validation (`Setting.validate`) is server-side only; `check` rules are not sent to the browser. |
| Storage | `graph_nodes.config` JSON (migration 0021, ADR-022); `seconds` and `fail_enabled` stay columns | **[Fact]** `merge_config` validates per key; `null` removes a key. |
| Controls | `static/js/editor/setting-controls.js`: `SettingControl` and one class per type (`IntegerControl`, `NumberControl`, `SwitchControl`, `TextControl`, `LinesControl`, `CodeControl`, `SelectControl`), `createControl(setting, value, save, suggest)` | **[Fact]** Controls save as the user works (multi-line after 800 ms, `AUTOSAVE_MS`) and show the server's refusal under the field. |
| References and suggestions | `Setting.references` (`"context"` or `"all"`), `editor/reference-suggest.js` | **[Fact]** Which fields take `${…}` is declared on the setting. |
| Groups of fields | `Setting.group` (If: *Condition 1…5*; Switch: *Case 1…6*; HTTP) → `details.ge-group` with "(empty)" in the summary (`inspector.js:76-95`, `NodeView.groupUsed`) | **[Fact]** The only existing progressive disclosure in the node dialog: a folded group per unused row. |
| Failure handling | `ON_FAILURE` (`node_types.py:497`): *If the node fails* = `fail` / `continue`, on Code, HTTP, Edit Fields, Agent, GitHub, Postgres | **[Fact]** One shared setting, already canonical for the kinds that do work and do not branch. |
| The dialog | `templates/graph_editor.html` `#node-modal`, `editor.js` `#openSettings`, `inspector-panel.js` | **[Fact]** Since this session the settings open in an overlay (double click, Enter), one title (renamed in place), saved at once. The panel is `min(52rem, 100vw − …)` wide (`css/editor.css`, `#node-modal`). |
| UI building blocks for optional settings | `components/settings-group.js` (`SettingsGroup`, `numberSetting`: a default always applies, a setting is a field once added, the bin = *not set*), `options-panel.js`, `switch.js`, `tabs.js`, `action-menu.js` | **[Fact]** ADR-045 and ADR-046, used by the agent editor page. |
| Identity | `.identity` (ADR-048): icon, name with badges, description, inline editing (`InlineName`) | **[Fact]** Used by the agent and the pipeline/action pages. |
| Rules of dialogs and controls | ADR-029 (dialog hierarchy), ADR-036 (primary = purple, destructive = `is-danger`, solid red only to confirm, neutral never coloured) | **[Fact]** |

### B.2 What is specific to one kind

| Kind | How its settings reach the screen |
|---|---|
| Agent | A dedicated renderer: `AgentBlock` (`agent-inspector.js`). The node holds `agent_id`, an `inputs` mapping and eleven override settings declared with `_override(...)` (`node_types.py:893-994`); the browser keeps its own list of them, `OVERRIDES` in `agents/model.js:6` (key, label, kind, bounds) **[Fact: this duplicates the server's declaration, against ADR-022's "the browser contains no list of fields"]**. Rows are `ag-override`: label, chip *From agent* / *Overridden*, a button *Override* / *Reset*, and "Agent: value" (`#override`, `agent-inspector.js:~207`). *Reset all N overrides* below. |
| If | `_if_settings()`: five condition rows (value, operator, compare with) as `Setting`s of groups *Condition n*, plus *combine* (all/any) and *case sensitive*. Generic rendering. |
| Switch | A *Value*, six *Case n* groups (operator, compare with), *Case sensitive*. An unused case has no output (`switch_case_used`). Generic rendering; the kind adds `groupUsed`. |
| HTTP request | method, URL, headers, body, `timeout_seconds`, `success_status`, `on_failure`; references on URL, headers, body. Generic flat list in the order declared. |
| Code | language, code (with the Tab/Escape handling in `CodeControl`), `secrets`, `sets_variables`, `timeout_seconds`, `on_failure`. Flat list. |
| Edit Fields, GitHub, Postgres, Timer, the four tools | Flat lists; GitHub and the tools hide or show fields by operation or mode in code. |

### B.3 Facts that decide the design

- **[Fact]** Only the Agent node has a parent that supplies defaults. `resolve.py`: *a node's setting that is not set (`None`) is inherited from the agent; one that is set overrides that field only*. A change of the agent reaches every node that does not override the field, because resolution happens when an execution starts (the snapshot freezes the result). The server tells the editor the effective state of each field: `SettingState {key, value, inherited, overridden}` in `PreviewRead` (`agents/schemas.py:308`).
- **[Fact]** ADR-046 settled the wording: a default always applies, a setting only overrides it; *removing is "not set"*, never "reset to default"; a stored value is explicit even when it equals the default.
- **[Fact]** Today an override **starts as a copy** of the inherited value where there is one (`#startValue`, `agent-inspector.js`), so the stored value equals the parent's until edited. After that it no longer follows the parent. This is the one place where the repository does not meet the task's "overrides are additive, not copies" literally (see G).
- **[Fact]** On the agent *page* (not in the node dialog) the optional settings already use the ADR-046 pattern: cards with *Add setting*, an empty field shows its default grey, the bin says "Use the default again". The node dialog shows all eleven agent settings as rows with an *Override* button instead. The two screens express the same idea in two ways.
- **[Fact]** Settings are saved immediately. There is no Save/Discard in the node dialog; the agent page has draft/publish (ADR-037) because an agent is versioned, a node is not.
- **[Fact]** There is no responsive concept for the node dialog beyond `modal.css` (padding at narrow widths) and the `min()` width; the ADR-029 sizing rule (height from content, width 34.75 rem to 800 px) belongs to the artifact dialog.

---

## C. Design Principles

Derived from the mockup and checked against the repository.

1. **One shape, many contents.** Every node's settings dialog is: *identity* (header), *definition* (what this node is), *behaviour* (how it runs), *advanced* (rarely needed), with the sections present only when the kind has something for them. A user switching from Agent to HTTP finds the same places for the same kinds of things.
2. **The essential first.** What a node cannot work without is always visible and never behind a click. Optional and advanced settings are *offered* (an "Add setting" menu, a folded group), never hidden without a way to find them (ADR-045/046).
3. **A default always applies; a setting only overrides it** (ADR-046). Not set is a state, not a value. Nothing is stored for what is not changed.
4. **Inheritance is a property of a setting, shown the same way everywhere it exists.** Where a setting has a parent, the row says where the value comes from and lets the user take over and give back. Where it has none, nothing pretends otherwise.
5. **Group by responsibility, not by storage.** *Model & Generation* and *Execution limits* are agent-specific groups of one canonical section (`behaviour`); *If the node fails* is canonical and shared.
6. **Do not force one look onto different content.** Conditions, cases, headers and prompts are repeating or long content; they keep their own presentation inside the *definition* section.
7. **The destructive action is where it always is, and quiet** (ADR-036): `is-danger`, never solid, never the first thing in reach.
8. **Reuse before building:** `SettingsGroup`, `OptionsPanel`, `Switch`, `InlineName`, `Modal`, `.identity`, `ActionMenu` already exist and already express these principles.

---

## D. Canonical Configuration Schema

### D.1 Proposal: extend `Setting`, do not replace it

The seven areas of the task map onto what exists like this:

| Task area | In the repository today | Proposal |
|---|---|---|
| 1 Identity (name, type, metadata) | `graph_nodes.name`, `kind`, `NodeType.label`; header with the editable title | unchanged (the node's type shows as a caption/chip, see E.2) |
| 2 Primary configuration | `Setting`s of the kind | `section = "definition"` (default) |
| 3 Inputs | Agent: `inputs` mapping (`references="context"`); If/Switch/HTTP: values with `references` | stays *definition*; the references mechanism is already shared |
| 4 Content (prompts, scripts, expressions) | `lines` / `code` settings | `section = "definition"`, long types take the full width |
| 5 Execution (timeouts, limits, retries, failure) | `timeout_seconds`, agent limits, `ON_FAILURE` | `section = "behaviour"` |
| 6 Optional overrides | Agent only (`_override`) | `inherits` (below) + the shared override row |
| 7 Advanced | none declared; partly implied by `group` | `level = "advanced"` |

Three optional fields on `Setting` and one on `NodeType`. All are optional, so existing kinds and persisted configurations are unaffected, and `describe()` only *adds* keys (the contract `Setting.describe` already follows: "the old keys keep their meaning, new ones are only added").

```python
@dataclass(frozen=True)
class Setting:
    ...                       # key, label, type, bounds, default, stored_in, check, group, references: unchanged
    #: Which part of the dialog the setting belongs to. "definition" (default): what the node is.
    #: "behaviour": how it runs (timeouts, limits, retries, failure handling).
    section: str = "definition"
    #: How prominent it is. "core": always shown. "optional": shown once added ("Add setting").
    #: "advanced": folded under "Advanced"; offered like an optional one when opened.
    level: str = "core"
    #: Where a value that is not set comes from, by name of the parent ("agent"). None: it has no parent;
    #: not set then means the default of the setting.
    inherits: str | None = None
```

```python
class NodeType:
    ...
    #: Titles of the groups the kind's settings fall into inside a section (Agent: "Model & Generation",
    #: "Execution limits"). A setting names its group with the existing `Setting.group`.
```

A typed example (HTTP request, abridged; the values are the repository's today, only `section`/`level` are new):

```python
Setting("method", "Method", "select", default="GET", options=HTTP_METHODS, stored_in="config")            # definition, core
Setting("url", "URL", "text", ..., references="all", stored_in="config")                                  # definition, core
Setting("headers", "Headers", "lines", ..., references="all", stored_in="config", level="optional")
Setting("body", "Body", "lines", ..., references="all", stored_in="config", level="optional")
Setting("timeout_seconds", "Timeout (seconds)", "integer", ..., section="behaviour", level="optional")
Setting("success_status", "Accepted status codes", "text", ..., section="behaviour", level="advanced")
ON_FAILURE  # section="behaviour", level="core"   (one shared setting, defined once)
```

### D.2 The four states of a setting

A setting's state is computed from data that already exists; nothing new is stored.

| State | Meaning | How it is known today |
|---|---|---|
| **Set** (overridden) | The node has its own value | `config[key]` present (`overrides_of`) |
| **Inherited** | Not set, and the setting has a parent that supplies a value | `SettingState.overridden == false`, `inherited` holds the value |
| **Default** | Not set, no parent: the setting's default applies | `config` lacks the key; `Setting.default` |
| **Unavailable / not configured** | Not set, and there is nothing to apply (a parent without a value, `inherited = null`; a required field empty) | `inherited is None` and no default (Agent: "not set") |
| *(Optional-off)* | Supported but not added to the dialog yet | a presentation state of an `optional` setting that is not set |

Rules (all **[Fact]** for the Agent, **[Proposal]** as the general contract): an override stores only the changed key; clearing removes the key (`merge_config(None)`); resolution happens when an execution starts, so changing the parent reaches every node that does not override; nothing is copied into the node except when the user takes over a value (see E.5).

### D.3 What the browser gets

`GET /api/node-types` already carries `settings[]`; it would carry `section`, `level`, `inherits` additionally. For inheritance the **values** come from the existing effective-state call (today `POST /api/agents/{id}/preview` → `settings: SettingState[]`). **[Recommendation]** Keep that call as the one source of the inherited value; do not duplicate parent defaults in the node description. If a second parent appears later, generalise the call; do not pre-build it.

### D.4 Conditional visibility

Today it is code in the view (`isVisible` for ports, `groupUsed` for groups, GitHub's operation-dependent fields). **[Recommendation]** Keep it in the kind's view class. A declarative `visible_when` would be a small expression language to maintain for four or five uses (GitHub operation, Postgres write switch, MCP tool mode, Switch case used); it is not justified by the evidence. Revisit if a sixth kind needs it.

### D.5 What is not proposed

No JSON-Schema layer, no form engine, no per-kind layout files, no new storage. The three fields above are the whole schema change.

---

## E. Canonical UI Specification

### E.1 Structure of the settings dialog

```
┌──────────────────────────────────────────────────────────────────────┐
│ [icon]  Node name (click to rename)   [type chip]  [status chip]  ✕  │  identity (.identity, ADR-048)
├───────────────────────────────────┬──────────────────────────────────┤
│ DEFINITION (left)                 │ BEHAVIOUR (right)                │
│  the kind's own settings          │  groups of the kind, e.g.        │
│  inputs / references              │   Model & Generation             │
│  prompts, script, conditions      │   Execution limits               │
│                                   │  If the node fails  (shared)     │
│                                   │  [Add setting ▾]  (optional ones)│
├───────────────────────────────────┴──────────────────────────────────┤
│ ▸ Advanced                                                           │  only if the kind has some
├──────────────────────────────────────────────────────────────────────┤
│ New (kind specific)                                  Delete (quiet)  │
└──────────────────────────────────────────────────────────────────────┘
```

- **Identity:** the title is the one inline-editable name already in the dialog; the kind appears as a quiet caption/chip (today `heading()` shows the caption when it differs from the name). A *status chip* ("Configured" in the mockup) is **[Open]**: it needs a per-kind rule for "configured" (the Agent node already computes problems and status, `#status`); for most kinds it would be an empty claim.
- **Columns:** a right column is drawn only if at least one setting has `section = "behaviour"`. Otherwise the definition uses the full width. Neither column is padded to match the other; each is its own flow, aligned at the top.
- **Widths and breakpoints [Proposal]:** two columns need roughly 56 rem; the dialog is `min(52rem, …)` today. Proposed: `min(64rem, 100vw − gutters)` **only when** the node has a behaviour column, `min(44rem, …)` for one column (a single column of long fields reads better narrower). Below 48 rem the columns stack, definition first.
- **Long content** (`lines`, `code`, prompts, the Agent's inputs table) always takes the full width of its column and may grow (existing behaviour).
- **Footer:** *New* where the kind has it (action shell, pipeline node, stage: unchanged), *Delete* as `is-danger` ghost at the left, no *Save* (settings are saved as they change, see G). The dialog's close button stays top right on the title's line.

### E.2 Sections and groups

- **Canonical sections (shared by every kind):** *Definition*, *Behaviour*, *Advanced*. These three names are the contract.
- **Canonical shared group:** *If the node fails* (`ON_FAILURE`), placed last in *Behaviour*, with its help text underneath (as in the mockup). It exists on six kinds already.
- **Kind-specific groups inside a section:** the Agent's *Model & Generation* and *Execution limits* (the same two cards ADR-046 gave the agent page), Switch's *Case n*, If's *Condition n*. A group is a title and its settings; it folds when unused (existing `details.ge-group` behaviour).
- **Shared title style:** a group title is a small heading with an icon where the kind has one (mockup: Model & Generation, Execution Limits); the icons exist in `icons.html` or are added once.

### E.3 Progressive disclosure

1. *core* settings: always visible.
2. *optional* settings: not shown until added. The right column ends with one **Add setting** menu listing what is not added, each entry with its default, exactly `SettingsGroup`'s behaviour (ADR-046: "Node time limit · default 600 s"; the field shows the default grey; the bin says "Use the default again"). `SettingsGroup` already supports this; it needs to be fed from `Setting` metadata instead of from a hand-written list.
3. *advanced* settings: folded under *Advanced* (a `details`), closed by default, opened for good while any of its settings is set (so a configured setting is never hidden).
4. A setting that has a value is **always** visible, whatever its level. Disclosure hides what is unused, never what is configured.

### E.4 Field presentation

Label above the field; one help line below (the `help` of the setting, already shown for several fields); the error under the field in place (`field__error`, already how controls show a refusal); placeholder is an example, the default is shown as the grey value of an empty optional field. A `required` field that is empty shows the existing "no X yet" caption on the node card, and the dialog marks it (the Agent block's problem list is the model).

### E.5 Inherited and overridden

For a setting with `inherits`, the row shows its state with one vocabulary:

| State | Row |
|---|---|
| Inherited | label · chip **Inherited** · the effective value in the muted style, with the source ("Agent: 0.2") · action *Override* |
| Overridden | label · chip **Overridden** · the control with the node's value · muted line "Agent: 0.2" · action *Use the agent's value* (the bin) |
| Not set / unavailable | label · chip **Not set** · "not set" muted · action *Set a value* |

- **Activating** an override puts the control in place and starts with the parent's value *as a suggestion in the field* (the Agent block does this today). **[Open]** whether that value is saved the moment the user clicks *Override* (today) or only once the user changes it. The task text says overrides must be additive, not copies; storing the copy at the click means a later change of the parent no longer reaches the node although the user never chose a value. **[Recommendation]** save nothing until the user commits a value (Enter or leaving the field), which keeps "Override" a no-op if abandoned. This needs one change in `#startValue` semantics.
- **Removing** an override deletes the key (`null` → `merge_config`) and the row returns to *Inherited*. The word is *use the agent's value*, in line with ADR-046's "unset", not "reset".
- **Wording:** the chip *Inherited* replaces today's *From agent* (the source is named next to the value). **[Open]** small, cosmetic, but it is a visible change.
- **Reset all** (*Reset all N overrides*) stays where it is today, at the end of the behaviour column.
- **Propagation** needs nothing new: resolution is at the start of an execution.

### E.6 Validation and errors

Server-side only (`Setting.validate`, kind `check`), shown under the field that was refused, never as a toast; the node card carries a hint when the node cannot work (existing hints from `connect_error`, reference checks, the Agent problem list). A refused value leaves what the user typed in place (existing behaviour, `editor.js` `#saveSetting`). The dialog does not block closing on an invalid field (the setting was not saved; the server still has the old value).

### E.7 Empty and unconfigured states

A kind with no settings (Trigger, Complete) opens a dialog with its identity and a one-line note, no empty columns. A kind whose only content is optional shows the *Add setting* menu and a line "Nothing to set. Add a setting when you need one." A node whose parent is missing (Agent: no agent chosen, agent deleted) shows the existing problem notes in the definition column and no behaviour column (its values would be meaningless).

### E.8 Placement of the destructive action

*Delete* in the footer's left corner as `is-danger` (ghost); confirmation by the existing dialog; the same on every kind (it is hidden for the fixed trigger/output/complete).

---

## F. Validation Against Four Node Kinds

Legend: **D** definition column, **B** behaviour column, **A** advanced, ○ inherits from a parent.

### F.1 Agent

| Section | Content |
|---|---|
| Identity | Name, caption *Agent*, chip: *Configured* when the agent resolves without problems (the existing preview already says so) |
| **D** | *Agent* choice (+ "Runs published version 3", *Open agent*), *Inputs* (the agent's declared inputs, mapped: one row each, references suggested), *Prompts* (user, system: ○ each a collapsible card with *Inherited / Overridden*) |
| **B** | *Model & Generation* (provider ○, model ○, temperature ○, max tokens ○); *Execution limits* (request timeout ○, node time limit ○, retries ○, max iterations ○); *If the node fails* |
| Always visible | Agent choice, input mapping, *If the node fails* |
| Advanced | None needed: the eleven overrides are already *optional* (ADR-046) |
| Inheritance | All override settings; shared override row; *Add setting* for the right column |
| Adaptation | The mockup's **Add input** does not apply: inputs are declared by the agent. The node only maps them (`agent_id` + `inputs`). The prompt text stays full-width inside its card. |

### F.2 If

| Section | Content |
|---|---|
| **D** | Condition rows: value · operator · compare with, repeating, as a *rule list*: the first row open, the others folded and "(empty)" (existing `details.ge-group` behaviour); *Combine* (all / any) and *Case sensitive* at the end |
| **B** | None (no timeout, no failure handling: it branches to Yes / No / Else) |
| Inheritance | None |
| Layout | **One column, deliberately.** A second column would be empty. The conditions list is the content. |
| Note | Five fixed rows is a limit the repository chose (`IF_ROWS = 5`); the rule-builder component from ADR-052 (`components/rule-builder.js`: groups of all/any, rows of field/operator/value) is the natural future shape for this content. It is a candidate, not part of this proposal. |

### F.3 Switch

| Section | Content |
|---|---|
| **D** | *Value* (the thing compared), then *Case 1…6*: operator and value, each a folded group when unused; *Case sensitive*; *Else* is implied by the port |
| **B** | None |
| Inheritance | None |
| Layout | One column. The output ports mirror the used cases (`switch_case_used`), which is feedback on the canvas, not in the dialog. |
| Adaptation | "Default behaviour" is the *Else* port: it needs no setting. The dialog could note it ("Nothing matches → Else") in the same muted style as other help lines. |

### F.4 HTTP request

| Section | Content |
|---|---|
| **D** | Method, URL, (optional) Headers, (optional) Body; references with suggestions in all three |
| **B** | Timeout (1 to 120 s, default 30 s; optional), *If the node fails* (core) |
| **A** | Accepted status codes (`success_status`) |
| Inheritance | **None today.** The timeout's default is the kind's own; Run limits (ADR-039) do not apply per request. Authentication is not a setting: it is a header with `${secret:NAME}` (ADR-024, ADR-051). |
| Layout | Two columns work: the request on the left, how it runs on the right. Headers and body are `lines` controls and take the column width. |
| Adaptation | The mockup's "authentication" dropdown would be a *different design*: a credential picker over the managed credentials (ADR-051) that writes the `Authorization: Bearer ${secret:NAME}` line. That is a possible later addition and needs its own decision; it is not part of the canonical shape. |

### F.5 The others in one line each

- **Code:** D = language, code (full width), secrets, sets variables; B = timeout, *If the node fails*; A = secrets/variables could fold. Two columns.
- **Edit Fields:** D = fields, value types; B = *If the node fails*. One column plus the shared group.
- **GitHub / Postgres:** D = operation or query and the connection secret; B = *If the node fails*; optional = limits, state filters. Two columns only when behaviour settings exist.
- **Timer, tools, stage, pipeline node:** one column; identity plus the few settings.

---

## G. Architecture Impact and Conflicts With Repository Evidence

### G.1 Reuse

| Need | Reuse |
|---|---|
| Settings, validation, storage | `Setting`, `NodeType`, `merge_config`, `graph_nodes.config` (unchanged) |
| Optional settings with defaults | `SettingsGroup`, `numberSetting` (`components/settings-group.js`) |
| Switches, menus, tabs, dialog | `Switch`, `ActionMenu` (works inside dialogs), `Modal`/`ActionDialog` |
| Identity | `.identity`, `InlineName` |
| Controls per type | `createControl` and the control classes |
| Effective values of an inherited setting | `PreviewRead.settings: SettingState[]` and `agents/resolve.py` |
| Destructive/primary/neutral rules | ADR-036 classes |

### G.2 Required changes

1. `graph/node_types.py`: `Setting.section/level/inherits`, `describe()` adds them; the Agent's `_override` helper sets `inherits="agent"`, `section="behaviour"` for the limits and model group. No schema or storage change.
2. `static/js/editor/inspector.js`: `settings(node)` groups by `section` and `level`; a layout wrapper with the two-column grid and the stacking breakpoint; an *Advanced* `details`.
3. `static/js/editor/agent-inspector.js` and `agents/model.js`: remove `OVERRIDES` (the browser's duplicate of the server's declaration) once the generic renderer reads the node description; keep the agent-specific pieces (agent choice, status, inputs mapping, the provider/model pair, which needs the provider list).
4. A shared **override row** component (`components/override-row.js`), used by the Agent block; it replaces `ag-override`.
5. `css/editor.css`: the two-column grid and widths for `#node-modal`.
6. Tests: the e2e tests that exercise the node settings use `.ge-inspector` and labels (`get_by_label`), which stay stable; those that exercise `ag-override` markup (`tests/e2e/test_agents.py`) change with step 3.

### G.3 Conflicts with the mockup (each decided by the evidence order)

| Mockup | Repository evidence | Decision |
|---|---|---|
| **Save changes** button | Settings are saved as they change; there is no draft of a node (`editor.js` `#saveSetting`, ADR-022); the agent's draft/publish belongs to the agent (ADR-037) | **Not adopted.** A save button would imply an unsaved state that does not exist. |
| **Delete** as a wide solid-outline red bar | ADR-036: `is-danger` on any control that deletes; solid `button--danger` only for the confirming button of a confirmation dialog | **Adopted as `is-danger` ghost, footer-left.** |
| **Add input** in the node | A node maps the inputs its agent declares; inputs are declared in the agent (ADR-037/045) | **Not applicable to the node.** The agent page keeps *Add input*. |
| Override row copies the parent's value | ADR-046: set = explicit, removing = not set; today `#startValue` saves the copy at the click | **Conflict kept visible, recommendation in E.5:** do not store until committed. **[Open]** |
| One wide dialog | The dialog is `min(52rem, …)` and single column since this session; ADR-029 sizing is for the artifact dialog | **New decision** (E.1 widths), no ADR contradicted. |
| *Configured* chip | A per-kind notion; only the Agent computes it (problems, status) | **[Open]** |
| Free-form icons per group | The set of icons is `templates/components/icons.html`; new ones are added there once | Fine, small. |

### G.4 Risks

- **Duplication of the Agent's declaration** (`OVERRIDES` in the browser vs `_override` on the server) already exists; the proposal removes it, but only after the generic renderer is proven on the Agent. Until then both must be kept in step.
- **Layout derived from data** can look uneven between kinds (some one column, some two). That is intended; the headers and the shared *If the node fails* keep the family resemblance.
- **`inherits` invites inheritance everywhere.** A setting should get a parent only when a parent really exists and supplies a value. Otherwise "Inherited: not set" rows are noise.
- **Optional settings hide things.** Rule 4 of E.3 (a set value is always visible) is the safeguard and needs a test per kind.

---

## H. Migration Strategy

Each step is shippable and reversible; none needs a database migration, and no persisted `config` changes (a setting keeps its key and storage).

| Step | Change | Visible? | Test |
|---|---|---|---|
| 0 | This document | No | – |
| 1 | `Setting.section/level/inherits` + `describe()`; set them on the existing kinds (HTTP, Code, Agent first) | No | A unit test that `describe()` carries the keys, that old keys are unchanged, and that every kind validates as before |
| 2 | Generic two-column rendering in `InspectorBlocks.settings`, single column when no `behaviour` setting exists; *Advanced* `details`; dialog width rules | Yes: HTTP, Code, Agent dialogs gain the right column | E2E: a kind with behaviour settings shows two columns, If/Switch one; stacking at a narrow width; a set advanced setting is open |
| 3 | `override-row.js` (inherited / overridden / not set) used by the Agent block; `SettingsGroup` for its optional settings; remove `OVERRIDES` from `agents/model.js` | Yes: the Agent dialog | Agent e2e tests updated; a test that clearing an override restores inheritance and that a parent change reaches a non-overriding node |
| 4 | `level="optional"` for HTTP headers/body/timeout, Code secrets/variables/timeout, GitHub limits; *Add setting* in the behaviour column | Yes | E2E: a configured optional setting is shown on reopening; *Add setting* lists defaults |
| 5 | (Later, separate decision) credential picker for HTTP/GitHub/Postgres over ADR-051; rule builder in If (ADR-052's component) | – | – |

---

## I. Open Decisions

1. **Override at the click or at commit** (E.5). *Option A (today):* save the parent's value at the click; simple, but it freezes the value. *Option B (recommended):* save only when the user commits a value; matches "additive, not copies", costs one small change in the Agent block. Trade-off: B shows an "Overridden" row that is not stored until committed.
2. **Chip wording:** *From agent* (today) or *Inherited* with the source named. Cosmetic; *Inherited* is shorter and generalises to a second parent.
3. **Status chip ("Configured"):** per-kind rule or none. Alternative: show it only on the Agent (where problems are already computed).
4. **Dialog width:** `min(64rem)` for two columns / `min(44rem)` for one (proposed) versus one width for all kinds (simpler, but the one-column kinds look empty at 64 rem, the two-column ones cramped at 52 rem).
5. **Which settings of HTTP/Code/GitHub are *optional* or *advanced*.** The proposal in F is a first reading; the owner knows what people reach for.
6. **Inheritance for the non-agent kinds.** Should HTTP/Code timeouts ever inherit from a global default (for example from Run limits, ADR-039)? Today they do not. Recommended: no, until there is a concrete parent.
7. **Conditions in If/Switch as a rule builder.** The ADR-052 component fits; moving If to it would change a stored shape (five fixed rows) and needs its own decision and migration. Not part of this proposal.

---

## J. Implementation Readiness

| Question | Answer |
|---|---|
| Is the canonical structure defined? | **Yes** (E.1, E.2): identity, definition, behaviour, advanced, with *If the node fails* as the shared group. |
| Is the schema change small and compatible? | **Yes** (D.1): three optional fields on `Setting`, no migration, old clients and stored configs unaffected. |
| Are the shared and kind-specific parts separated? | **Yes** (B.2, F). |
| Do inheritance and overrides have one consistent rule? | **Yes** (D.2, E.5), with decision I.1 open for the Agent's copy-at-click behaviour. |
| Can step 1 and 2 start now? | **Yes**, they do not depend on the open decisions except the widths (I.4), which can start with the proposed values. |
| What must be decided before step 3? | I.1 (override semantics) and I.2 (wording). |
| What is deliberately not decided? | Conditions as rule builder, credential picker, inheritance outside the Agent. |

**Verdict:** ready to implement from step 1; steps 3 and later need the decisions in section I. The first two steps change no behaviour and give every node the shared shape; the third brings the Agent in line with the system instead of being its exception.

---

## Evidence index

| Topic | Path |
|---|---|
| Node kinds, `Setting`, `ON_FAILURE`, Agent overrides, If/Switch settings | `openartifact/graph/node_types.py` (`Setting` l.200, `ON_FAILURE` l.497, `HttpType` l.596, `IfType` l.738, `SwitchType` l.792, `AgentType` l.893) |
| Resolution of inherited values | `openartifact/agents/resolve.py`, `openartifact/agents/schemas.py` (`OVERRIDABLE`, `SettingState`, `PreviewRead`) |
| Node settings dialog, controls | `openartifact/static/js/editor/{inspector,inspector-panel,setting-controls,agent-inspector,editor}.js`, `openartifact/templates/graph_editor.html`, `openartifact/static/css/editor.css` |
| Browser copy of the override list | `openartifact/static/js/agents/model.js` (`OVERRIDES`) |
| Optional-settings components | `openartifact/static/js/components/{settings-group,options-panel,switch,action-menu,rule-builder,rule-set}.js` |
| Decisions | ADR-012, 022, 029, 036, 037, 039, 040, 045, 046, 048, 051, 052 (`docs/architecture/adr/`) |
