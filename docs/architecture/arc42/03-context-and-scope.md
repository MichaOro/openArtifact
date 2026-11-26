# 3. Context and Scope

## 3.1 Business Context

OpenArtifact is a self-hosted board of artifacts that run through pipelines:

- **Users** — work in the web interface: they create artifacts, edit pipelines and action definitions, start and stop processing, read the execution history.
- **Scripts and other systems** — create and follow artifacts and read executions through the integration API (`/api/v1`, bearer token); they also manage credentials there.
- **LLM agents** — do the same through the MCP server (`/mcp`, bearer token, 19 tools).
- **Persistent storage** — one SQLite file for artifacts, pipelines, executions and the encrypted credentials.
- **HTTP targets** — HTTP nodes call URLs that the pipeline designer chose. Requests go to checked public addresses only, unless private networks are allowed by a setting.
- **Child processes** — Code nodes run a shell or Python script as a child process of the application.
- **Not built:** AI model providers, Git, notification services and PostgreSQL as a data source. They are planned integrations behind a future connector layer (ADR-020); an HTTP or Code node can reach such systems by hand, but there is no first-class support.

## 3.2 Technical Context

```
┌──────────┐   HTTP, SSE    ┌───────────────┐  SQLite   ┌──────────┐
│ Browser  │ ◄────────────► │ OpenArtifact  │ ◄───────► │  SQLite  │
│ (cookie) │  /, /api/*     │ (port 2909)   │           │  (WAL)   │
└──────────┘                │               │           └──────────┘
┌──────────┐  /api/v1       │               │
│ Scripts  │ ─────────────► │               │   HTTP    ┌──────────────┐
└──────────┘  (Bearer)      │  run engine:  │ ────────► │ HTTP targets │
┌──────────┐  /mcp          │  HTTP node    │           └──────────────┘
│ LLM agent│ ─────────────► │  Code node    │  fork     ┌──────────────┐
└──────────┘  (Bearer)      │               │ ────────► │ child        │
                            └───────────────┘           │ processes    │
                                                        └──────────────┘
```

- **Browser** — server-rendered Jinja2 pages with vanilla JavaScript; JSON API for board, editor and execution data; live updates via server-sent events (ADR-011); signs in with the token and keeps a session cookie (ADR-016, ADR-017).
- **Scripts and agents** — `Authorization: Bearer <token>` on `/api/v1/*` and `/mcp` (guide: [Sign in and use the API and MCP](../../guides/integration.md); reference: [API reference](../../guides/api-reference.md)).
- **OpenArtifact** — application server, run engine, artifact store, credential store; behind an optional TLS reverse proxy ([guide](../../guides/reverse-proxy.md)).
- **SQLite** — persistent storage (WAL mode); one process opens it.
- **HTTP targets** — one request per HTTP node, no redirects, size and time limits, address checked before the connection (DNS-rebinding safe); see [8.1](08-cross-cutting-concepts/08.01-security.md) and ADR-023.
- **Child processes** — started per Code node with resource limits, in their own process group; they are not isolated from the network or the file system (ADR-023).
- **Swagger UI** — `/api/docs` loads its scripts from a public CDN; this is the only external asset (chapter 2).
- **LLM providers** — OpenRouter or an OpenAI-compatible endpoint, called by Agent nodes through the same address guard as HTTP nodes (ADR-037).
- **Remote MCP servers and tool targets** — the tools of an agent (MCP Client Tool over Streamable HTTP, e.g. GitHub's; HTTP Request Tool) reach them through the same guard, only when the model calls them (ADR-040).
- **GitHub's API** — the GitHub node reads repositories, issues, pull requests, files and comments and writes comments, through the same address guard (ADR-041).
- **PostgreSQL databases of the user** — a data source read (and, if allowed, changed) by the Postgres node and the Postgres Tool with a statement the flow's author wrote; the connection URL is a secret and the address guard applies (ADR-020, ADR-041).
- **Planned** — Git as a source through a future connector layer.
