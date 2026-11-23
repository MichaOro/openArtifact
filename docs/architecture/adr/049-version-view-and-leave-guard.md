# ADR-049: A published version can be looked at; a page's own links ask before unsaved changes are lost

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-047](047-agent-versions-and-use.md) (the versions of an agent)  
**Implemented in:** `static/js/agents/version-view.js`, `static/js/agents/editor-page.js`, `static/js/agents/api.js` (`getVersion`), `templates/agent_editor.html` (`version-modal`), `static/js/components/leave-guard.js`, `templates/components/leave_modal.html`, `static/js/components/confirm-dialog.js` (`tone`)  
**Affected chapters:** guide [agents](../../guides/agents.md)

## 1. Context

*Publish again* asked at once, without a way to see what the earlier version defined. And a click on *Open* (or any
other link of the page) with unsaved changes got the browser's "leave the page?" question.

## 2. Decision

- **Show:** every version has *Show*. A wide dialog grows in (scale and fade, none with reduced motion) and shows the
  version read-only in the editor's tabs: *Prompts*, *Inputs*, *Model & Limits*; an area the version did not use has no
  tab, and an unset setting shows the default it got. No status, options or description. The version comes from the
  existing `GET /api/agents/{id}/versions/{n}`. *Publish again* is in the dialog too, for a version that is not in use.
- **Publish again** asks with the accent colour, not red: it makes something new and removes nothing
  (`ConfirmDialog.open({tone: "primary"})`).
- **Leaving:** a page with unsaved changes catches clicks on its own links (`LeaveGuard`) and asks in the page: *Stay*,
  *Leave without saving*, *Save and leave*. Closing the tab, reloading or typing an address still gets the browser's
  question; no page can replace that one. The guard and its dialog are generic.

## 3. Consequences

- A rollback is a decision made after looking, not a guess.
- Other editors with a draft can use `LeaveGuard` and `leave_modal` as they are.
