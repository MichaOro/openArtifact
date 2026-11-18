# 3. Context and Scope

## 3.1 Business Context

OpenArtifact operates at the center of a workflow orchestration ecosystem:

- **Users** — Interact via web interface for project management, workflow orchestration, and human oversight
- **AI Agent Providers** — External AI models/services that execute autonomous tasks within workflows
- **Persistent Storage** — SQLite database for artifact and workflow state
- **External Systems** — Future integrations via API/webhooks (GitHub, notification services, etc.)

## 3.2 Technical Context

```
┌──────────┐     HTTP      ┌──────────────┐     SQLite     ┌──────────┐
│  Browser  │ ◄──────────► │ OpenArtifact │ ◄─────────────►│  SQLite  │
│ (HTMX/   │              │   (Port 2909) │               │  (WAL)   │
│  WS)     │              │              │                 │          │
└──────────┘              └──────┬───────┘                 └──────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼────┐ ┌────▼─────┐ ┌────▼─────┐
              │  Git     │ │ AI APIs  │ │External  │
              │  (future)│ │(OpenAI,  │ │ Webhooks │
              │          │ │ Anthropic│ │ (future)│
              └──────────┘ │, etc.)    │ └──────────┘
                           └──────────┘
```

- **Browser** — HTMX + Jinja2 frontend, WebSocket for real-time progress
- **OpenArtifact** — Application server, workflow engine, artifact store
- **SQLite** — Persistent storage (WAL mode for concurrency)
- **AI APIs** — External model providers (OpenAI, Anthropic, etc.)
- **Git / External Systems** — Planned integrations (future WP)

---

*This chapter follows the arc42 template. TBD fields are limited to context changes introduced in later Work Packages.*
