# ADR-046: Model and limit settings of an agent are optional; not set is not the default

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-037](037-agent-harness.md) (the configuration of an agent), [ADR-045](045-agent-editor-progressive-disclosure.md) (the Model & Limits tab)  
**Implemented in:** `agents/schemas.py` (`AgentConfig`: the four limits `int | None`, `loads` reads old stored defaults as not set); `static/js/components/settings-group.js` (`SettingsGroup`, `numberSetting`), `static/js/agents/editor-page.js`, `templates/agent_editor.html`, `css/components.css` (`.settings-card`, `.setting`)  
**Affected chapters:** guide [agents](../../guides/agents.md)

## 1. Context

The Model & Limits tab showed all eight settings as fields, and the four limits were always stored, with their default
when nobody chose one. An agent is a template: it may say which model or limits it wants, but it need not; the node that
uses it, or the runtime, decides the rest.

## 2. Decision

- **Every setting is optional**, provider and model included. `request_timeout_seconds`, `total_timeout_seconds`,
  `retries` and `max_iterations` become `int | None` like the other four. `None` is **not set**; the runtime default
  applies at the node (60 s, 600 s, 3, 10), and a stored value is an explicit value, even when it equals the default.
- **Resolution** stays as it was: the node's override, else the agent's value, else the runtime default. Whether a
  provider and a model can be resolved is checked where the node's configuration is put together (the node's hints in
  the editor, the snapshot at the start of a run), not when the agent is published.
- **Older drafts and versions** stored the four limits always. A stored configuration without the switch of ADR-045
  (`limits_enabled`) reads a limit equal to the old default as not set: the value is the runtime default, so no run
  changes, and the editor does not show settings nobody chose. No migration.
- **UI:** two cards, *Model configuration* (provider, model, temperature, max tokens) and *Execution limits* (node
  time limit, max iterations, retries, request timeout: by importance), one setting per row. The wording says what is
  true: a default always applies, a setting only overrides it. *Add setting* lists the settings not added yet, each with
  its default ("Node time limit · default 600 s"); an added empty field shows the default grey; the bin says "Use the
  default again". Removing is **unset**, never "reset to default".
- **Inputs table:** Name, Type, Required (a select: Required / Optional), Default, Description and a menu per row. A
  description is added from the row's menu (*Add description* or *Remove description*, never both, and *Remove input*);
  the Description column is there while any input has one, derived from the data. The data model is unchanged (an empty
  description is none).
- **Reusable:** `SettingsGroup` takes the settings declaratively (key, label, hint, how the control is made, read and
  written) and knows nothing about agents; `numberSetting` makes a bounded number field. The card styles are global.

## 3. Consequences

- A simple agent stores no model or limit at all.
- The node inspector shows "not set" for an inherited value the agent does not set.
- New settings are one more entry in a card's list.
