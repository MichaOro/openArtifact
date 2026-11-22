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
| Execution node | A node inside an action definition that holds business logic (timer, output ...); the kinds are classes (ADR-014). |
| Pipeline node | A node in a pipeline that calls another pipeline and continues when it is complete (ADR-013 §2.2). |
| Graph | The storage term for a pipeline or an action definition: nodes and edges (tables `graphs`, `graph_nodes`, `graph_edges`, ADR-015). Not shown in the UI. |
| Run | One artifact's pass through a pipeline: state, current stage and action, snapshot (ADR-013). |
| Run stage | The state of one stage within a run: `pending`, `running`, `passed`, `failed` or `skipped`. |
| `created_by` / `started_by` | Where an artifact came from (`user`, `api`, `mcp`, `action`) and who started a run (`user` or `system`). |
| API token | The one secret (`OPENARTIFACT_API_TOKEN`) that protects the whole application; sent as a bearer header or entered once on the sign-in page (ADR-016). |
| Sign-in, session | The browser's way in: the token is entered once and exchanged for a signed, expiring cookie (30 days); never the token itself (ADR-017). |
| Integration API | `/api/v1`: the stable REST interface for scripts and other systems, addressed by artifact number or id (ADR-016). |
| MCP server | `/mcp`: the same operations as tools for LLM agents (Model Context Protocol, Streamable HTTP, bearer token). |
| Request hardening | The middlewares for Host check, body limit, cross-site guard and security headers (ADR-017). |
| Quarantine | Unused code that is listed in `quarantine.json` and removed after 14 days without use (ADR-014 §3.6). |

