# ADR-021: Execution nodes as executors

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-013](013-execution-engine-and-runs.md), [ADR-014](014-building-blocks-and-extension-points.md)  
**Amended by:** —  
**Implemented in:** migration 0021 (kinds `code` and `http`, table `run_node_results`); `engine/executors.py`, `engine/code_runner.py`, `engine/http_runner.py`, `engine/results.py`  
**Affected chapters:** [05.06](../arc42/05-building-block-view/05.06-execution-engine-internals.md), [06.07](../arc42/06-runtime-view/06.07-code-node-execution.md), [08.05](../arc42/08-cross-cutting-concepts/08.05-execution-nodes-safety.md); guide [execution nodes](../../guides/execution-nodes.md)

## 1. Title

How an action definition does real work: Code and HTTP nodes run through a registry of executors.

## 2. Context

ADR-013 built the engine with the timer as the only business logic, and ADR-014 noted that the engine "executes
kinds by name": a new kind that runs needed a branch in the engine. The platform is meant to run work (a script, a
call to another system) as part of a pipeline, and every new kind should not touch the walk of the graph.

## 3. Decision

- **Executor registry** (`engine/executors.py`): an executor is an async function `(node, limits) -> NodeResult`
  registered per kind with `register_executor(kind, run, by_outcome=...)`. The engine looks the kind up, runs it,
  stores the result and leaves the node by the matching port: *On Pass* or *On Fail* for kinds that decide by
  outcome, *Next* for the rest (the timer).
- The engine keeps what it owns: the trigger and the output of a definition have no executor.
- **Built kinds:** `code` (language `sh` or `python`, run as a child process) and `http` (one request), next to the
  existing `timer`. `Limits` carries the settings the executors depend on.
- **Every executed node is a step.** Each one is stored as a `RunNodeResult` (`run_node_results`): position, port,
  exit code, output, reason and data. Steps are the basis of the history (ADR-025) and the flow (ADR-027).

## 4. Consequences

- A new kind that runs is a registration plus a node type (ADR-014, ADR-022), not a branch in the engine.
- Steps can be queried afterwards (history, flow, MCP).
- A result carries text that comes from outside (command output, a response body); a consumer must treat it as
  untrusted input, and secret values are masked before it is stored (ADR-024).
- Running foreign code and calling networks needs its own safety model (ADR-023).
