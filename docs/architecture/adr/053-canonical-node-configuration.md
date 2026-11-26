# ADR-053: One configuration experience for every node: sections, levels, inheritance

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-022](022-node-settings-as-json-config.md) (the description of a setting), [ADR-046](046-optional-model-and-limit-settings.md) (overrides in the node's dialog)  
**Implemented in:** `graph/node_types.py` (`Setting.section/level/inherits`, `SECTIONS`, `LEVELS`, `GROUP_MODEL`, `GROUP_LIMITS`), `api/schemas.py` (`SettingRead`); `static/js/editor/settings-plan.js`, `settings-layout.js`, `setting-controls.js` (`unsaved`, `choices`), `inspector.js`, `agent-inspector.js`, `static/js/components/override-row.js`, `css/editor.css`, `css/components.css`  
**Affected chapters:** guide [extending](../../guides/extending.md), research [research-action-configuration-ux.md](../../research-action-configuration-ux.md)

## 1. Context

The node's settings dialog was one column: a flat list for most kinds, a dedicated renderer with its own list of
overridable fields for the Agent, and eleven override rows that were all shown. The research proposal
(`docs/research-action-configuration-ux.md`) derived one shape for every node from the Agent mockup.

## 2. Decision

- **The schema stays the existing one.** A `Setting` gains `section` (`definition` / `behaviour`), `level` (`core` /
  `optional` / `advanced`) and `inherits` (a parent, or none), all optional with defaults that keep every existing setting
  as it was. `describe()` and `GET /api/node-types` carry them; the browser declares no setting of its own. Section,
  group and level are separate: the section is the column, the group is the semantic title, the level is how prominent;
  *Advanced* is a level, not a column, and stays with its section.
- **One layout** (`settings-layout.js`, planned without a DOM in `settings-plan.js`): *Definition* and *Behaviour*
  columns, two only when both have something (dialog up to 64 rem; one column up to 44 rem), stacked below 44 rem of
  the dialog's own width (a container query). Core settings are always shown, optional ones once they have a value or are
  added through *Add setting* (the menu names the default, or the parent's value), advanced ones folded and open while one
  is set. A stored value that is only the default does not count as set: a new node stores its defaults.
- **Inheritance is for real parents only.** Today that is the agent. An inheriting setting is an *override row*
  (`components/override-row.js`): *Inherited* (with the source: "Agent: 0.2"), *Overridden*, *Not set*. **Overriding is
  additive:** *Override* opens the control with the parent's value as a suggestion and stores nothing; a value is stored
  when the user commits it (Enter, or a change), and the bin deletes it, which restores inheritance. This replaces
  the copy-at-click of the old agent block. Resolution is unchanged (`agents/resolve.py`, at the start of an execution).
- **Removed duplication:** the browser's list of overridable fields (`OVERRIDES` in `agents/model.js`) is gone; the
  node's dialog reads labels, bounds and kinds from the server; `overridesOf` takes the settings that inherit. Only the
  *names* of the agent's fields remain in `agents/model.js` for the agent pages and step details.
- **Classification of the kinds:** `ON_FAILURE` is `behaviour`/core everywhere it exists; timeouts are `behaviour`/optional
  (group *Execution limits*); the Agent's model and limits are `behaviour`/optional/inherits (*Model & Generation*,
  *Execution limits*), its prompts `definition`/core/inherits; HTTP's accepted status codes, Code's secrets and declared
  variables, GitHub's API URL, Postgres' private-network switch and the HTTP tool's accepted status codes are `advanced`.
  If, Switch, Timer, Edit Fields and the tools have no behaviour settings except the shared failure setting where they have it.
- **Not changed:** settings are saved as they change (no Save button), validation is the server's, references and their
  suggestions, the Agent's choice of an agent, published-version status and input mapping (drawn by the agent block and
  passed to the layout as `extras`), the footer actions (*New*, *Delete*).

## 3. Deviations from the research proposal

- Optional settings are added through the layout's own *Add setting* menu (`ActionMenu`), not through `SettingsGroup`:
  the group's rows are label, control and bin for numbers saved as one draft, while a node's controls save one by one and
  carry help text and errors. The wording and semantics (defaults named in the menu, the bin means *not set*) are
  ADR-046's.
- The status chip ("Configured") of the mockup is not implemented (a per-kind rule that only the Agent has).
- The dialog's own title is hidden (the name is the editable heading), and the heading gains the kind's icon.

## 4. Consequences

A kind gets the shared shape by declaring metadata on its settings; the Agent is no longer an exception except for the
two things only it has. Optional settings are less discoverable than before (they sit behind *Add setting*), which the
menu and the rule "a set value is always shown" are meant to offset.

## Addendum (2026-11-26): the row of an optional setting

The bin of an optional setting is the end of the control's row, not an element laid over it, and a setting may have a type of its own (`retry`, with *Max. tries* and a wait as a number and a unit): [ADR-074](074-setting-row-and-durations.md), [ADR-073](073-retry-on-fail.md).
