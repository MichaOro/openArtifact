# 3. Context and Scope

## 3.1 Business Context

OpenArtifact is a self-hosted board of artifacts that run through pipelines:

- **Users** — work in the web interface: they create artifacts, edit pipelines, start and stop processing.
- **Scripts and other systems** — create and follow artifacts through the integration API (`/api/v1`, bearer token).
- **LLM agents** — do the same through the MCP server (`/mcp`, bearer token).
- **Persistent storage** — one SQLite file for artifacts, pipelines and runs.
- **AI model providers, Git, webhooks, notification services, PostgreSQL as a data source** — planned integrations; none exists yet (actions are empty shells or timers today).

## 3.2 Technical Context

```
┌──────────┐   HTTP, SSE    ┌──────────────┐   SQLite   ┌──────────┐
│ Browser  │ ◄────────────► │ OpenArtifact │ ◄────────► │  SQLite  │
│ (cookie) │  /, /api/*     │  (port 2909) │            │  (WAL)   │
└──────────┘                │              │            └──────────┘
┌──────────┐  /api/v1       │              │
│ Scripts  │ ─────────────► │              │
└──────────┘  (Bearer)      │              │
┌──────────┐  /mcp          │              │
│ LLM agent│ ─────────────► │              │
└──────────┘  (Bearer)      └──────┬───────┘
                                   │ planned
                  ┌────────────────┼─────────────────┐
            ┌─────▼────┐     ┌─────▼──────┐    ┌─────▼──────┐
            │   Git    │     │ AI APIs    │    │ Webhooks,  │
            │          │     │            │    │ PostgreSQL │
            └──────────┘     └────────────┘    └────────────┘
```

- **Browser** — server-rendered Jinja2 pages with vanilla JavaScript; JSON API for board data; live updates via server-sent events (ADR-011); signs in with the token and keeps a session cookie (ADR-016, ADR-017).
- **Scripts and agents** — `Authorization: Bearer <token>` on `/api/v1/*` and `/mcp` (guide: [Sign in and use the API and MCP](../../guides/integration.md)).
- **OpenArtifact** — application server, run engine, artifact store; behind an optional TLS reverse proxy ([guide](../../guides/reverse-proxy.md)).
- **SQLite** — persistent storage (WAL mode); one process opens it.
- **Planned** — Git, AI model providers, webhooks and PostgreSQL as a data source (ADR-020) through a future connector layer.
