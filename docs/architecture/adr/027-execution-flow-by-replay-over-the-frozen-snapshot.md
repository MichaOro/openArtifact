# ADR-027: Execution flow by replay over the frozen snapshot

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-025](025-execution-history-and-retention.md)  
**Amended by:** —  
**Implemented in:** `engine/flow.py`, `engine/flow_schemas.py`, `engine/snapshot.py`; endpoints `.../executions/{id}/flow` and `.../steps/{step_id}`; page `/artifacts/{ref}/executions/{id}` (`static/js/execution/`); no migration  
**Affected chapters:** [06.09](../arc42/06-runtime-view/06.09-history-retention-and-flow.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md); guide [execution history](../../guides/execution-history.md)

## 1. Title

How the path of an execution through its pipeline is shown without recording it.

## 2. Context

Only nodes of action definitions leave steps. Stages, actions without a definition and called pipelines leave
nothing, yet the page of an execution should show the walked path on the graph as the editor draws it.

## 3. Decision

- The path is replayed in `engine/flow.py` over the execution's frozen snapshot and its steps with the engine's
  own rules (start at the entry, follow *On Pass* or *On Error* by what the steps say, one group of steps per run
  through an action definition). The result lists graphs, visits, traversed edges and reached nodes.
- Snapshots frozen before the flow existed lack ids, names, sizes and edge ids; they are filled in when read, so
  old executions stay viewable.
- The page `/artifacts/{ref}/executions/{id}` shows the snapshot read-only on the editor canvas, highlights the
  walked path, lets the user drill into actions and nested pipelines and loads the output of a step on demand.

## 4. Consequences

- Nothing extra is recorded during a run; the same data serves every client (REST, MCP).
- The replay can drift from the engine; the replay has its own constant for the step bound (1000, like the engine) and must be kept in line by hand.
- Where the steps run out, the replay stops; an open end is shown as running only while the execution runs.
