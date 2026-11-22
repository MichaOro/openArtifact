# Security

What the application protects, against whom, with which layers, where those layers end, and what you must
do when you run it. The decisions are in [ADR-016](../architecture/adr/016-access-protection-integration-api-and-mcp.md),
[ADR-017](../architecture/adr/017-request-hardening-and-signed-sessions.md),
[ADR-023](../architecture/adr/023-safety-model-of-execution-nodes.md) and
[ADR-024](../architecture/adr/024-credential-store.md); how to report a vulnerability is in
[SECURITY.md](../../SECURITY.md).

## Summary

OpenArtifact is a **single-tenant** application for one owner or one trusting team. There is one access
token and no user accounts or roles: **whoever holds the token can do everything, including running code on
the host as the application's user** (Code nodes). The layers below keep out everyone who does not hold the
token, keep a malicious web page or text from acting with the token holder's rights, and limit the damage of
mistakes and untrusted *outputs*. They are not a sandbox for hostile *editors*.

## Threat model

| Who or what | Assumed | What the application does about it |
|-------------|---------|------------------------------------|
| A network attacker without the token | Can reach the port | The access gate refuses everything but `/health`, the sign-in page and static files; `/api/v1` and `/mcp` are closed without a token |
| A web page open in the owner's browser | Can make the browser send requests, and rebind DNS | Cookie `SameSite=Strict`, cross-site guard, JSON-only writes, `Host` check |
| Content of artifacts, outputs, HTTP responses | Hostile text | Rendered with `textContent` only, Content-Security-Policy, secrets masked in results |
| A client that holds the token (script, agent) | Trusted with all rights | No further limit: it can edit actions and so run code. Give the token only to what you trust with the host |
| A node's output read by an LLM agent | May contain instructions (prompt injection) | Marked as untrusted in the API and MCP descriptions; the application cannot prevent an agent from obeying it |
| A stolen database file or backup | Can read it | Secrets are encrypted; the key is not in the database |
| A vulnerable dependency or image | Public CVEs | Weekly `pip-audit`, Dependabot, slim non-root image |

Out of scope today: multiple users with different rights, TLS (the reverse proxy does it), rate limiting
beyond a half-second delay for a wrong token, per-session revocation, an audit log, sandboxing of Code
nodes. Several of these are listed in arc42 chapter 11.

## The layers

### 1. Access gate (token, session)

- With `OPENARTIFACT_API_TOKEN` set (at least 32 characters; shorter stops the start), a middleware guards
  every path: pages, the browser's API, the event stream, Swagger and `/api/v1`. Open stay `/health`,
  `/login`, `/logout` and `/static/`. The MCP server at `/mcp` accepts only the bearer header.
- A request carries the token as `Authorization: Bearer <token>` or, for a browser, a session cookie from the
  sign-in page. The comparison is constant-time on bytes; a wrong token on the sign-in page costs half a
  second. A browser asking for a page is sent to the sign-in page; everything else gets `401`.
- The cookie holds `<issued-at>.<HMAC-SHA256>` signed with the secret key over the time and the token, never
  the token itself; valid for 30 days; `HttpOnly`, `SameSite=Strict`, `Secure` (and named `__Host-oa_session`)
  over HTTPS. Changing the token or the secret key ends every session. Logging out clears the cookie in that
  browser only; there is no server-side revocation.
- **Without a token the application is open** (pages and browser API); `/api/v1` and `/mcp` still refuse
  everything. Open mode is for a local, single-user try-out on a loopback address. In open mode **Code nodes are
  refused** (unless `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true`, a switch for local development) and
  **credentials cannot be stored**, because anyone who can reach the port could otherwise run code or read the
  secrets. The application logs a warning at start.
- Start-up refuses a token with a missing, default or shorter-than-32-character `OPENARTIFACT_SECRET_KEY`.
  The same key encrypts the credential store.

### 2. Request hardening (CSRF, Host, size, headers, CSP)

Pure ASGI middlewares around everything, including `/mcp` and Swagger (ADR-017):

- **Cross-site guard:** an unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) is refused with `403` when
  `Sec-Fetch-Site` is `cross-site` or `same-site` or `Origin` does not match `Host`; clients without those
  headers (curl, scripts, MCP) pass. An unsafe `/api/` request with a body must be `application/json`
  (`415` otherwise), which a cross-site HTML form or `no-cors` fetch cannot send.
- **Host check:** `OPENARTIFACT_ALLOWED_HOSTS`; a different `Host` gets `400` (DNS rebinding). Empty means no
  check: set it on any exposed deployment. `/health` is exempt.
- **Body limit:** `OPENARTIFACT_MAX_REQUEST_BYTES` (1 MiB), `413`; the sign-in form 4096 bytes.
- **Headers on every response:** `Content-Security-Policy` (`default-src 'self'`, `script-src 'self'`, no inline
  scripts, `frame-ancestors 'none'`, `base-uri 'none'`, `form-action 'self'`; `style-src` still allows
  inline styles because the UI sets style attributes), `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`, `Strict-Transport-Security` over HTTPS. Swagger
  (`/api/docs`) has its own policy that also allows `cdn.jsdelivr.net`.
- **Caps:** `OPENARTIFACT_MAX_CONCURRENT_RUNS` (`429`) and `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` (`503`).
- **Output handling:** everything that came from a node, an artifact or a response is shown with
  `textContent`, never as HTML.

### 3. SSRF guard (HTTP node)

The HTTP node resolves the host itself, checks every address, connects to the checked address (so DNS cannot
change the answer in between), never follows redirects and ignores proxy variables. Loopback, private,
link-local and other non-public addresses are refused unless `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS=true`;
the unspecified, multicast and cloud-metadata addresses are refused always. Details and the list are in the
[execution nodes guide](execution-nodes.md#http-node). Limit: it protects what **HTTP nodes** can reach; a
Code node is not behind it.

### 4. Credential store

Named secrets, AES-256-GCM, key derived from `OPENARTIFACT_SECRET_KEY`, referenced by name, resolved only
when a node runs and masked in results and logs. Needs a token and a key. The masking is by value and cannot
catch a deliberate leak; a node that can read a secret can always exfiltrate it. See
[Credentials](credentials.md).

**Artifact parameters** (`${card.NAME}`, defined per artifact type) are plain user data: stored as they are in
`tasks.parameters`, copied into the context of every execution, never masked. Do not put credentials in them; a
`${secret:NAME}` written into a parameter stays that text (a replaced value is never scanned again) and is not
resolved. They are validated when saved (kinds, limits, 4 KiB in total) and, like any value from outside, pasted
literally into requests (percent-encoded in a URL), never evaluated.

The **run context** (variables and the results of the nodes that ran, stored with the execution, shown in the
History and read by later nodes) is built from the results *after* secret masking, so a secret a node printed is
`***` there and in the `context.json` the next Code node gets. A secret used in an HTTP node's request does not enter
it. Context values are text from outside (responses, script output): `${node...}` and `${var...}` references paste
them literally, never evaluate them and never search them for references again (no injection into the secret
references or the URL: in a URL they are percent-encoded and never allowed in the scheme or host). The context is
never logged (only ids and sizes). A node that is allowed to read a secret can still leak it into a variable on
purpose, like anywhere else. `context.json` is a temporary file in the node's own temporary directory.

### 5. Code node hardening, and its honest limits

A Code node runs arbitrary shell or Python text from an action definition. What the application does:

- The process starts with a **clean environment**: `PATH`, `LANG`, `HOME` (a private temporary directory) and
  the secrets the node lists; no application setting, so not the token and not the secret key.
- Resource limits set before it starts (a node fails if a limit cannot be applied): CPU time, address space
  (512 MiB), processes, file size, open files, no core files. A wall-clock timeout (default 30 s, at most
  600 s) ends the whole process group. Output is capped.
- The application marks itself non-dumpable (`PR_SET_DUMPABLE=0`), so code running as the same user cannot read
  the application's environment through `/proc/<pid>/environ`. This is hardening against one way of reading
  the parent's secrets, not a boundary.
- The code runs in a private directory that is deleted afterwards; leftovers of a hard-killed application
  are cleaned up at the next start.
- A switch turns the node off: `OPENARTIFACT_CODE_NODES_ENABLED=false`.

What it does **not** do, whatever the limits say:

- It is **not a sandbox**. There is no network isolation (the code can reach every address the application
  can, including internal services and cloud metadata that HTTP nodes refuse), no file system isolation (it
  can read and write whatever the application's user can, including the SQLite database and the data volume)
  and it runs as the application's user.
- Memory and process limits are per process and per user, not a control group; a determined program can still
  use the container's resources, and a fork bomb is bounded by the container's process limit, not only by the
  node's.
- It can read the secrets it was given and anything else the user can read, and send them anywhere.

So: **whoever can edit an action definition can execute code as the application user.** That is why Code
nodes need a token, why the token is as powerful as shell access to the container, and why the container
hardening below matters.

### 6. Container hardening

The Docker image runs as a non-root user (uid 1000) with `/app` owned by root; the compose file
(`deploy/docker-compose.yml`) adds a read-only root file system with a tmpfs `/tmp` (Code nodes need it),
`cap_drop: ALL`, `no-new-privileges`, a process limit and a memory limit, and publishes the port on
`127.0.0.1` only by default. The only writable persistent place is the `/data` volume. The CI smoke test starts
the image in exactly this shape. A compromised Code node is therefore confined to the container, not to the
host, as far as the container runtime enforces it.

## What the owner of a deployment must do

1. **Set a token and a key**: `OPENARTIFACT_API_TOKEN` and `OPENARTIFACT_SECRET_KEY`, each at least 32
   characters from `openssl rand -hex 32`, different from each other. Never run an exposed instance in open
   mode.
2. **Terminate TLS** at a reverse proxy and follow the [reverse proxy guide](reverse-proxy.md): forward
   `Host` and `X-Forwarded-Proto`, set `FORWARDED_ALLOW_IPS`, `OPENARTIFACT_COOKIE_SECURE=true`, and ask the
   proxy for rate limiting if the service is reachable from the internet.
3. **Set `OPENARTIFACT_ALLOWED_HOSTS`** to your host names.
4. **Keep the bind local** (`OPENARTIFACT_BIND=127.0.0.1`, the default) unless a proxy on another host needs
   to reach it; open it to a network only with the token and TLS in place.
5. **Hand out the token as you would shell access.** Anyone or any agent with it can run code. Use separate
   instances for separate trust levels; there are no per-client tokens.
6. **Decide about Code nodes.** If nobody needs them, set `OPENARTIFACT_CODE_NODES_ENABLED=false`. If they are
   needed, keep the compose hardening (read-only, no capabilities, limits), do not mount the Docker socket or
   host paths into the container, and keep anything valuable off the machine or network the container can
   reach.
7. **Keep the private-network switch off** (`OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS=false`) unless HTTP nodes
   must call your own services.
8. **Protect the key and the data**: back up the data volume and the secret key separately; never commit
   `deploy/.env`. Changing the key makes every stored credential unreadable ([Credentials](credentials.md)).
9. **Treat outputs as untrusted** when an LLM agent reads them (MCP, API): an HTTP response or a program's
   output can contain instructions.
10. **Update.** Track releases; the repository runs a weekly dependency audit and Dependabot, and the image
    is rebuilt on release. Report vulnerabilities as described in [SECURITY.md](../../SECURITY.md).

See also the [configuration reference](configuration.md) for every setting named here.
