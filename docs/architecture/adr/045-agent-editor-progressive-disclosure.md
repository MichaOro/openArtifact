# ADR-045: The agent editor shows what an agent needs: tabs, an options panel, switches that are kept

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-037](037-agent-harness.md) (the agent page, the configuration of an agent)  
**Implemented in:** `agents/schemas.py` (`inputs_enabled`, `limits_enabled`, `effective()`), `agents/freeze.py`, `agents/service.py`; `templates/agent_editor.html`, `static/js/agents/editor-page.js`, `static/js/agents/model.js` (`optionsOf`), `static/js/components/` (`tabs.js` `setVisible`, `switch.js`, `options-panel.js`), `css/agents.css`, `css/components.css` (tabs)  
**Affected chapters:** guide [agents](../../guides/agents.md)

## 1. Context

The agent page was one long column (prompts, inputs, model and limits, draft, preview, versions, used by). A simple agent
needs a user prompt only; everything else is shown anyway. The owner asked for progressive disclosure: the core always,
optional areas when switched on.

## 2. Decision

- **Layout (full width, after the owner's mock):** a header (back, the agent's icon, name, rename, chips, description,
  Save / Discard / Publish), a bar of tabs with icons above the active area, and on the right a *Status & info* card
  (Active, version, draft, used by, created, updated), the *Options* accordion and, while switched on, the *Quick test*
  card (example values for the inputs with a grey example of what goes in, *Run preview*). *Prompts* and *Versions & use* are always tabs; *Inputs*
  and *Model & Limits* are tabs only while their option is on; the system prompt shows inside *Prompts*.
  Switching an option on does not jump to its tab; switching off the tab that is shown goes back to *Prompts*.
- **Off means kept but not in effect** (the owner's choice, as the system prompt already worked): the backend has
  defaults, and switching an area on lets the agent override them. `AgentConfig` gains `inputs_enabled` and
  `limits_enabled`; `effective()` is what a run, the preview and the publish check use: inputs switched off are none
  (a prompt that still reads `${input.x}` cannot be published), Model & Limits switched off are the defaults (default
  provider and model, the default limits). The draft keeps every value.
- **Agents from before:** the two fields are optional (`null`); then the data decides: Inputs is on when any input is
  declared, Model & Limits when any of its values differs from the default. No migration.
- **What is not kept:** the panel is closed whenever the page opens; *Quick test* is off whenever the page opens and is
  not part of the agent; its example values live while the page is open. Opening or closing the panel saves nothing; an
  option switch is a change of the draft like any other (Save draft / Publish).
- **Reusable parts:** `Tabs.setVisible` (a tab and its panel come and go), `Switch` / `createSwitch` (one switch for
  every page), `OptionsPanel` (named options with a tooltip and a switch, closed by default, no state of its own); the
  tab styles moved to `components.css`.

## 3. Consequences

- A simple agent shows a user prompt and nothing else to fill in.
- A node may still override single settings of an agent whose Model & Limits is off: the node's values win as before.
- New optional areas are one more option and one more tab.

## Addendum 1 (2026-11-26): the inputs are reordered by a handle

- **A handle at the left of every input row** (`.ag-input__grip`, the shared `Sortable`, ADR-050) reorders the inputs: drag it with the
  pointer, or focus it and press Arrow Up / Down. Only the handle starts a move, so the text fields and selects of the row stay what they
  were. The table has a first column for it (2 rem; in a table that breaks into pairs the handle sits at the row's left edge and the pairs
  stay as they were).
- **The rows are the data** of this form (`readInputs()` reads them in order), so a move is a move of the row in the list; it marks the draft
  as changed like any edit, and the order is what *Save draft* stores and what *Publish* publishes (the server keeps the list as sent, and a
  new order counts as a change of the inputs). The *Quick test* examples follow the new order.
- **`Sortable`'s `onMove(from, to, by)`** got a third argument: `"pointer"` when the drag has moved the entry already, `"key"` when the owner
  has to move it. Owners that draw their list anew from data (the field editor) ignore it and are unchanged.
- **Reading aloud:** after a move the handle keeps the focus and a live region says "{name} is now input {n} of {total}".
