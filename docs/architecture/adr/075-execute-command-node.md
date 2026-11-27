# ADR-075: The Code node is called Execute Command, is off by default and has an output limit of its own

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-021](021-execution-nodes-as-executors.md) (the node's name and default), [ADR-023](023-safety-model-of-execution-nodes.md) (the switch is off unless set), [ADR-053](053-canonical-node-configuration.md) (a `size` setting), [ADR-059](059-one-catalog-of-ui-building-blocks.md) (a new component, `SizeInput`), [ADR-074](074-setting-row-and-durations.md) (sizes follow the rule of durations)  
**Implemented in:** `config.py` (`code_nodes_enabled` is `false`), `engine/executors.py` (`CODE_DISABLED_REASON`, `node_output_limit`), `agents/local_tools.py`, `api/graphs.py` (`unavailable`), `graph/nodes/code.yaml`, `graph/nodes/code_tool.yaml`, `graph/node_types.py` (`size`), `static/js/components/size-input.js`, `static/js/components/size-model.js`, `static/js/editor/setting-controls.js` (`SizeControl`), `static/js/editor/add-menu.js`, `static/js/editor/inspector-panel.js`, `tests/test_execution_nodes.py`, `tests/js/size-model.test.mjs`, `tests/e2e/test_execute_command.py`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [security](../../guides/security.md), [configuration](../../guides/configuration.md), [operations](../../guides/operations.md), [agents](../../guides/agents.md)

## 1. Context

The node called *Code* runs shell or Python text as a child of the application, with the application's own rights: it can read the database and
the data volume and reach the network ([security guide, section 5](../../guides/security.md)). That is what n8n calls *Execute Command*, not
what its *Code* node is (JavaScript or Python in an isolated runtime with an allow-list of modules; *Execute Command* is a node of its own that
n8n has switched off by default since version 2.0). Calling the node *Code* suggests a protection it does not have. The owner decided: name it
honestly, switch it off unless the environment says so, keep the scripts of the old n8n pipeline running through it on his own instance, and
build a real Code node with a sandbox later (card #133).

## 2. Decision

- **The name people read is *Execute Command*; the kind id stays `code`.** The manifest's label (and the tool's, *Execute Command Tool*) and every
  text of the interface and the guides change. Stored actions, pipelines and agent tools name the kind `code` / `code_tool`, the API, the
  history and the context keep those ids, so old definitions run unchanged: there is **no alias table and no migration**, because nothing stored
  holds the name. A node added from now on gets the label as its default name (*Execute Command*); a stored node keeps the name it has, so a
  reference such as `${(Code).output}` keeps working.
- **Off by default.** `OPENARTIFACT_CODE_NODES_ENABLED` is `false` without an entry. A node (and the Execute Command Tool of an agent) then
  fails with `CODE_DISABLED_REASON`: "Execute Command nodes are switched off on this instance: set OPENARTIFACT_CODE_NODES_ENABLED=true in the
  environment and restart to switch them on". The editor does not hide the kind: `GET /api/node-types` carries `unavailable` (the reason) for
  `code` and `code_tool`, the "+" menu marks the entry *Switched off* and the node's window says so at its top; the node stays editable.
- **The breaking change.** An installation that used Code nodes and updates keeps its data, but every such node fails until the variable is
  `true` in its environment (`deploy/.env`). The owner's instance has it set. `deploy/.env.example`, the configuration guide and the update
  notes of the operations guide say so.
- **An output limit per node.** An optional setting `output_limit_bytes` (type `size`, a number and a unit B, KiB or MiB, kept as bytes, 1 KiB
  to 64 MiB) caps what the node keeps of standard output and standard error, each. `OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES` stays the ceiling: the
  effective limit is the smaller of the two (`node_output_limit`), and the setting's help says so. The setting row and the unit select follow
  [ADR-074](074-setting-row-and-durations.md); an added setting starts at 64 KiB and is stored at once, like *Retry on fail*.
- **Not built:** a command with separate arguments (a shell text already is one) and a free working directory (the private directory that is
  deleted afterwards is part of what limits the damage).
- **Honest text.** The node's help says "Not a sandbox"; the security chapter keeps its list of what the node does not do.

## 3. Approaches considered

1. **Keep the name, only document the limits.** Rejected by the owner: the name promises more than it gives.
2. **Rename and migrate the kind id (`execute_command`).** Rejected: it would rewrite stored graphs and the snapshots of past runs for no
   gain; the id is internal.
3. **Rename the label only, off by default (chosen).** Smallest change that stops the suggestion of protection; the sandbox is a separate card.

## 4. Consequences

- Existing installations need one variable to run their Execute Command nodes again; that is the price of a safe default.
- A new node's context key is `Execute Command` (the default name); tests and examples that relied on `Code` as a default name changed with it.
- Retry, the result contract, guards and history are unaffected: they know the kind by its id.
