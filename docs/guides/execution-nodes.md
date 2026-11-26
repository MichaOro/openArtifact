# Execution nodes: Code, HTTP, GitHub, Postgres, Artifact, If, Switch and Edit Fields

The nodes that do work inside an action definition (see [Concepts](concepts.md)). You add them in the
action editor with the "+" menu and set them in the node's settings (a double click on the node opens them in an overlay); every setting is saved as you type or leave
the field. This guide is the reference for what each node does, what it returns, what limits it has and how a
failure is routed. Read [Security](security.md) before you let anyone other than yourself edit actions: a Code
node runs arbitrary code with the application's rights.

Settings of the application that affect the nodes are in the [configuration reference](configuration.md).

The **Agent node** (asks a language model for a centrally managed agent, with tools attached below it if you want) has
a guide of its own:
[Agents and LLM providers](agents.md). It is an execution node like the ones here: *On Pass* / *On Fail*,
*If the node fails*, a result in the run context (`${node.NAME.output}`, `${node.NAME.data.model}`,
`${node.NAME.data.usage.total_tokens}`).

An output longer than a step keeps (256 Ki characters) is cut visibly for every kind: the text ends with
`[output truncated]`, the data has `output_truncated: true` and the reason says so.

## How an action definition runs

When a run reaches an action that is linked to a definition, the engine walks the definition:

1. It starts at the **trigger** and records a step for it.
2. It follows the connection leaving the current node. A node with an executor (timer, Code, HTTP, GitHub, Postgres, Artifact, If, Switch) runs; the
   engine records its result as a step and leaves by the port that matches the outcome: **On Pass** or **On Fail**
   for Code and HTTP, **Next** for the timer (which always passes), the branch the node chose for If and Switch.
3. Reaching the **Output** by its **On Pass** connector makes the action pass; reaching it by **On Fail**
   makes the action fail. The Output's On Fail connector exists only when its switch is on.
4. If a leaving port has no connection (a dead end), the action fails.
5. Actions and the nodes of their definitions count against one limit of 1000 steps per run; a run that
   exceeds it (a loop through On Error that never ends) fails with "The pipeline does not come to an end".

Back in the pipeline, a **passed** action leaves by its **On Pass** connection and a **failed** one by its
**On Error** connection. If the connection that is needed does not exist, the run fails with a note naming
the action ("X failed" or "X has no On Pass connection"). So a failure path is something you draw:

- *Retry or recover:* connect On Error of the action to an earlier action of the same stage (a loop) or to a
  different action that cleans up.
- *Notify and fail:* inside the definition, connect a Code or HTTP node's **On Fail** to a second HTTP node
  that posts to a chat webhook, then to the Output's **On Fail**.
- *Tolerate a failure:* connect On Error to the end of the stage; the run goes on as if the action had passed.

Stopping a run cancels the node that is running: an Execute Command node's process group is killed, an HTTP request is
abandoned.

## Results

Every executed node leaves one step (visible in the History tab and the flow view, and returned by the API under the
execution) and, in the run context, one entry with the same **core**, whatever its kind (the result contract, ADR-072):

| Field | Type | Meaning |
|-------|------|---------|
| `success` | `true` / `false` | the node succeeded; the engine sets it from `outcome`, a kind does not have to |
| `outcome` | `pass` / `fail` | the port it leaves by (a node that chooses its branch, If and Switch, passes when it could decide) |
| `reason` | text or `null` | why it failed (or a note on a pass); a sentence for people, cut at 1000 characters |
| `output` | text | what the node produced as text; at most 4 KiB in the context, the step has all |
| `data` | object or `null` | the extras of the kind (the table below) |
| `attempts` | whole number | how many tries it took: 1, or more with *Retry on fail* ([below](#retry-on-fail)) |
| `duration_ms` | whole number | wall time of the step in milliseconds, all tries and the waits between them |
| `exit_code` | number or `null` | only where a kind has one (Code) |

`success` reads as the text `true` or `false` in a reference, so a condition on it is `${(HTTP: ping).success}` *is true*; a
context stored before the contract has no `success` or `attempts`: they are derived from `outcome` and 1. Nothing was taken
away: `outcome`, `exit_code`, `reason`, `output` and `data.key` mean what they always meant.

What each kind puts in `output` and `data` (the rest of the core is the same for all):

| Kind | `output` | `data` |
|------|----------|--------|
| Timer | none | none |
| Code | stdout, then `[stderr]` and stderr; `exit_code` is the process exit code (negative: ended by a signal) | an object the code reported, at most 16384 characters of JSON |
| HTTP | the response body | `status`, `content_type`, `truncated` |
| Postgres, SQLite | the rows as JSON | `rows`, `columns`, `row_count`, `truncated` |
| GitHub | the answer as JSON (a list: the items) | the object, or `items`, `count`, `truncated`; a diff: `diff`, `truncated` |
| Artifact | what the node did, or the comments | `id` (comment added), or `comments`, `count`, `left_out` |
| Build Context | the package: one section per source ([below](#build-context-node)); the context keeps all of it, up to the node's size limit | `included`, `omitted`, `size_bytes`, `limit_bytes`, `approx_tokens` |
| Hand Over Tool | the document as JSON (stored by the agent node, not run as a step; [Agents](agents.md#hand-over-tool)) | the document's fields, as the tool node's fields define them |
| Edit Fields (Set) | none | `fields` (the names set) |
| If | the port chosen | `condition` (`true`, `false`, `null` when undecidable), `rows` |
| Switch | the port chosen | `value`, `matched`, `cases` |
| Agent | the final answer; with an [answer format](agents.md#2-write-and-publish-an-agent) the checked document as JSON | `model`, `usage`, `finish_reason`, `iterations`, ... and, with an answer format, its fields (`passed`, ...), `repaired`, `answer_calls` ([Agents](agents.md)) |

A `reason` is a sentence for people. Output is text: anything the code prints or the server answers ends up in it (and in
the history, and in whatever agent reads it), so treat it as untrusted. Used secrets are masked in all of these
([Credentials](credentials.md)). Guards read the step as `v_guard_steps` (`success`, `attempts` and the rest, below).

## The run context and references

Every execution has a **context**: the variables Execute Command nodes set and the latest result of every node that ran. A later
node can use it, however many steps earlier the value was produced. It is stored with the execution, so it survives a
server restart and is shown in the History tab ([Execution history](execution-history.md)).

```json
{"vars": {"user": "bob"},
 "card": {"urgency": "high", "tier": "gold"},
 "nodes": {"Fetch_user": {"name": "Fetch user", "kind": "http", "success": true, "outcome": "pass", "port": "pass",
                          "exit_code": null, "output": "{\"id\": 7}", "reason": null,
                          "data": {"status": 200, "content_type": "application/json", "truncated": false},
                          "attempts": 1, "duration_ms": 212, "at": "2026-11-22T10:00:00.000Z"}}}
```

**References.** In an HTTP node's URL, headers and body:

| Reference | Value |
|-----------|-------|
| `${(Node name).output}` | the node's output (a node keeps at most 4 KiB of it in the context; the step has all) |
| `${(Node name).success}` | `true` or `false`: did the node succeed (use it with *is true* / *is false*) |
| `${(Node name).exit_code}`, `.outcome`, `.reason` | exit code, `pass` or `fail`, the reason (`null` text when there is none) |
| `${(Node name).attempts}`, `.duration_ms` | the number of tries, the milliseconds it took |
| `${(Node name).data}` | the node's data as compact JSON |
| `${(Node name).data.key.sub.0}` | one value in the data; numbers index lists |
| `${node:ID.output}`, `${node:ID.data.key}` ... | the same fields of a node named by its **id** (ADR-082): the editor inserts this form and shows the name; a rename changes nothing, and two nodes of one name are told apart |
| `${input.name}` | an input of the action that is running (ADR-083): declared on its Trigger, given by the node that runs it |
| `${var.name}` | a variable |
| `${card.name}` | a parameter of the artifact (see [below](#card-parameters-card-the-artifact-fields)) |

A node is best written by its **id**, `${node:<uuid>.output}`: the reference list of the editor inserts it and shows the node's name (`(Fetch).output`),
and a line under the field says which nodes the ids are now (`Reads: …`). The same action definition placed more than once in a pipeline is shown as
`Name #1`, `#2`, `#3` (the lowest free number; the number appears only while it is placed more than once) and each placement has its own id, so each
has its own result. The name forms below keep working while the name is unique.

A node is written by its name **as the editor shows it**, in parentheses: `${(Code: hello).output}`. The name may hold
blanks and punctuation, only `(`, `)` and `}` are not possible in it. The older spelling `${node.NAME.output}` stays valid:
`NAME` is the node's name as the editor shows it, with every character outside letters, digits, `_` and `-`
written as `_` (`Fetch user` is `Fetch_user`). Text is inserted as it is; numbers, lists and objects as compact
JSON. In the URL the inserted text is percent-encoded; a reference is allowed in the path and the query, never in
the scheme or the host (refused already when you save). There is no expression language: no arithmetic, no
conditions. Inserted values are text, never evaluated, and never searched for references again, so a response that
contains `${var.x}` or `${secret:X}` stays that text. Context references are replaced together with
`${secret:NAME}`.

**Failure.** A reference that cannot be resolved fails the node, and the reason names it, for example
`${node.Fetch_user.data.id}: the data of node "Fetch_user" has no 'id'`, `${var.token}: variable 'token' is not set`,
`${node.Later.output}: node "Later" has not run yet`, `... no node is named "X"`. Nothing is replaced by an empty
string.

**Names are not unique.** A reference resolves to the node of the frozen pipeline that has that name. If two
different nodes have it, the reference fails with `ambiguous node name "Same": "Same" (code) in action "A" and "Same"
(http) in action "B"; rename one of them`, so nothing is picked silently; the default names (`Code`, `HTTP request`)
are ambiguous as soon as two nodes use them, so rename the ones you refer to. A node that ran several times (the
same action in two stages) keeps its **latest** result. When you save an HTTP node, the answer carries `warnings`:
ambiguous names inside the action, names no action has, malformed references. The node is saved anyway; at run time
these are errors.

### Card parameters (`card`): the artifact fields

Every artifact is a source of its run (ADR-064). When the execution starts, `card` holds a **copy** of:

- the built-in values `${card.id}`, `${card.number}`, `${card.title}` and `${card.body}`, and `${card.text}`, which is
  derived (`#<number> <title>`, a blank line, the body); `${card.body}` holds the body with its own `${card.x}` already filled in; an agent input from the artifact takes its part from the card
  by itself (see [agents](agents.md)), the node maps nothing for it;
- every artifact field ([concepts](concepts.md#terms), ADR-044) with the artifact's value, else the field's default,
  else nothing.

A custom field cannot be named like a built-in (`title`, `body`, `number`, `id`, `text`; refused with 422, and existing
clashes were renamed to `title_field` and so on by migration 0051, also in the references of node settings).
`${card.urgency}` is replaced like `${var.urgency}`: text as it is, numbers and yes/no as JSON (`3`, `true`), a choice as its
value, percent-encoded in a URL. A field that is defined but empty on this card is empty text. The name is the field's
name (`[a-z][a-z0-9_]{0,31}`), not its label. A name that does not exist is a warning when the node is saved (it lists
the known names) and fails the node in the run: `${card.x}: the artifact has no field "x" (it has: ...)`; the same holds
for a field that was renamed or deleted after the node mapped it. Execute Command nodes read `card` in `context.json`. The card
of a run may hold at most 40 KiB; a larger one is refused when the run starts (never cut). Changing the artifact later
never changes an execution that exists, and the History shows what that run saw.

The editor offers all of it first in the picker, in the group **Card of this run**, and shows what a text becomes with a
real card: *Preview with card* at the top of the settings (remembered per browser, `?card=` in the address) puts the
resolved text under every field that takes references. Only `${card...}` is resolved there; nodes and variables stay
placeholders and secrets are never shown.
Field values are plain data: do not put secrets in them ([Security](security.md)).

**Setting variables.** An Execute Command node ends with a result line (see the *Result protocol* below). Add `"vars"`:

```python
print(json.dumps({"ok": True, "vars": {"user": "bob", "limit": 5}}))
```

Names are lowercase letters, digits and `_`, starting with a letter (at most 64 characters, at most 100 per
node); values are JSON (text, number, true/false, null, list, object, nested at most 3 levels). An invalid name or
value fails the node with `Invalid vars: ...`. Only a passing node sets variables. The optional **Sets variables** setting (one name per line) documents which
variables the code sets and feeds the editor's suggestions; if it is not empty and the node passed, the step's reason
notes a difference (`undeclared variable 'x'`, `declared variable 'y' was not set`). It is a hint: the node still passes. The line must be short enough to
survive the 8 KiB tail of the output the protocol is read from. All variables together may use 32 KiB; a node that
would exceed it fails. HTTP nodes do not set variables (their parsed body is not stored; use `data` and the
`output` of the node, or an Execute Command node that reads `context.json` and sets the variable).

**Execute Command nodes read `context.json`.** The text of an Execute Command node is never interpolated. The file `context.json` in the
node's working directory holds the whole context, written (read-only) just before the script starts:
`json.load(open("context.json"))["vars"]["user"]`. It is a temporary file in the node's own temporary directory
(`/tmp`, usually memory) and is removed with it when the node ends; nothing about it is written to disk
permanently. Changes the script makes to it are not read back.

**Limits and safety.** The whole context is at most 64 KiB (when it grows, the oldest node results lose their
output, then their data, then are dropped; variables are never dropped). It is built from the masked results, so
a secret a node printed is `***` in it and in `context.json`. The values are text from outside (responses, script
output), so treat them as untrusted, like any output.

## Inputs and outputs of an action

An action definition can say what it needs and what it gives (ADR-083). Both are optional: a definition that declares nothing runs as before.

- **Inputs** are declared in the window of its **Trigger**: a list of fields with a name, a type (text, number, true or false, choice, list), *required*
  and a default. Inside the definition a node reads an input as `${input.name}` (an optional input with no value reads as empty text).
- **Outputs** are declared in the window of its **Output** node: a name, a type and a value (a text, or references such as `${(Fetch).output}` or
  `${input.who}`). When the action ends on *On Pass* the values are worked out and become the `data` of the node that ran it; a value that cannot be
  worked out fails the action and names the output.
- **The node that runs the action** (in a pipeline) shows one row per declared input and takes a text, a card field (`${card.title}`) or the output of an
  earlier node (`${node:<id>.data.greeting}`; pick it from the list). A row left empty uses the default of the input; a required one without a value
  fails the run: `Greet: input 'who' is required and has no value`. A value that does not fit the type fails with the input and the value.
- **Outputs are read by the id of that node.** The same definition placed twice, or three times, gives each placement its own outputs, so the third
  action can take the outputs of the first and the second.

The result of a node that ran a definition with a contract carries the result contract (`success`, `outcome`, `reason`, `attempts`); a node that ran a definition
without one has no result of its own. A called pipeline works the same way: it declares its inputs on its Trigger and its outputs on its **Complete**, the pipeline node that calls it
maps the inputs, and the outputs are the `data` of that pipeline node.

## Execute Command node

Runs shell or Python text stored in the node. It was called *Code* before ADR-075: the kind is still `code` in stored actions and in the
API (old actions run unchanged), only the name people read changed, because it is not a sandbox but a command run as the application's user.
**It is off by default**: set `OPENARTIFACT_CODE_NODES_ENABLED=true` to switch it on. While it is off a node fails with a message that names the
switch, the editor marks the kind *Switched off* and says so in the node's window, and existing nodes stay editable. A real Code node with a
sandbox is a later card (#133).

| Setting | Values | Default |
|---------|--------|---------|
| Language | `sh` or `python` | `sh` |
| Code | up to 20000 characters | empty (an empty program fails with "The code is empty") |
| Secrets | one secret name per line, up to 32 | none |
| Timeout (seconds) | 1 to 600 | 30 |
| Output limit | optional: a size (B, KiB, MiB) from 1 KiB to 64 MiB; never above `OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES` | the limit of the instance (64 KiB) |

**How it runs.** The code is written to a new private directory (mode 0700) under the system temporary
directory and run as a child process of the application: `sh script.sh`, or the application's own Python
interpreter in isolated mode (`python -I script.py`: no `PYTHON*` variables, no user site directory). The
working directory and `HOME` are that directory, which is deleted afterwards. Standard input is empty. The
child leads its own process group, so a timeout or a stopped run ends everything it started.

The shell is the image's `sh`; the image is a slim Python image, so do not rely on tools such as `curl` or
`git` being present. Python's standard library is.

**Environment.** Exactly `PATH`, `LANG`, `HOME`, the secrets the node lists (each as a variable of its name)
and one random marker variable `OPENARTIFACT_CODE_RUN` that the application uses to clean up leftovers. No
application setting reaches the process: not the API token, not the secret key. The names `PATH`, `HOME`,
`LANG` and anything starting with `OPENARTIFACT_` cannot be used as secret names in a node.

**Result protocol.** The exit code decides: `0` passes, anything else fails (`reason`: "Exit code N"). The
code may say more by printing, as the **last non-empty line of standard output**, one JSON object with a
boolean `ok`:

```json
{"ok": false, "reason": "nothing to do", "data": {"n": 3}}
```

`ok: false` fails the node even with exit code 0; `reason` (a string) becomes the reason; `data` (an
object, at most 16384 characters when serialised) is stored on the step, for a pass as well as a fail.
Anything else on that last line (not JSON, no boolean `ok`) is just output. `vars` sets variables in the
[run context](#the-run-context-and-references).

**Output caps.** Standard output and standard error are each read up to `OPENARTIFACT_CODE_OUTPUT_LIMIT_BYTES`
(64 KiB); beyond that `[output truncated]` is appended, but the last 8 KiB of standard output is always
kept for the protocol line. A step keeps at most 256 KiB of output, and all outputs of one execution together
at most 1 MiB; beyond that the oldest outputs are replaced by `[output removed: the results of this execution
are limited]`.

**Limits.** Applied by a small wrapper before the code starts; if a limit cannot be applied the node fails
instead of running unlimited.

| Limit | Value | Setting |
|-------|-------|---------|
| Wall time | the node's timeout; then SIGTERM, 2 s later SIGKILL of the whole group; reason "Timeout after N s" | Timeout |
| CPU time | timeout + 5 s (`RLIMIT_CPU`) | - |
| Address space | 512 MiB (`RLIMIT_AS`) | `OPENARTIFACT_CODE_MEMORY_LIMIT_MB` |
| Processes and threads added | 64 (`RLIMIT_NPROC`; counted per user) | `OPENARTIFACT_CODE_PROCESS_LIMIT` |
| File size written | 64 MiB (`RLIMIT_FSIZE`) | `OPENARTIFACT_CODE_FILE_SIZE_LIMIT_MB` |
| Open files | 256 (`RLIMIT_NOFILE`) | `OPENARTIFACT_CODE_OPEN_FILES_LIMIT` |
| Core files | none | - |

Runtimes that reserve a lot of address space (Java, Node.js, Go) need a higher memory limit. The limits are
Linux resource limits, not a container: where the `resource` module is missing (not Linux) the code runs
without them and the result's reason says so.

**What the limits do not do.** There is no network isolation (the code can reach every address the application
can, including internal services that HTTP nodes refuse), no file system isolation (it reads and writes what
the application's user can read and write) and it runs as the application's own user. Memory and process
limits are per process and per user, not a control group. Details and the consequences are in
[Security](security.md).

**Switches.** `OPENARTIFACT_CODE_NODES_ENABLED=false` makes every Execute Command node fail with "Execute Command nodes are
disabled". Execute Command nodes also require `OPENARTIFACT_API_TOKEN`: an open application (no token) refuses them
unless `OPENARTIFACT_CODE_NODES_WITHOUT_TOKEN=true` is set, which is for local development only.

### Code examples

A shell step that passes and prints (output: `hello`, then `[stderr]` and `oops`):

```sh
echo hello
echo oops >&2
```

A Python step that decides for itself (the node fails with the reason "nothing to do" and keeps the data):

```python
import json
print("working")
print(json.dumps({"ok": False, "reason": "nothing to do", "data": {"n": 3}}))
```

A step that uses a secret (Secrets setting: `API_KEY`). The step passes; its output shows `key=***`:

```sh
echo "key=$API_KEY"
```

Never put the secret's value in the code itself: the code is stored and shown in plain text, and
`${secret:NAME}` is **not** replaced inside code.

## HTTP node

Sends one request and passes when the status is accepted.

| Setting | Values | Default |
|---------|--------|---------|
| Method | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` | `GET` |
| URL | `http` or `https`, up to 2000 characters, no user name or password | empty (fails with "The URL is empty") |
| Headers | one `Name: value` per line | none |
| Body | text, up to 20000 characters, sent as UTF-8 | none |
| Timeout (seconds) | 1 to 120; covers name resolution, connecting, sending and reading | 30 |
| Success status | comma separated codes or ranges, 100 to 599, for example `200-299, 404` | `200-299` |

**Secrets.** Write `${secret:NAME}` in the URL's path or query (percent-encoded there), in a header value or in
the body; the value is put in when the node runs. A reference in the scheme or host of the URL is refused,
already when you save the setting. The three fields are stored in plain text, so the reference, not the value,
belongs there: `Authorization: Bearer ${secret:API_TOKEN}`.

**Request details.** The headers `Host`, `Content-Length`, `Transfer-Encoding` and `Connection` cannot be set;
`Accept-Encoding: identity` is sent unless you set it. No `Content-Type` is added: set it yourself for a body.
**Redirects are not followed**: a `301` is just a status, which fails unless you list it under Success status.
Proxy variables of the environment are ignored.

**Response.** The body is read up to `OPENARTIFACT_HTTP_RESPONSE_LIMIT_BYTES` (1 MiB), uncompressed; beyond
that `[response truncated]` is appended and `data.truncated` is true. The step's `output` is the body as
text; `data` is `{"status": 200, "content_type": "...", "truncated": false}`. A status outside the accepted
set fails the node with "HTTP 404 is not an accepted status (200-299)" but still keeps the body and the
data, so a failure path can inspect them.

**SSRF protection.** The host name is resolved by the application and **every** address is checked before
any connection; the request then goes to the checked address itself (the URL's host is replaced by the IP,
`Host` and the TLS server name stay the original), so the name cannot resolve to something else between the
check and the connection (DNS rebinding). One refused address refuses the host.

| Address | Refused |
|---------|---------|
| Loopback, private (10/8, 172.16/12, 192.168/16, fc00::/7), link-local, carrier-grade NAT and other non-public addresses | unless `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS=true` |
| Unspecified (`0.0.0.0`, `::`) and multicast | always |
| Cloud metadata: `169.254.169.254`, `169.254.170.2`, `100.100.100.200`, `fd00:ec2::254` | always |

IPv4-mapped and NAT64 IPv6 addresses are judged by the IPv4 address inside them; numeric forms such as `0x7f.1`
are judged as the IP they are. A refused address fails the node with "The address is not allowed (...)".

**The private-network switch.** Off by default, so a node cannot be pointed at the host's own network. Switch
it on only if the nodes must call services on your network (a database API, a home server). With it on,
a node can also call the application itself on its loopback address; together with a stored token that is
equivalent to the owner's own access, which is the trust level an action editor already has.

### HTTP examples

A health check that accepts `200-299` (the default), method `GET`, URL `https://example.org/health`.

A call with a secret in the header and one in the query. With the secret `API_KEY` stored, the stored
settings are

```
method:   GET
url:      https://api.example.org/v1/items?key=${secret:API_KEY}
headers:  Authorization: Bearer ${secret:API_KEY}
```

and the request goes out with the value substituted. If the server echoes it back, the step's output shows
`***` in its place.

A call where 404 is a normal answer: set Success status to `200-299, 404`.

A POST with a JSON body:

```
method:   POST
url:      https://hooks.example.org/notify
headers:  Content-Type: application/json
body:     {"text": "deployment finished"}
```

The metadata endpoint is never reachable: `http://169.254.169.254/latest` fails with "The address is not
allowed (cloud metadata address)".

### The same through the API

A definition is built with the graph API. The calls below create an action definition `Ping` with an HTTP
node between the trigger and the Output (On Pass and On Fail); `$ID` stands for ids returned by the
previous calls. Use the browser API (`/api/...`; it takes the token as a bearer header or a session) or
the editor.

```bash
curl -X POST $BASE/api/actions -H 'Content-Type: application/json' -d '{"name": "Ping"}'
#   returns the definition with its id; GET /api/actions/$ID lists its nodes (trigger, output) and the
#   default trigger -> output edge, which must be deleted first:
curl -X DELETE $BASE/api/actions/$ID/edges/$EDGE
curl -X PATCH  $BASE/api/actions/$ID/nodes/$OUTPUT -H 'Content-Type: application/json' -d '{"fail_enabled": true}'
curl -X POST   $BASE/api/actions/$ID/nodes -H 'Content-Type: application/json' \
     -d '{"kind": "http", "config": {"method": "GET", "url": "https://example.org/health"}}'
curl -X POST   $BASE/api/actions/$ID/edges -H 'Content-Type: application/json' \
     -d '{"source_id": "'$TRIGGER'", "source_port": "out",  "target_id": "'$HTTP'",   "target_port": "in"}'
#   likewise: $HTTP pass -> $OUTPUT pass, and $HTTP fail -> $OUTPUT fail
```

Then link an action of a pipeline to it (`PATCH /api/pipelines/$P/nodes/$ACTION` with
`{"definition_id": "$ID"}`) and start an artifact in the pipeline (`POST /api/tasks/$TASK/run`). The
[API reference](api-reference.md) lists every route.

## Artifact node

Reads or writes the comments of **the artifact this run belongs to** (never another one; there is no setting for a target). The
label "Artifact" is the manifest's; it sits in the *Data* group of the "+" menu.

| Setting | Meaning | Default |
|---------|---------|---------|
| Operation | `Get comments` or `Add comment` | Get comments |
| Newest comments | Get: how many of the newest comments (1 to 100) | 20 |
| Characters per comment | Get: a longer one is cut with `…[cut]` (20 to 4000) | 800 |
| Characters in total | Get: the transcript is at most this long (100 to 4000); older comments are left out first | 3500 |
| Comment | Add: the text; may hold `${node...}`, `${var...}`, `${card...}`; no secrets (refused when saved) | empty |
| If the node fails | `fail`, `continue` or `error_output` | fail |

*Get comments* passes with the transcript as output (`[time] author (kind):` and the text, the oldest of the kept ones first; a first
line says how many older comments were left out) and `data.comments`, a list of `{author, kind, body, at}`, plus `data.count` and
`data.left_out`; an artifact without comments gives `No comments yet`. The output stays within the 4 KiB a node keeps. *Add comment*
writes one under the **node's name** with the kind *Run* and the execution it came from (the Comments tab links to it) and returns
`data.id`; an empty text fails with a reason. Comments are text from outside: an agent that reads them must not treat them as
instructions.

## Build Context node

Builds **one package of text** for an agent from the card and what is around it, so the agent gets a small, fitting amount instead of
everything (or only what a prompt happens to name). It only reads and never changes a card (ADR-078). It sits in the *Data* group of the "+"
menu, leaves by *On Pass* / *On Fail* and has the *If the node fails* setting; no *Retry on fail*, because it is deterministic. The package is
the node's `output`: an agent's prompt (or an Edit Fields node) uses `${(Build Context).output}`.

**Sources.** *Sources* is an ordered list (add with the select under it, reorder with the handle or ArrowUp / ArrowDown on it, remove with the
bin); a source can be there once. A new node starts with *Title and body* and *Comments*; a node whose list was never saved builds from
those two.

| Source | What it gives | Options |
|--------|---------------|---------|
| Title and body | `#number title`, a blank line and the text of the run's card | none |
| Fields | `name: value` of the card's own fields, one per line (a field nobody filled is left out) | none |
| Comments | the newest comments as `[time] author (kind):` and the text, oldest of them first | number, 1 to 100 (20) |
| Parent card | the card this card belongs to | title only, or title and text |
| Child cards | the cards that belong to it, by number | number, 1 to 50 (20); title only, or title and text |
| Sibling cards | the other cards of the same parent, by number | number, 1 to 50 (20); title only, or title and text |
| Results of earlier nodes | the output of the nodes you name (names, one per line, at most 10) that already ran in this execution; the run keeps at most 4 KiB of a node's output | the names |
| Handover documents | the documents agents handed over in this execution through a [Hand Over Tool](agents.md#hand-over-tool): `### name`, then `field: value` per line; none named means all, oldest first | the names of the tool nodes (optional, at most 10) |
| Earlier executions | the last finished executions of this card (not the running one): `#n status, time, started by, pipeline`, the note and the output of the last step that produced text | number, 1 to 10 (3) |

Archived cards are not used as related cards. There is no *depends on* source: the application has no such relation, only parent and children.

**Size.** *Size limit* is a size in bytes with a unit like every size (1 KiB to 32 KiB, default 8 KiB): the most the whole package takes,
headings, markers and separators included. About four bytes make a token of English text, so 8 KiB is roughly 2,000 tokens; the step shows
the estimate. A bigger package gives the agent more to read and costs more, a smaller one costs less and may leave out what it needs.
*Longest item* (an optional setting, 256 B to 16 KiB, default 2 KiB) cuts one comment, card or result to that size with the mark `…[cut]`
before it is weighed.

**What is left out, and in what order** (the rules, the same every time):

1. The card's own title and text are **reserved first** and cut **last**: the other sources give way before it is cut; it keeps its place in the order.
2. The other sources are weighed **in the order of the list**; what does not fit is left out whole, never half a comment or card.
3. Comments and earlier executions drop the **oldest first** (a line `[... 12 older comments left out]` stands in front, the heading says
   `Comments (5 of 30, oldest first)`); fields, related cards and nodes drop the **last first** (`[... 4 more child cards left out]` at the end).
4. A source that gives nothing, or does not fit at all, is listed with its reason in `data.omitted`.
5. The package never exceeds the limit; `data.size_bytes` is what it takes.

`data` holds `included` (per source: `source`, `label`, `items`, `available`, `bytes`, `cut`), `omitted` (`source`, `reason`),
`size_bytes`, `limit_bytes` and `approx_tokens`. The step in the History and the flow shows the same as a list: *In the package* and *Left out*.
A package larger than the 4 KiB a node usually keeps stays whole in the run context (up to the limit); the whole context is still limited
(64 KiB), the oldest results lose their output first.

**The text is data, never a reference.** Cards, comments and results are pasted as they are and never read for `${...}`: a card that holds
`${secret:TOKEN}` puts those characters into the package, never the secret. The section headings (`## Comments`) say where a source starts, but a
card can write a line that looks like one: an agent should treat the package as data, not as instructions.

## GitHub node

Reads GitHub and, if you allow it, comments, without a model. It calls GitHub's REST API through the same guarded
path as the HTTP node (every address vetted and pinned, no redirect followed, a capped body) and needs nothing but a
token for private repositories. To let a *model* work with GitHub, use the MCP Client Tool of an [agent](agents.md)
instead; this node is for steps whose outcome you want to be the same every time.

| Setting | Values | Default |
|---------|--------|---------|
| Operation | `Get repository`, `List issues`, `Get issue`, `List pull requests`, `Get pull request`, `Get pull request diff`, `List pull request files`, `Get file`, `List comments`, `Create comment` | `Get repository` |
| Repository | `owner/name`; may hold `${node...}` and `${var...}` | empty (fails with "The repository is not set") |
| Number | the number of the issue or pull request (get, files, diff, comments); may be a reference | empty |
| File path | `Get file`: a path in the repository; a folder lists its entries | empty (the root) |
| Branch, tag or commit | `Get file`: empty is the default branch | empty |
| State | `open`, `closed`, `all` for the two lists | `open` |
| Limit | 1 to 100: the most items a list returns (one page, the newest first) | 30 |
| Comment | `Create comment`: the text; may hold references, no secrets | empty |
| Allow comments | `Create comment` writes to GitHub: it only runs with this on | off |
| Secret with the token | the *name* of a stored secret holding a personal access token; empty: no token | empty |
| API address | GitHub Enterprise: `https://HOST/api/v3` | `https://api.github.com` |
| Timeout (seconds) | 1 to 120 | 30 |

Settings an operation does not use are ignored.

**What comes back.** GitHub's objects are large and full of URLs, so the node keeps the useful facts of each (listed
below) and puts them in `data`; the step's `output` is the same as JSON. One object is the object itself, so
`${node.Issue.data.title}` works; a list is `{"items": [...], "count": n, "truncated": false}`, so a later step can
take `${node.Issues.data.items}`. A body is cut at 8000 characters and a patch at 4000 (`…[cut]`); a list that does
not fit the 48 KiB a result keeps drops its last items and says `truncated: true`. The list of issues does not contain
pull requests (GitHub's API mixes them in).

| Operation | `data` |
|-----------|--------|
| Get repository | `full_name`, `description`, `private`, `archived`, `default_branch`, `language`, `topics`, `stars`, `forks`, `open_issues`, `license`, `html_url`, `created_at`, `pushed_at` |
| List issues, Get issue | `number`, `title`, `state`, `author`, `labels` (names), `assignees` (logins), `comments`, `created_at`, `updated_at`, `closed_at`, `html_url`, `body` |
| List pull requests, Get pull request | the issue's fields and `draft`, `merged`, `mergeable`, `head` (branch), `head_sha`, `base`, `additions`, `deletions`, `changed_files`, `commits`, `merged_at` (some only come with *Get*) |
| List pull request files | `filename`, `status`, `additions`, `deletions`, `changes`, `patch` |
| Get pull request diff | `diff`, `truncated`; the output is the diff as text |
| Get file | `name`, `path`, `type`, `size`, `sha`, `html_url`, `content`, `truncated`; the output is the file's text (a folder is a list of `name`, `path`, `type`, `size`, `html_url`) |
| List comments | `id`, `author`, `body`, `created_at`, `updated_at`, `html_url` |
| Create comment | the same for the new comment; the output is its address |

**Writing.** Create comment is the only operation that writes, and only on an issue or pull request, only with
*Allow comments* on; otherwise the node fails with "Create comment is off: turn on 'Allow comments' on the node" and
sends nothing. The comment is sent as a JSON string, so quotes and line breaks in it cannot break the request. Use a
token that may comment and nothing more.

**Values in the address.** The repository, the number and the path are checked after the references are resolved
(`owner/name`, a whole number, no `..`), and a path is percent-encoded segment by segment, so an earlier result cannot
change which address is called.

**Failures** are reported in words: a refused token ("GitHub refused the token (HTTP 401)"), no access or not found,
the rate limit with its reset time, a redirect (a renamed repository: use the new name), an answer over
`OPENARTIFACT_HTTP_RESPONSE_LIMIT_BYTES`. The token never appears in a reason, the data or the log.

**Network.** The API address follows the HTTP node's rules, including the private-network switch
`OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS` (only needed for an Enterprise server on your network). The token goes to
the *API address* of the node: whoever may edit the node can point it elsewhere, just as they could put
`${secret:...}` into the header of an HTTP node.

## Postgres node

Runs one SQL statement on a Postgres database and returns the rows. The database is *your* data: OpenArtifact's own
data stays in SQLite ([ADR-020](../architecture/adr/020-sqlite-stays-postgres-as-data-source.md)). The same statement
can be offered to an [agent](agents.md) as a *Postgres Tool*.

| Setting | Values | Default |
|---------|--------|---------|
| Secret with the connection URL | the *name* of a stored secret that holds `postgresql://user:password@host:5432/db` | empty (fails with "No secret with the connection URL is set") |
| Query | one SQL statement, up to 20000 characters, stored in plain text | empty |
| Values | one value per line: the first is `$1`, the second `$2`, ...; may hold `${node...}` and `${var...}`, no secrets | none |
| Allow changes | off: the database refuses every change; on: the statement may change data | off |
| Private network | the database is on a private network (also needs the operator's switch, below) | off |
| Max rows | 1 to 1000 | 100 |
| Timeout (seconds) | 1 to 120; covers connecting and the statement | 30 |

**The connection URL is a secret.** Store it under Secrets and name it in the node; the node, the snapshot of a run
and its history only ever hold the name. Add `?sslmode=require` (or `verify-full`, with `sslrootcert=system` for the
system's certificates) to use TLS: without it the driver's default `prefer` applies. Only a plain connection is
accepted: one host, no socket, and none of `options`, `service` or files named in the URL.

**Values are parameters, not text.** Write `$1`, `$2` in the query and put the values in *Values*; they are sent to the
database apart from the statement, so a value can never become SQL (`WHERE status = $1` with the value
`x'; DROP TABLE t; --` looks for that text). A `${...}` reference in the query itself is refused. The values are
text; the database converts them to what the query expects (`WHERE id = $1`, value `42`). For a NULL use
`NULLIF($1, '')`. Every `$n` the query uses needs a value and every value must be used. Exactly one statement runs: a
second one after a `;` is refused by the database.

**Read-only is the database's.** By default the statement runs in a `READ ONLY` transaction that is rolled back, and a
first query has run before it, so the server itself refuses `INSERT`, `UPDATE`, `DROP` and a `DO` block that tries to
change the mode: "25006: cannot execute DELETE in a read-only transaction (the node is read-only: turn on 'Allow
changes' to write)". With *Allow changes* the statement may change data and its transaction is committed when it
succeeds, rolled back when it fails. This does not replace a database role with only the privileges the node needs:
**connect with such a role** (a read-only one for a read-only node).

**Result.** `data` is `{"rows": [...], "columns": [...], "row_count": 2, "truncated": false}`; the step's `output` is
the rows as JSON. Each row is an object by column name (a repeated name becomes `name_2`). Numbers and text are as they
are, `numeric` as text (`"12.50"`, no precision lost), dates and times as ISO text, `bytea` as `\x...`, `jsonb` as
JSON, arrays as lists. A later step reads `${node.Postgres.data.rows.0.title}` or takes the whole list
`${node.Postgres.data.rows}`. At most *Max rows* rows and 48 KiB are kept; more are left out and `truncated` is true.
A read-only statement is read row by row and cancelled when the limit is reached; one with *Allow changes* runs to its
end (it is committed whole) and reports the rows it changed in `row_count`. `columns` is empty when a read-only
statement returns no row.

**Time.** The timeout is also the statement timeout on the server; when it is up the node fails with
"Timeout after N s" and the statement is cancelled there.

**Network.** The host name is resolved by the application and every address is vetted like the HTTP node's (cloud
metadata, unspecified and multicast addresses never; loopback and private addresses only when the node's *Private
network* switch **and** `OPENARTIFACT_HTTP_ALLOW_PRIVATE_NETWORKS=true` are on); the connection goes to the vetted
address and keeps the name for TLS. A database in the same Docker network or on the host is a private address, so both
switches are needed for it.

**Failures** are reported in words without the URL, the user or the address: "Could not connect to the database: the
user or the password was refused", or an SQL error with its code (`42P01: relation "tickets" does not exist`).

### Example: the open tickets

Secret `TICKETS_DB`; *Query* `SELECT id, title FROM tickets WHERE status = $1 ORDER BY id LIMIT 20`, *Values* `open`,
*Private network* on if the database is internal. A following node reads `${node.Postgres.data.rows}`.

## SQLite node (guard actions only)

The **SQLite** node (and the **SQLite Tool** for an agent) reads data of the application with one **read-only** SQL statement. It exists
only in a **guard action** (ADR-067); a pipeline action does not offer it and the server refuses it there. It is in the menu group
*Apps and data* next to Postgres, and the Tool is among the *Agent tools*. It is for everyone, never for writing (for that there are the
API, MCP and the interface). Safe by construction (ADR-068):

- the file is opened read-only and the database itself refuses every change, `ATTACH`, `PRAGMA` and transaction; one statement only;
- a table is read **through the views** of the data source, never directly. The data source *Application data* has:

| View | One row per | Columns |
|---|---|---|
| `v_guard_runs` | execution | `id`, `task_id`, `number`, `pipeline_name`, `started_stage_name`, `started_action_name`, `final_stage_name`, `final_action_name`, `status`, `started_by`, `dry_run`, `step_count`, `created_at`, `started_at`, `finished_at` |
| `v_guard_steps` | step (a node that ran) | `id`, `execution_id`, `seq`, `node_id`, `node_name`, `kind`, `outcome`, `success` (1 or 0), `attempts`, `port`, `exit_code`, `reason`, `started_at`, `finished_at` |
| `v_guard_tool_calls` | tool call of a *finished* Agent step | `execution_id`, `step_id`, `step_name`, `step_seq`, `turn`, `tool`, `tool_node`, `arguments` (first 200 characters), `is_error`, `duration_ms` |
| `v_guard_artifacts` | artifact (card) | `id`, `number`, `title`, `lane`, `parent_id`, `pipeline_id`, `stage_id`, `action_id`, `created_by`, `created_at`, `updated_at` |
| `v_guard_lanes` | lane | `key`, `title`, `position` |

- what holds content or a secret is not in the views, and a fixed **floor** blocks secrets, credentials, tokens, providers and settings even
  through a view. *Blocked tables* (optional) adds more: `table` or `table.column` per line; a view that reads a blocked column is blocked.

Values go in as `?1`, `?2` (the *Values* list; `${node...}` and `${var...}` are resolved first), never as text of the statement. The result
is JSON: `rows`, `columns`, `row_count`, `truncated`, and the rows as the output. *Max rows* and *Timeout* are optional settings.

Examples:

```sql
-- how many artifacts a lane holds (an empty backlog while a pipeline runs is a sign the pipeline has nothing to do)
SELECT count(*) AS n FROM v_guard_artifacts WHERE lane = ?1
-- the same call made again and again: more than 3 times in a row with the same arguments is a storm
SELECT tool, arguments, count(*) AS calls FROM v_guard_tool_calls WHERE execution_id = ?1 GROUP BY tool, arguments HAVING calls > 3
-- how long ago the last step of an execution ended
SELECT max(finished_at) AS last_step FROM v_guard_steps WHERE execution_id = ?1
```

## If and Switch nodes

Two nodes that choose the way on by a value of the [run context](#the-run-context-and-references). They do no work
of their own and cannot fail open (there is no *If the node fails* setting). There is no scripting, no regular
expression and no loop: a fixed list of comparisons.

### If

Up to five conditions (rows **Condition 1** to **5**; a row whose *Value* is empty is unused) joined by *all*
(and) or *any* (or). Each row has a *Value* (text, may hold `${node.NAME.output}` or `${var.name}`), an *Operator*
and *Compare with* (text, may hold references; ignored by the operators without a right side).

| Outputs | Meaning |
|---------|---------|
| **Yes** | The conditions hold (all, or any) |
| **No** | They do not |
| **Else** | They could not be evaluated: an unresolvable reference, a side that is not a number or a boolean where one is needed, or no condition set. The step is a failure with the reason; if nothing is connected at Else, the action fails |

| Operator | Holds when | Right side |
|----------|------------|------------|
| equals / not equals | equal; as numbers when both sides are numbers (`1.0` equals `1`), otherwise as text | yes |
| contains / not contains | the left text contains the right text | yes |
| starts with / ends with | the left text starts or ends with the right text | yes |
| greater than / less than / greater or equal / less or equal | numeric comparison; both sides must be numbers, otherwise **Else** | yes |
| is true / is false | the left side is `true` or `false` (lowercase, JSON); anything else goes to **Else** | no |
| is empty / is not empty | empty text, only white space, `null`, `[]` or `{}` | no |

Comparison rules: both sides are trimmed of white space first (so the newline at the end of an Execute Command node's output does
not matter); text is compared **case-sensitively** unless *Case sensitive* is switched off; a number is an optional
sign, digits, an optional decimal point and an optional exponent (`-3`, `+2.5`, `1e3`), no thousands separators; all
conditions are evaluated, and an error in any of them sends the node to **Else** (the reason names the first one).
`${secret:NAME}` is refused in conditions when you save (a branch could reveal a secret); only the run context is a
source.

The step records the way taken and what was compared (values cut at 200 characters):

```json
{"condition": true,
 "rows": [{"left": "high", "operator": "equals", "right": "high", "result": true},
          {"left": "7", "operator": "greater than", "right": "5", "result": true}]}
```

outcome `pass` for Yes and No, outcome `fail` with port `else` (and `"condition": null`) when it could not be decided.

### Switch

Compares one *Value* with up to six *cases* and leaves by the first case that holds: outputs **Case 1** ... **Case 6**
and **Else**. Each case is a rule of its own: an *Operator* (the same list as the If node; `equals` when nothing is
chosen) and the value to *Compare with*, which may hold references (`${node...}`, `${var...}`, `${card...}`, not
secrets). *Case sensitive* (on by default) applies to every case. A case is in use when it has a value, or an operator
that needs none (`is empty`, `is not empty`, `is true`, `is false`); an unused case has no output at all (connections to
it are refused, and making it unused removes its connection). In the editor an output is labelled with its rule: the
value for `equals`, otherwise the operator before it (`> 10`, `contains urgent`, `is empty`).

**Else** is taken when no case holds (outcome `pass`), or when the value or a case cannot be resolved or compared
(outcome `fail`, with the reason, for example `Case 2: both sides must be numbers for greater than`). Step data:
`{"value": "gold", "matched": "case_2", "cases": [{"case": "case_1", "operator": "equals", "right": "silver",
"result": false}, ...]}` lists the cases that were checked, up to the one that held; `matched` is `null` for Else.
Switches made before case operators existed compare with `equals`, as they did.

## Edit Fields node

Sets variables of the run without code. *Fields* is one `name = value` per line; each line sets `${var.name}` for the
nodes after this one. The value is text and may hold `${node.NAME.output}`, `${node.NAME.data.key}`, `${var.name}`
and `${card.name}`; a secret is refused, because a variable is plain data that later nodes and the history show.
Names are lowercase letters, digits and underscores, starting with a letter, at most 100 fields.

*Value types*: `text` (the default) stores every value as text. `detect` stores a value that is a JSON number, `true`,
`false`, `null`, an object or a list as that value (so `score = 7` can be compared as a number and
`data = ${node.Fetch.data}` keeps the object); anything else, a quoted string included, stays text as written.

The node leaves by **On Pass** with the variables set, or by **On Fail** (nothing is set) when a reference cannot be
resolved or a value does not fit the limits of the run context (names, nesting of at most 3 levels, 32 KiB of
variables). Its output is the fields as compact JSON; `data` lists their names. The editor suggests the names it sets
as `${var.name}` in the nodes after it.

### Example: support triage

An Execute Command node *Classify* reads the text of the ticket from `context.json`, prints
`{"ok": true, "vars": {"priority": "high", "score": 7}}` and declares `priority` and `score` under *Sets variables*.
An **If** node *Is urgent* with `${var.priority}` equals `high` and `${var.score}` greater than `5` (all) leads by
**Yes** to an HTTP node that pages on-call, by **No** to an Execute Command node that queues the ticket, and by **Else** (the
variable was not set, the score is no number) to the Output's **On Fail**. A **Switch** on `${var.tier}` with the
cases `silver`, `gold`, `platinum` sends each tier to its own handling and everything else by **Else**.

### Suggestions while typing

In every text field that takes references (HTTP URL, headers and body; the If and Switch values and cases; the
fields of Edit Fields; the inputs of an Agent node) typing `${` (or
pressing Ctrl+Space inside an open `${`) opens a list under the caret that leads in steps, so that it stays short in a large action: first `card.` (the artifact
fields), `var.` (variables the Execute Command nodes declare and the Edit Fields nodes set), `secret:` (your secrets, in the fields
that allow them, not in conditions) and the nodes of the action being edited by name, `(Code: hello).`; once one is
chosen, what is behind it: the fields of the artifact, the variables, the secrets, or `output`, `exit_code`, `outcome`,
`reason` and `data.` of the node. Typing a part of a name finds the node at once. Arrow keys move, Enter or
Tab insert (the closing `}` is added), Escape closes the list and keeps the text, typing narrows it. Suggestions are
hints; nothing is checked in the browser and the Code text gets none (it is never interpolated).

## Retry on fail

A node that fails can be tried again before the failure counts: the optional setting **Retry on fail** (`retry`), added through
*Add setting* in the *Behaviour* part of the node's window and taken away again with its bin ([ADR-073](../architecture/adr/073-retry-on-fail.md)).
It is offered by every node that runs something, read or write: Code, HTTP, Agent, Postgres, SQLite, GitHub and Artifact, and by an
**action** in a stage (an action can fail, a stage does not). It is not offered by the Timer, the Trigger and the Output, nor by If,
Switch and Edit Fields, which only look at the run context and would answer the same again.

| Setting | Values | Default |
|---------|--------|---------|
| the switch | *On* / *Off* (Off keeps the numbers) | On when added |
| Max. tries | a whole number from 2 to 10; **the first try counts** (3 is one try and two more) | 3 |
| Wait between tries | a number and a unit (**ms**, **sec**, **min**), stored as milliseconds: 0 to 10 minutes | 1 sec |

The form shows the largest unit that divides the stored value evenly (3467 ms stays 3467 ms, 90000 ms is 90 sec, 120000 ms is 2 min),
so nobody converts by hand. All the waits of one node together are at most 30 minutes (`(max tries - 1) x wait`); a value outside the
bounds is refused with the reason (`422`, and under the field in the editor).

- **Only the failing node is tried again, not the run.** After the last failed try the node leaves as it does today: by On Fail or as
  *If the node fails* says (*Continue* too: it comes after the last try). A node that passes on a later try passes.
- **An action** is run again as a whole (every node of its definition, each run with its own steps) and, after the last try, fails with
  "(after N tries)" in its reason.
- **The history shows it:** one step per node, with `attempts` (the tries) and, in the step's `detail`, the failed tries before the
  last one (`tries`: number, reason, milliseconds). The History tab and the flow page say "3 tries" and list them under *Tried 3 times*.
  In the context, `${(Node).attempts}` is the number of tries and `${(Node).duration_ms}` includes the waits.
- **Stop works during a wait:** the wait is a pause of the node's task, so stopping the run (the Stop button of the executions list too)
  ends it at once, with no further try. A user's Stop and a guard that stops the node are never retried. A node that runs into its own
  timeout has failed that try like any other.
- **Take care with writes.** A try that repeats an HTTP write, a Postgres change, a GitHub comment or issue, or an Artifact comment can
  do it twice; that is why the setting is off until it is added, and its help says so.
- **The Agent node** keeps its own retry for the model request (network errors, 408, 429, 5xx after 3, 10, 30 and 60 seconds,
  [ADR-037](../architecture/adr/037-agent-harness.md)); *Retry on fail* is independent of it and tries the whole node again.

## What a failure does to the way on

Both nodes leave by **On Pass**, and by **On Fail** when you ask for it. The setting **If the node fails** (`on_failure`)
chooses what a failure means for the way on ([ADR-061](../architecture/adr/061-what-a-failure-does.md)):

- `fail` (**Stop the run**, the default): the failure ends the action as failed, and so the run, unless the action says
  otherwise (*If the action fails* in its settings). There is no error output.
- `continue` (**Continue**, fail open): the node leaves by On Pass although it failed. The step is still recorded as a failure
  with its reason, followed by "(continued through On Pass)", so the history and the flow view show what happened.
  A node that passes is not affected.
- `error_output` (**Error output**): the node leaves by **On Fail**, which is shown only with this value. If nothing is
  connected there, the action fails.

Whatever the value, a failure is data of the step: `${node.NAME.data.error.message}` (and `.mode`, `.node`) are readable by a later node,
and `${node.NAME.output}` is what the node produced (empty when it produced nothing). A connection at On Fail needs the value
`error_output` first (the editor and the API refuse it otherwise); changing the value away from it disconnects what was connected there, and the editor says so.
An **action** has the same three values as *If the action fails* in the settings of the action in its stage; its **On Error**
output exists only with `error_output`, `continue` goes on through On Pass and leaves `data.error` under the action's name.

**An action's error output and its definition's On Fail are one state.** The definition's Output has the switch *On Fail*;
the place that uses the definition has *If the action fails: Error output*. Whichever you switch, the other follows
([ADR-061](../architecture/adr/061-what-a-failure-does.md) §4), because a definition is shared by every place that uses it:

- *On Fail* on in the definition: every use that stops the run gets the error output (an unconnected one fails like Stop,
  so no behaviour changes); a use on *Continue* stays.
- *Error output* on a use: the definition's *On Fail* is switched on. When other uses exist, the editor says "Also switched
  on in the action 'X'; it applies to N other uses." (and they get the error output too); with a single use it says nothing.
- *On Fail* off in the definition: the connections at the error output of **every** use and the connections inside the
  definition that end at *On Fail* are disconnected, and the uses go back to *Stop the run*. The editor says how many and where.
  You draw them again if you want them.
- A use leaves *Error output*: its connection goes; the definition's *On Fail* goes off only when no other use still has the
  error output, otherwise it stays on ("Stays on …").

Open editors follow: a pipeline editor that shows a use loads the graph again when the definition changes in another tab.

The Execute Command node ends when the shell ends: a background process that keeps the output open (`sleep 300 &` without a
redirect) does not hold the node until the timeout. Whatever the code left running is killed with the process
group when the node ends.

## When something fails

| Reason shown | Cause |
|--------------|-------|
| `The code is empty` / `The URL is empty` | Nothing to run |
| `Execute Command nodes are disabled` | `OPENARTIFACT_CODE_NODES_ENABLED=false` |
| `Exit code N`, `Killed by signal N` | The process ended that way; the output has the details |
| `Timeout after N s` | The node's timeout; the process group was killed |
| `CPU time limit exceeded`, `File size limit exceeded (N MiB)`, `... (memory limit of N MiB exceeded?)` | A resource limit |
| `The resource limits could not be applied (...)` | The platform refused a limit; the code did not run |
| `The address is not allowed (...)`, `The host name could not be resolved` | SSRF rules or DNS |
| `HTTP N is not an accepted status (...)` | The server answered, but not with an accepted code |
| `The connection failed (...)`, `The request failed (...)` | Network error (only the exception's type is shown, never its text) |
| `Secret NAME does not exist`, `Secret NAME cannot be read: the secret key changed` | See [Credentials](credentials.md) |
| `${node...}: ...`, `${var...}: ...`, `malformed reference ...`, `ambiguous node name ...`, `Invalid vars: ...` | A context reference or a reported variable that cannot be used, see [the run context](#the-run-context-and-references) |
| `The node failed (ErrorType)` | An unexpected error in the node; details are in the application log, never in the result |
