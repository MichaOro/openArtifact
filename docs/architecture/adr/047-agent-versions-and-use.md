# ADR-047: Versions & use of an agent: two columns, Open and Remove reference

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-045](045-agent-editor-progressive-disclosure.md) (the tab *Versions & use*)  
**Implemented in:** `templates/agent_editor.html`, `static/js/agents/editor-page.js`, `static/js/agents/api.js` (`removeAgentReference`), `static/js/editor/navigation.js` (`setupBackToAgent`), `static/js/editor/editor.js` (`?select=` in actions too), `static/js/components/confirm-dialog.js` (`title`), `css/agents.css`  
**Affected chapters:** guide [agents](../../guides/agents.md)

## 1. Context

*Versions & use* listed the versions and the agent nodes below each other, without a way to act on a use.

## 2. Decision

- **Two columns:** *Used by* on the left (room for a node's facts and actions), *Versions* on the right (compact rows like
  *Status & info*). On a narrow screen they stack in that order. Each column has its own empty state.
- **A use** shows the node, "Agent node · Action: NAME" and what the node sets itself, with **Open** and **Remove
  reference**. *Open* goes to `/actions/SLUG?select=NODE&agent=ID`: the editor selects the node and offers *Back to
  AGENT*.
- **Remove reference** asks first in the confirmation overlay ("Remove agent reference?", the action's name, the warning
  that future executions may fail until the node is reconfigured). It empties that node's `agent_id` with the existing
  `PATCH /api/actions/{id}/nodes/{node}` (one request, nothing else of the node changes). The agent, its other uses and
  every execution that exists stay as they are; the node then reports that it has no agent. No API change.
- **Versions:** the one executions use is *In use*; an older one has *Publish again* (unchanged logic: a new version with
  its content).

## 3. Consequences

- Where an agent runs is one click away, and a use can be cut without opening the action.
- `ConfirmDialog.open` takes a `title`, so one confirmation markup serves different questions.
