# 3. Context and Scope

## 3.1 Business Context

OpenArtifact operates at the center of a pipeline orchestration ecosystem:

- **Users** — Interact via web interface for project management, pipeline orchestration, and human oversight
- **AI Agent Providers** — External AI models/services that execute autonomous tasks within pipelines
- **Persistent Storage** — SQLite database for artifact and pipeline state
- **External Systems** — Future integrations via API/webhooks (GitHub, notification services, etc.)

## 3.2 Technical Context

```
┌──────────┐     HTTP      ┌──────────────┐     SQLite     ┌──────────┐
│  Browser  │ ◄──────────► │ OpenArtifact │ ◄─────────────►│  SQLite  │
│ (Jinja2  │              │   (Port 2909) │               │  (WAL)   │
│  + JS)   │              │              │                 │          │
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

- **Browser** — server-rendered Jinja2 pages with vanilla JavaScript; JSON REST API for board data; live updates via server-sent events (ADR-011)
- **OpenArtifact** — Application server, pipeline engine, artifact store
- **SQLite** — Persistent storage (WAL mode for concurrency)
- **AI APIs** — External model providers (OpenAI, Anthropic, etc.)
- **Git / External Systems** — Planned integrations (future WP)

---

*This chapter follows the arc42 template. TBD fields are limited to context changes introduced in later Work Packages.*
