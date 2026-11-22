# 12. Glossary

## Terms

| Term | Definition |
|------|------------|
| Artifact | Structured unit of work within OpenArtifact; a card on the board. **UI wording:** the interface always says "artifact" (never task, issue or work package). In code, API and database the same thing is still named `task` (`/api/tasks`, table `tasks`); that is an implementation name, not product language. Every artifact has a permanent number (`#12`) that is never reused and can be referenced as `#12` in other artifacts' bodies. |
| Lane | A column of the board. Defined in `BOARD_LANES` (`openartifact/tasks/lanes.py`); lane N always has colour N of the lane palette. |
| Orchestration | Carrying artifacts through pipelines: the run engine starts, executes, stops and records the runs. |
| Agent | An LLM-driven client of the integration API or the MCP server. Agents that run *inside* a pipeline are planned, not built. |
| Pipeline | What an artifact runs through: a trigger, stages and a complete, connected by edges (ADR-012, ADR-013). Pages `/pipelines`. Formerly called "workflow" (ADR-015). |
| Trigger | The start node of a pipeline or action definition (placeholder for manual, webhook or event starts). |
| Stage | A container inside a pipeline that holds actions and connects to other stages. |
| Action | A step inside a stage that stands for one business execution; has an input, *On Pass* and *On Error*. It is linked to an action definition. |
| Action definition | What an action does: a graph of execution nodes between a trigger and an output with *On Pass* and optional *On Fail*. Pages `/actions`. |
| Execution node | A node inside an action definition that holds business logic: *timer* (waits), *Code* (a script), *HTTP* (a request), plus the *trigger* and *output* that frame the definition; the kinds are classes (ADR-014, ADR-021). |
| Code node | An execution node that runs `sh` or Python as a child process with resource limits; no sandbox (ADR-023, [8.5](08-cross-cutting-concepts/08.05-execution-nodes-safety.md)). |
| HTTP node | An execution node that calls an address and passes when the status is accepted; checked against server-side request forgery. |
| Executor | The registered async function that runs one kind of execution node and returns a `NodeResult` (`pass` or `fail`, output, reason, data); the engine stores the result as a step and leaves the node by the matching port (ADR-021). |
| Node setting / `config` | A setting of a node in the inspector (types integer, switch, text, lines, code, select); old ones are columns of `graph_nodes`, newer ones live in its JSON `config` (ADR-022). |
| Pipeline node | A node in a pipeline that calls another pipeline and continues when it is complete (ADR-013 §2.2). |
| Graph | The storage term for a pipeline or an action definition: nodes and edges (tables `graphs`, `graph_nodes`, `graph_edges`, ADR-015). Not shown in the UI. |
| Run | The *current state* of an artifact's processing: one row per artifact, reused by every start (status, current stage and action, snapshot) (ADR-013). The history of the starts is the executions. |
| Execution | One start of an artifact in a pipeline, restarts included: a number per artifact, its origin, status, note, steps and a frozen copy of the pipeline. The run is the state, the execution is a history entry (ADR-025). |
| History | The executions of an artifact (the History tab of its dialog) and the global list of all of them (`/executions`). |
| Retention | The rule that bounds the history of an artifact: `keep_last` (1 to 1000) and/or `keep_hours` (1 to 8760), both must hold; without a policy the default (50) applies; the newest and running executions are never removed ([8.7](08-cross-cutting-concepts/08.07-history-and-retention.md)). |
| Step | One executed node of an action definition within an execution (a `run_node_results` row): outcome, port, exit code, masked output, reason, data. |
| Snapshot (frozen) | The copy of the pipeline and the action definitions it uses, taken when an execution starts; later edits do not change it. |
| Flow | The view of an execution as graphs with the path it took, computed by replaying the snapshot with the engine's rules (ADR-027, [6.9](06-runtime-view/06.09-history-retention-and-flow.md)). |
| Visit | One pass of an execution through a graph (a pipeline or an action definition); a node of the outer graph enters it. |
| Keyset cursor | The continuation mark `(started_at, id)` of the global executions list; pages stay stable when rows are inserted or deleted (ADR-028). |
| Deep link | `/?artifact=N` opens artifact N on the board. |
| Run stage | The state of one stage within a run: `pending`, `running`, `passed`, `failed` or `skipped`. |
| `created_by` | Where an artifact came from: `user` (browser), `api`, `mcp` or `action`. |
| Origin (`started_by`) | How a run or execution was started: `user` (browser), `api` (`/api/v1`) or `mcp` (MCP server); `system` is reserved for starts by the application itself and is not used yet (ADR-026). |
| API token | The one secret (`OPENARTIFACT_API_TOKEN`) that protects the whole application; sent as a bearer header or entered once on the sign-in page (ADR-016). |
| Sign-in, session | The browser's way in: the token is entered once and exchanged for a signed, expiring cookie (30 days); never the token itself (ADR-017). |
| Integration API | `/api/v1`: the stable REST interface for scripts and other systems, addressed by artifact number or id (ADR-016). |
| MCP server | `/mcp`: the same operations as tools for LLM agents (Model Context Protocol, Streamable HTTP, bearer token). |
| Request hardening | The middlewares for Host check, body limit, cross-site guard and security headers (ADR-017). |
| Credential (secret) | A named value stored encrypted in the credential store (AES-256-GCM); nodes use it by name. Managed through the API only; values are never returned (ADR-024, [8.6](08-cross-cutting-concepts/08.06-credential-store.md)). |
| Secret reference | How a node names a credential: `${secret:NAME}` in an HTTP node's path, query, headers or body, or a list of names in a Code node's `secrets` setting. |
| Masking | Replacing a credential's value (as it is, percent-encoded, Base64, JSON-escaped) with `***` in a node's result and in log lines ([6.8](06-runtime-view/06.08-credential-resolution.md)). |
| Run context | The variables and the latest result of every node that ran in an execution, stored in `executions.context` (at most 64 KiB), written with every step and read by later nodes (ADR-033). |
| Reference (context) | `${node.NAME.output}`, `${node.NAME.data.key}`, `${var.name}` in an HTTP node's URL path or query, header values or body; replaced by text when the node runs, fails the node if it cannot be resolved. Not the same as a secret reference. |
| Variable | A named JSON value a Code node sets with `"vars"` in its result line; part of the run context. |
| Branching node | An If or Switch node: compares values of the run context and leaves by a port of its own choice (`yes` / `no` / `else`, `case_1` ... `case_6` / `else`); `else` means the comparison could not be decided (ADR-034). |
| Open mode | Running without `OPENARTIFACT_API_TOKEN`: pages and the browser API are open, `/api/v1` and `/mcp` answer 401, Code nodes are refused and credentials cannot be saved. |
| Orphan process | A background process started by a Code node that outlives a hard-killed application; the next start ends it using the registry (`code_registry`). |
| Quarantine | Unused code that is listed in `quarantine.json` and removed after 14 days without use (ADR-014 §3.6). |

