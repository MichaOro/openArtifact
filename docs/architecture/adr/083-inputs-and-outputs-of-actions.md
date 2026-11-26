# ADR-083: Inputs and outputs of actions

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-033](033-run-context.md) (a run's context gets the inputs of the action that runs), [ADR-072](072-result-contract.md) (an action node leaves a result of its own), [ADR-054](054-node-kinds-as-yaml-manifests.md) (settings `fields` with an extra text and `mapping`)  
**Implemented in:** `graph/nodes/trigger.yaml`, `output.yaml`, `complete.yaml`, `action.yaml`, `pipeline.yaml`, `graph/field_schema.py` (`extra`, `coerce`), `graph/node_types.py` (`mapping`), `engine/context.py` (`bind_inputs`, `build_outputs`, `${input.name}`), `engine/runner.py` (`_run_action`, `_walk_called`, `_place_result`), `static/js/components/schema-fields.js`, `editor/setting-controls.js` (`MappingControl`)  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [concepts](../../guides/concepts.md)

## 1. Context

An execution has one shared context: a later node reads the result of an earlier one, also from another action. That works without a contract, but
names collide, the inner nodes of a definition are overwritten by every placement, and nothing says what an action needs or gives. The owner wants an
action (and a pipeline) to declare its inputs and outputs so that, in a stage, the third action can take what the first and second produced, even when
the first and the second are one definition.

## 2. Decision

- **Inputs on the Trigger, outputs on the end.** A definition declares its **inputs** on its Trigger and its **outputs** on its Output (a pipeline on its
  Complete). Both are lists of flat fields (name, type, required, default or value, description) with the editor and the check of the Hand Over Tool
  (`graph/field_schema.py`, `components/schema-fields.js`); an input carries a **default**, an output a **value**. Types: text, number, true/false, choice
  (inputs only) and list; a value is read as its type (`coerce`), with a plain message when it does not fit.
- **Optional and backward compatible.** A definition that declares nothing runs as before: its nodes read the shared context and the node that runs it
  leaves no result of its own. The settings sit in the nodes' config (no migration).
- **The node that runs it maps the inputs** (`input_values`, one text per input, drawn as one row per declared input): a text, `${card.x}`, or a reference to
  the outputs of an earlier node (`${node:<id>.data.name}`). An empty row uses the default; a required input without a value fails the run with
  `Name: input 'x' is required and has no value`; a value that does not fit the type fails with the input and the value. Inside the definition the inputs
  are read as `${input.name}` (an optional input without a value reads as empty text).
- **Outputs are the result of the node.** When a definition with a contract ends on *On Pass*, its outputs are worked out (references in their value are
  resolved inside the definition, with its inputs) and stored as the `data` of the **node that ran it**, by the id of that node (ADR-082), with the
  result contract (`success`, `outcome`, `reason`, `attempts`); a failure leaves `success` false. An output that cannot be worked out fails the action
  with `output 'x': …`. Only the declared outputs are visible from outside, not the inner nodes.
- **Same definition, own results.** The result is kept by the id of the placement, so three placements of one definition have three results; the
  context also shows the `inputs` of the action that is running while it runs.
- **A pipeline is the same.** A called pipeline declares its inputs on its Trigger and its outputs on its Complete; the pipeline node that calls it maps the
  inputs (`input_values`) and the outputs become the `data` of the pipeline node (`_walk_called`), evaluated where the called pipeline ends, with its inputs.
- Not built: an earlier run of a placement, and mock data for a test run (they follow with the dry run).

## 3. Consequences

- The check before publishing (ADR-082) reads a declared contract: a required input without a mapping, an output that is not declared, and an action that
  declares nothing but is read as if it did, are findings.
- The window of the Trigger, the Output, the Complete and of the node that runs an action are the places to see and change the contract.
