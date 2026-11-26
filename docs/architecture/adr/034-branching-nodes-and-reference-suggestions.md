# ADR-034: Branching nodes and reference suggestions

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-021](021-execution-nodes-as-executors.md), [ADR-022](022-node-settings-as-json-config.md)  
**Amended by:** —  
**Implemented in:** migration 0029 (kind check gains `if`, `switch`); `engine/branching.py`, `engine/executors.py`, `engine/results.py` (`NodeResult.port`), `engine/runner.py` (`_run_action`), `graph/node_types.py` (`IfType`, `SwitchType`, `Setting.group`, `Setting.references`, `sets_variables`), `graph/rules.py` (`Endpoint.config`), `graph/repository.py`; `static/js/editor/node-types.js`, `reference-completion.js`, `reference-suggest.js`, `setting-controls.js`, `inspector.js`  
**Affected chapters:** [05.06](../arc42/05-building-block-view/05.06-execution-engine-internals.md), [05.07](../arc42/05-building-block-view/05.07-frontend-dialogs-tabs-and-flow-viewer.md), [06.06](../arc42/06-runtime-view/06.06-start-of-an-execution.md), [12](../arc42/12-glossary.md); guides [execution nodes](../../guides/execution-nodes.md), [extending](../../guides/extending.md), [concepts](../../guides/concepts.md), [security](../../guides/security.md)

## 1. Title

Two nodes that choose the way on (If, Switch), suggestions while typing a reference, and declared variables.

## 2. Context

The run context (ADR-033) made values available to later nodes, but the way through an action definition was still
decided by pass or fail alone. Branching on a value needs nodes that read the context and leave by a port of their
own choice, without turning the editor into a scripting language.

## 3. Decision

- **Two kinds, no language.** `if` (outputs `yes`, `no`, `else`) and `switch` (`case_1` ... `case_6`, `else`), in action
  definitions, addable, chained, input `in`. Fixed, documented comparison rules in `engine/branching.py`: text compared
  as text (trimmed), numbers parsed strictly (`[+-]digits[.digits][e[+-]digits]`) for the numeric operators and for
  `equals` when both sides are numbers, booleans only `true` / `false`, empty is `""`, `null`, `[]`, `{}`;
  case-sensitive unless switched off. No regular expressions, no expressions, no loops.
- **`else` means: could not be decided.** An unresolvable reference, a side that is not a number or a boolean where one is
  required, or no condition at all sends the If node to `else` with outcome `fail` and a reason that names the
  reference. A Switch that simply matches no case leaves by `else` with outcome `pass`; an unresolvable value is the same
  error as in the If node. A dead end after any port fails the action like everywhere else. These nodes have no
  `on_failure` setting: there is nothing to fail open.
- **Executors choose their port.** `NodeResult.port` (optional) names the output; without it the engine decides by
  `by_outcome` as before (Code, HTTP, timer unchanged). The step records the port, so the flow replay (ADR-027) follows
  `yes` / `no` / `else` / `case_n` with no change of its own.
- **Settings stay flat.** The conditions are ordinary config settings (`left_1`, `operator_1`, `right_1` ... five rows,
  unused rows are empty); `Setting.group` only tells the inspector to show the three fields of a row together. A
  repeating-group control was not built: five fixed rows cost no new machinery. The Switch cases are `case_1` ...
  `case_6`; a case without a value is unused: its output is hidden in the editor, the connection rules refuse an edge from
  it (`Endpoint.config`), and emptying a case deletes its edge.
- **Context is the only source.** Both nodes read references through the existing resolver. `${secret:NAME}` in a
  condition is refused when it is saved: a branch could reveal a secret value bit by bit. Saving returns `warnings` for
  unknown or ambiguous node names, as for HTTP nodes.
- **Recording.** If: `data = {"condition": true|false|null, "rows": [{"left", "operator", "right", "result"}]}`; Switch:
  `{"value", "matched": "case_2"|null}`; resolved values cut at 200 characters. They come from the masked context.
- **Suggestions.** `Setting.references` (`context` or `all`) tells the editor which text settings take references; typing
  `${` (or Ctrl+Space inside one) opens a list of node results, declared variables and, where allowed, secret names
  (`GET /api/secrets`, names only). Pure logic in `reference-completion.js`, popup in `reference-suggest.js`
  (listbox with `aria-activedescendant`, live count). Hints only: nothing is validated in the browser. The Code text is
  never interpolated and gets no suggestions.
- **Declared variables.** Code setting `sets_variables` (one name per line). A convention, not a type system: when it is
  not empty and the node passed, the reason of the step notes `undeclared variable 'x'` / `declared variable 'y' was not
  set`; the node does not fail.

## 4. Consequences

- A new migration for the kind check only. Old snapshots are unaffected (no new fields on steps).
- The node-types description grows by `group` and `references`; the old keys keep their meaning.
- Repeating rows are limited to five; more conditions mean a second If node. Regular expressions, loops and resuming a
  run are not part of this decision.
