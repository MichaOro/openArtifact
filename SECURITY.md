# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately, not in a public issue: use GitHub's private vulnerability
reporting for this repository (**Security** tab, **Report a vulnerability**, i.e. a security advisory at
<https://github.com/MichaOro/openArtifact/security/advisories/new>). Describe what you found, how to
reproduce it and which version or commit you tested. This is a small project maintained by one person: expect
an acknowledgement within about a week, and a fix or an explanation after that. Please give us the chance to
fix the problem before you publish it.

## Supported versions

Only the latest release (currently `0.1.x`) and the `main` branch receive security fixes. There are no
backports to older versions.

## Scope

In scope: the application in this repository (the `openartifact` package), the Docker image built from the `Dockerfile` and
the example deployment in `deploy/`: authentication (token and session), request hardening, the credential
store, the HTTP and Code execution nodes, the REST API and the MCP server.

Out of scope: weaknesses that need an attacker who already holds the API token (see below: they can run code by
design), your reverse proxy, TLS or host configuration, and vulnerabilities in third-party dependencies that
are not reachable through OpenArtifact (report those upstream; the weekly `pip-audit` workflow watches them).

## What the application protects

- Everything (pages, browser API, integration API, MCP server) is behind one token,
  `OPENARTIFACT_API_TOKEN`; the browser gets a signed, expiring session cookie. The application refuses to
  start with a weak token or with the default secret key
  ([ADR-016](docs/architecture/adr/016-access-protection-integration-api-and-mcp.md),
  [ADR-017](docs/architecture/adr/017-request-hardening-and-signed-sessions.md)).
- Request hardening: `Host` check, request size limits, a cross-site guard for unsafe methods, security headers
  and a Content-Security-Policy.
- Credentials are stored encrypted (AES-256-GCM, key derived from `OPENARTIFACT_SECRET_KEY`) and masked in logged
  step output. HTTP nodes block cloud-metadata addresses and, by default, private networks.
- The container runs as a non-root user; `deploy/docker-compose.yml` adds a read-only root file system, no
  capabilities and process and memory limits.

## What it does not protect

- **There is no sandbox for Code nodes.** A Code node runs `sh` or `python` as a child process with the rights of
  the application (resource limits and a timeout only). It can read the data directory, the database and the
  application's environment, and with them the token, the secret key and all stored credentials. Whoever can
  edit pipelines (every holder of the token) is effectively the operator. Set
  `OPENARTIFACT_CODE_NODES_ENABLED=false` if you do not need Code nodes.
- Without a token the application is open to everyone who can reach the port, including code execution. Always set
  `OPENARTIFACT_API_TOKEN`, and bind to a trusted interface (`127.0.0.1`) or put it behind a TLS proxy.
- There is a single shared token: no users, roles or per-user audit trail. The application serves plain HTTP; TLS
  and rate limiting are the proxy's job.
- Changing `OPENARTIFACT_SECRET_KEY` makes stored credentials unreadable; back up the key with the database.
- Output of executions (HTTP responses, Code output) is untrusted data; do not feed it to other systems as instructions.
