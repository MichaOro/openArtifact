# Sign in and use the API and MCP

One token protects the whole application ([ADR-016](../architecture/adr/016-access-protection-integration-api-and-mcp.md)).
This guide covers setting it, signing in with a browser, calling the integration API (`/api/v1`) with
`curl` and connecting an MCP client. Names below are placeholders: replace `<token>` with your token.

## 1. Set the token

Generate a token and a separate secret key, and put both into `deploy/.env` (or the environment of a
local run):

```bash
openssl rand -hex 32     # the token       -> OPENARTIFACT_API_TOKEN
openssl rand -hex 32     # the secret key  -> OPENARTIFACT_SECRET_KEY
```

The application refuses to start with a token shorter than 32 characters, or with a token and no
secret key of your own. Without a token the pages and the browser API are open to everyone who can
reach the port, and `/api/v1` and `/mcp` answer `401`. Restart after changing the file:

```bash
docker compose -f deploy/docker-compose.yml up -d
```

## 2. Sign in with a browser

Open the application. With a token set you are sent to `/login`; paste the token once. The session
cookie `oa_session` is `HttpOnly`, `SameSite=Strict`, valid for 30 days on the server, and contains a
signature, never the token. Over HTTPS (see [Reverse proxy](reverse-proxy.md)) it is `Secure` and named
`__Host-oa_session`. *Sign out* in the header forgets the cookie in that browser.

- A wrong token costs half a second. There is no rate limit beyond that yet.
- Changing the token or the secret key ends every session. There is no per-session revocation yet.
- Swagger UI at `/api/docs` is behind the same gate; its *Authorize* button takes the token.

## 3. Call the integration API

Scripts send the token as a bearer header. The artifacts of the board are addressed by id or number:

```bash
export OA=http://localhost:2909
export TOKEN=<token>

# the pipelines with their stages and actions (the ids to start with)
curl -s -H "Authorization: Bearer $TOKEN" $OA/api/v1/pipelines

# list artifacts
curl -s -H "Authorization: Bearer $TOKEN" $OA/api/v1/artifacts

# create one (not started); the answer carries its number
curl -s -X POST $OA/api/v1/artifacts \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"title": "Check the release notes", "body": "Compare with #3", "status": "backlog"}'

# start processing artifact #12 with the pipeline, stage and action it already has
curl -s -X POST $OA/api/v1/artifacts/12/run -H "Authorization: Bearer $TOKEN"

# or choose where to start
curl -s -X POST $OA/api/v1/artifacts/12/run \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"pipeline_id": "<id>", "stage_id": "<id>", "action_id": "<id>"}'

# how it stands, then stop it
curl -s -H "Authorization: Bearer $TOKEN" $OA/api/v1/artifacts/12/run
curl -s -X POST -H "Authorization: Bearer $TOKEN" $OA/api/v1/artifacts/12/run/stop
```

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/pipelines` | Pipelines with stages in running order and the actions of each stage |
| `GET /api/v1/artifacts`, `POST /api/v1/artifacts` | List, create (`title`, optional `body`, `status`, `parent_id`, `pipeline_id`, `stage_id`, `action_id`) |
| `GET`, `PATCH`, `DELETE /api/v1/artifacts/{ref}` | Read, change (partial), delete; `ref` is the number (`12`) or the id |
| `GET /api/v1/artifacts/{ref}/run` | State of the run: status, where it is, every stage |
| `POST /api/v1/artifacts/{ref}/run` | Start (body optional) |
| `POST /api/v1/artifacts/{ref}/run/stop` | Stop; the artifact keeps its stage and action |

Rules that scripts meet:

- **Send `Content-Type: application/json`** with every body. `curl -d` alone sends a form type and gets `415`.
- An artifact can only be started when it has a pipeline (`422 Choose a pipeline first` otherwise): give `pipeline_id` when creating it or in the start body, ids from `GET /api/v1/pipelines`.
- Creating and starting are two calls. A run started this way records `started_by: system`; the artifact records `created_by: api`.
- While a run is `running`, changing lane, order, parent or pipeline and deleting the artifact answer `409`. Starting twice also answers `409`; more active runs than `OPENARTIFACT_MAX_CONCURRENT_RUNS` answers `429`.
- Errors are `{"detail": "..."}` with the HTTP status. A request body over 1 MiB gets `413`.
- Requests that carry `Origin` or `Sec-Fetch-Site` headers (browsers) must come from the same site; plain HTTP clients send neither and pass.
- The full schema is the OpenAPI document at `/api/docs` (Swagger UI) and `/openapi.json`; both need the token.

## 4. Connect an MCP client

The MCP server answers at `/mcp` over Streamable HTTP, stateless, with the same bearer token. Point the
client at `http://localhost:2909/mcp` (or your public address) and send `Authorization: Bearer <token>`.
The configuration syntax differs per client; the common shapes are:

```bash
# Claude Code
claude mcp add --transport http openartifact http://localhost:2909/mcp \
  --header "Authorization: Bearer <token>"
```

```json
{
  "mcpServers": {
    "openartifact": {
      "type": "http",
      "url": "http://localhost:2909/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

Tools (all go through the same service as the browser and the REST API):

| Tool | Purpose |
|------|---------|
| `list_pipelines` | Pipelines with stages and actions |
| `list_artifacts(lane?)` | Artifacts in board order, optionally one lane (`backlog`, `in_progress`, `done`) |
| `get_artifact(artifact)` | One artifact by number (`12` or `#12`) or id |
| `create_artifact(title, body?, lane?, parent?, pipeline?, stage?, action?)` | Create; pipeline, stage and action by name, parent by number; not started |
| `update_artifact(artifact, title?, body?, lane?)` | Change title, body or lane |
| `start_processing(artifact, pipeline?, stage?, action?)` | Start |
| `stop_processing(artifact)` | Stop |
| `get_processing_status(artifact)` | Run state, or `never processed` |

A refused call returns the reason as the tool's error text. An artifact created through MCP records
`created_by: mcp`.

## Behind a proxy or on the network

The Host check, cookie flags and body limit are described in [Reverse proxy](reverse-proxy.md) and the
[configuration reference](configuration.md). Do not publish the port to the network without a token.
