# ADR-040: Tools for agents: tool nodes attached to the Agent node, the MCP Client Tool, a loop with a bound

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-037](037-agent-harness.md), [ADR-012](012-workflow-definition-editor.md)  
**Amended by:** [ADR-041](041-github-and-postgres-nodes.md) (the Postgres Tool)  
**Implemented in:** migration `0035_tool_nodes`; `graph/node_types.py` (tool kinds, ports with a side), `agents/tool_config.py`, `agents/freeze.py`, `agents/mcp_client.py`, `agents/tools.py`, `agents/local_tools.py`, `agents/runtime.py` (the loop), `agents/client.py` (`tools`, `tool_calls`); the editor (`static/js/editor/`)

## 1. Title

An agent calls tools. Tools are nodes attached to the Agent node from below, as in n8n; the first ones are the MCP Client
Tool (for example GitHub's MCP server), the HTTP Request Tool and the Code Tool.

## 2. Context

ADR-037 built one request per agent node and named tool calling as the next step. The owner takes n8n as the model and
wants an agent that works with GitHub through GitHub's MCP server, with tools as nodes of their own. In n8n the AI Agent
node has a *Tools* connector; tool sub-nodes hang below it and run only when the model calls them. Which tools a node
offers decides what the agent may do (*Tools to include*: all, selected, all except), so a read-only GitHub agent is a
matter of choosing the read tools.

## 3. Decision

- **Attached, not walked.** The Agent node gets an input port `tools` (drawn at its bottom); each tool kind has one output
  port `tool` (drawn at its top) and no flow ports. An edge from `tool` to `tools` is an attachment: the engine never
  walks it; the agent calls the tool. A tool attaches to one agent; an agent takes any number of tools. Only tool ports
  connect to `tools` and a tool port connects only there. The editor draws these edges dashed and vertical.
- **Tool kinds** (action definitions only, addable, settings in `config`):
  - `mcp_tool` *MCP Client Tool*: endpoint URL (Streamable HTTP), the name of the secret sent as a bearer token,
    *Tools to include* (`all`, `selected`, `all_except`) with a list of tool names, a timeout per call. Only remote
    servers: no local process (n8n does the same for this node). GitHub: `https://api.githubcopilot.com/mcp/` with a
    personal access token.
  - `http_tool` *HTTP Request Tool*: a tool name and description for the model, method, URL, headers, body, and
    parameters the model fills (`name: description` per line), used as `{name}` in the URL, headers and body.
  - `code_tool` *Code Tool*: a tool name and description, the Code node's language, code, secrets and limits, and
    parameters like the HTTP Request Tool's; the model's arguments are `input` in `context.json`, the answer is what the
    Code node would give as output (what it prints, or the result protocol's output).
- **The loop.** The agent node sends the request with the tools (OpenAI function calling), runs every tool call of the
  answer, sends the results back and repeats until the model answers without a tool call, at most *Max iterations*
  (agent setting, 1 to 50, default 10, overridable on the node like every setting). The node's time limit covers all
  turns and tool calls; each request keeps its retries (ADR-037). A failed tool call is sent back to the model as an
  error text (as n8n does), it does not fail the node; hitting the iteration limit fails it.
- **Frozen at the start.** The tools attached to an agent node are frozen with the agent into the snapshot.
- **Safety.** MCP and HTTP tools go through the guarded HTTP path (SSRF, metadata refused, pinned addresses, no
  redirects off the origin, capped bodies); the private-network permission is the LLM providers' (operator switch plus
  the tool's own: both MCP and HTTP tools have a *Private network* switch). Tokens only as secrets; the values are masked
  in results, detail and logs, and in a tool's answer before the model reads it. Model-supplied values are put into the
  request after the references are resolved and are never scanned again (a model cannot reach a secret by writing
  `${secret:...}`); a parameter in the scheme or host of an HTTP tool's URL is refused. A Code Tool runs under the Code node's rules (needs the API token, limits, no sandbox).
  Tool results are foreign text for the model and the history.
- **Names for the model.** A tool is called by its *Tool name* (empty: the node's name); an MCP tool keeps its own name.
  When two tools share a name, both get their tool node's name in front; characters a model does not accept become `_`.
- **Failures.** A tool that cannot be used at all (an MCP server that refuses the token or cannot be reached, a Code Tool
  while Code nodes are off) fails the node before its first request, naming the tool node.
- **History.** The step's detail gets the turns: per turn the attempts and the tool calls (tool, arguments, result cut to
  16 KiB, error, duration). Usage is summed over the turns; `data.iterations` counts the requests.

## 4. Consequences

- A read-only GitHub agent is an MCP Client Tool with only read tools selected.
- Not built: memory, several agents, approval before a tool call, local MCP servers, tools of the n8n kind "call a
  workflow".

## 5. Addendum (2026-11-25): the state of a tool node in the run

- A tool call carries the **tool node** it belongs to (`node_id`, `node_name`; a node such as an MCP server offers many tools).
  The step keeps `data.tools`, a summary per tool node (`calls`, `errors`), and the flow of the execution shows it: green (all
  calls went well), red (at least one failed), dim and dashed (never asked).
- The agent loop stays independent of the application: it reports through a callback (`on_tool`, `agents/runtime.py`); the
  engine hands the events to the event bus as **`agent.tool_call`** (`Limits.publish`, `engine/executors.py`) with the artifact,
  the execution, the agent node, the tool node, the tool, `state` (`started`, `finished`), `ok` and `duration_ms`. The
  browser subscribes to it (`EVENT_TYPES`); the flow page counts the calls per tool node while the execution runs and the
  finished step takes over. Events carry names and states only (no arguments, no results, no secrets).
- Not built: a live protocol of the agent's turns, health figures for guards, the state of a call that began before the page was
  opened.

## 6. Addendum (2026-11-25, card #104): the engine of the agent node

**Context.** A review run with the GitHub MCP node showed three problems at once: *Stopped after 10 iterations without a final answer*
(the tools had worked, nothing was lost but the answer), a request that did not answer in time four times with the same large prompt
(156,000 prompt tokens after seven rounds: the whole conversation was sent again each round), and no sight of what the agent was
doing. The owner does not want the agent node held in check by hard limits: the guards judge the health of a run ([guards](../../guides/guards.md));
the node gets a protection of its own that never loses the work.

- **The engine is its own module** (`agents/loop.py`; `completion.py` is the single request, `context_window.py` what the model
  reads). `runtime.py` stays the node: inputs, prompts, tools, `NodeResult`. The engine is driven by `complete`, `sleep` and a
  `Budget`; it knows neither the event bus nor the database.
- **A limit ends in an answer.** The iterations (default 100, up to 500), the time of the node (default 900 s, up to 1800) and the new
  token budget (not set: none), a run that makes **no progress** (the same call with the same result 8 times in a row) and a request that
  **fails for good after tools ran** do not fail the node: the agent gets **one more request without tools** from a shorter conversation
  (results to 3000 characters, older ones to 600) and is asked to answer from what it has. The step **passes with a note** (as with the token limit
  of the model). The final request may take up to 120 s beyond the time limit of the node. Only when it fails too the node fails.
- **The model reads a view.** The conversation is kept whole; each request is made from a view: a tool result is cut at the setting
  *Tool result limit* (default 12000 characters), results of the rounds before the last two are shortened to 1500. The step keeps the
  result as the tool returned it (up to 16 KiB, unchanged), so what the model read and what the tool answered are both known.
- **Calls that repeat** (the same tool, the same arguments, 3 times in a row) get a note on the result for the model, which the step
  does not keep. The judgement whether that is healthy stays with the guards.
- **A tool that hangs** is stopped after 300 s (or the time left) and becomes an error text for the model; it no longer holds the run
  until the time limit of the node and no longer fails the node.
- **Retry policy.** The attempt after a *timeout* gets 1.5 times the time of the one before (at most 300 s); other failures keep the
  limit. The waits (3, 10, 30, 60 s, `Retry-After`) are unchanged.
- **Events.** The engine reports through `signal(event, data)` (it replaces `on_tool`): `tool_call` (now with the round, `turn`) and
  `turn` (a request started or ended: the round, the first 300 characters of the answer, the tokens of the request and in all, the number of tool
  calls it asked for, the limit when it is the final answer, or the error). The engine hands them to the event bus as `agent.tool_call` and **`agent.turn`**.
  The flow page shows the rounds of the selected running agent (*Rounds so far*, `components/live-rounds.js`); the step is the record after the run.
- **New settings** of the agent and of its node (overridable): `token_budget` and `tool_result_chars` (`agents/schemas.py`, `graph/nodes/agent.yaml`).
  No migration: agents, versions and nodes keep them in JSON. Stored values of before (10 iterations, 600 s) that were written as the old
  defaults are still read as *not set*.
- Not built: persistence of the events and their retention (card #100), the guard figures built from them (card #103), shortening of
  the tool *definitions* sent with every request (the GitHub MCP server offers about forty; they are most of the 15,000 tokens of each
  request), a summary instead of a cut for older results.

## Addendum 1: the Execution Trace (card #155)

The long list *Rounds so far* in the side panel of the flow page grew without end on a long run and was drawn only while the agent worked.
The right area of the execution page is now the **Execution Trace**: three registers (the shared `Tabs`), kept in the address (`#overview`,
`#trace`, `#context`).

- **Overview**: the path, the details of the selected node and the output of its step (what the panel showed before, in one register).
- **Trace**: only for a selected agent step, working or finished (the register is not there for other nodes). The rounds, **the newest first**: the
  latest three, "Show more rounds" without counts (a chunk of twenty per click; only what is shown is drawn) and **the first round always last**, as an anchor
  (it holds the request), also while rounds in between are hidden. A round is an accordion row (status, "Round n", the tools as chips, tokens,
  time); the working round and a round with a failure are open. Open, a round lists its events: the model request (model, tokens), each tool call
  (identical consecutive ones as one, `get_artifacts ×3`, with the time added up) and "Result returned to the agent" or the error text of a
  failed call, and the answer. A working agent has a **Live** pill (it says *Paused* when the user has scrolled away and goes back with a click),
  a search over tool names and errors and a filter (all events, only errors, only tool calls). The rounds of a working agent come from the events
  (as before); the rounds of a finished one from the step's `detail.turns`, read when the register is shown. **No message, argument or result texts** are
  shown in this stage: the step keeps them, a later stage shows them (card #156).
- **Context**: the run context (what *Run context* was) in a register of its own, with its Copy button.
- **One addition to what is stored**: a turn of the step's `detail` now also keeps its `tokens` (the events carried them, the step did not), so a
  finished Trace can show the tokens per round. Older executions show no tokens per round.
- `components/live-rounds.js` (the old list) is in quarantine; its words ("Round n", "Final answer (the limit ...)") live on in the Trace.


## Addendum 2: the Execution Trace from the start, one column of events, no counts on the button (2026-11-27)

The owner used the Trace on a long run and asked for three things. (1) **The register exists as soon as the agent works**: it appeared only when the first round event
arrived because the panel looked for the heard events or the finished step. Now an agent node that is the working node of the visit (or has a finished step) has its
Trace at once, **empty** until the first round: "0 rounds", the Live pill and the line "No rounds yet. The agent has not asked the model yet."; a finished agent without
rounds says "No rounds were recorded." (2) **One column of events, left-aligned**: each event is a title line with its time at the far right of the **same line**, and
detail lines under it (model and tokens; the tool's node; "Result returned to the agent" or the error in red). A duration shows only from 0.1 s (a "0 s" is left out). The
round header keeps the numbers on its line (the tool chips give way with an ellipsis, not the numbers). (3) **The button says "Show more rounds"**, with no number, and the
"N rounds hidden" text is gone: the highest round number tells how many there are.
