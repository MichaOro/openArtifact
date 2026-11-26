# ADR-016: Access protection, integration API and MCP

**Status:** Accepted  
**Date:** 2026-11-21  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-006](006-api-design.md), [ADR-008](008-security-operations.md), [ADR-015](015-vocabulary-and-storage-names.md) §6  
**Amended by:** [ADR-017](017-request-hardening-and-signed-sessions.md) (sessions, hardening), [ADR-026](026-origin-of-a-run-started-by.md) (origin of a run)

## 1. Title

One API token protects the whole application; artifacts can be created and followed through a REST
integration API and an MCP server that share one service with the browser.

## 2. Context

Artifacts should be created completely (title, body, lane, parent, pipeline with its first stage and
action) without the browser: by scripts, by other systems, by agents driven by an LLM and, later, by
actions inside a pipeline. At the same time the browser's own API (including Swagger and endpoints
such as deleting a pipeline) answered to anyone who could reach the port.

## 3. Decision

### 3.1 One service, three ways in

`tasks/service.py` (`ArtifactService`) holds everything that can be done with artifacts: list, read
(by id or number), create, update, delete, start, stop, the state of a run and the list of pipelines
with their stages and actions. It validates, applies the lock while an artifact is processed, publishes
the events (`task.*`) and records where an artifact came from (`created_by`: `user`, `api`, `mcp`,
`action`). The browser's API (`/api/tasks`, `/api/runs`), the integration API (`/api/v1`) and the MCP
server are thin layers over it, and so will be an action that creates artifacts.

An artifact carries the pipeline, stage and action it starts with (`tasks.pipeline_id`, `stage_id`,
`action_id`, migration 0019). Choosing a pipeline selects its first stage and that stage's first
action; the target can be changed until a run starts; starting records it again.

**Creating and starting are separate calls** everywhere (a "create and start" is only ever a shortcut
of a caller). There is no batch call: a caller loops; imports are a different requirement.

### 3.2 The integration API (`/api/v1`)

The same operations under the name the user sees ("artifacts"), addressed by id or number
(`/api/v1/artifacts/12`), plus `GET /api/v1/pipelines` (ids to start with). It is documented by the
OpenAPI document (Swagger UI at `/api/docs`). A run started this way has `started_by: system`.

### 3.3 The MCP server (`/mcp`)

Model Context Protocol over Streamable HTTP, stateless, built with the official Python SDK
(`mcp.server.MCPServer`) and mounted in the application. Eight tools: list pipelines, list / get /
create / update artifacts, start and stop processing, read the processing status. Parameters accept
names where an agent would use them (a pipeline, stage or action by name, a parent by number); a
refused call returns the reason as the tool's error text (`ToolError`). It is a layer over
`ArtifactService`, not a second implementation.

### 3.4 One token protects everything

`OPENARTIFACT_API_TOKEN` (settings). With a token configured, `AccessGate` (ASGI middleware, in
`security.py`) guards **every** path except `/health`, the sign-in page and the static
files: pages, the browser's API, `/api/events`, Swagger and `openapi.json`, `/api/v1`, `/mcp`.
A request is let through with `Authorization: Bearer <token>` (scripts, agents, Swagger's *Authorize*)
or with the session cookie of a browser that signed in. A browser asking for a page without either is
sent to `/login?next=...`; everything else gets `401`.

- **Sign-in** (`/login`, `/logout`): the user enters the token once; the cookie `oa_session` carries a
  signature of the token, `HttpOnly`, `SameSite=Strict`, `Secure` over HTTPS, 30 days (the exact format is
  amended by [ADR-017](017-request-hardening-and-signed-sessions.md)). The token itself is never in the cookie. A wrong token costs half a second. `next` may only be a path of the
  application. The header offers *Sign out* while a token is configured.
- **Without a token** the application is open as before (development), but `/api/v1` and `/mcp`
  answer `401` regardless: they are meant to be reached from outside and are closed by default.
- The compose file reads the token from `deploy/.env` (not in git; `.env.example` explains it). `deploy/.env` is
  required and sits next to the compose file.
- **Planned:** with a *Settings* area, separate tokens (browser, integration, MCP), their lifetime
  and scopes. Until then the browser sign-in and the integration share the one token.

### 3.5 Not decided here

Rate limiting, audit of who did what beyond `created_by`/`started_by`, OAuth for MCP clients, and
user accounts. The loop protection for artifacts that create and start artifacts belongs to the
planned settings (ADR-013 §4).

## 4. Consequences

- A configured token turns the sign-in on for the whole application. Losing the token means editing
  `deploy/.env`.
- Every way in shares validation and locking, so a rule is written once.
- The SQLite migrations run with a plain file backup as the only protection for a half-finished DDL:
  back up the database file before an upgrade that renames tables (see ADR-015).

## Update (2026-11-22): module, open paths, secret key

- **Module.** Access protection (`AccessGate`, `TokenProtected`, `token_matches`, `token_error`, the session cookie
  and `require_api_token`) is in `openartifact/security.py`; there is no `api/auth.py`. `TokenProtected` moved there
  from `mcp_server.py`.
- **Open paths** are `/health`, `/login`, `/logout` and `/static/`. `/api/health` was removed; `/api/info` and
  `/api/docs` need the token.
- **Secret key.** It is enforced once a token is set: the application refuses to start with a token shorter than 32
  characters or a missing or default `OPENARTIFACT_SECRET_KEY`.
- **Sessions and hardening** (signed, expiring session value; Host check; CSRF guard; body limit; headers) are
  [ADR-017](017-request-hardening-and-signed-sessions.md). Behind a TLS proxy see the
  [reverse proxy guide](../../guides/reverse-proxy.md).
- **Not decided here** still holds: rate limiting, per-client tokens, OAuth for MCP clients, user accounts.

## Update (2026-11-22): origin of runs, tools, secrets

- A run started through `/api/v1` has `started_by: api`, one started through MCP has `started_by: mcp`; `system` is
  reserved ([ADR-026](026-origin-of-a-run-started-by.md)). §3.2 ("`started_by: system`") is the older state.
- The MCP server has **19 tools** now (update 2026-11-23: agents and providers read-only, ADR-037), not eight: besides the artifact and run tools of §3.3 there are
  `list_executions`, `list_all_executions`, `get_execution`, `get_execution_flow` ([ADR-025](025-execution-history-and-retention.md), [ADR-028](028-global-executions-page-and-keyset-paging.md)) and `list_secrets`
  ([ADR-024](024-credential-store.md)). The integration API has the matching routes (`/api/v1/executions`, `/api/v1/secrets`).
- Features that use credentials need a token ([ADR-023](023-safety-model-of-execution-nodes.md), [ADR-024](024-credential-store.md)).
