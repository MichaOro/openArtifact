# ADR-044: Artifact fields: global custom fields instead of artifact types

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** [ADR-035](035-artifact-types-and-card-parameters.md) (artifact types and their parameters)  
**Superseded by:** —  
**Amends:** [ADR-033](033-run-context.md) (`card`), [ADR-036](036-ui-conventions-and-lane-settings.md) (board header, artifact rail)  
**Implemented in:** migration 0038; `artifact_fields/` (`rules.py`, `schemas.py`, `service.py`), `tasks/`, `api/artifact_fields.py`, `api/v1.py`, `api/mcp.py`, `engine/runner.py`; `static/js/artifact-fields/`, `static/js/tasks/`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [execution nodes](../../guides/execution-nodes.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md)

## 1. Context

ADR-035 gave an artifact an optional *type* with its own parameters, chosen when the artifact is made. In use the owner
thinks of them as **custom fields** (Jira, GitHub Projects): one set of fields every artifact has, edited on the card. A
type to pick first is in the way. The system is work in progress; a clean model counts more than keeping the old one (the
running instance had one test type and no artifact using it).

## 2. Decision

- **Artifact fields are global.** One ordered list (at most 30) of fields: name (`[a-z][a-z0-9_]{0,31}`, what pipelines
  read), label, kind (text, number, yes/no, choice) and the kind's limits, and a **default**. There is **no
  "required"**: with global fields every existing artifact would break it at once. The default pre-fills new artifacts.
- **Every artifact has every field.** Its values are stored with it (`tasks.field_values`); a value that is not set
  reads as the field's default. Runs see all fields as `${card.NAME}` (frozen at the start of the run, as before).
- **The list is replaced as a whole** (`PUT /api/artifact-fields`). A removed field takes its values with it (the UI
  asks first, naming how many artifacts have one). A changed field is refused (409) when stored values no longer fit,
  naming the field and how many artifacts are affected.
- **Artifacts** carry `fields` ({name: value}) in the API; an update merges, `null` clears a value. Lane, fields and the
  rest stay locked while the artifact runs.
- **UI:** a menu next to *Add lane* on the board opens *Artifact fields* in a dialog. The sidebar entry *Artifact
  types* goes. In the artifact dialog the left rail gets a *Fields* entry: clicking it expands the rail and shows the
  fields indented below it, each with its name and its control (text, number, a yes/no switch, a choice list); a change
  is saved at once.
- **Artifact types are removed** without migration: tables `artifact_types` and `artifact_type_fields` and
  `tasks.type_id` are dropped, `tasks.parameters` becomes `tasks.field_values` (emptied), the `/artifact-types` API, MCP
  tool and page go.

## 3. Consequences

- Simpler to use and to explain; pipelines read the same `${card.NAME}`.
- Different kinds of artifacts can no longer have different fields; all share one list. If that is needed later,
  fields could be shown per lane or pipeline, without bringing back a type to choose.
- API break for `/api/v1` clients using types (none known).
