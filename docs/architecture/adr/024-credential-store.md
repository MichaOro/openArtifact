# ADR-024: Credential store

**Status:** Accepted  
**Date:** 2026-11-22  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-008](008-security-operations.md) §5, [ADR-017](017-request-hardening-and-signed-sessions.md) §5.2  
**Amended by:** —  
**Implemented in:** migration 0022 (table `secrets`); `secret_crypto.py`, `secret_store.py`, `secret_refs.py`, `api/secrets.py`, `/api/v1/secrets`, MCP tool `list_secrets`  
**Affected chapters:** [05.06](../arc42/05-building-block-view/05.06-execution-engine-internals.md), [06.08](../arc42/06-runtime-view/06.08-credential-resolution.md), [08.06](../arc42/08-cross-cutting-concepts/08.06-credential-store.md); guide [credentials](../../guides/credentials.md)

## 1. Title

How execution nodes get credentials without putting them into pipelines, snapshots, logs or results.

## 2. Context

An HTTP node needs a token, a Code node a password. ADR-008 allowed secrets only as environment variables of the
application and deferred a secret manager. Writing a credential into a node would copy it into every snapshot of
every execution (ADR-025) and into exports of the database.

## 3. Decision

- **Storage.** Table `secrets` (`name`, encrypted `value`, timestamps). A name is capitals, digits and
  underscores (`[A-Z][A-Z0-9_]{0,63}`). The value is encrypted with AES-256-GCM; the key is HKDF-SHA256 of
  `OPENARTIFACT_SECRET_KEY` with its own `info` string, so it differs from the key that signs sessions. Each value
  has a random 96-bit nonce and the name as associated data, so a ciphertext moved to another name does not decrypt.
- **Use.** Nodes hold names only. An HTTP node writes `${secret:NAME}` in its URL, headers or body (percent-encoded
  in the URL); a Code node lists names in its `secrets` setting and receives them as environment variables. The
  executor resolves the values just before running (`resolve`); snapshots and settings never hold a value.
- **Masking.** Output, reason, data and log lines of a node are searched for every used value in the forms it
  usually takes (as is, percent-encoded, Base64, JSON-escaped) and replaced by `***`.
- **Who may store.** Only when an API token is set and the secret key is neither empty nor the default, and at
  least 32 characters (ADR-023). Otherwise saving is refused with `409`.
- **Management.** API only: `/api/secrets` and `/api/v1/secrets` (list names, create or replace, delete; the
  browser API also has `GET /api/secrets/{name}/uses`). A value is never returned. MCP can list names. There is no
  user interface for credentials yet.

## 4. Consequences

- A database backup holds credentials only in encrypted form; reading them needs the secret key.
- The secret key is now also the credential key: changing it makes every stored secret unreadable, and there is
  no re-encryption and no key rotation. Rotating the token alone ends sessions only (ADR-017 §5.2).
- Masking is best effort: a Code node can deliberately transform a value into a form that is not recognised, and
  it runs with the application's rights (ADR-023).
- ADR-008's "no secrets in the database" no longer holds; its "file permissions 600" for the database file is still
  not done by the application.
