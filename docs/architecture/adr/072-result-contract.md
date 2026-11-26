# ADR-072: The result contract of a node

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-033](033-run-context.md) (the shape of a node's entry in the run context), [ADR-054](054-node-kinds-as-yaml-manifests.md) (what a kind that produces a result must leave)  
**Implemented in:** `engine/results.py` (`NodeResult.success`, `attempts`, `duration_ms`), `engine/context.py` (`record`, the reference fields), `engine/runner.py` (the time is measured by the engine), `engine/schemas.py` (`ContextNodeRead`), `engine/guard_views.py` (`success`), `static/js/editor/reference-completion.js`, `tests/test_result_contract.py`  
**Affected chapters:** guide [execution-nodes](../../guides/execution-nodes.md#results)

## 1. Context

Every kind of node told the run what happened in its own words: a Code node has an `exit_code`, an HTTP node a `status` in `data`, an
If node a `condition`. A later node (an If, a Set, a guard, an agent reading the context) could read `outcome` (the text `pass` or
`fail`) and `output`, but not ask the one question every flow asks: *did it work?* as a boolean, nor how many tries it took. The owner
wants a canonical schema that every node maps to, so that `success` can be asked of any node; the node knows whether it succeeded.

## 2. Decision

- **One core for every node that ran**, in the step and in the run context: `success` (boolean), `outcome` (`pass` | `fail`), `reason`,
  `output` (4 KiB in the context, the step has all), `data` (the extras of the kind), `attempts` (whole number, 1 without *Retry on fail*,
  ADR-073) and `duration_ms` (wall time in milliseconds). `exit_code` stays where a kind has one.
- **`success` is derived, never set apart:** it is `outcome == "pass"`, computed by the engine when the result is recorded
  (`NodeResult.success` is a property). A kind cannot say `success` and `outcome` differently, so there is nothing to keep in step.
- **The engine measures `duration_ms`** around the whole node, all tries and the waits between them included. A kind's own
  `NodeResult.duration` (seconds) stays what it was.
- **References:** `${(Node).success}`, `.attempts`, `.duration_ms` (and the older `${node.NAME...}` spelling). `success` renders as `true`
  or `false`, which is what an If node's *is true* / *is false* reads. Only `data` takes a path.
- **Nothing is taken away.** `outcome`, `exit_code`, `reason`, `output`, `data.key` mean what they meant; old pipelines run unchanged. A
  context stored before this ADR has no `success` or `attempts`: the resolver and the API (`ContextNodeRead`) derive `success` from
  `outcome` and `attempts` as 1.
- **The editor offers the three new fields** after `${(Node).` for every node that leaves a result; guards read `success` in
  `v_guard_steps` (`attempts` too, with ADR-073).
- **The contract is kept by a test:** `tests/test_result_contract.py` runs every registered executor and checks that the entry has the
  core with the right types, and that a manifest that says `produces_result` has an executor.

## 3. Consequences

- A condition on any node is `${(Name).success}` is true, the same for Code, HTTP, Postgres, an agent or a future kind: a new kind that
  returns a `NodeResult` gets the whole core for free.
- Mapping to the canonical schema is the kind's job only for `output` and `data`; the extras stay in `data` under the keys the
  guide lists per kind.
- The contract is about the *result of a node*, not the state of a run, a stage or an action (an action's failure is data of the action,
  ADR-061).
