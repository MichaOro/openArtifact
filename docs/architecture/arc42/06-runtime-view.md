# 6. Runtime View

## 6.1 Key Scenarios

### WP-03: Application Startup and Shutdown

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
  5. Lifespan startup: log identity, validate config
  6. Server binds to 0.0.0.0:2909

Shutdown:
  1. SIGTERM received (docker stop, kill)
  2. Lifespan shutdown: log shutdown event
  3. Server stops accepting connections
  4. Active requests drain
  5. uvicorn exits
```

### WP-03: Health Check Flow

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

### WP-03: Web Request Flow

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

## 6.2 State Behavior

> TBD — State machines for artifacts, workflows, and executions to be defined in WP-04 through WP-06.

---

*This chapter follows the arc42 template. Runtime scenarios documented as WP-03 completed.*
