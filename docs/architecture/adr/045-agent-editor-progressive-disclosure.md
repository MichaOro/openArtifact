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

- **Layout:** a header (back, name, rename, chips, description, Active, the draft's state and Save / Discard / Publish),
  tabs in the main area and an options panel on the right. *Prompts* and *Versions & use* are always tabs; *Inputs*,
  *Model & Limits* and *Quick test* are tabs only while their option is on; the system prompt shows inside *Prompts*.
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
