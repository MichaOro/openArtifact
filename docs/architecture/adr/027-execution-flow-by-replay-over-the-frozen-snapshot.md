# ADR-027: Execution flow by replay over the frozen snapshot

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-025](025-execution-history-and-retention.md)  
**Amended by:** —  
**Implemented in:** `engine/flow.py`, `engine/flow_schemas.py`, `engine/snapshot.py`, `engine/neighbours.py`, `engine/neighbour_schemas.py` (add. 1); endpoints `.../executions/{id}/flow` and `.../steps/{step_id}`; page `/artifacts/{ref}/executions/{id}` (`static/js/execution/`); no migration  
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

## Addendum 1 (2026-11-26): the position of an execution and the neighbours of a graph, read by API and MCP

The owner wants *what I see technically I see visually, and the other way round*: a node, an action and a stage know their predecessors
and successors, and an execution knows where it is, askable without the page.

- **One implementation of the connections.** `engine/neighbours.py` `links_of(nodes, edges)` turns the nodes and edges of any graph into the
  predecessors and successors of every node (the other end, the connector `port` and its editor label `port_label`, a `connection` sort).
  Labels come from the node types the editor loads (`node_type(kind)`), names are `definition_name ?? label ?? name` as `nameOf` of the page.
- **Graphs:** `GET /api/{pipelines|actions}/{id}/neighbours?version=published|draft|N`, `GET /api/v1/{pipelines|actions}/{ref}/neighbours` (id, URL
  name or name), MCP `get_graph_neighbours`. `published` is the default because it is what executions run (ADR-070: the draft while nothing is
  published); `draft` is what the editor draws. The answer says which one it read.
- **Executions:** `GET .../executions/{id}/position` (browser API and `/api/v1/artifacts/{ref}/...`), MCP `get_execution_position`. It is made from
  the `ExecutionFlow` of this ADR (`position_of(flow)`), never from the live graphs: `at` is the chain of visits from the root down to the one
  the run is in (the newest visit that is running or stopped, once it ended the newest of all), the node of each level being the tail of its
  visit (the documented *node it waits in*) or the node the next visit was entered from; `next` are the successors of the innermost node in its
  frozen graph, `afterwards` those of the outer ones. The `state` of each node on the `path` follows `FlowModel.describe` of the flow view (a node
  with a step has the step's outcome, one with child visits the last child's outcome, the tail of an unfinished visit the visit's own state).
  The path keeps the newest 200 visits; step outputs are not part of it (`get_execution_step`).
- **The two stay in agreement by a test**, not by a second copy: `tests/test_neighbours.py` holds the neighbours against `GET /api/pipelines/{id}`
  (every connection the editor draws is once a successor and once a predecessor, with the editor's names and labels, nothing more) and the
  position against the flow of a running, a stopped, a finished and a failed execution. The rule of the view for a stopped run (the last node
  inside the action keeps its step's *pass*, the stop shows on the action node of the pipeline) is the view's own, not an invention of the API.
- Read only, no migration; an unknown graph, version or execution is 404 like the neighbouring endpoints, an invalid `version` is 422.

