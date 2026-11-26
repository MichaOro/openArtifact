# ADR-035: Artifact types and card parameters

**Status:** Superseded by [ADR-044](044-artifact-fields.md)  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** [ADR-044](044-artifact-fields.md)  
**Amends:** [ADR-033](033-run-context.md), [ADR-022](022-node-settings-as-json-config.md)  
**Amended by:** —  
**Implemented in:** migration 0031 (`artifact_types`, `artifact_type_fields`, `tasks.type_id`, `tasks.parameters`); `artifact_types/` (`fields.py`, `schemas.py`, `service.py`), `tasks/schemas.py`, `tasks/service.py`, `api/artifact_types.py`, `api/v1.py`, `mcp_server.py`, `engine/context.py` (`card`), `engine/history.py`, `engine/runner.py`; `static/js/artifact-types/`, `static/js/tasks/parameter-form.js`, `parameters.js`, `artifact-dialog.js`; `templates/artifact_types.html`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md), [06.06](../arc42/06-runtime-view/06.06-start-of-an-execution.md), [12](../arc42/12-glossary.md); guides [concepts](../../guides/concepts.md), [execution nodes](../../guides/execution-nodes.md), [security](../../guides/security.md), [integration](../../guides/integration.md), [API reference](../../guides/api-reference.md)

## 1. Title

Typed parameters on artifacts, defined per artifact type as data, readable in runs as `${card.NAME}`.

## 2. Context

Pipelines need facts about the artifact they process (an urgency, a customer tier) to branch on them (If/Switch nodes,
a support triage) and to put them into requests. Which facts exist differs per kind of artifact, so it cannot be code:
a second kind of artifact with its own facts must work without a release. A typo in such a fact must be refused when it
is saved, not found when a run fails.

## 3. Decision

- **Types are data.** An *artifact type* (UI: "Artifact type") has a name (1 to 60 characters, unique ignoring case) and an
  ordered list of parameters: `name` (`[a-z][a-z0-9_]{0,31}`), `label`, `kind` (`text`, `number`, `boolean`, `choice`),
  `required`, `default`, for a choice 2 to 20 allowed values of at most 40 characters, for text a maximum length (1 to
  1000, default 200), for a number optional minimum, maximum and whole-numbers-only. Tables `artifact_types` and
  `artifact_type_fields` (fields cascade with their type); an artifact has `type_id` (`NULL`: untyped, the behaviour of
  before; `ON DELETE RESTRICT`) and `parameters` (JSON object text, only the values that are set). Parameters live only
  in `tasks.parameters`; the type holds definitions, never values (no parameter is kept in two stores).
- **Validated when saved**, through every way in (browser API, `/api/v1`, MCP all call `ArtifactService`):
  `artifact_types/fields.py` (pure) checks kinds and limits, choice membership (message with the allowed values and a
  "Did you mean" for near misses), required values (defaults fill what is missing), unknown names (422 with the valid
  names) and a cap of 4 KiB for all parameters. All problems of a request come back together, one line each:
  `Parameter urgency: "hgh" is not one of low, normal, high. Did you mean "high"?`. `null` or blank means "not set".
- **Updates merge**: `parameters` in a PATCH are merged into the stored ones (`null` clears one back to its default).
  **Changing the type** is allowed when the stored values are all valid for the new type; otherwise 422 naming the
  problem, unless `reset_parameters: true` drops them first. Removing the type with values needs the same flag.
- **Locked while processed**: `type_id`, `parameters` and `reset_parameters` are locked (409) with lane, parent and
  pipeline while a run is running (the run has its copy, so an edit could not take effect anyway).
- **Types in use stay valid**: deleting a type that artifacts use is 409 with the count. While artifacts use it, changing
  the parameters is refused (409, one line per problem) when it could invalidate stored values: removing a parameter,
  changing its kind, removing an allowed value, a shorter text limit, narrower number bounds, making a parameter
  required without a default, adding a required parameter without a default. Labels, order, defaults, more allowed
  values, wider limits and making a parameter optional are free.
- **Into the run**: when an execution is opened, the artifact's parameters are copied into its context under the new
  key `card` (`RunContext.initial(card)`, written in the same `INSERT` as the execution; one extra query per start for
  the type's fields, none per node). Every parameter of the type is a key: its value, else its default, else `null`;
  an untyped artifact has `{}`. `${card.NAME}` (`engine/context.py`, same single pass and rendering as `${var...}`)
  fails the node naming the reference when the artifact has no such parameter: `${card.x}: the artifact has no
  parameter "x"`. Code nodes see `card` in `context.json`. Later changes of the artifact never change an execution that
  exists (a copy, not a reference).
- **API.** `GET/POST /api/artifact-types`, `GET/PUT/DELETE /api/artifact-types/{id}` (PUT replaces the name and the whole list),
  mirrored under `/api/v1` (a type can be read by name there); `type_id`, `parameters` (and `reset_parameters` on update)
  in the artifact models; MCP `list_artifact_types`, and `type` (name or id) and `parameters` on `create_artifact` and
  `update_artifact`. Event `artifact_types.changed` (`{"types": [...]}`).
- **UI.** A page "Artifact types" (sidebar): list, create, rename, delete (disabled with the reason when in use) and an
  editor of the parameters (add, remove, reorder, kind, required, default, allowed values) that shows the server's
  `Field NAME: ...` messages at their rows. The artifact dialog has a Type select (only when types exist) and, for a
  typed artifact, typed controls (text, number, switch, select) with required markers, defaults and the server's messages
  inline without losing what was typed; the view lists the parameters in a grid whose rows are as tall as the controls,
  so the size the dialog is fitted to (ADR-029) holds both. Changing the type asks inline before values are dropped.
  Cards show the type name in their meta line.

## 4. Consequences

- A second kind of artifact with its own parameters is a few clicks, no code or migration.
- Parameters are plain user data: no secret belongs in them, `${secret:...}` in a parameter is just text (and is never
  replaced, because a replaced value is not scanned again). They are not masked.
- The type's field definitions are read at start and at save, never per node. A type edited later does not change a
  running execution's `card`; an artifact keeps its stored values, and the rules above keep them valid.
- A renamed parameter is a removed plus an added one, so it is refused while artifacts use the type; this is the price
  of keeping stored values valid without migrating them.
- A deleted type cannot happen under artifacts (`RESTRICT`); `tasks.type_id` is indexed for the count.
- Follow-ups: If/Switch nodes that branch on `${card...}`, a rename that migrates values, parameters set by actions,
  a type chip on the card as a real component.
