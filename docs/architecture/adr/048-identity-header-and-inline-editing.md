# ADR-048: One identity header and one inline editing for resources

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-045](045-agent-editor-progressive-disclosure.md) (the agent's header)  
**Implemented in:** `static/js/components/inline-name.js` (`multiline`, `allowEmpty`, `emptyText`), `css/components.css` (`.identity`), `css/tokens.css` (`--identity-text-width`), `templates/agent_editor.html`, `static/js/agents/editor-page.js`  
**Affected chapters:** guide [agents](../../guides/agents.md)

## 1. Context

The agent's header put the pencil between the name and its badges, and the description grew with the page. Name and
description could only be changed in the dialog; lane and graph names are already edited in place.

## 2. Decision

- **`.identity`** (global): the resource's icon, the name with its badges on one line, and below it the description
  with the edit button inline after its last line (`vertical-align: bottom`), so it stays beside the last line whatever
  the text's length. The description's maximum width is a token of its own, `--identity-text-width` (48rem), not tied to
  the tab bar below; the text wraps, it is never cut.
- **Two ways to edit, on purpose:** a click on the name or the description edits it in place (Enter saves, Escape
  discards; a description is a text area where Shift+Enter is a new line and empty is allowed); the pencil opens the
  existing dialog with every field, as before. Both save through the same `PATCH /api/agents/{id}`; name and description
  are not part of the draft, as before.
- **One inline editing:** `InlineName`, already used for lane and graph names, gains `multiline`, `allowEmpty` and
  `emptyText` instead of a second component. Its existing rules stay (an empty name discards; with `keepOpenOnError` a
  refusal keeps the field open with the message).

## 3. Consequences

- Pipelines and actions can show their identity with the same classes and the same inline editing.
