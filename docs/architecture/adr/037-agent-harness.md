# ADR-037: Agent harness

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-021](021-execution-nodes-as-executors.md), [ADR-022](022-node-settings-as-json-config.md), [ADR-024](024-credential-store.md), [ADR-025](025-execution-history-and-retention.md), [ADR-027](027-execution-flow-by-replay-over-the-frozen-snapshot.md), [ADR-033](033-run-context.md)  
**Amended by:** [ADR-040](040-agent-tools.md) (tools and the loop), [ADR-042](042-provider-addresses.md) (addresses of providers), [ADR-045](045-agent-editor-progressive-disclosure.md) (the editor, switches of optional areas)  
**Implemented in:** migration 0033 (`agents`, `agent_versions`, `llm_providers`, `llm_models`, `run_node_results.detail`, kind `agent`); `agents/` (`schemas.py`, `resolve.py`, `render.py`, `freeze.py`, `client.py`, `runtime.py`, `service.py`, `providers.py`), `api/agents.py`, `engine/executors.py` (`_agent`), `engine/snapshot.py`, `engine/runner.py` (`_cut`, `detail`), `engine/http_runner.py` (`guarded_exchange`), `graph/node_types.py` (`AgentType`, setting type `number`), `mcp_server.py`; `static/js/agents/`, `static/js/editor/agent-inspector.js`  
**Affected chapters:** [04](../arc42/04-solution-strategy.md), [11](../arc42/11-risks-and-technical-debt.md), [12](../arc42/12-glossary.md); guides [agents](../../guides/agents.md), [API reference](../../guides/api-reference.md), [configuration](../../guides/configuration.md), [credentials](../../guides/credentials.md), [security](../../guides/security.md), [execution nodes](../../guides/execution-nodes.md)

## 1. Title

Reusable agents, LLM providers and one agent node that sends a single request to a model.

## 2. Context

Actions could run code and call HTTP addresses, but not ask a language model. A prompt written into an HTTP node is
copied into every node that needs it, carries no rules for its inputs, and puts the provider's address and the handling
of its key into each node. The wish was a definition that is managed in one place, used by many nodes, changed under
control, and that leaves a complete trace of what was sent.

## 3. Decision

- **An agent is data, with a draft and versions.** `agents` holds the name, the description, the active switch and the
  *draft* (JSON); `agent_versions` holds what was published: a number per agent that counts up and is never reused, the
  configuration, when and how (`user` or `api`) it was published, and `source_number` when it repeats an earlier
  version. A version row is written once and has no update path. Publishing copies the draft into a new version and
  makes it the one in use. A **rollback** publishes an earlier version again: a new version with that content, the history
  untouched. A draft without changes of its own follows a rollback, one that is being edited is kept. Saving a draft
  changes no execution.
- **The configuration** (`agents/schemas.py`, the single place for the bounds): `user_prompt` (needed to publish),
  `system_prompt` with its own switch, `inputs` (name `[a-z][a-z0-9_]{0,31}`, type `string` / `number` / `boolean`,
  `required`, `default`; a required input has no default), optional `provider_id` and `model`, `temperature` (0 to 2),
  `max_tokens` (1 to 8192), `request_timeout_seconds` (1 to 300, default 60), `total_timeout_seconds` (1 to 1800, default
  600), `retries` (0 to 4, default 3).
- **Prompts read inputs only.** A prompt takes `${input.NAME}` and nothing else: `${node...}`, `${var...}`, `${card...}`
  and `${secret:...}` are refused when a draft is published and when a node saves a prompt of its own. The node maps the
  inputs to the run (`inputs` setting, one `name = value` per line; the value is text with the references of ADR-033).
  So an agent never depends on the nodes of a pipeline. Secrets are no source of an input.
- **One node kind, flat settings, overrides without a default.** `agent` is an execution node of action definitions
  (On Pass / On Fail, `on_failure`). Its settings are `agent_id`, `inputs` and one setting per overridable field
  (`system_prompt_enabled`, `system_prompt`, `user_prompt`, `provider_id`, `model`, `temperature`, `max_tokens`,
  `request_timeout_seconds`, `total_timeout_seconds`, `retries`) whose default is `None`: **not set means inherited**, a
  value overrides that field only, saving `null` resets it (the existing `merge_config`). Switching a value on that
  the agent does not set is an override too. A new setting type `number` (decimal) was added for the temperature. No
  repeating-group control was built (as in ADR-034).
- **One resolution, three users.** `agents/resolve.py` merges a published configuration with a node's overrides and
  picks provider and model: the node's provider, else the agent's, else the *default provider*; the node's model, else
  the agent's if the provider in effect is the one it was chosen for, else the provider's default model; the model must be
  enabled. There is no further fallback. The snapshot, the preview (`POST .../preview`) and the editor (which asks the
  preview) all use it.
- **Frozen when an execution starts.** `build_snapshot` puts the result on every agent node of the frozen action
  definitions (`node["agent"]`): agent id, name, version, active flag, the published configuration, the declared inputs,
  the node's overrides, the merged settings, the provider (kind, address, name of the secret, private switch) and the
  model. An execution keeps this to its end: publishing, deactivating, deleting, changing a provider or a model later
  does not touch it. A node that cannot be resolved (no agent, nothing published, **inactive**, no usable model) is
  frozen with an `error` and fails with it when the run reaches it; the start is never refused for it. Only the *name*
  of the secret is frozen: its value is read when the node runs (as for every node, ADR-024). Snapshots of before this
  decision have no `agent`; such a node fails with "This execution has no agent for the node".
- **Providers.** `llm_providers`: `openrouter` (address fixed in the code, at most one, needs a secret) or
  `openai_compatible` (any http(s) address without credentials, query or fragment), the name of the secret, `allow_http` (ADR-042; first `allow_private`),
  `default_model`, `is_default`, and the outcome of the last test. `llm_models`: fetched from `/models` or defined by hand,
  `enabled` (new fetched ones start switched off), `available` (a fetched model the provider no longer lists stays and is
  marked). A provider is saved only after its **connection test** passed: the address is vetted, `/models` must be an
  OpenAI model list; OpenRouter's key is checked at `/key` (its `/models` is public); an endpoint without a usable
  `/models` needs a model defined by hand and must answer one minimal chat completion in the OpenAI shape. A success
  status alone never passes. `http` is allowed and answered with a warning.
- **One guarded HTTP path.** `guarded_exchange` (extracted from the HTTP node, whose behaviour is unchanged) is used by
  the test, the model list and the runtime: resolve, vet every address, pin the connection to a vetted address (no DNS
  rebinding), never follow a redirect, no proxy of the environment, capped body. Cloud metadata addresses are always
  refused. *Amended by ADR-042:* a provider may be on any address; only `http://` needs the provider's `allow_http`;
  OpenRouter's address stays fixed and public.
- **Runtime: one request.** `agents/runtime.py` resolves the inputs, fills the prompts (one pass, a replaced value is not
  scanned again; a missing or failed input is an error, never an empty text; an optional input without mapping and
  default is the empty text and says so), sends one chat completion (no streaming, no tools) and retries what can pass:
  network errors, timeouts, HTTP 408, 429 and 5xx, after 3, 10, 30 and 60 seconds; a `Retry-After` of a 429 replaces the
  wait. Other 4xx are not retried. The time limit of the node bounds every attempt and no wait is started that does not fit
  it. Waiting is `asyncio.sleep`, so stopping the run ends it. The runtime writes nothing; the engine stores the result.
  No SDK was added: the existing `httpx` goes through the guarded path.
- **Result and history.** `output` is the answer. `data` (which the run context carries, ADR-033) is small: `agent_id`,
  `agent_version`, `provider`, `model`, `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`; a number the
  provider did not send is `null`, never 0), `finish_reason`, `attempts`, and `status` on a failure. The new
  `NodeResult.detail` goes to `run_node_results.detail` only: the prompts as they were sent, the inputs with source and
  value, the overrides, the settings and every attempt (time, duration, HTTP status, error, wait). It is **never** part
  of the run context, is deferred, is returned only when one step is read, is masked like every result and goes with its
  execution. An empty answer fails the node; `finish_reason: length` and an answer longer than the 4 KiB of the context
  are noted in the step's reason.
- **No silent cut.** An output beyond the limit of a step (256 Ki characters) is now cut *with* a marker in the text,
  `output_truncated: true` in the data and a note in the reason, for every kind of node. Shorter outputs are stored as
  before.
- **Lifecycle.** An agent that agent nodes refer to cannot be deleted (409 with the nodes); a provider cannot while a
  draft, any published version or a node's override names it (an agent without a provider names the default provider);
  a model defined by hand cannot while it is named or the default. `GET .../uses` lists the nodes with their overrides;
  publishing answers with the changed fields and the nodes that override one of them.
- **Three ways in.** Browser API `/api/agents`, `/api/providers`; the same routes under `/api/v1` (one router builder,
  the origin of a version is `user` or `api`); MCP read-only: `list_agents`, `get_agent`, `list_providers`. Events
  `agents.changed` and `providers.changed`. No route, tool or event carries a key.

## 4. Consequences

- A prompt is edited in one place and reaches every node with the next execution; what a node overrides stays. What ran
  is reproducible from the execution alone.
- A deactivated agent stops new executions, not running ones: stopping a run is the way to end one at once.
- The secret's value is read at run time, so changing or deleting the key takes effect for running executions too.
- **Data leaves the application.** Whatever a node maps into an input is sent to the provider and stored in the step's
  detail. The masking covers the provider's key (and what a node declares as its secret), not arbitrary sensitive text
  that sits in a variable, a card parameter or an earlier output. An answer is foreign text (prompt injection), like
  every node output.
- A provider needs a stored secret, and secrets can only be stored with an API token and a secret key of the operator's
  own (ADR-024); a local endpoint without a key works without them.
- There is no budget, no rate limit and no cost view: up to five requests per node run, each bounded by `max_tokens`.
  Usage is recorded per step for a later view.
- Not built, and not prepared beyond a function boundary: tool calling and loops (built since by ADR-040, inside
  `run_node` around `run_completion`), structured output, streaming, fallback chains, memory, multi-agent runs, approval steps,
  an external secret manager (the existing `SecretResolver` callable is the seam), a provider plugin system.
- Deviation from the pre-implementation audit: the frozen agent sits on the node (`node["agent"]`) instead of in a
  `snapshot["agents"]` map, so the executor signature and the engine's walk stayed as they were; the default provider
  (audit decision E-1) is a flag of a provider, not a global setting; `SecretStore.uses` was not extended to providers
  (a provider shows whether its secret exists instead).
