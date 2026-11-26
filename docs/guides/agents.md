# Agents and LLM providers

An **agent** is a reusable prompt for a language model, managed in one place. An **Agent node** in an action runs it:
a request to a model, the answer is the node's output. With **tools** attached below the node (an MCP server such as
GitHub's, an HTTP request, a piece of code) the model may call them first, in a bounded loop, as in n8n. This guide
covers providers, agents, the node, tools, what an execution keeps and the limits. The decisions behind it are
[ADR-037](../architecture/adr/037-agent-harness.md) and [ADR-040](../architecture/adr/040-agent-tools.md).

Not part of it: several agents working together, memory, approval before a tool call, local MCP servers (a process on
the host), structured output, streaming, fallback chains, budgets.

## 1. Set up a provider

*Settings › LLM providers* (`/settings/providers`), or `POST /api/v1/providers`.

| Kind | Address | Models |
|------|---------|--------|
| OpenRouter | fixed (`https://openrouter.ai/api/v1`), at most one | fetched from its list |
| OpenAI-compatible | yours, `http` or `https`, no user name, password, query or fragment | fetched from `/models`, or defined by hand |

- **The API key lives in the credential store.** The provider holds only the *name* of a secret
  ([credentials guide](credentials.md)). The dialog can store a key for you: type it into *API key* and it is saved to
  the secret named above, never to the provider. Storing secrets needs `OPENARTIFACT_API_TOKEN` and a secret key of
  your own. An endpoint that needs no key (a model server on your host) can leave the secret empty.
- **A provider is saved only when its connection test passes.** *Test connection* shows the steps without saving:
  1. the secret exists;
  2. the address is allowed (see below) and `/models` answers with an OpenAI model list;
  3. OpenRouter: the key is accepted (`/key`);
  4. an endpoint without a usable `/models`: one minimal chat completion (`max_tokens: 1`) with the first model you
     defined by hand must come back in the OpenAI shape. Without such a model the test fails.

  A success status alone is not enough: a web page or another API is refused.
- **`http`** is allowed and shown with a warning: the key and every prompt travel unencrypted.
- **Any address works**: public, on this host (`http://127.0.0.1:4000/v1`) or in your network, without a setting of the
  operator. Only an `http://` address needs the tick *Allow unencrypted connection (HTTP)*, your confirmation that there is
  no TLS here or that it sits in front of the endpoint; it is shown only for such an address. From a container,
  `127.0.0.1` is the container itself: use the name of the other container on a shared Docker network or
  `host.docker.internal`. Cloud metadata addresses are refused in every case, redirects are never followed, the
  connection goes to the address that was checked (ADR-042).
- **Models.** Only a model that is switched on can be chosen. Fetched models start switched off. *Refresh models* reads
  the list again: new ones are added, a model the provider no longer lists stays and is marked "No longer listed".
  Models defined by hand are managed the same way and can be deleted while nothing names them.
- **Default provider / default model.** An agent that names no provider uses the default provider; without a model it
  uses the provider's default model. There is no other fallback: a node whose model cannot be used fails and says why.
- A provider cannot be deleted while a draft, any published version or a node's override names it.

## 2. Write and publish an agent

*Agents* (`/agents`, under *Pipeline*), or `/api/v1/agents`.

The page shows what the agent needs (ADR-045). The header holds the name, the state of the draft and *Save draft*,
*Discard draft* and *Publish*. *Prompts* and *Versions & use* are always there; **Options** on the right (closed when the
page opens) switches the rest on: *System prompt* (a field below the user prompt), *Inputs* and *Model & Limits* (a tab
each) and *Quick test* (a card on the right: example values for the inputs, the prompts filled with them). A switched-off area is **kept but not in effect**: the defaults of the
backend apply (default provider and model, the default limits), and inputs switched off are none. The switches are part
of the draft; *Quick test* is not saved and is off whenever the page opens.

- **Prompts.** The user prompt is required; the system prompt is switched on in *Options*. A prompt uses `${input.NAME}` and
  nothing else: `${node...}`, `${var...}`, `${card...}` and `${secret:...}` are refused. That keeps an agent independent
  of any pipeline. Every input has a **source** (ADR-064): a *Value*
  (the agent node of an action gives it: typed text, or a reference such as `${card.title}`, `${card.NAME}` of a field or any
  other) or the *Artifact* (a part of the card the run belongs to: *Title*, *Body*, *Title and body*, *Number* or
  *Comments*, all comments oldest first with author and time). An input from the artifact is fixed here, in the agent: the
  action's node shows it as a fixed line and cannot change it (the API answers 422). A line a node still has for an
  input that now comes from the artifact is ignored and shown with a *Remove* button; a mapped name the agent does not
  declare fails the run until removed.
  **The card is a source, never an implicit part of the request: the prompt decides.** The model sees an artifact
  input only where a prompt contains `${input.x}`; a prompt that does not use an input does not send it, and the node
  dialog warns about an input that no prompt uses. A run that has no artifact fails the node when the agent needs one.
  To give an agent more than the card itself (its comments, the parent and the child cards, earlier results), put a
  [Build Context node](execution-nodes.md#build-context-node) before the agent and map its output (`${(Build Context).output}`) to a
  *Value* input of the agent; the node keeps the package within a size you set and says what it left out.
- **Inputs.** Declare what the agent needs in the table: a name (`[a-z][a-z0-9_]{0,31}`), where it *Comes from* (*Value* with a type `string`, `number` or `boolean`, or *Artifact* with its part), for a value
  *Required* or *Optional*, and a default for an optional one. A description is added from the row's menu
  (⋮); the Description column shows while any input has one.

  | Input | Node maps it | Result |
  |-------|--------------|--------|
  | required | no | the node fails: `required input 'x' is not mapped` |
  | optional, with default | no | the default |
  | optional, no default | no | empty text (shown as "not set") |
  | any | yes, and the source cannot be resolved | the node fails and names the reference |
  | any | yes, and the value does not fit the type | the node fails |

- **Model and limits** (ADR-046). Every setting is optional and is added with *Add setting* in its card: *Model
  configuration* (provider, model, temperature 0 to 2, max tokens 1 to 8192) and *Execution limits* (request timeout 1 to
  300 s, node time limit 1 to 1800 s, retries 0 to 4, max iterations 1 to 500, counting only with tools, token budget,
  tool result limit; see section 4). The bin removes a setting: it is then **not set**, and at the node its override, else
  the default applies (default provider and its default model; 60 s, 900 s, 3 retries, 100 iterations, no token budget,
  12000 characters of a tool result for the model). An agent without provider and model can be
  published; whether one can be resolved is checked at the node.
- **Draft and versions.** You edit the *draft*. Nothing an execution uses changes until you **publish**: that makes a
  new version (numbers count up, a version is never changed) and executions that start from then on use it. *Discard
  draft* goes back to the published version. **Publish again** on an earlier version is the rollback: a new version with
  that content; the history stays.
- **Quick test (preview).** Shows the prompts as they would be sent, with example values, and which inputs are missing. It sends
  nothing to a model.
- **Active.** An inactive agent is not run: its nodes fail in every execution that starts while it is inactive. A
  running execution is not affected; stop the run to end it at once.
- An agent cannot be deleted while agent nodes refer to it. *Versions & use* lists them (*Used by*) with the settings
  each overrides: *Open* shows the node in its action, *Remove reference* (after asking) takes the agent out of that one
  node; its next execution then fails until it is given an agent again. The versions stand next to it; *Publish again*
  is the rollback. With more than three versions the list shows the newest two and the first one; the others are behind
  *Show more versions (N)* (a click or Enter opens them, they are used like the others).

The **Agents** page lists the agents as cards or rows (search, order, cards or list). A click selects one and shows its **user prompt**
and, while it is switched on, its **system prompt** on the right, with the provider and model it sets itself, its limits and its versions; a
double click or the pencil opens the editor, the bin deletes an agent no node refers to. *Properties* changes the name and the description.

## 3. Use it in an action

Add an **Agent** node to an action definition and choose the agent.

- **Inputs.** One field per declared input. The value is text and may hold `${(Node name).output}`,
  `${(Node name).data.key}`, `${var.name}` and `${card.name}` ([execution nodes](execution-nodes.md)); secrets cannot be
  used. Stored as one `name = value` per line in the node's `inputs` setting.
- **Settings.** Every setting shows the agent's value (*From agent*) until the node sets its own (*Overridden*):
  user prompt, system prompt and its switch, provider, model, temperature, max tokens, both time limits, retries, max
  iterations. A value
  the agent does not set can be switched on in the node. *Reset* removes the node's value; *Reset all overrides* removes
  them all. In the API an override is a key of the node's `config`; `null` resets it.
- **When the agent changes**, the fields a node does not override follow with the next execution; overridden fields
  stay. Publishing lists the nodes that override a changed field.
- The node leaves by *On Pass* with the answer. A failure follows *If the node fails*: *Stop the run* (default), *Continue* through On Pass, or *Error output* (*On Fail*, shown only then).
- Later nodes read `${(Agent name).output}` and `${(Agent name).data.model}`, `.data.usage.total_tokens`,
  `.data.finish_reason`, `.data.iterations`.

## 4. Tools

A tool is a node of its own that hangs **below** an Agent node: drag from the tool's port (on its top) to the agent's
*Tools* port (on its bottom), or the other way round from the agent's *Tools* port to a tool's port, or add the tool from the menu while the agent is selected and it is attached at once.
The edge is drawn dashed; it is an attachment, not a step of the flow: a tool runs only when the model calls it. An
agent takes any number of tools; a tool belongs to one agent.

| Tool | What the model gets | Settings |
|------|---------------------|----------|
| **MCP Client Tool** | the tools of a remote MCP server, with their own names, descriptions and parameters | endpoint (Streamable HTTP), secret with the token (sent as `Authorization: Bearer`), *Tools to include*: `all`, `selected` or `all_except` with one tool name per line, timeout per call (1 to 300 s, 60) |
| **GitHub MCP** | the tools of GitHub's MCP server (a fixed address), read-only until *Allow writes* is on | credential (a GitHub access token), *Allow writes*, *Tools to include* (`all`, `selected`, `all except`) with one tool name per line, tool name, timeout |
| **HTTP Request Tool** | one function with the parameters you declare | tool name and description, method, URL, headers, body, parameters (`name: description` per line), timeout (1 to 120 s, 30), success status |
| **Execute Command Tool** | one function with the parameters you declare | tool name and description, language (`sh`, `python`), code, secrets, parameters, timeout (1 to 600 s, 30) |
| **Hand Over Tool** | one function whose parameters are the fields you define: the model hands over a document, the server checks it ([below](#hand-over-tool)) | tool name and description, *Fields* (name, type, required, description; a choice has values), *Size limit* (1 to 64 KiB, 16 KiB) |
| **Postgres Tool** | one function: your SQL statement, with the parameters you declare | tool name and description, secret with the connection URL, query, parameters, *Allow changes*, *Private network*, max rows (1 to 1000, 100), timeout (1 to 120 s, 30) |

- **Fewer tools, a smaller prompt.** The description of **every** tool the model is offered goes with each request. GitHub's server
  has about forty tools (roughly 15,000 tokens per request), so a long run sends a very large prompt and can time out. Choose
  *Tools to include* → *selected* on the GitHub MCP node (or the MCP Client Tool) and name only what the agent needs, for example
  `get_file_contents`, `list_commits`, `get_issue`, `list_pull_requests`. A name the server does not have is no error; the step says
  which wanted tool is missing.
- **GitHub.** The **GitHub MCP** node (credential, no address to enter) or an MCP Client Tool with the endpoint `https://api.githubcopilot.com/mcp/` and a secret holding a personal
  access token. For an agent that only reads, choose *selected* and list the read tools (`get_issue`, `list_issues`,
  ...); the tools the agent is not offered cannot be called. For a fixed step of a flow, without a model, there is the
  [GitHub node](execution-nodes.md).
- **The Postgres Tool** lets the model look something up in a database with a query *you* wrote: the statement uses
  `$1`, `$2`, ... and the declared parameters, in the order you list them, are what the model fills in (`id: The number
  of the ticket` is `$1`). The model's values are bound parameters, never part of the SQL text, so it cannot change the
  query, only what it asks for. The statement runs read-only by the database's own enforcement unless you switch on
  *Allow changes*; use a database role with only the privileges the tool needs. The answer to the model is
  `{"rows": [...], "row_count": n, "truncated": bool}`, cut so that it stays under 15 KiB; an SQL error or a missing
  parameter goes back as an `Error:` text. The rules for the connection URL (a secret), the network and the limits are
  those of the [Postgres node](execution-nodes.md); the private-network permission is the providers' one
  (`OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS` *and* the tool's switch). A tool whose placeholders and parameters do not
  agree, or whose secret is missing, fails the node before its first request.
- **Names.** The model calls a tool by its *Tool name* (empty: the node's name, made a valid name). When two tools
  have the same name (two MCP servers with a `search`), both get their tool node's name in front (`github_search`,
  `jira_search`).
- **Parameters of the HTTP Request Tool** are `{name}` in the URL (percent-encoded there), the headers and the body.
  They are filled in *after* the references (`${secret:...}`, `${var...}`, `${node...}`) are resolved, in one pass: a
  model that writes `${secret:X}` sends exactly that text, and a value is never filled in again. A parameter in the
  scheme or host of the URL is refused, so the model never chooses where a request goes. In a JSON body (its
  Content-Type says JSON, or it is valid JSON) a value is escaped for the inside of a JSON string, so quotes and line
  breaks in a comment cannot break the body or add fields; write the placeholder in quotes (`"{text}"`). The answer to the model is
  `HTTP <status>` and the body; another status than the accepted ones is an error.
- **The Execute Command Tool** runs under the rules of the Execute Command node ([execution nodes](execution-nodes.md)): it needs the API
  token, can be switched off, has its limits and no sandbox. The model's arguments are the object `input` in
  `context.json`; what the code prints (or the result protocol's output) is the answer.
- **The loop.** The node asks the model with the tools offered, runs every tool call of the answer, sends the results
  back and asks again, until an answer calls no tool. The engine is its own module (`agents/loop.py`; the single request
  with its retries is `agents/completion.py`, what the model reads is `agents/context_window.py`).
- **The limits are a safety net, not a way to hold an agent in check** (the guards judge its health, [guards](guards.md)).
  *Max iterations* (default 100, up to 500), the *time limit* of the node (default 15 minutes, up to 30) and the *token
  budget* (not set: none) do not fail the node. When one is reached, or a run **makes no progress** (the same call with the
  same result 8 times in a row), or a request **fails for good after tools ran** (a model that did not answer a large
  prompt in time), the agent gets **one more request without tools** from a much shorter conversation: *"Answer with what
  you have found so far, and say clearly what is still missing."* The step passes with a note, for example `the limit of
  100 iterations was reached: this answer was written without tools from what the agent had found by then and may be
  incomplete`. Only when that last request fails too the node fails, and the reason says both. It may take up to two
  minutes beyond the node's time limit.
- **What the model reads.** The node keeps the whole conversation, each request is made from a *view* of it: a tool result
  is cut at the *tool result limit* (12000 characters; a note says how much was cut), and the results of the rounds before the
  last two are shortened to 1500 characters, so the prompt does not grow by everything every tool ever returned. **The step
  keeps the result** as the tool returned it, up to 16 KiB: the view is what the model read, the step is what the tool
  answered. A call that is made again and again (the same tool with the same arguments, 3 times in a row) gets a note on its
  result for the model (`this is the same call ... use what you have, or try something else`); the note is not kept in the
  step. Whether such repetition is healthy is the guard's to judge.
- **A tool that does not answer** is stopped after 5 minutes (or the time that is left): it becomes an error text for the
  model (`Error: the tool X did not answer within N s`) and the run goes on.
- **After a timeout the next attempt gets more time** (1.5 times the one before, at most 300 s): a model that did not answer
  a large prompt in 60 s will not in the same time again. The time limit of the node covers every request and every tool
  call; each request keeps its retries (section 6).
- **Live.** While the agent runs the flow page shows its **rounds** in the panel of the selected agent node (*Rounds so far*:
  each request with the start of its answer, the tokens and the calls it made, working, done or failed; a final answer
  after a limit is marked). The events behind it (`agent.turn`, `agent.tool_call` with the round) carry names, counts and
  states only. A page opened in the middle of a run shows the rounds from then on; the finished step has the whole story.
- **A failing tool does not fail the node.** An unknown tool, arguments that are not a JSON object, an HTTP error or a
  failing script go back to the model as a text starting with `Error:`, and the model may try something else. A tool
  that cannot be used at all (the MCP server refuses the token or cannot be reached, an Execute Command Tool while Execute Command nodes are
  off) fails the node before its first request, with the tool's name in the reason.
- **Results** are cut to 16 KiB for the model and the history, and the values of the run's secrets are masked in them
  before the model reads them.
- **The tool nodes in the flow.** In the flow of an execution a tool node the agent used is no longer dim and dashed: **green**
  when every call went well, **red** when at least one failed (the badge counts the calls, the tooltip says "9 calls, 1 failed"),
  and the line to its agent takes the same colour. While a call is in progress the node pulses like a running node and bubbles run
  along its line from the agent to the tool. A tool the agent never asked stays dim. Every tool call remembers its tool node
  (`node_id`, `node_name` in `detail.turns[].tool_calls[]`), and the step keeps a summary per tool node in `data.tools`
  (`[{"node", "name", "calls", "errors"}]`); older steps have none and show no tool state. The live part is the event
  `agent.tool_call` (`state` `started` or `finished`, `ok`, `duration_ms`, `agent_node_id`, `tool_node_id`, `tool`, `turn`, with the
  artifact and the execution): names and states only, never arguments or results. A page opened while a call is already
  running shows the node working only from the next call on (events are not replayed); the finished step has the whole state.
- **Private addresses** for MCP and HTTP tools need the same two permissions as a provider: the operator's
  `OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS=true` *and* the tool's *Private network* switch. Cloud metadata addresses are
  always refused and the connection goes to the checked address. An HTTP Request Tool follows no redirect; the MCP
  client follows one only within the endpoint's origin, and every request is checked again.

### Hand Over Tool

A model that must answer in a shape (a verdict, a score, a list of reasons) is better asked to **fill in fields** than to write text that someone parses
afterwards ([ADR-080](../architecture/adr/080-hand-over-tool.md)). The *Hand Over Tool* gives the model one function whose parameters are exactly the
fields you define. The server checks every call:

- A field has a **name** (lowercase letters, digits and `_`), a **type** (*Text*, *Number*, *True or false*, *Choice* with its values, *List of texts*), *Required*
  or not, and a **description** the model reads. The list is **flat**: no field holds another object. At most 30 fields; the whole document at most
  *Size limit* (default 16 KiB).
- A call that does not fit (a required field missing, a wrong type, a value that is not one of a choice, a field that is not in the list, a document that is too big)
  is **refused** and the model gets all that is wrong in one answer, `Error: the document was not accepted: 'passed' must be true or false; 'verdict' is required.
  Call the tool again with a corrected document.` It may try again; every call stays in the step.
- A call that fits answers `handed over`. **The last accepted document counts.** It is stored in the run under the name of the tool node, so a later node reads it as
  `${(Review).data.passed}` (or `${node.Review.data.passed}`), and `${(Review).success}` is true. `attempts` is the number of calls the model needed. The agent's step
  names it (*Handed over: Review*) and shows the document in its data.
- A **Build Context** node can take the documents as a source (*Handover documents*), so a later agent gets what an earlier one handed over.
- What the model hands over is **text from outside**: it is stored and pasted as it is and never read for `${...}` references, and the check never executes anything.
  A step that was never handed anything has no document: a reference to it says the node has not run.

*Example:* an agent reviews a change. Its Hand Over Tool "Review" has the fields `passed` (true or false, required), `verdict` (choice: approve, reject; required) and
`reasons` (list of texts). The next node is an If node with the condition `${(Review).data.passed}` *is true*; its *On Fail* goes on to the node that asks for rework.

A step that is not an agent cannot write a document yet: the tool is the only writer.

## 5. What an execution keeps

When an execution starts, every agent node is resolved once and frozen in the execution's snapshot: the published
version, whether the agent is active, the prompts, the inputs, the node's overrides, the provider, the model and the
tools attached to it with their settings.
Publishing, deactivating or deleting an agent, or changing a provider, afterwards does not change that execution. The
API key is not part of it; it is read from the credential store when the node runs.

A node that could not be resolved at the start (no agent, nothing published, inactive, model not enabled, no provider)
does not stop the start: it fails with that reason when the run reaches it.

## 6. Retries and time limits

A request is tried again after a network error, a timeout, HTTP 408, 429 or 5xx; not after 400, 401, 403, 404 or
another 4xx. The waits are 3, 10, 30 and 60 seconds; a `Retry-After` of a 429 replaces the wait. The time limit of the
node covers all attempts and waits: an attempt gets at most what is left, and no wait is started that does not fit.
Stopping the run ends a request or a wait at once.

## 7. History

The step shows the answer, the model, the tokens and the number of attempts. *Request (prompts, inputs, attempts)*
opens what was actually sent: both prompts, every input with its source and value, what the node set itself, every
tool call (turn, tool, arguments, result, duration) and each attempt with its duration, HTTP status and error. With
tools, `detail.turns` holds the requests one by one with their attempts and tool calls; the tokens are summed over the
turns. In the API this is `detail` of one step
(`GET .../executions/{id}/steps/{step_id}`); lists do not carry it. It is deleted with its execution
([execution history](execution-history.md)).

- Tokens the provider did not report are `null`, not 0.
- The run context keeps the first 4 KiB of an answer; the step keeps all of it (up to 256 Ki characters, cut visibly
  beyond that: a marker in the text, `output_truncated` in the data, a note in the reason).
- The prompts are never in the run context.

## 8. What to keep in mind

- **Whatever you map into an input is sent to the provider** and stored in the step. The masking removes the provider's
  key from results; it does not recognise other sensitive text in a variable, a card parameter or an earlier output.
- **An answer is text from outside.** It can contain instructions; do not let a later node treat it as trusted.
- **A tool's answer is text from outside too**, and so is what an MCP server says about its tools. A page or an issue
  can tell the model to call another tool; offer an agent only the tools it needs (*selected*), and only read tools
  where reading is enough.
- **There is a budget only when you set one.** A node sends up to `retries + 1` requests per iteration and up to *Max
  iterations* iterations, each bounded by max tokens; the *token budget* bounds all of them together (the agent then
  answers from what it has).
- Changing or deleting the key takes effect at once, also for running executions.

## 9. API and MCP

`/api/v1/agents` and `/api/v1/providers` offer everything above ([API reference](api-reference.md)). The MCP server
is read-only here: `list_agents`, `get_agent`, `list_providers`.

```sh
# an agent, published
curl -sS -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name": "Triage", "draft": {"user_prompt": "Analyse: ${input.ticket}", "inputs": [{"name": "ticket", "required": true}]}}' \
  $URL/api/v1/agents
curl -sS -X POST -H "Authorization: Bearer $TOKEN" $URL/api/v1/agents/Triage/publish
# back to version 1 (makes a new version)
curl -sS -X POST -H "Authorization: Bearer $TOKEN" $URL/api/v1/agents/Triage/versions/1/republish
```
