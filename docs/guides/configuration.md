# Configuration reference

Every setting is an environment variable with the prefix `OPENARTIFACT_`. The application reads them
from the process environment and, outside Docker, from a `.env` file in its working directory
(`apps/backend/.env` for a local run). The single source of the names and defaults is
[`config.py`](../../apps/backend/openartifact/config.py); a setting it does not know is ignored.

With Docker Compose the variables go into `deploy/.env` (copy of [`deploy/.env.example`](../../deploy/.env.example));
the compose file passes the whole file to the container and also reads it for its own substitutions.

## Application settings

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENARTIFACT_HOST` | `0.0.0.0` | Address the server binds to inside its process or container. |
| `OPENARTIFACT_PORT` | `2909` | Port the server listens on. In Docker it is the port *inside* the container; the published port is `OPENARTIFACT_PUBLISHED_PORT`. |
| `OPENARTIFACT_DEBUG` | `false` | Debug mode: SQL echo, and an unexpected error answers with its message instead of `Internal server error`. Never in production. |
| `OPENARTIFACT_DATA_DIR` | `/data` | Directory of the database file; created if it does not exist. Outside Docker `/data` is usually not writable: use `./.data`. |
| `OPENARTIFACT_DATABASE_FILENAME` | `openartifact.db` | Name of the SQLite file inside the data directory. |
| `OPENARTIFACT_SECRET_KEY` | `change-me-in-production` | Signs the session cookie. With an API token set the application refuses to start while this is empty or the default. Changing it signs every browser out. Generate: `openssl rand -hex 32`. |
| `OPENARTIFACT_API_TOKEN` | *(empty)* | The one access token, at least 32 characters (`openssl rand -hex 32`); shorter tokens stop the start. Set: the whole application asks for it (sign-in page, `Authorization: Bearer`). Empty: pages and browser API are open, `/api/v1` and `/mcp` answer `401`, and the log warns at startup. See [Sign in and use the API](integration.md). |
| `OPENARTIFACT_ALLOWED_HOSTS` | *(empty)* | Comma-separated host names the application answers to, for example `oa.example.com, *.example.org`. Any other `Host` header gets `400`. Empty: no check. `/health` is always reachable, so container health checks work. Protects against DNS rebinding. |
| `OPENARTIFACT_COOKIE_SECURE` | `auto` | `auto`: the session cookie is `Secure` (and named `__Host-oa_session`) when the request scheme is `https`. `true`: always (and HSTS is sent even if the proxy does not forward the scheme); right behind a TLS-terminating proxy. The application sends `Strict-Transport-Security` whenever the request is https. `false`: never. See [Reverse proxy](reverse-proxy.md). |
| `OPENARTIFACT_MAX_REQUEST_BYTES` | `1048576` | Largest request body in bytes (1 MiB); a larger one gets `413`. The sign-in form has its own cap of 4096 bytes. |
| `OPENARTIFACT_CSP_SCRIPT_UNSAFE_INLINE` | `false` | Opt-out only: adds `'unsafe-inline'` to the `script-src` of the Content-Security-Policy. The pages have no inline scripts, so the default policy is `script-src 'self'`. Leave it off. |
| `OPENARTIFACT_MAX_CONCURRENT_RUNS` | `8` | Pipeline runs that may be active at the same time; a further start gets `429`. |
| `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` | `50` | Open live-update streams (browser tabs); a further one gets `503`. |
| `OPENARTIFACT_LOG_LEVEL` | `INFO` | Log level of the application (`DEBUG`, `INFO`, `WARNING`, `ERROR`) and of uvicorn. |

Settings that the application refuses to start with: a token shorter than 32 characters, and a token
together with an empty or default secret key.

## Docker Compose only

These are read by [`deploy/docker-compose.yml`](../../deploy/docker-compose.yml) for its own
substitutions (from `deploy/.env` or the shell environment). The application does not use them.

| Variable | Default | Meaning |
|----------|---------|---------|
| `OPENARTIFACT_BIND` | `127.0.0.1` | Host address the container's port is published on. `127.0.0.1` keeps it local; `0.0.0.0` opens it to the network (set a token first). |
| `OPENARTIFACT_PUBLISHED_PORT` | `2909` | Host port. |
| `OPENARTIFACT_TAG` | `latest` | Image tag for `docker compose pull` of a [released image](CI-CD.md). Building from source ignores it. |

The mapping is `BIND:PUBLISHED_PORT:OPENARTIFACT_PORT`, and the health check calls `OPENARTIFACT_PORT`, so
changing the in-container port keeps both consistent.

## Read by uvicorn, not by the application

| Variable | Default | Meaning |
|----------|---------|---------|
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Addresses whose `X-Forwarded-*` headers uvicorn trusts. Behind a reverse proxy in another container set it to the proxy's address (or `*` if only the proxy can reach the container). Without it the application sees `http` and does not issue a `Secure` cookie. Put it into `deploy/.env` to pass it into the container. |

## Example `deploy/.env` for a server behind HTTPS

```ini
OPENARTIFACT_API_TOKEN=<openssl rand -hex 32>
OPENARTIFACT_SECRET_KEY=<another openssl rand -hex 32>
OPENARTIFACT_ALLOWED_HOSTS=oa.example.com
OPENARTIFACT_COOKIE_SECURE=true
FORWARDED_ALLOW_IPS=172.18.0.1
OPENARTIFACT_BIND=127.0.0.1
```
