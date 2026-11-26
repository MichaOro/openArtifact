# ADR-038: Repository layout: one Python project at the root

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-001](001-project-initialization.md), [ADR-019](019-module-boundaries-and-single-sources.md)  
**Amended by:** —  
**Implemented in:** the move of `apps/backend/*` to the root; `credentials/`, `api/mcp.py`, `models/*.py`; `Dockerfile`,
`.dockerignore`, `.github/workflows/*`, `.github/dependabot.yml`  
**Affected chapters:** [05.03](../arc42/05-building-block-view/05.03-backend-components.md), [05.04](../arc42/05-building-block-view/05.04-frontend-components.md); guides [development](../../guides/development.md), [testing](../../guides/testing.md), [CI/CD](../../guides/CI-CD.md)

## 1. Title

The repository is one Python project; the application package sits at the root, and its parts are grouped by area.

## 2. Context

The application lived in `apps/backend/`. The name said "backend", but the folder held the whole application: the
package serves the web UI as well (Jinja2 templates and ES modules, no build step, ADR-010). `apps/README.md` itself said
that it was the only application and that no second one should be added without an ADR. The extra level made every
command start with `cd apps/backend`, and a newcomer looked for a frontend that does not exist. Inside the package, three
`secret_*.py` modules, an `mcp_server.py` beside the API routers and a 640-line `models/__init__.py` made the top level
read like a list of loose files.

## 3. Decision

- **One project at the root.** `pyproject.toml`, `alembic.ini`, `alembic/`, `openartifact/` and `tests/` sit at the
  repository root next to `docs/`, `deploy/`, `scripts/` and `tools/`; `.python-version` too. Every command runs from the
  root. `apps/` is gone. The repository README is the package's readme.
- **Templates and static files stay in the package** (`openartifact/templates`, `openartifact/static`): the package
  serves them, they are package data, as in other server-rendered Python web applications. "Backend" and "frontend" are not
  folder names; arc42 5.3 and 5.4 describe the server and the browser parts.
- **Inside the package, grouping by area where it is clear:** `credentials/` (`crypto`, `store`, `refs`), `api/mcp.py`
  (an interface like `api/v1.py`), `models/` with one module per area and `__init__` re-exporting every model. The
  application's core modules (`app`, `cli`, `config`, `database`, `events`, `exceptions`, `logging_config`, `security`,
  `schemas_common`, `version`) stay at the top level: they are what every area uses.
- **A second application** (a worker, an extension host) gets its own top-level package or project by a new ADR; the
  layout of the time is then reconsidered, not prepared now.
- ruff and mypy check the whole repository (the tools in `tools/` included); Markdown is not formatted by ruff.

## 4. Consequences

- Commands lose the `cd apps/backend`; CI, Dockerfile, `.dockerignore`, Dependabot and the guides name root paths.
- A development install has to be redone once: `pip install -e ".[dev]"` (or `uv sync --all-extras`) from the root.
- Imports changed for `openartifact.credentials.*` and `openartifact.api.mcp`; `openartifact.models` is unchanged for its
  users. Older ADRs keep the file names of their time.
- No behaviour changes; the tests, the migrations and the image are the same.
