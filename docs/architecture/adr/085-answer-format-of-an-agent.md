# ADR-085: The answer format of an agent: the final answer as a checked document, with one repair

**Status:** Accepted  
**Date:** 2026-11-26  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-040](040-agent-tools.md) (the loop ends with a report instead of free text), [ADR-047](047-agent-versions-and-use.md) (a new setting of the agent), [ADR-054](054-node-kinds-as-yaml-manifests.md) (the `fields` setting may refuse reserved names), [ADR-072](072-result-contract.md) (what `data` of an agent holds), [ADR-080](080-hand-over-tool.md) (its schema module and editor are reused)  
**Amended by:** —  
**Implemented in:** `agents/answer_format.py` (the report tool, the sink, the reminder), `agents/loop.py` (the ending of the loop, the reminder, the repair, the final request), `agents/runtime.py`, `agents/tools.py` (`Toolbox.add`, `schemas(only=)`), `agents/schemas.py` (`AgentConfig.answer_format`), `graph/field_schema.py` (`RESERVED_NAMES`), `graph/nodes/agent.yaml` (the setting `answer_format`), `static/js/agents/editor-page.js`, `static/js/editor/` (the reference list), `static/js/agents/view.js`  
**Affected chapters:** guides [agents](../../guides/agents.md), [execution nodes](../../guides/execution-nodes.md), [api reference](../../guides/api-reference.md)

## 1. Context

An agent answers in text. A node after it that must branch on the answer has to read free text, and a parser that reads the text of a model fails whenever the
model writes it in another form (the output parsers of other tools showed this). The Hand Over Tool (ADR-080) already gives a model a function whose
parameters are the fields of a schema, checks every call and sends the exact reasons back. The card *the structured answer of the agent* asks for the same for
the **final answer** of an agent: a shape you define, a deterministic check, one repair, and the fields as data a condition can read.

## 2. Decision

- **The format is a flat list of fields**, the module and the editor of ADR-080 (`graph/field_schema.py`, `components/schema-fields.js`), not a copy: `AgentConfig.answer_format`
  is checked with `field_schema.normalise`. It is **off by default** (an empty list; an agent without a format is exactly as before). It belongs to the agent's version
  like its prompts (a draft, published versions, ADR-047), and a node may **override** it like any other setting of the agent (ADR-053): the setting `answer_format` of the
  agent node (type `fields`, optional, inherits from the agent). A node's own list wins; **an empty list on the node switches the agent's format off for that node**; a
  node that sets nothing follows the agent.
- **The model answers through a tool.** When a format is in effect the run adds one tool, `report_result`, to whatever tools the agent has (a tool with that name that is
  already there keeps it; the report tool then gets the next free name and the loop uses the name it was given). Its parameters are exactly the fields (a JSON schema
  of an object, no other keys); its description tells the model that the final answer must be given by calling it. Tool calling is the mechanism the loop already has
  (ADR-040); asking a model to write a JSON text and parsing it, or a provider setting such as `response_format`, would be less reliable or not available at every
  OpenAI-compatible provider.
- **A call that fits is the answer and ends the node** at once, with no further request. The checked fields are the node's **`data`** (`${(Agent).data.passed}`, readable
  by If, Switch and Set variable like any data), `output` is the document as JSON text, and the result contract holds (ADR-072). The agent's own data (`model`, `usage`,
  `iterations`, ...) stays next to the fields, so a field may not be named like it: `field_schema.RESERVED_NAMES["agent_data"]` (`agent_id`, `agent_version`,
  `provider`, `model`, `usage`, `finish_reason`, `attempts`, `status`, `iterations`, `tools`, `repaired`, `answer_calls`) is refused when the format is saved, in the agent
  (422 with the name) and in the node's setting (`field_reserved: agent_data`).
- **One repair.** A call that does not fit (a required field missing, a wrong type, a value outside a choice, a field that is not in the list, too big; arguments that are
  no JSON object count too) comes back as the tool result `Error: the answer was not accepted: <all problems at once>. Call report_result again with a corrected answer
  (this is your only repair).` The model may call once more. **A second call that does not fit fails the step**, with the reasons of the last one in `reason`
  (*The answer did not fit the answer format, also after one correction: ...*); the node then goes on as any failed node does (`If the node fails`, ADR-061, Retry on
  fail, ADR-073). A repaired answer passes with the note *the answer was corrected once: <what was wrong>* and `data.repaired` true.
- **A text answer is reminded once.** A model that answers in text without calling the tool gets one more request with the reminder *Give your final answer by calling
  the tool report_result now ... Do not write the answer as text.*; if it answers in text again, the step fails with *The agent did not report a result: it answered in
  text although its answer format asks for the tool ...*. A model without tool calling cannot use an answer format and fails the same way: that is said, not hidden.
- **Other tools come first as usual.** The agent may use its other tools for as many rounds as its limits allow and report when it has the answer.
- **The limits.** When a limit ends the loop (iterations, time, token budget, no progress, a request that failed after tools had run), the final request that ADR-040 makes
  without tools **offers the report tool only** and asks for the answer through it, from the shortened conversation; one call, no repair there. A valid call passes with the
  note that the answer was reported at a limit and may be incomplete; no call or an invalid one fails the step with the reason.
- **What the step shows.** Every call of the report tool is a tool call of the step (the tool node name is *Answer format*), so both attempts and their results stay in
  the history. `detail.answer` holds the calls, the refusals (the problem lists) and the document; `data.answer_calls` the number of calls and `data.repaired` whether a
  repair happened. The step says *Answer reported* or *Answer reported, corrected once*, and the agent's detail lists *Call 1: not accepted: ...*, *Call 2: accepted*.
  `attempts` of the result contract stays what ADR-073 says (tries of the node); the calls of the report tool are not tries of the node.
- **The editor.** The agent's page has the section *Answer format* in its *Prompts* tab (the shared field-list editor); a published version shows it read-only in its
  *Prompts* tab. The agent node's window offers the setting through *Add setting* (the menu names the agent's fields; it starts from them as a new override). The reference
  list offers the fields of the format in effect as `data.NAME` of the agent node: the node's own list, else the published format of its agent (fetched when the graph opens
  and when the agent is chosen).
- **Security.** What the model reports is text from outside: it is stored and pasted as it is and never read for `${...}` references (a `${secret:X}` in a field stays that
  text), the check executes nothing, the document is masked for the secrets the agent used like the rest of the result, and its size is limited (16 KiB, the module's default).
- **No migration.** The format is a key of the agent's configuration and of the node's config; an agent from before has none.

## 3. Consequences

- A review or a classification can be a decision a condition reads, and a model that does not fit gets exactly one chance to fix it, visibly.
- A model that cannot call tools cannot give a structured answer; it needs no format for free text.
- A reminder or a repair costs one more request; the limits of the agent bound it.
- The same module checks the Hand Over Tool and the answer format, and both editors are the same component: a rule of the schema changes in one place.
- A dry run (card *dry run*) runs the model for real, so nothing special is needed here; a mocked agent node (card *mock data*) will return its stored result.
- Not built: nested fields, an answer format for a step that is not an agent, a limit of repairs other than one.
