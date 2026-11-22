# OpenArtifact

OpenArtifact is a self-hosted board of **artifacts** (cards) that you move through **pipelines** of stages and actions. An
action is a small graph of execution nodes (timer, Code, HTTP, output) that the in-process run engine executes when an
artifact enters a stage. Every execution is recorded, so you can see afterwards what ran, in which order, with which output.

It is one Python process (FastAPI) with a SQLite database and a web UI without a build step. A browser API, an integration API
(`/api/v1`) and an MCP server (`/mcp`) let scripts and AI agents create artifacts and start and read runs.

Status: pre-release (`0.1.x`), built for a single operator or a small trusted team. Read [Status and limitations](#status-and-limitations)
before you expose it.

## Quick start with Docker (about 5 minutes)

```bash
git clone https://github.com/MichaOro/openArtifact.git && cd openArtifact

cp deploy/.env.example deploy/.env        # the compose file reads deploy/.env
#   set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY, each with: openssl rand -hex 32

docker compose -f deploy/docker-compose.yml up -d --build
```

Open <http://localhost:2909> and sign in with the token. `curl http://localhost:2909/health` checks the service.
`docker compose -f deploy/docker-compose.yml down` stops it; the `openartifact-data` volume (the database) stays.

- The token is required: Code nodes, the credential store and the integration API are refused without it. Without a token the
  pages and the browser API are open to everyone who can reach the port.
- The secret key (at least 32 characters) signs the session cookie and encrypts stored credentials. Do not change it
  afterwards: stored credentials could no longer be read.
- The container is published on `127.0.0.1` only. For network access and TLS see
  [Run behind a reverse proxy](docs/guides/reverse-proxy.md); update, backup and restore are in
  [Operate the Docker deployment](docs/guides/operations.md).

## Development

```bash
cd apps/backend
uv sync --all-extras                  # or: pip install -e ".[dev]"
printf 'OPENARTIFACT_DATA_DIR=./.data\nOPENARTIFACT_HOST=127.0.0.1\n' > .env
uv run alembic upgrade head           # create the database
uv run openartifact                   # http://localhost:2909
```

`OPENARTIFACT_HOST` defaults to `0.0.0.0`; bind to loopback on a workstation, especially without a token. In open mode (no
token) Code nodes are refused; for local work only, add `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true` to `.env`. Checks, tests
and conventions: [CONTRIBUTING](.github/CONTRIBUTING.md) and [apps/backend/README.md](apps/backend/README.md). The interactive
API documentation of a running instance is at `/api/docs`.

## Concepts

| Term | Meaning |
|------|---------|
| Artifact | A card on the board with a title, a description and a lane. The unit of work that is moved and processed (`task` in the code and the API) |
| Pipeline | The path an artifact takes: a trigger, stages in order, a completion. Edited as a graph |
| Stage | A step of a pipeline; contains actions. Entering a stage starts its actions |
| Action | One unit of work inside a stage, linked to an action definition. Continues on *Pass* or *Error* |
| Action definition | What an action does: a graph of execution nodes between a trigger and an output |
| Execution node | A node of an action definition: Timer (wait), Code (shell or Python), HTTP (request), Output (result and routing) |
| Run | The current processing state of an artifact (live, shown on the board) |
| Execution | The recorded history of one run: a frozen snapshot of the pipeline, its steps and outputs, kept by retention |
| Flow | The read-only view of an execution on the editor canvas, with the walked path highlighted |

More with examples: [Concepts](docs/guides/concepts.md). Terms of the architecture: [glossary](docs/architecture/arc42/12-glossary.md).

## What it does today

- Board of artifacts with lanes, live updates (server-sent events) and a pipeline per artifact.
- Editor for pipelines and action definitions with Timer, Code, HTTP and Output nodes
  ([execution nodes](docs/guides/execution-nodes.md)); the run engine executes stages and actions in-process.
- Code nodes run shell or Python as a child process with CPU, memory, process, file and output limits; HTTP nodes refuse
  loopback, private and metadata addresses unless you allow them.
- Agents: reusable prompts with declared inputs, a draft and published versions (rollback included), run by an Agent
  node that sends one request to a model of OpenRouter or an OpenAI-compatible endpoint; the prompts as sent, the tokens
  and every attempt are in the history ([agents](docs/guides/agents.md)).
- Credential store: secrets are encrypted in the database and referenced by name from nodes, never returned by the API
  ([Credentials](docs/guides/credentials.md); API only, there is no UI for it yet).
- Execution history per artifact with steps and outputs, retention policy (default keep 50), delete and clear
  ([Execution history](docs/guides/execution-history.md)).
- Flow view of one execution and a global executions page (`/executions`) across all artifacts, with filters and summary.
- Integration API (`/api/v1`) and an MCP server (`/mcp`, 14 tools) with token authentication
  ([Sign in and use the API and MCP](docs/guides/integration.md), [API reference](docs/guides/api-reference.md)).

Planned and not implemented: AI agent nodes, Git and webhook connectors, extension packaging. The authoritative list is
[arc42 chapter 4.3](docs/architecture/arc42/04-solution-strategy.md#43-built-and-planned).

## Architecture in short

```
Browser / script / MCP client
        | HTTP, SSE
        v
FastAPI app (one process)
  web pages + browser API  |  /api/v1  |  /mcp        <- access gate (token, session cookie)
        |
  task service ---- run engine (asyncio) ---- executors: Timer, Code (child process), HTTP
        |                    |
        +------ SQLite (WAL, one file, Alembic migrations): artifacts, graphs, runs,
                executions, encrypted secrets
```

Frontend: Jinja2 templates, CSS design tokens and vanilla JavaScript, no build step. Details:
[arc42 building block view](docs/architecture/arc42/05-building-block-view/README.md),
[runtime view](docs/architecture/arc42/06-runtime-view/README.md) and the
[architecture decision records](docs/architecture/adr/).

## Status and limitations

- Pre-release, version `0.1.x`. The application's own data stays in SQLite; PostgreSQL may later come only as a data source
  through a connector layer, not as the application database.
- **No sandbox for Code nodes.** Code runs as the application's user, with resource limits, without network or file system
  isolation. The application is hardened against Code reading its parent's environment (API token and secret key), but anyone who
  may edit a pipeline can run code in the container. Give edit access only to people you trust.
  See [SECURITY.md](SECURITY.md) and [Security for operators](docs/guides/security.md).
- A token is required for Code nodes and credentials; without one the instance is open to everyone who reaches the port.
- Single process, single database file: do not run several instances against one database. The in-process event bus and
  run engine do not scale out.
- Accessibility is limited: connections in the graph editor are made by dragging (no keyboard-only way) and screen reader
  support is not tested. A later goal.
- There is no user management: one shared token, no roles.
- Further known risks and technical debt: [arc42 chapter 11](docs/architecture/arc42/11-risks-and-technical-debt.md).

## Documentation

Start at the [documentation map](docs/README.md). Configuration: every setting is an `OPENARTIFACT_*` environment variable
(in Docker: `deploy/.env`), see the [configuration reference](docs/guides/configuration.md).

| You want to | Read |
|-------------|------|
| Run it | [Operations](docs/guides/operations.md), [reverse proxy](docs/guides/reverse-proxy.md), [configuration](docs/guides/configuration.md), [security](docs/guides/security.md) |
| Use the API or MCP | [Integration](docs/guides/integration.md), [API reference](docs/guides/api-reference.md) |
| Understand the model | [Concepts](docs/guides/concepts.md), [arc42](docs/architecture/arc42/), [ADRs](docs/architecture/adr/) |
| Change the code | [CONTRIBUTING](.github/CONTRIBUTING.md), [extending](docs/guides/extending.md), [testing](docs/guides/testing.md), [CI/CD](docs/guides/CI-CD.md) |

## Contributing and security

Contributions are welcome: read [CONTRIBUTING](.github/CONTRIBUTING.md) first. Report vulnerabilities as described in
[SECURITY.md](SECURITY.md), not in a public issue.

## License

Apache License 2.0, see [LICENSE](LICENSE).
