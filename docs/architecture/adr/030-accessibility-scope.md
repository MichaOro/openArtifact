# ADR-030: Accessibility scope

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-012](012-workflow-definition-editor.md) (update of 2026-11-22), [ADR-014](014-building-blocks-and-extension-points.md) §4  
**Amended by:** —  
**Implemented in:** documentation only; the behaviour is in `static/js/components/` and `static/js/editor/`  
**Affected chapters:** [08.08](../arc42/08-cross-cutting-concepts/08.08-accessibility-scope.md), [11](../arc42/11-risks-and-technical-debt.md)

## 1. Title

What the user interface supports for keyboard and screen readers today, and what it does not.

## 2. Context

The board can be used with the keyboard, but connections in the graph editor can only be made by dragging since the
routing select was removed (ADR-012 update, ADR-014 §4). Notes about this were scattered over several ADRs.

## 3. Decision

Accessibility beyond the following is a later goal, not a current promise. Today: the board is operable by
keyboard, dialogs are native `<dialog>` elements, tabs follow the ARIA pattern, and status changes are announced
in live regions. Connecting nodes in the graph editor needs a pointing device, and parts of the editor are not
usable with a screen reader. This is a known limitation, listed in arc42 chapter 11.

## 4. Consequences

- One place states the scope instead of scattered side notes.
- A later ADR will decide how connections are made by keyboard; until then, the editor is not accessible
  to keyboard-only users.
