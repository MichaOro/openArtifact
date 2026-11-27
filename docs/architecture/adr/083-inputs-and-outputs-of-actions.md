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

## Addendum 1: the field list of the Trigger, Output and Complete windows is one row per field

The first version drew every field stacked (name, type and *Required*, a description with the text meant for a model, a default), which is right for the narrow
window of the Hand Over Tool and wrong for a window with room. The `fields` setting that carries an `extra` (the default of an input, the value of an output) is
drawn by the **wide variant** of `SchemaFields` (`wide: true`, the same component and model): **one row per field under a row of column heads**: handle, *Name \**,
*Type*, *Required* (not in an output's list), *Description*, *Default* (inputs) or *Value* (outputs), bin; the columns of the heads and of the rows are one grid
(`rowPlan` in `schema-fields-model.js` gives the columns and the template). The keyboard goes through a row in the order of its columns (name, type, required,
description, default or value, bin). The text "What the model puts here" and the default and value placeholders are not drawn there (the head names the column; the
text for a model belongs to the Hand Over Tool, where it stays). The window gets the wide size (`is-wide`, 56 rem) when it holds such a list. In a window narrower than
44 rem (a container query on the list) the stacked layout is back, so nothing lies over anything at any width. The values of a choice stay a line of their own under
the row.

## Addendum 2: compact rows with a menu, and the contract is the one of the version that runs

**Compact rows.** Addendum 1 drew a description and a default column in every row; the Trigger, Output and Complete windows became too wide for what they hold. The
wide variant now draws **one compact row per field**: handle, *Name \**, *Type*, *Required* (the shared Checkbox), the value of an output, and a **⋮ button**. The
description and the default of an input are not columns: the ⋮ menu (`ActionMenu`, `role=menu`) offers *Add description*, *Add default value* (inputs only) and
*Delete*; an added one is a line under the row and its item then reads *Remove …* (removing clears the value). The bin is in the menu. The keyboard: Tab to ⋮,
Enter or Space opens, the arrows move, Escape closes. Below 28 rem (a container query on the list) the row stacks. The Hand Over Tool keeps its compact layout
without the menu. This replaces the column list of addendum 1; the container threshold there (44 rem) is now 28 rem.

**The contract is read from the version that runs.** What a placement shows as inputs and outputs, what the check validates mappings against and what a run
requires is the contract of the version an execution uses (ADR-070, `graph_for_run`): the published one, and for a graph never published its draft. One server
function, `graph/contract.py` (`contract_of`, answered by `GET /api/{kind}/{graph_id}/contract` with `running` `published` or `draft`, `version`, `draft_changed`),
serves the editor, `preflight.check` and the run. While the draft of an action is edited the pipelines keep the published contract; it changes when the action is
published, republished or its draft discarded, which publishes the event `graph.contract_changed` so an open pipeline editor reads it again. This corrects the
first version of this ADR, where the editor read the draft.

**Publish warns about the users.** Publishing an action or pipeline whose contract changes adds warnings (never errors; the owner decides) naming the graphs that
use it: `contract_input_removed` (a placement still gives a value to a removed input), `contract_input_new` (a placement has no value for a new required input),
`contract_output_removed` (an output a graph may read is gone). Nothing is reported while the graph was never published.

**Names ghosted.** At a placement each declared input is a mapping row whose placeholder is the input's name; a typed value overrides it, the default is shown
muted beside the label.

## Addendum 3: what a row shows beside the compact row is a column when the window has room

Seen in use, the description and default lines under a row made the list look cramped. Now, when any row of the list shows a description or a default (the row menu),
those are **columns of the same row**, to the right of the compact row (`Default`, `Description`, each with a column head; a row that has none leaves its cell empty),
so a field stays one line without wrapping, and the Trigger, Output and Complete window **widens** to hold them (`#node-modal:has(.sf--inline)`, at most 62 rem and never
wider than the screen). When the list is narrower than 44 rem (a small screen) they stay the lines under the row of Addendum 2. `rowPlan` returns both layouts
(`inlineColumns`, `inlineRow`, `isInline`); the list decides from the rows' `shown` state and redraws its heads. The "Required" box is as tall as the fields beside it
(2.7 rem, a square), its column is 3.75 rem wide and its tick is larger.
