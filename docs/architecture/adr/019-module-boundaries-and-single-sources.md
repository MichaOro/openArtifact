# ADR-019: Module boundaries and single sources

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-014](014-building-blocks-and-extension-points.md)  
**Amended by:** [ADR-022](022-node-settings-as-json-config.md) (settings), [ADR-032](032-removal-of-the-unused-workspace-model.md) (unused code removed)

## 1. Title

Where access protection, request hardening, shared types and start-up live, and that every fact has one source.

## 2. Context

The first version had facts written in several places: the version in `pyproject.toml` and in the code, the
server start in the entrypoint, in `cli.py` and in the end-to-end fixtures, icon paths in several templates, storage
keys in several scripts, the allowed node settings as a hard-coded set next to the node-kind registry, and access
protection split between `api/auth.py` and `mcp_server.py`. Extension points (ADR-014) only work if the places a
contributor has to touch are few and named.

## 3. Decision

### 3.1 Backend modules

| Module | Responsibility |
|--------|----------------|
| `openartifact/security.py` | Access protection: `AccessGate`, `TokenProtected`, `token_matches`, `token_error`, the session cookie, `require_api_token` |
| `openartifact/api/hardening.py` | Request hardening middlewares: `SecurityHeaders`, `HostCheck`, `BodyLimit`, `CrossSiteGuard` |
| `openartifact/api/deps.py` | FastAPI dependencies (`SessionDep`, `ServiceDep`) |
| `openartifact/schemas_common.py` | Types shared by schemas (the UTC timestamp) |
| `openartifact/engine/schemas.py` | `RunRead`, `RunStageRead` |
| `openartifact/version.py` | `__version__`, the only place the version is written (`pyproject.toml` reads it with hatch) |
| `openartifact/web/` | A regular package: pages, `navigation`, static files; `templates/` and `static/` are plain folders |

`openartifact/__init__.py` no longer imports the application: use `openartifact.app:create_app`.
Node settings are derived from the node-kind registry (`NODE_TYPES`) instead of a hard-coded set; the timer bounds
exist once in `graph/node_types.py`; `GraphKind` is a `StrEnum` in the models, and `Ports` names the connectors.

### 3.2 One start path

The server starts one way: `openartifact` (`openartifact.cli:main`). The Docker entrypoint runs
`alembic upgrade head` and then `exec openartifact`; it neither calls uvicorn itself nor sets defaults. The CLI
passes `timeout_graceful_shutdown=3` (an open event stream must not hold up the shutdown) and the log level.
The application factory configures logging after building the MCP server.

### 3.3 Frontend single sources

All icon paths live in `templates/components/icons.html` (rendered once into `<template id="icons">`, cloned by
`static/js/components/icons.js`); storage keys are defined once in `theme.js` (`window.OpenArtifact.keys`) and used
through `storage.js`; the layout is `base_bare.html` extended by `base.html` and `login.html`; macros `alert()`,
`form_modal()` and `confirm_modal()` replace copies. The graph editor is split into modules with a `ge-` class prefix,
and the templates contain no inline scripts, which is what lets the Content-Security-Policy say `script-src 'self'`
([ADR-017](017-request-hardening-and-signed-sessions.md)).

## 4. Consequences

- A change to the version, the start command, an icon or a storage key is one edit.
- Access protection and hardening can be read in two short modules; both are on the path of `/mcp`.
- Unused code is not deleted at once but quarantined (`Project`/`WorkItem` models and `repositories/`, `BOARD_STATUSES`,
  `PipelineError`, `DatabaseError`); `release.yml` does not yet compare the version with the tag.

## Update (2026-11-22): modules added, quarantine closed

- The table in §3.1 predates `engine/` (executors, runners, history, flow, `code_registry`), `secret_crypto.py`,
  `secret_store.py` and `secret_refs.py`; chapter 5 of arc42 lists them.
- Node settings are described by `Setting` and stored in JSON ([ADR-022](022-node-settings-as-json-config.md)).
- The step bound exists twice on purpose (`engine/runner.py` `MAX_STEPS`, `engine/flow.py` `MAX_ACTIONS`, both 1000):
  the replay keeps its own constant ([ADR-027](027-execution-flow-by-replay-over-the-frozen-snapshot.md)), an exception to "one source".
- The quarantined code of §4 (`Project`/`WorkItem`, `repositories/`, `BOARD_STATUSES`, `PipelineError`,
  `DatabaseError`) was removed ([ADR-032](032-removal-of-the-unused-workspace-model.md)); a release tag must equal `version.py` (see the
  [CI/CD guide](../../guides/CI-CD.md)); the sentence in §4 that `release.yml` does not compare them is outdated.
