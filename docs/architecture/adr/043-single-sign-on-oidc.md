# ADR-043: Single sign-on through OpenID Connect

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-017](017-request-hardening-and-signed-sessions.md) (the access gate)  
**Implemented in:** `oidc.py` (`Oidc`), `web/routes.py` (`/login/sso`, `/login/sso/callback`), `security.py` (`OPEN_PATHS`), `config.py` (`oidc_*`, `public_url`, `security_problems`), `templates/login.html`; `pyjwt[crypto]`  
**Affected chapters:** guides [security](../../guides/security.md), [configuration](../../guides/configuration.md), [reverse proxy](../../guides/reverse-proxy.md)

## 1. Context

The only way in is the API token (ADR-017): a sign-in page that checks it and sets a signed cookie. An owner who runs
an identity provider (Authelia, later perhaps Microsoft, Google or GitHub) wants to sign in with it. The application has
no users: whoever is in may do everything, Code nodes and secrets included.

## 2. Decision

- **OpenID Connect, authorization code flow with PKCE (S256)**, state and nonce, a confidential client (the secret stays
  on the server). Provider-neutral: the issuer address is all it needs (`/.well-known/openid-configuration`), so any
  OIDC provider works; Authelia is the first one tried.
- **The token stays.** SSO is a second way to the same cookie; scripts and MCP keep the bearer token. SSO needs
  `OPENARTIFACT_API_TOKEN` (it is what closes the application) and is refused at start otherwise.
- **Who may come in is the operator's list**, not the provider's word alone: `OIDC_ALLOWED_EMAILS` (verified addresses),
  `OIDC_ALLOWED_USERS` (`preferred_username` or `sub`), `OIDC_ALLOWED_GROUPS`; one match is enough. Without any list the
  start is refused, because everyone who is in may do everything.
- **What is checked:** the ID token's signature against the provider's published keys with **asymmetric algorithms
  only** (no `none`, no `HS*`), issuer, audience, expiry and the nonce of this sign-in; the signed state cookie (10
  minutes, `SameSite=Lax` because the provider sends the browser back) must match the `state` and is used once. Claims the
  ID token lacks (Authelia keeps them in userinfo) are read from the userinfo endpoint and merged only when its `sub` is
  the token's.
- **The discovery document is the provider's word about its own addresses:** token endpoint, key set and userinfo
  endpoint must be on the issuer's origin, so a document cannot point the client secret elsewhere. No redirects are
  followed there.
- **A refusal leaves nothing:** no session cookie, the state cookie is deleted, the provider's error text is never shown.
- The session is the existing cookie (`SameSite=Strict`, 30 days, signed over the token and the key).

## 3. Consequences

- Anyone the provider signs in *and* the list names has the full rights of the token. There are still no users, no
  roles and no sign-out at the provider (the logout clears this browser's cookie only).
- Further providers (Microsoft, Google, GitHub) would be more entries of the same flow; GitHub is OAuth, not OIDC, and
  would need its own small step. Not built yet.
- The client secret is an operator setting in the environment (like the API token), not an entry of the secret store.
