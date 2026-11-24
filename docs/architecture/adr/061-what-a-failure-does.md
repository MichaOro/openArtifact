# ADR-061: What a failure does: Stop, Continue, or the error output

**Status:** Accepted  
**Date:** 2026-11-24  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-039](039-edit-fields-switch-rules-and-run-limits.md) (the setting *If the node fails*), [ADR-054](054-node-kinds-as-yaml-manifests.md) (a port may be there by a setting), [ADR-060](060-guards.md) (the *error* event is unchanged)  
**Implemented in:** `graph/node_types.py` (`FailureMode`, `NodeType.port_hidden`), `graph/manifest.py` (`visible_when: {setting, equals}`, `option_labels`), `graph/nodes/_shared.yaml` and the kinds, `graph/repository.py`, `engine/runner.py` (`_node_failed`, `_action_failed`), migration `0048`, `static/js/editor/node-types.js`  
**Affected chapters:** guide [execution nodes](../../guides/execution-nodes.md), [concepts](../../guides/concepts.md), [extending](../../guides/extending.md), [API reference](../../guides/api-reference.md)

## 1. Context

*If the node fails* had two values (`fail` and `continue`), and a node always showed an **On Fail** output, an action
always an **On Error** output (when its definition had an Output with On Fail). Most nodes of a pipeline have nothing
connected there, and an owner who does not look after error outputs sees an unused connector on every card. n8n has
three answers to a failure: stop the workflow, continue, or continue using the error output, and shows the error output
only for the third.

## 2. Decision

- **Three values** of `on_failure`, for every kind that has the setting and for **actions**: `fail` (*Stop the run*, the
  default), `continue` and `error_output` (*Error output*). They are named by `FailureMode`.
- **`fail`**: the failure ends the action as failed. For an action, that fails the run (`"Name" failed: reason`). The
  error output is not there.
- **`continue`**: the failure is recorded, the flow goes on through **On Pass**, and the step keeps its failure and its
  reason, followed by "(continued through On Pass)". The error output is not there.
- **`error_output`**: the flow goes on through the error output (On Fail of a node, On Error of an action). If nothing is
  connected there, the action fails (a node) or the run fails (an action), as it did before.
- **The failure is data**, whatever the value: the step's `data.error` is `{message, mode, node}`, so a later node reads
  `${node.NAME.data.error.message}`; `output` stays what the node produced. An action set to `continue` or `error_output`
  leaves the same `data.error` in the run context under its own name.
- **The error output exists only with `error_output`.** A manifest says so with a port's `visible_when: {setting:
  on_failure, equals: error_output}`; a setting that is not set counts as its default. The server **refuses** a connection
  at a port that is not there (422, "The error output of … is off: set … first"). A change of the value that hides a
  port with a connection first **refused** it; since the addendum below it disconnects and says so.
- **An action's error output no longer depends on its definition.** Before, it existed when the definition's Output had
  *On Fail* (and linking another definition could remove the connection). Now only the action's own setting decides;
  the Output's *On Fail* only decides whether the definition itself can end in a failure.
- **Migration 0048:** a node or action with a connection that leaves its error output gets `error_output` (it followed that
  connection before); one set to `continue` never used the output, so a connection there was dead and is removed; all others keep
  their value. A guard's *error* event fires on the actual failure, whatever the value.

## 3. Consequences

A pipeline that is not looked after shows one output per card instead of two, and a failure with no route stops the run with
its reason instead of looking for a connector that is not drawn. A failure that was handled through `fail` + a connection before
needs `error_output`, which the migration sets. Third parties declare the setting once (`use: on_failure`) and the port with
`visible_when`; the server's rule and the editor's drawing follow from it. The step shows `outcome: fail` with `port: pass`
(continued) or `port: fail` (error output).

## 4. Addendum 2026-11-24: the error output is one state of a definition and its uses

An action definition can be used in many places, and the owner switches *On Fail* on in the definition and expects the
place that uses it to get *On Error*, and the other way round. The decoupling of §2 left the two apart, so one of them
had to be switched twice. They are now **one state**, kept in step by the server in one transaction. This is a
deliberate decision: the definition is shared, so a change on one side reaches every use, and the notices say so.

- **State.** The definition's Output `fail_enabled` (*On Fail*) and, per use (an action node), `on_failure =
  error_output`. Older definitions may hold several Outputs; the switch of one is the switch of all, and a definition
  *has* On Fail if any Output has it.
- **Definition On Fail on:** every use whose value is `fail` (stop) gets `error_output`. A use on `continue` is left alone.
  Nothing changes in behaviour: an error output with nothing connected fails the run like *Stop the run*. No notice.
- **A use set to `error_output`:** the definition's On Fail is switched on and, as above, the other uses on `fail` follow.
  The editor says *Also switched on in the action 'X'; it applies to N other uses.* **only when N > 0**.
- **Definition On Fail off:** the connections at the error output of **every** use are disconnected, the uses on
  `error_output` fall back to `fail`, and the connections inside the definition that end at the Output's *On Fail* are
  disconnected too. The editor says how many and where (*Disconnected N connections (…)*), only when N > 0. Nothing else
  is repaired: drawing a connection again is the user's work.
- **A use leaves `error_output`:** its own connection at the error port is disconnected. The definition's On Fail goes off
  only if no other use is still on `error_output` (then as above); otherwise it stays on and the notice says *Stays on …
  N other uses still have the error output.*
- **Linking** an action node to a definition does the same: a use on `fail` of a definition with On Fail gets
  `error_output`; a use on `error_output` of one without it switches it on.
- **Disconnect instead of refuse** holds for every kind: a node that leaves `error_output` loses the connection at its On
  Fail and the answer says so. Creating a connection to a port that is not there is still refused.
- **One function, one transaction.** `GraphRepository.update_node` does all of it (`_sync_definition`, `_sync_use`,
  `_definition_off`); a failure keeps nothing. The `PATCH` of a node answers with `notices` (machine readable:
  `definition_on`, `definition_stays_on`, `disconnected`) and `reload` (other nodes of this graph changed); the **other**
  graphs that changed are announced by the event `graph.changed` (`{"graph_ids": [...]}`), so an open editor loads
  the graph again.
- **Migration 0050** brings existing data in step: a use on `error_output` switches its definition's On Fail on (its other
  uses follow), and every use on `fail` of a definition with On Fail gets `error_output`. Downgrade: nothing to undo.
- **Not included:** a view of all uses of a definition for cleaning up (an optional board card).

