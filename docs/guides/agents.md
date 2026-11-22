# Agents and LLM providers

An **agent** is a reusable prompt for a language model, managed in one place. An **Agent node** in an action runs it:
one request to a model, the answer is the node's output. This guide covers providers, agents, the node, what an
execution keeps and the limits. The decision behind it is [ADR-037](../architecture/adr/037-agent-harness.md).

Not part of it: tool calling, loops, several agents working together, memory, approval steps, structured output,
streaming, fallback chains, budgets.

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
- **Private and local addresses** need two permissions: the operator sets `OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS=true`
  ([configuration](configuration.md)) *and* the provider has *This endpoint is on a private or local network*. This does
  not open HTTP nodes. Cloud metadata addresses are refused in every case, redirects are never followed, the connection
  goes to the address that was checked.
- **Models.** Only a model that is switched on can be chosen. Fetched models start switched off. *Refresh models* reads
  the list again: new ones are added, a model the provider no longer lists stays and is marked "No longer listed".
  Models defined by hand are managed the same way and can be deleted while nothing names them.
- **Default provider / default model.** An agent that names no provider uses the default provider; without a model it
  uses the provider's default model. There is no other fallback: a node whose model cannot be used fails and says why.
- A provider cannot be deleted while a draft, any published version or a node's override names it.

## 2. Write and publish an agent

*Agents* (`/agents`), or `/api/v1/agents`.

- **Prompts.** The user prompt is required; the system prompt has its own switch. A prompt uses `${input.NAME}` and
  nothing else: `${node...}`, `${var...}`, `${card...}` and `${secret:...}` are refused. That keeps an agent independent
  of any pipeline.
- **Inputs.** Declare what the agent needs: a name (`[a-z][a-z0-9_]{0,31}`), a type (`string`, `number`, `boolean`),
  required or not, and a default for an optional one.

  | Input | Node maps it | Result |
  |-------|--------------|--------|
  | required | no | the node fails: `required input 'x' is not mapped` |
  | optional, with default | no | the default |
  | optional, no default | no | empty text (shown as "not set") |
  | any | yes, and the source cannot be resolved | the node fails and names the reference |
  | any | yes, and the value does not fit the type | the node fails |

- **Model and limits.** Provider and model are optional (see defaults above). Temperature 0 to 2, max tokens 1 to
  8192, request timeout 1 to 300 s (60), time limit of the node 1 to 1800 s (600), retries 0 to 4 (3).
- **Draft and versions.** You edit the *draft*. Nothing an execution uses changes until you **publish**: that makes a
  new version (numbers count up, a version is never changed) and executions that start from then on use it. *Discard
  draft* goes back to the published version. **Publish again** on an earlier version is the rollback: a new version with
  that content; the history stays.
- **Preview.** Shows the prompts as they would be sent, with example values, and which inputs are missing. It sends
  nothing to a model.
- **Active.** An inactive agent is not run: its nodes fail in every execution that starts while it is inactive. A
  running execution is not affected; stop the run to end it at once.
- An agent cannot be deleted while agent nodes refer to it. *Used by* lists them with the settings each overrides.

## 3. Use it in an action

Add an **Agent** node to an action definition and choose the agent.

- **Inputs.** One field per declared input. The value is text and may hold `${node.NAME.output}`,
  `${node.NAME.data.key}`, `${var.name}` and `${card.name}` ([execution nodes](execution-nodes.md)); secrets cannot be
  used. Stored as one `name = value` per line in the node's `inputs` setting.
- **Settings.** Every setting shows the agent's value (*From agent*) until the node sets its own (*Overridden*):
  user prompt, system prompt and its switch, provider, model, temperature, max tokens, both time limits, retries. A value
  the agent does not set can be switched on in the node. *Reset* removes the node's value; *Reset all overrides* removes
  them all. In the API an override is a key of the node's `config`; `null` resets it.
- **When the agent changes**, the fields a node does not override follow with the next execution; overridden fields
  stay. Publishing lists the nodes that override a changed field.
- The node leaves by *On Pass* with the answer, or by *On Fail* (or goes on, with *If the node fails: continue*).
- Later nodes read `${node.NAME.output}` and `${node.NAME.data.model}`, `.data.usage.total_tokens`,
  `.data.finish_reason`.

## 4. What an execution keeps

When an execution starts, every agent node is resolved once and frozen in the execution's snapshot: the published
version, whether the agent is active, the prompts, the inputs, the node's overrides, the provider and the model.
Publishing, deactivating or deleting an agent, or changing a provider, afterwards does not change that execution. The
API key is not part of it; it is read from the credential store when the node runs.

A node that could not be resolved at the start (no agent, nothing published, inactive, model not enabled, no provider)
does not stop the start: it fails with that reason when the run reaches it.

## 5. Retries and time limits

A request is tried again after a network error, a timeout, HTTP 408, 429 or 5xx; not after 400, 401, 403, 404 or
another 4xx. The waits are 3, 10, 30 and 60 seconds; a `Retry-After` of a 429 replaces the wait. The time limit of the
node covers all attempts and waits: an attempt gets at most what is left, and no wait is started that does not fit.
Stopping the run ends a request or a wait at once.

## 6. History

The step shows the answer, the model, the tokens and the number of attempts. *Request (prompts, inputs, attempts)*
opens what was actually sent: both prompts, every input with its source and value, what the node set itself, and each
attempt with its duration, HTTP status and error. In the API this is `detail` of one step
(`GET .../executions/{id}/steps/{step_id}`); lists do not carry it. It is deleted with its execution
([execution history](execution-history.md)).

- Tokens the provider did not report are `null`, not 0.
- The run context keeps the first 4 KiB of an answer; the step keeps all of it (up to 256 Ki characters, cut visibly
  beyond that: a marker in the text, `output_truncated` in the data, a note in the reason).
- The prompts are never in the run context.

## 7. What to keep in mind

- **Whatever you map into an input is sent to the provider** and stored in the step. The masking removes the provider's
  key from results; it does not recognise other sensitive text in a variable, a card parameter or an earlier output.
- **An answer is text from outside.** It can contain instructions; do not let a later node treat it as trusted.
- **There is no budget.** A node sends up to `retries + 1` requests, each bounded by max tokens.
- Changing or deleting the key takes effect at once, also for running executions.

## 8. API and MCP

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
