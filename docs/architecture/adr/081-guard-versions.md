# ADR-081: Versions of guard definitions

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-060](060-guards.md) (a definition has a draft and published versions; a change no longer reaches a guard at once), [ADR-070](070-versions-of-actions-and-pipelines.md) (the same words for guards), [ADR-069](069-management-pages.md) (the *Versions* tab of the Guards page)  
**Implemented in:** `models/guards.py` (`GuardVersion`, `GuardDefinition.published_number`), `guards/versions.py`, `guards/service.py`, `guards/schemas.py`, `api/guards.py`, `engine/snapshot.py` (`freeze_guards`), `guards/monitor.py`, migration `0065`, `static/js/guards/` (`library-page.js`, `editor-window.js`, `model.js`), `static/js/editor/versions-tab.js`, `static/js/editor/publication-control.js`  
**Affected chapters:** guides [guards](../../guides/guards.md), [API reference](../../guides/api-reference.md)

## 1. Context

Pipelines, actions and agents have a draft and published versions (ADR-037, ADR-047, ADR-070): only publishing changes what executions use. The guard
library did not: a change to a definition in the guard window was stored at once and reached every place the guard is attached to with the next run.
A guard acts on running executions (it can pause or abort one), so an unfinished edit was the more dangerous one to leave without a draft. The owner wants
the system to be consistent: guards get what the other definitions have.

## 2. Decision

- **A definition has a draft and published versions.** The columns of `guard_definitions` are the **draft** (what the guard window and `PATCH` change). A
  version is a frozen copy of what the definition is (`guard_versions`: name, description, scope types, trigger, condition, consequence, fallback,
  escalation and the guard's own action), written once and never changed. `number` counts per definition from 1 and is never reused;
  `source_number` is set when a version was made by publishing an earlier one again; `published_via` is `user` (browser) or `api`
  (`/api/v1`). A `fingerprint` (a hash of the whole content) tells whether the draft differs from the published version
  (`draft_changed`). `guard_definitions.published_number` is the version executions use.
- **Only a published version is in effect.** A **new** definition is a draft and **watches nothing until it is published**. An attachment to a
  definition that was never published is allowed (so it can be set up before it is published) but inactive: the API says
  `guard_published: false` on it and the editors say so in plain words. This differs on purpose from pipelines and actions, where a never-published
  graph runs its draft: a guard that is half written must not stop a run.
- **Publish, publish again, discard.** *Publish* makes a new version of the draft and points to it (409 when the draft equals the published version;
  422 when a guard that runs an action has none). *Publish again* makes a new version with the content of an earlier one (a rollback; history stays,
  the draft is not touched and shows as changed when it differs). *Discard draft* makes the draft the published version again (409 while nothing is
  published and while they are equal; 422 when that version's scope types no longer cover where the guard is attached). The three
  words and the chip (`Draft`, `v3 published`, `Draft has changes`) are those of ADR-070; the popup on the chip is the same component
  (`publication-control.js`), which takes the calls and the differing words as options.
- **An execution freezes the published version.** `freeze_guards` (`engine/snapshot.py`) reads, for every switched-on attachment that applies to the run,
  the **published version** of its definition and the guard's own action through `graph_for_run`, never the draft row, and writes `version` into the
  frozen guard. The monitor reads the snapshot only, so a later save, publication or republication does not reach a running execution. A guard
  firing carries `guard_version` (the execution flow shows "Health guard v3"). **Fallback:** an execution that was frozen before this change has
  no `version` in its snapshot (the guards in it are the definitions as they were then); it keeps running as it started, and its firings show no version.
- **Exempt from the freeze: switching an attachment on or off.** It stays immediate, is not part of a version, makes no version and acts on
  running executions at once (the monitor's live check of `guard_attachments.enabled`; `PUT /guard-attachments/{id}/enabled`, MCP
  `set_guard_enabled`). So a guard can be switched off in an emergency without a publication. Attaching and detaching are not versions either.
- **API.** The browser API (`/api/guards`) and the integration API (`/api/v1/guards`) get `GET /{id}/versions`, `GET /{id}/versions/{number}` (what the
  version held, to show it read-only), `POST /{id}/publish`, `POST /{id}/versions/{number}/republish` and `POST /{id}/draft/discard`; a definition
  carries `published_version` and `draft_changed`. The integration API publishes as `api`. **MCP**: `list_guards` shows `published_version` and
  `draft_changed`; there is **no** MCP tool that creates, changes or publishes a guard (guard management is not exposed to agents on purpose; `set_guard_enabled`
  stays).
- **Templates** (Stall, Runtime, Health guard) are finished guards: they are installed as published version 1.
- **Migration 0065.** Creates `guard_versions` and `published_number`; every guard that exists becomes **published version 1 with its current content**, so
  nothing changes for an installation that runs guards. The downgrade drops the table and the column: the definition's own columns stay and hold
  what was the draft.
- **Panel and window.** The Guards page shows the chip on the card and in the panel, and a *Versions* tab (the tab of ADR-070: *Publish*, the list newest
  first with *In use*, *Show* and *Publish again*). *Show* draws an earlier version read-only in the *Overview* with a way back to the draft.
  The guard window's *Save* is *Save draft*; the mark under the title opens the popup (*Publish*, *Discard draft*; a changed form is saved as the draft first)
  inside the window, because a modal window hides what is outside it. The text under the title says "Used in N places. Only the published version applies."
  and, for a guard nobody published, that it watches nothing yet.

## 3. Consequences

- An edit of a guard is safe: it does not act until it is published, and a published change does not act on a run that is under way.
- The price is the second step: a new guard must be published before it watches anything. The window and the Guards page say so; the Usage tab marks
  an inactive attachment *Not published*.
- Not built: pinning an attachment to a version, comparing two versions, an MCP way to publish a guard.
