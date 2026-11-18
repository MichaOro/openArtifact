# 5. Building Block View

## 5.1 Domain Model

> TBD — Domain entities (Project, Artifact, Workflow, Execution) to be defined in WP-02.

## 5.2 Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      OpenArtifact                           │
│                                                             │
│  ┌─────────────┐ ┌─────────────┐ ┌───────────────────────┐ │
│  │  HTTP Layer │ │  Workflow   │ │     Artifact Store    │ │
│  │             │ │   Engine    │ │                       │ │
│  │ FastAPI     │ │ Asyncio     │ │ Pydantic Models       │ │
│  │ Routes      │ │ Task Mgmt   │ │ SQLite Persistence    │ │
│  └──────┬──────┘ └──────┬──────┘ └──────────┬────────────┘ │
│         │               │                    │              │
│  ┌──────▼───────────────▼────────────────────▼────────────┐ │
│  │              Application Core                          │ │
│  │  Config · Logging · Lifecycle · Database Migrations    │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 5.3 Component View

> TBD — Detailed component specifications deferred to WP-02 through WP-04.

## 5.4 Interface View

| Component | Interface | Protocol |
|-----------|-----------|----------|
| HTTP Layer | REST API + HTMX templates | HTTP/1.1 |
| HTTP Layer | Real-time progress | WebSocket / SSE |
| Artifact Store | SQLite database | SQLite (file) |
| External | AI Agent APIs | HTTP/HTTPS |

---

*This chapter follows the arc42 template. TBD fields are limited to components introduced in later Work Packages.*
