# ADR-080: The Hand Over Tool: a model hands over a document that the server checks, and a later node reads it

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-040](040-agent-tools.md) (a new kind of tool node), [ADR-054](054-node-kinds-as-yaml-manifests.md) (a new kind and a new setting type, `fields`), [ADR-072](072-result-contract.md) (the result of a tool node, recorded by the agent node), [ADR-078](078-build-context-node.md) (a new source, *Handover documents*)  
**Amended by:** —  
**Implemented in:** `graph/field_schema.py` (the schema and its check), `agents/handover.py` (the sink of one node run), `agents/local_tools.py` (`build_handover_tool`), `engine/results.py` (`NodeResult.recorded`), `engine/context.py` (`RunContext.record`), `engine/executors.py` (`_agent`), `engine/context_builder.py` (the source), `graph/nodes/handover_tool.yaml`, `components/schema-fields.js` and `schema-fields-model.js`, `FieldsControl` in `editor/setting-controls.js`, migration `0062`  
**Affected chapters:** guides [agents](../../guides/agents.md), [execution nodes](../../guides/execution-nodes.md), [ui catalog](../../guides/ui-catalog.md)

## 1. Context

An agent answers in text. A node after it that must branch on the answer ("did the review pass?") has to read free text, which is unreliable: the
model writes it in whatever form it likes. The review of card #117 asked for *handover files*: named JSON documents with a schema that a step writes and
a later step reads, checked at the moment of writing, with the exact reason going back to the writer so that it can correct it. The application has no
workspaces and no files for runs (ADR-032), so the "files" are documents of the run.

## 2. Decision

- **A tool node `handover_tool`** (label *Hand Over Tool*, German *Übergabe-Tool*) attached to an agent like the other tool nodes. Its settings are the tool
  name and description, **the fields** and a size limit. The tool's parameters for the model are exactly the fields (a JSON schema of an object, no other
  keys allowed).
- **A schema is a flat list of fields**, one small module for it (`graph/field_schema.py`): a field has a `name` (lowercase letters, digits, `_`, at most 32
  characters), a `type` (`text`, `number`, `boolean`, `choice` with 2 to 20 values, `list` of texts), `required` and a `description`. At most 30 fields. **No
  nested objects**: a flat shape is what a model fills in reliably and what a condition can read with `${(Node).data.field}`. The same module checks a stored
  list (`normalise`), says what the model is told (`json_schema`) and checks a document (`validate`).
- **The check is data checking only.** Types, required fields, the values of a choice, no field that is not in the list, text of at most 8000 characters, a
  list of at most 50 texts of at most 500 characters, the whole document at most the node's *Size limit* (1 to 64 KiB, default 16 KiB). A left-out or `null`
  field is "not given"; a required field may be neither. **All problems come back at once, in plain words** (`'passed' must be true or false; 'verdict' is
  required`), as the tool's error text, so one more call can fix them; it counts as a failed tool call like any other. Nothing in a document is evaluated,
  and a text that looks like a reference (`${secret:X}`) stays that text everywhere it goes.
- **An accepted call answers `handed over`; the last accepted document counts.** Every call stays in the step's tool calls. The node run keeps a
  `HandoverSink` (in the tool context): it counts the calls per tool node and holds the last document that passed.
- **The document is the result of the tool node.** A tool node has no step of its own, so when the agent node has ended, the engine stores each accepted
  document in the run context **under the tool node's name** as that node's result (`NodeResult.recorded`: `RunContext.record` stores the extra results
  after the node's own): `data` is the document, `output` its JSON, `outcome` `pass` (so `success` is true), `attempts` the number of calls the model
  needed. A later node reads it with the normal references, `${(Review).data.passed}`; the result contract holds (ADR-072). The kind is therefore not in the
  list of kinds without a result. **The agent's step** keeps the documents too: `data.handovers` (`{name: document}`) and a fact line *Handed over: Review*.
  A document is stored even when the agent fails afterwards; when no call ever passed, nothing is stored and a reference says the node has not run.
- **Masking.** The documents are masked for the secrets the agent used, like the rest of its result.
- **Build Context** gets a source, *Handover documents* (`handovers`): the documents of this run as `### name` and `field: value` lines, oldest first,
  optionally only those named. It works without a card. The list of sources is nine now, so at most nine in a list.
- **The editor of the fields is a shared component** (`components/schema-fields.js`, the rules in `schema-fields-model.js`): rows with a handle (drag or
  the arrow keys), the name and a bin, the type and *Required*, the description and, for a choice, its values. It knows nothing of the node: it takes a list
  and tells its owner when to save (`onInput` while typing, `onSettle` when a choice is made or a text field is left). `FieldsControl` (the `fields` setting type) is
  its only user today. The next card, *the structured answer of the agent* (the model reports its final answer as a validated document, with one repair
  attempt), mounts the same component and calls the same `validate`.
- **Only an agent writes a document.** The tool node is the only writer. A step that is not an agent could write one through a node of its own that takes a
  schema and a source for the values and uses the same `validate`; that is not built.
- **Migration 0062** adds the kind to the check of `graph_nodes`; the downgrade removes the nodes of the kind and their edges.

## 3. Consequences

- A review, a classification or a verdict can be a decision a condition reads, not a sentence to parse. The model sees the fields and their descriptions as
  the parameters of one function, which models fill in more reliably than a requested text format.
- A refused call costs one more round of the model; the iteration limit of the agent bounds it, and the step shows every call.
- The documents of a run are limited like every node result: the run context keeps at most 64 KiB in all and drops the oldest results first (ADR-033), so
  a large document should stay small (the node's size limit is 16 KiB by default).
- A field named like the keys of the result (`output`, `success`) is no problem: the document is under `data`.
- Flat only. A list of objects has to be several tools or several fields; that is on purpose.
