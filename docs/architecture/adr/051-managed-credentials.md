# ADR-051: Managed credentials: internal tokens and external secrets under one service

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Extends:** [ADR-024](024-credential-store.md), [ADR-043](043-single-sign-on-oidc.md)  
**Implemented in:** migration 0040; `models/credentials.py`, `credentials/types.py`, `tokens.py`, `service.py`, `schemas.py`, `testing.py`, `credentials/store.py` (switched-off and stale-test handling), `api/credentials.py`, `security.py` (`managed_token_name`), `templates/credentials.html`, `static/js/credentials/`, `css/credentials.css`  
**Affected chapters:** guide [credentials](../../guides/credentials.md), arc42 [08.06](../arc42/08-cross-cutting-concepts/08.06-credential-store.md)

## 1. Context

There was one API token (environment) and a secret store without a UI, types, state or audit. The task asked for
central management of tokens OpenArtifact makes and values users give, without breaking `${secret:NAME}`.

## 2. Decision

- **One `CredentialService`**, two lifecycles, one registry of **types** (`credentials/types.py`: id, label, category,
  fields, `testable`, `consumers`). A type describes the mechanism, not the node.
- **Tables** (conventions of the repo: UUID string ids, naive UTC datetimes, NOCASE names): `credentials` (common
  metadata, `backend` + `backend_ref`), `internal_credentials` + `internal_tokens` (lifecycle, hashes, one row per token so
  a rotation keeps history), `external_credentials` (non-secret settings, last test), `credential_events` (audit, no
  foreign key so it outlives the credential). No nullable fields that only one category uses.
- **Internal tokens**: `oa_<12 hex>_<256-bit secret>`; SHA-256 of the whole token is stored, compared in constant time
  by public id. Not bcrypt/Argon2: the secret is high-entropy random, so a slow hash adds latency per request and no
  protection; it also does not depend on the secret key, so changing that key does not end the tokens. Shown once,
  never logged. Rotation sets `valid_until` on existing tokens (grace period); revocation is final; disable is reversible.
- **Authentication**: `OPENARTIFACT_API_TOKEN` is checked first and unchanged; only if it does not match, and the
  presented bearer has the shape of a managed token, the database is asked (`AccessGate`, `require_api_token`,
  `TokenProtected`). Scopes: API token → api + mcp, MCP token → mcp. Cookie and SSO untouched. Without a configured
  environment token the application stays closed to managed tokens too (nothing to create them with).
- **External values stay in the `SecretStore`** (encryption unchanged); a small `SecretBackend` protocol is the seam for
  another backend later. The credential name is the secret name, so every existing reference works; unknown secrets are
  adopted as *Generic API key* on migration and on first listing. `SecretStore.resolve` refuses a switched-off credential;
  internal credentials have no secret row and so can never be resolved.
- **Tests** run a real request for GitHub, OpenRouter, an OpenAI-compatible endpoint and PostgreSQL; other types have none.

## 3. Deviations from the research documents

- No `credential_audit` table with hash chains; a plain event table. No hash-before-encrypt layer: internal tokens are
  never encrypted (nothing to decrypt), external values use the existing encryption.
- `oa_` prefix kept; the token carries a public id instead of looking up by hash.
- "Used by" covers nodes and LLM providers only; MCP tool servers and agent tools are not tracked.
- No credential picker with type filtering in the inspectors (existing `${secret:}` suggestions stay).

## 4. Consequences

Revocation is immediate (state is read per request; `last_used_at` is written at most once a minute). A managed token
needs a database read per request to the API. Deleting an external credential deletes its secret. Postgres, OpenBao and
other backends are out of scope.
