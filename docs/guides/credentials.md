# Credentials

The credential store keeps named secrets (API keys, tokens, passwords) encrypted in the database so that
Code and HTTP nodes can use them without the value ever being written into a pipeline. This guide covers how
to store and reference them, what protection they have, and what that protection does not cover. There is
**no user interface for credentials yet**: values are managed through the API only.

## Requirements

Secrets can be saved only when

- `OPENARTIFACT_API_TOKEN` is set (at least 32 characters), and
- `OPENARTIFACT_SECRET_KEY` is set to a value of your own, at least 32 characters
  (`openssl rand -hex 32`), not the default.

Otherwise saving answers `409` ("Set OPENARTIFACT_API_TOKEN and OPENARTIFACT_SECRET_KEY first"). The reason
is the open mode: without a token everyone who can reach the application is allowed to edit actions, so a
stored secret would be readable by all of them through any node. The same reasoning is why Code nodes are
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
- **Code node:** list the names, one per line, in the **Secrets** setting. Each is provided to the process as an
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
- The values are not protected against a Code node: it runs with the application's rights.

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

## What is not built

- A user interface for credentials (list, create, replace, delete, "used by"). The text of the Code node's
  **Secrets** setting may point to "Secrets" in the UI; that page does not exist yet.
- Per-secret permissions, an audit log of who read or changed a secret, expiry or versioning.
- A way to read a value back, deliberately.
- Credentials as a first-class feature of other node kinds: only Code and HTTP nodes use them.
