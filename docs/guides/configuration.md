# Configuration reference

Every setting is an environment variable with the prefix `OPENARTIFACT_`. The application reads them
from the process environment and, outside Docker, from a `.env` file in its working directory
(`.env` at the repository root for a local run). The single source of names, defaults and bounds is
[`config.py`](../../openartifact/config.py); a variable it does not know is ignored. A
value outside its bounds, or one of the wrong type, stops the start with an error that names the variable.

With Docker Compose the variables go into `deploy/.env` (copy of [`deploy/.env.example`](../../deploy/.env.example));
the compose file passes the whole file to the container and also reads it for its own substitutions.

Read first: [Security](security.md) (what the token protects, what Code nodes can do),
[Credentials](credentials.md) (what the secret key encrypts) and [Execution nodes](execution-nodes.md)
(Code and HTTP nodes). The vulnerability policy is in [SECURITY.md](../../SECURITY.md).

## Server

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_HOST` | string | `0.0.0.0` | none | Address the server binds to inside its process or container. **Outside Docker `0.0.0.0` listens on every interface**; for a local run set `127.0.0.1`, because without a token the pages and the browser API are open to everyone who can reach the port. In Docker the published address is `OPENARTIFACT_BIND`. |
| `OPENARTIFACT_PORT` | integer | `2909` | valid TCP port | Port the server listens on. In Docker it is the port *inside* the container; the published port is `OPENARTIFACT_PUBLISHED_PORT`. |
| `OPENARTIFACT_DEBUG` | boolean | `false` | | Debug mode: SQL echo, and an unexpected error answers with its message instead of `Internal server error`. Never in production. |

## Database

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_DATA_DIR` | path | `/data` | | Directory of the database file; created if it does not exist. Outside Docker `/data` is usually not writable: use `./.data`. |
| `OPENARTIFACT_DATABASE_FILENAME` | string | `openartifact.db` | | Name of the SQLite file inside the data directory. |

The database is SQLite in WAL mode and stays so ([ADR-020](../architecture/adr/020-sqlite-stays-postgres-as-data-source.md)).

## Security

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_SECRET_KEY` | string | `change-me-in-production` | at least 32 characters when a token is set or credentials are stored | Signs the session cookie **and is the source of the key that encrypts stored credentials** (AES-256-GCM, key derived with HKDF). Required as soon as a token is set: an empty or default key stops the start. **Never change it once credentials are stored: every stored credential becomes unreadable** (there is no re-encryption); it also signs every browser out. Generate: `openssl rand -hex 32`. See [Credentials](credentials.md). |
| `OPENARTIFACT_API_TOKEN` | string | *(empty)* | at least 32 characters when set | The one access token (`openssl rand -hex 32`); a shorter one stops the start. Set: the whole application asks for it (sign-in page, `Authorization: Bearer`). Empty: pages and browser API are open, `/api/v1` and `/mcp` answer `401`, Code nodes are refused (see `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN`), credentials cannot be stored, and the log warns at startup. See [Sign in and use the API](integration.md). |
| `OPENARTIFACT_ALLOWED_HOSTS` | string | *(empty)* | comma-separated; `*.example.org` allowed | Host names the application answers to, for example `oa.example.com, *.example.org`. Any other `Host` header gets `400`. Empty: no check. `/health` is always reachable, so container health checks work. Protects against DNS rebinding. |
| `OPENARTIFACT_COOKIE_SECURE` | `auto` / `true` / `false` | `auto` | the three values | `auto`: the session cookie is `Secure` (and named `__Host-oa_session`) when the request scheme is `https`. `true`: always (and HSTS is sent even if the proxy does not forward the scheme); right behind a TLS-terminating proxy. `false`: never. The application sends `Strict-Transport-Security` whenever the request is https. See [Reverse proxy](reverse-proxy.md). |
| `OPENARTIFACT_MAX_REQUEST_BYTES` | integer | `1048576` | at least 1 | Largest request body in bytes (1 MiB); a larger one gets `413`. The sign-in form has its own cap of 4096 bytes. |
| `OPENARTIFACT_CSP_SCRIPT_UNSAFE_INLINE` | boolean | `false` | | Opt-out only: adds `'unsafe-inline'` to the `script-src` of the Content-Security-Policy. The pages have no inline scripts, so the default policy is `script-src 'self'`. Leave it off. |

## Run limits

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_MAX_CONCURRENT_RUNS` | integer | `8` | at least 1 | Pipeline runs that may be active at the same time; a further start gets `429`. |
| `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` | integer | `50` | at least 1 | Open live-update streams (browser tabs); a further one gets `503`. |

The limits of a single execution (how many steps, how much time) are not environment variables: they are set on
*Settings > Run limits* in the web interface or with `PUT /api/v1/settings/run-limits`, take effect for the executions
that start afterwards and are kept in the database ([ADR-039](../architecture/adr/039-edit-fields-switch-rules-and-run-limits.md)).

## Execution history

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_EXECUTION_HISTORY_DEFAULT_KEEP` | integer | `50` | 0 to 100000 | How many executions of an artifact are kept when its owner has set no retention policy of its own; the oldest finished ones beyond that are deleted (a running one and the newest one are never deleted by retention). `0` keeps all of them: the database then grows with every run (step outputs of up to 1 MiB each), so use it only with a policy per artifact. See [Execution history](execution-history.md) and [Database size](operations.md#database-size-and-history-retention). |

## Code and HTTP nodes

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_CODE_NODES_ENABLED` | boolean | `true` | | Whether Code nodes run. Code runs as a child of the application with the application's own rights (hardened against reading the parent's environment, no sandbox); off: a Code node fails with "Code nodes are disabled". |
| `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN` | boolean | `false` | | Code nodes need `OPENARTIFACT_API_TOKEN`. In open mode (no token) they are refused unless this is `true`. It exists for local development on `127.0.0.1`; never set it on a reachable instance. |
| `OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES` | integer | `65536` | at least 1 | Largest stdout and stderr (each, in bytes) kept of a Code node; the rest is cut off. |
| `OPENARTIFACT_CODE_MEMORY_LIMIT_MB` | integer | `512` | 64 to 65536 | Address space (virtual memory) of a Code node's process in MiB (`RLIMIT_AS`). Python and the shell need little; runtimes that reserve much address space (Java, Node.js, Go) need more. |
| `OPENARTIFACT_CODE_PROCESS_LIMIT` | integer | `64` | 1 to 4096 | Processes and threads a Code node may add (`RLIMIT_NPROC`). The kernel counts per user, not per process tree, so the limit is the user's current count plus this number. Does not apply to a process that runs as root. |
| `OPENARTIFACT_CODE_FILE_SIZE_LIMIT_MB` | integer | `64` | 1 to 10240 | Largest file in MiB a Code node's process may write (`RLIMIT_FSIZE`). |
| `OPENARTIFACT_CODE_OPEN_FILES_LIMIT` | integer | `256` | 16 to 65536 | Open files of a Code node's process (`RLIMIT_NOFILE`). |
| `OPENARTIFACT_HTTP_RESPONSE_LIMIT_BYTES` | integer | `1048576` | at least 1 | Largest response body (bytes) an HTTP node reads; the rest is cut off. |
| `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS` | boolean | `false` | | Whether HTTP nodes may call loopback, private, link-local and carrier-grade NAT addresses. Off by default (protects the host network); self-hosters calling their own services switch it on. Metadata, unspecified and multicast addresses stay blocked. A Code node is not bound by this: it reaches whatever the application reaches. |
| `OPENARTIFACT_LLM_ALLOW_PRIVATE_NETWORKS` | boolean | `false` | | Whether an LLM provider, an MCP Client Tool or an HTTP Request Tool of an agent may be on a loopback, private or link-local address (a model server on this host or in the internal network). It is the operator's half of the permission: the provider must also have its own *private network* switch on. Independent of `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS`: it does not open HTTP nodes. Metadata, unspecified and multicast addresses stay blocked. See [Agents and LLM providers](agents.md). |

The limits do not replace each other: in the container the memory limit (`mem_limit`, 1 GiB) and the process
limit (`pids_limit`, 256) apply to the whole container, the `CODE_*` limits to one Code process. See
[Operate the Docker deployment](operations.md#code-nodes-in-the-container).

## Logging

| Variable | Type | Default | Bounds | Meaning |
|----------|------|---------|--------|---------|
| `OPENARTIFACT_LOG_LEVEL` | choice | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (case-insensitive) | Log level of the application and of uvicorn. Configured secrets and the values of credentials in use are masked in every line. |

## Docker Compose only

These are read by [`deploy/docker-compose.yml`](../../deploy/docker-compose.yml) for its own
substitutions (from `deploy/.env` or the shell environment). The application does not use them; they
also reach the container environment because the whole file is passed on, which is harmless.

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENARTIFACT_BIND` | `127.0.0.1` | Host address the container's port is published on. `127.0.0.1` keeps it local (reach it with an SSH port forward or a reverse proxy on the host); `0.0.0.0` opens it to the network (set a token first). |
| `OPENARTIFACT_PUBLISHED_PORT` | `2909` | Host port. |
| `OPENARTIFACT_TAG` | `latest` | Image tag for `docker compose pull` of a [released image](CI-CD.md). Building from source ignores it. |

The mapping is `BIND:PUBLISHED_PORT:OPENARTIFACT_PORT`, and the health check calls `OPENARTIFACT_PORT`, so
changing the in-container port keeps both consistent.

## Read by uvicorn, not by the application

| Variable | Default | Meaning |
|----------|---------|---------|
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Addresses whose `X-Forwarded-*` headers uvicorn trusts. Behind a reverse proxy in another container set it to the proxy's address (or `*` if only the proxy can reach the container). Without it the application sees `http` and does not issue a `Secure` cookie. Put it into `deploy/.env` to pass it into the container. |

## What stops the start

The application refuses to start (and says why) when

- the token is shorter than 32 characters,
- a token is set and the secret key is empty, the default or shorter than 32 characters,
- a setting is out of its bounds or of the wrong type (including an unknown `OPENARTIFACT_LOG_LEVEL`
  or `OPENARTIFACT_COOKIE_SECURE`).

## Example `deploy/.env` for a server behind HTTPS

```ini
OPENARTIFACT_API_TOKEN=<openssl rand -hex 32>
OPENARTIFACT_SECRET_KEY=<another openssl rand -hex 32>
OPENARTIFACT_ALLOWED_HOSTS=oa.example.com
OPENARTIFACT_COOKIE_SECURE=true
FORWARDED_ALLOW_IPS=172.18.0.1
OPENARTIFACT_BIND=127.0.0.1
```

## Example `.env` for a local run (at the repository root)

```ini
OPENARTIFACT_HOST=127.0.0.1
OPENARTIFACT_DATA_DIR=./.data
OPENARTIFACT_DEBUG=true
# open mode refuses Code nodes; to try them locally, either set a token and a key (>= 32 characters each) or:
# OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true
```
