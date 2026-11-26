# ADR-082: References by the id of a node, numbered placements, and the check before publishing

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-033](033-run-context.md) (a node can be named by its id), [ADR-070](070-versions-of-actions-and-pipelines.md) (publishing asks a check first)  
**Implemented in:** `engine/context.py` (the id form, `NodeIndex.by_id`, `RunContext.entry_of`), `graph/placements.py`, `graph/preflight.py`, `api/graphs.py` (`GET …/check`, the publish body), `graph/repository.py` (`_numbered`, `placement_numbers`), `static/js/editor/reference-completion.js`, `findings.js`, `publication-control.js`, `versions-tab.js`, `clipboard.js`  
**Affected chapters:** guides [execution nodes](../../guides/execution-nodes.md), [API reference](../../guides/api-reference.md), [concepts](../../guides/concepts.md)

## 1. Context

A reference in a setting named a node by its **name**: `${(Fetch).output}`. Names are not unique, and the same action definition can be placed three
times in one pipeline, so three nodes carry one name: the reference failed with "ambiguous node name", and the nodes inside a definition shared one
result key, the latest run of any placement winning. A rename also broke every reference to the node. The edges of the graph already name nodes by
id; only the text did not.

## 2. Decision

- **A reference can name a node by its id:** `${node:<uuid>.output}`, `${node:<uuid>.data.key}` and every other field of the result. The name forms
  `${(Name).field}` and `${node.NAME.field}` keep working while the name is unique; nothing in stored text is migrated, and a context stored before
  ids answers an id by the name of the node (a context entry carries the `id` of the node that ran from now on).
- **The editor inserts the id and shows the name.** The reference list shows `(Fetch).output` and inserts `node:<uuid>.output`; typing a name finds the
  node, typing the id form works too. A field whose text holds ids shows a line under it, `Reads: …${(Fetch).output}`, with the names the nodes have
  now, so a rename shows at once and changes nothing. Where an input cannot hold a chip, the line under it is the readable form.
- **Results are kept per node id.** Two nodes of one name keep both results (the second gets the key `Name~<first 8 of its id>`); the context keeps
  one entry per node and the latest run of a node wins (the visits stay in the history; a run index is not offered). A placement of an action in a
  pipeline is a node with an id of its own, so one definition placed three times has three results of its own (ADR-083).
- **Placements are numbered.** When the same definition is placed more than once in a pipeline each placement is shown as `Name #n`: a new
  placement takes the **lowest free number** (a gap is filled), the others keep theirs, and the number is shown only while the definition is placed
  more than once there. The number is kept in the node (`config._number`, never a setting) and in a published version (`number`), and is only a label:
  references use ids. Neighbours, flow and editor show it.
- **A paste turns ids into the ids of the copies.** A copied node that holds `node:<old id>` of another copied node reads the copy after the paste;
  a reference to a node that was not copied stays as it is.
- **The check before publishing** (`graph/preflight.py`) reads the draft as data and runs nothing. For every setting of every node it looks at each
  `${…}`: a node by id or name, a card field, a secret, an input of the graph, a variable; and at the inputs a placement maps. **Errors** cannot work
  (a node or output that does not exist, a secret that does not exist, a required input without a value, an `${input.x}` the graph does not declare);
  **warnings** may (a node that is not in front of this one on every path, a variable only a script sets, a node of another action, an input
  mapped that the action does not declare). `GET /api/{pipelines|actions}/{id}/check` answers the findings. **Publish** asks the same: with findings
  the browser opens the confirmation window (as for a delete) that lists them, errors first and by the node's name, and publishes only after
  *Publish anyway* (red when there are errors); the API answers 409 `findings` with the list unless the body says `{"acknowledge": true}`.
  **Saving a draft never checks**: only what is published runs, so a draft may be wrong. The same module is what a later dry run asks.

## 3. Consequences

- A rename breaks nothing; the same action twice in a stage is addressable; an old pipeline runs unchanged.
- Raw text (API, MCP, an Execute Command's input) shows ids, not names; the editor's line under the field is the readable form.
- The check is static: a variable a script sets and a path that depends on data are warnings at most.
- Not built: a run index (an earlier run of a node), a chip inside a text field (a line under the field instead), a check of the guards.

## Addendum 1: how a numbered placement is written on its card

The number is the system's: it counts the placements of one definition in one pipeline (a copied stage in the same pipeline continues the count) and the
user cannot change it. On the card it comes **first and quiet** (`#4`, lighter and not larger than the name, secondary text colour), then the name:
`#4 Test: Code und HTTP`; a card without a number shows only the name. The name is **one line, cut with an ellipsis**, and the whole name (with its
number) is the tooltip; an action card draws its port labels (On Pass, On Error) inside its right edge, so it keeps room for them (`padding-right: 4rem`)
and the name stops before them. The node's window shows the number in front of the heading in the same quiet way; it is not part of the text that can be
edited. A node the user names is edited as a whole: the existing limit of 255 characters stands (the API refuses a longer name with 422; the owner
suggested about 200, and the larger limit that was already there is kept so no stored name becomes invalid). Menus, dialogs, the reference list and the
flow keep saying `Name #n`. `NodeView.nameParts` gives the two parts, `displayName` the whole.
