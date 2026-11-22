# ADR-017: Request hardening and signed, expiring sessions

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-016](016-access-protection-integration-api-and-mcp.md)  
**Amended by:** —

## 1. Title

How the application protects itself against hostile requests and how a browser's sign-in is kept.

## 2. Context

ADR-016 put the whole application behind one token. A security review of the first version found that the
protection around it was thin: the session cookie was a fixed hash that never expired, anyone who could make a
user's browser send a request (a foreign web page) could change data, a page served under any `Host` header
could be used for DNS rebinding, bodies had no size limit, the pages sent no security headers, and the number
of runs and open event streams was unbounded. The application also runs behind reverse proxies, where the
request scheme and `Host` header must stay trustworthy.

## 3. Decision Drivers

- Few moving parts: no new dependency, no session table, one process (ADR-013).
- The same protection for pages, the browser API, the integration API and the MCP server.
- Scripts, agents and MCP clients (no cookies, no `Origin`) must keep working without extra headers.
- Safe defaults with settings only to loosen them where a deployment needs it.

## 4. Considered Options

### Option A: server-side session table

Rotating, revocable sessions. Needs a table, cleanup and a migration for one shared token; rejected for now.

### Option B: signed, self-contained session value

Chosen: nothing is stored; rotating the token or the secret key ends all sessions.

### Option C: rely on the reverse proxy for hardening

The application would be unsafe when reached directly (the default published address is local, but not every
deployment has a proxy); rejected. The proxy is still asked to do TLS and, optionally, rate limiting.

## 5. Decision

### 5.1 Middlewares (`api/hardening.py`, `security.py`)

Pure ASGI wrappers, outermost first: `SecurityHeaders`, `HostCheck`, `BodyLimit`, `CrossSiteGuard`, then
`AccessGate` (`security.py`). `TokenProtected` additionally guards the mounted MCP server. Because they are
middlewares they cover every path, including `/mcp` and Swagger.

- **Host check.** `OPENARTIFACT_ALLOWED_HOSTS` (comma separated, `*.example.com` patterns); a different `Host`
  gets `400`. Empty: no check. `/health` is exempt so container health checks work.
- **Body limit.** `OPENARTIFACT_MAX_REQUEST_BYTES` (1 MiB) answers `413`, declared or streamed; the sign-in form is
  capped at 4096 bytes.
- **Cross-site guard.** An unsafe method (`POST`, `PUT`, `PATCH`, `DELETE`) is refused with `403` when
  `Sec-Fetch-Site` is `cross-site` or `same-site`, or when `Origin` does not match `Host`. Requests without those
  headers (curl, scripts, MCP clients) pass. An unsafe `/api/` request with a body must be `application/json`
  (`415` otherwise), which a cross-site form or `no-cors` fetch cannot send. The frontend sends the type on every
  request, so the browser needs no workaround.
- **Security headers** on every response: `Content-Security-Policy` (`default-src 'self'`, `script-src 'self'`,
  `style-src 'self' 'unsafe-inline'`, `img-src 'self' data:`, `connect-src 'self'`, `frame-ancestors 'none'`,
  `base-uri 'none'`, `form-action 'self'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`,
  `X-Frame-Options: DENY`, and `Strict-Transport-Security` over HTTPS. `/api/docs` has its own policy that also
  allows `cdn.jsdelivr.net` (Swagger UI). The flag `OPENARTIFACT_CSP_SCRIPT_UNSAFE_INLINE` (default `false`) is an
  opt-out only; the pages carry no inline scripts.
- **Caps.** `OPENARTIFACT_MAX_CONCURRENT_RUNS` (`429`) and `OPENARTIFACT_MAX_SSE_SUBSCRIBERS` (`503`).

### 5.2 Sessions

The cookie value is `<issued-at>.<HMAC-SHA256(secret_key, "session:<issued-at>:<token>")>`. The server accepts it
for 30 days after `issued-at` (and refuses one from the future). It never contains the token, and rotating
either the token or the secret key ends every session. The cookie is `HttpOnly`, `SameSite=Strict`, `Path=/`;
when secure it is also `Secure` and named `__Host-oa_session`. "Secure" follows `OPENARTIFACT_COOKIE_SECURE`:
`auto` (request scheme is `https`), `true`, `false`. Logout clears the cookie in the browser only; there is no
per-session revocation.

### 5.3 Start-up checks

With a token set the application refuses to start if the token is shorter than 32 characters or the secret key
is empty or the default. Without a token it starts open and logs a warning; `/api/v1` and `/mcp` stay closed.

## 6. Consequences

- A foreign page cannot make a signed-in browser change data, and a wrong `Host` cannot reach the application
  when `ALLOWED_HOSTS` is set.
- A reverse proxy must keep `Host`, send `X-Forwarded-Proto` and be listed in `FORWARDED_ALLOW_IPS`
  ([reverse proxy guide](../../guides/reverse-proxy.md)); otherwise browser writes fail with `403` or the cookie is
  not `Secure`.
- API clients must send `Content-Type: application/json` with a body.
- **Not decided or built:** rate limiting (beyond the half-second delay on a wrong token), per-session
  revocation, separate tokens per client, an audit log. These are listed in arc42 chapter 11.
- `style-src` still allows `'unsafe-inline'` because the UI sets inline style attributes.
