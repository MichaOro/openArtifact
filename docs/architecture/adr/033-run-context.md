# ADR-033: Run context

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-021](021-execution-nodes-as-executors.md), [ADR-025](025-execution-history-and-retention.md)  
**Amended by:** —  
**Implemented in:** migration 0028 (`executions.context`); `engine/context.py`, `engine/runner.py` (`_record`), `engine/executors.py`, `engine/http_runner.py`, `engine/code_runner.py`, `engine/schemas.py`, `graph/node_types.py`, `graph/repository.py`; `static/js/tasks/context-block.js`  
**Affected chapters:** [05.01](../arc42/05-building-block-view/05.01-domain-model.md), [05.06](../arc42/05-building-block-view/05.06-execution-engine-internals.md), [06.06](../arc42/06-runtime-view/06.06-start-of-an-execution.md), [12](../arc42/12-glossary.md); guides [execution nodes](../../guides/execution-nodes.md), [execution history](../../guides/execution-history.md), [security](../../guides/security.md), [concepts](../../guides/concepts.md), [integration](../../guides/integration.md), [API reference](../../guides/api-reference.md)

## 1. Title

A context per run: variables and the results of the nodes that ran, readable by later nodes.

## 2. Context

Nodes of an action ran independently: a later node could not use what an earlier one produced. Branching on a value
(If/Switch nodes), card parameters and an agent all need a place where a run keeps values, and a way for a node to read
them without a scripting language.

## 3. Decision

- **Storage.** `executions.context` (JSON text, default `{}`, deferred) is the only copy. The live run reads and writes it
  through `pipeline_runs.execution_id`; deleting the execution (by hand, retention, clear, policy, artifact FK cascade)
  deletes the context. A new start opens a new execution and so begins empty. `recover()` does not touch it: the
  context of an interrupted run stays readable.
- **Shape.** `{"vars": {name: value}, "nodes": {key: {name, kind, outcome, port, exit_code, output, reason, data, at,
  truncated?}}}`. Per node only the compact facts and the output cut to 4 KiB (the whole output stays in
  `run_node_results`, the single place for it); the whole context at most 64 KiB, the variables alone at most 32 KiB.
  When the context grows too large the oldest node results lose their output, then their data, then are dropped;
  variables are never dropped, a write that does not fit fails the writing node with that reason.
- **Writing.** The engine records every executed node (Code, HTTP, timer) with a single `UPDATE` of the execution row
  that also counts the step, in the transaction of the step record, from the already masked result. A Code node's result
  protocol (last stdout line, JSON with `ok`) may carry `"vars": {name: value}`: names `[a-z][a-z0-9_]{0,63}`, JSON values
  nested at most 3 levels, at most 100 per node; only a passing node's variables count; an invalid one fails the node
  with "Invalid vars: ...". The line must fit the 8 KiB tail the protocol is read from.
- **Node keys.** The key of a node is its name with characters outside `A-Za-z0-9_-` replaced by `_`. Names are not
  unique. A reference resolves to the node of the frozen snapshot that has that name; two different nodes with the same
  name make it fail with "ambiguous node name" (both are listed). A node that ran several times keeps its latest result.
- **References** (one module, `engine/context.py`; no expressions): `${node.NAME.output|exit_code|outcome|reason|data}`,
  `${node.NAME.data.key.sub.0}`, `${var.name}`. Text as it is, anything else as compact JSON. Allowed in an HTTP node's URL
  path and query (percent-encoded, never scheme or host), header values and body. A Code node's text is never
  interpolated; the whole context is the read-only file `context.json` in its temporary working directory. Context and
  secret references are replaced in one pass: a replaced value is never scanned again, so a response that contains
  `${secret:X}` stays that text. An unresolvable reference fails the node with a reason that names it.
- **Visibility.** The execution detail (`GET .../executions/{id}`, `/api/v1`, MCP `get_execution`) and
  `GET .../executions/{id}/context` carry the context; lists do not; a run read has `context_size`. Saving an HTTP node
  returns `warnings` about ambiguous, unknown or malformed references (it is saved anyway).

## 4. Consequences

- Cost: one UPDATE of one row per executed node, no additional query; at most 64 KiB written per node. The context counts
  toward the retention budget: with the default of 50 executions per artifact an execution holds at most about 1 MiB of
  step output plus 64 KiB of context.
- `context.json` exists only in the node's temporary directory (tmpfs `/tmp`), written just before the script starts and
  removed with the directory; nothing persistent is written to disk.
- Context values are text from outside (responses, script output): references paste them literally, nothing evaluates
  them. A node that reads a secret can still put it into a variable on purpose; masking covers the value as the node
  returns it, like everywhere else (ADR-024).
- The context lives in the execution row, so every way of deleting an execution (or its artifact) removes it and,
  with `auto_vacuum = FULL` (ADR-005, update of 2026-11-22), gives its space back to the file system.
- Follow-ups: editor autocomplete for references, the If/Switch nodes, card parameters, the agent, resuming a stopped run
  with its context.
