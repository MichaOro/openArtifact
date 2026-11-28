# Credentials

The credential store keeps named secrets (API keys, tokens, passwords) encrypted in the database so that
Code and HTTP nodes can use them without the value ever being written into a pipeline. This guide covers how
to store and reference them, what protection they have, and what that protection does not cover. Named secrets
have no page of their own: they are stored through the API (and the provider dialog stores an API key); the managed
credentials (access tokens and credentials for other systems) have the page *Settings → Credentials*, see
[Managed credentials](#managed-credentials-the-credentials-page).

## Requirements

Secrets can be saved only when

- `OPENARTIFACT_API_TOKEN` is set (at least 32 characters), and
- `OPENARTIFACT_SECRET_KEY` is set to a value of your own, at least 32 characters
  (`openssl rand -hex 32`), not the default.

Otherwise saving answers `409` ("Set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY first"). The reason
is the open mode: without a token everyone who can reach the application is allowed to edit actions, so a
stored secret would be readable by all of them through any node. The same reasoning is why Execute Command nodes are
refused in open mode ([Security](security.md)).

## Store a secret

A name is capital letters, digits and underscores, starting with a letter, at most 64 characters
(`API_TOKEN`, `DEPLOY_KEY_2`). A value is 1 byte to 8 KiB of text without NUL characters. Use the browser API
or the integration API (both take the bearer token):

```bash
# create or replace (201 when created, 200 when replaced); the answer never contains the value
curl -X PUT "$BASE/api/v1/secrets/API_TOKEN" \
     -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
     -d '{"value": "the-secret-value"}'

curl "$BASE/api/v1/secrets" -H "Authorization: Bearer $TOKEN"          # names and dates
curl -X DELETE "$BASE/api/v1/secrets/API_TOKEN" -H "Authorization: Bearer $TOKEN"   # 204
```

The browser API has the same routes under `/api/secrets` plus `GET /api/secrets/{name}/uses`, which lists the
Code and HTTP nodes that refer to a secret and the pipelines that call their actions. Look at it before you
delete a secret: nodes that still refer to a deleted secret fail with "Secret NAME does not exist". The MCP
server can list the names (`list_secrets`) but not read or write values. There is no way to read a value back
through any interface.

## Use a secret

A node never holds a value, only a name.

- **HTTP node:** write `${secret:NAME}` in the URL's path or query (the value is percent-encoded there), in a
  header value or in the body: `Authorization: Bearer ${secret:API_TOKEN}`. A reference in the scheme or host
  of the URL is refused. A malformed reference (a name that is not capitals, digits and underscores) is
  refused when you save the setting.
- **Execute Command node:** list the names, one per line, in the **Secrets** setting. Each is provided to the process as an
  environment variable of that name (`$API_TOKEN` in shell, `os.environ["API_TOKEN"]` in Python). Up to 32
  per node. The names `PATH`, `HOME`, `LANG` and `OPENARTIFACT_*` are reserved. `${secret:NAME}` is not
  substituted inside the code text: the code is stored and shown in plain text.
- **LLM provider:** a provider names the secret that holds its API key (*Settings › LLM providers*, or
  `secret_name` in the API). An Agent node gets the key from there when it runs; it cannot be mapped into a prompt
  or an input. The provider dialog can store the key for you. See [Agents and LLM providers](agents.md).
- A missing secret fails the node with "Secret NAME does not exist", before anything runs.

Values are looked up and decrypted by the executor at the moment the node runs. A frozen snapshot of a
pipeline, an event, a log line or the API never contains a value, only the names in the nodes' settings.

## Masking

Everything a node returns (`output`, `reason`, `data`) and every log line written while it runs is passed
through masking: each used value is replaced by `***`, in the forms a value usually takes on its way out: as it
is, percent-encoded (`%20` and `+` variants), Base64 (standard and URL-safe, with and without padding) and
JSON-escaped. This is why a server that echoes your header back shows `Bearer ***` in the step's output.

Masking is a safety net, not a guarantee. It works by value, so it **cannot** find a secret that was
transformed in another way: hashed, reversed, split over several lines, printed one character at a time,
encrypted. A node that is allowed to read a secret can always leak it on purpose, by printing it differently
or by sending it to a host it controls. The same goes for very short values that happen to appear in other
text (they are masked wherever they appear). Treat "can edit actions" as "can read every secret that is
stored", and give the rights accordingly.

Separately, the log filter masks the configured API token and secret key wherever they appear (values of at
least 8 characters) and any value that follows a secret-looking name.

## How they are protected at rest

- Values are encrypted with AES-256-GCM. The encryption key is derived with HKDF-SHA256 from
  `OPENARTIFACT_SECRET_KEY` with a fixed purpose string, so it is a different key from the one that signs the
  session cookie. Each value has a fresh random 96-bit nonce, and the secret's **name** is bound in as
  associated data, so a ciphertext copied to another row (another name) does not decrypt.
- The `secrets` table holds the name, the encrypted blob and two timestamps.
- Whoever has the secret key **and** the database can read every secret. The key is not in the database, so a
  stolen database file or backup alone is not enough, and a stolen key alone is not enough either. Keep the key
  out of the backup of the data volume (the operations guide describes the backup of the database).
- The process holds the derived key and the decrypted values in memory while it uses them.
- The values are not protected against an Execute Command node: it runs with the application's rights.

## Key rotation and what changes break

There is **no re-encryption and no key rotation**. If you change `OPENARTIFACT_SECRET_KEY`:

- every stored secret becomes unreadable: nodes that use one fail with "Secret NAME cannot be read: the secret
  key changed";
- every browser session ends (the key also signs the cookie).

To rotate, set the new key, restart, then store every secret again (`PUT` each name; the old rows are
replaced). Do it in one maintenance step; between the two moments the nodes fail. Rotating only the API token
signs browsers out but leaves the secrets intact. Restoring a database backup together with a *different*
key has the same effect as a rotation. Losing the key loses the secrets: there is no recovery, only entering
them again.

## Managed credentials (the Credentials page)

*Settings → Credentials* (`/settings/credentials`, API `/api/credentials`, ADR-051) manages two kinds:

- **Internal**: access tokens OpenArtifact makes, of the types *API access token* (opens the browser API, `/api/v1` and
  `/mcp`) and *MCP access token* (opens `/mcp` only). A token looks like `oa_<id>_<secret>`, is **shown once**, when it
  is made or rotated, and only its SHA-256 hash is kept (the 12-character id is the lookup key). A credential can expire,
  be switched off and on, be **revoked** for good, or be **rotated**: the old token works for a grace period (default
  1 hour, `OPENARTIFACT_CREDENTIALS_ROTATION_GRACE_SECONDS`, or per rotation) and then fails. Each request is checked
  against the stored state, so a revoked, disabled or expired token fails on its next request. `OPENARTIFACT_API_TOKEN`
  stays the administrator's token and the session cookie and SSO are unchanged; managed tokens are an addition for
  people and programs that should be cut off independently. Internal credentials are never in the secret store and can
  never be used as `${secret:NAME}`.
- **External**: values for other systems, of the types *GitHub access token*, *OpenRouter API key*,
  *OpenAI-compatible API key*, *PostgreSQL connection*, *Bearer token*, *MCP authentication* and *Generic API key*. The
  value is stored by the credential store exactly as before (the credential's name is the secret's name), so every
  `${secret:NAME}`, Execute Command node setting and provider keeps working; secrets made with the older API appear as *Generic
  API key* credentials. **Test connection** makes a real request (GitHub `/user`, OpenRouter `/key`, the endpoint's
  model list, `SELECT 1`) and records the time and the outcome; types without a meaningful test (bearer, MCP, generic)
  have none and are never shown as tested. A changed value clears the last test. A switched-off credential is refused to
  nodes and providers ("Secret NAME is switched off"). *Used by* counts the nodes and LLM providers that refer to it
  (not other places such as an MCP server's own configuration); deleting asks first and names them.

The name of an internal credential is also **who the token is**: a comment written through the API or MCP with it carries that name as
author (see [ADR-055](../architecture/adr/055-comments-on-artifacts.md)), so give every agent or script its own token.

Every change (created, rotated, revoked, enabled, disabled, tested, deleted) leaves an entry without any value or hash in
`GET /api/credentials/{id}/events`.

## What is not built

- A picker in the node inspectors that offers only credentials of a compatible type: they still type
  `${secret:NAME}` with the existing suggestions.
- Per-secret permissions, a log of who *read* a secret, expiry or versioning of external values, usage counters of
  internal tokens beyond *last used*.
- A way to read a value back, deliberately.
- Credentials as a first-class feature of other node kinds: only Code and HTTP nodes use them.
