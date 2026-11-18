# 6. Runtime View

## 6.1 Key Scenarios

### WP-03/04: Application Startup and Shutdown

```
┌────────┐   docker compose   ┌──────────────┐   uvicorn   ┌──────────┐
│  User  │ ───────────────►   │ OpenArtifact │ ─────────►  │  FastAPI │
│        │                    │   Container  │             │ (2909)   │
│        │ ◄────────────────  │              │             │          │
│  curl  │   GET /health      │              │             │          │
│ browser│   GET /           │              │             │          │
└────────┘                    └──────────────┘             └──────────┘

Startup:
  1. uvicorn loads openartifact.app:create_app
  2. Settings loaded from env vars (OPENARTIFACT_* prefix)
  3. FastAPI app created with lifespan hooks
  4. Router registration (api + web)
  5. Lifespan startup:
     a. Log identity, validate config
     b. Build async engine (_build_engine)
     c. Create data directory if needed
     d. Enable WAL mode
     e. Verify connectivity (SELECT 1)
     f. Log database connection
  6. Server binds to 0.0.0.0:2909

Shutdown:
  1. SIGTERM received (docker stop, kill)
  2. Lifespan shutdown: dispose_engine()
  3. Server stops accepting connections
  4. Active requests drain
  5. uvicorn exits
```

### WP-03/04: Health Check Flow

```
User/HealthCheck ──GET /api/health──► FastAPI
                                              │
                                     api.routes.health_check()
                                              │
                                     {"status":"ok","application":"OpenArtifact",
                                      "version":"0.1.0","uptime_status":"running"}
                                              │
User/HealthCheck ◄── HTTP 200 + JSON ◄───────┘
```

### WP-03/04: Web Request Flow

```
Browser ──GET /──► FastAPI
                      │
             web.routes.index()
                      │
             Jinja2.render("index.html")
                      │
             HTMX script loaded from CDN
                      │
Browser ◄── HTML 200 + "OpenArtifact 0.1.0" ◄──────────
```

### WP-04: Database Session Flow

```
FastAPI Request ──► get_db_session() (FastAPI dependency)
                            │
                    engine is initialized?
                    /          \
                   yes          no → ConfigurationError (503)
                    │
              Create AsyncSession
                    │
              ┌─────▼─────┐
              │   yield   │ ← Request handler
              │  session  │   uses session.execute()
              └─────┬─────┘
                    │
              ┌─────▼─────┐
              │ commit /  │
              │ rollback  │
              └─────┬─────┘
                    │
              Session closed
```

### WP-04: Migration Flow

```
Developer ──► modify openartifact/models/*.py
                    │
              (optional) alembic revision --autogenerate -m "add table"
                    │
              alembic upgrade head
                    │
              SQLite: SELECT alembic_version
                    │
              Apply migration if version not found
                    │
              INSERT alembic_version(2nd_migration_id)
```

## 6.2 State Behavior

> TBD — State machines for artifacts, workflows, and executions to be defined in WP-05 through WP-06.

### SQLite WAL Mode State

```
┌─────────────────────────┐
│      SQLite (WAL)       │
│                         │
│  read: concurrent ✓     │
│  write: serial ⏱        │
│  journal: WAL mode      │
│  sync: NORMAL           │
│  max_journal: 8 MB      │
└─────────────────────────┘
```

---

*This chapter follows the arc42 template. Runtime scenarios documented as WP-03/04 completed.*
