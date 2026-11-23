# Execution nodes: Code, HTTP, If, Switch and Edit Fields

The nodes that do work inside an action definition (see [Concepts](concepts.md)). You add them in the
action editor with the "+" menu and set them in the inspector; every setting is saved as you type or leave
the field. This guide is the reference for what each node does, what it returns, what limits it has and how a
failure is routed. Read [Security](security.md) before you let anyone other than yourself edit actions: a Code
node runs arbitrary code with the application's rights.

Settings of the application that affect the nodes are in the [configuration reference](configuration.md).

The **Agent node** (one request to a language model for a centrally managed agent) has a guide of its own:
[Agents and LLM providers](agents.md). It is an execution node like the ones here: *On Pass* / *On Fail*,
*If the node fails*, a result in the run context (`${node.NAME.output}`, `${node.NAME.data.model}`,
`${node.NAME.data.usage.total_tokens}`).

An output longer than a step keeps (256 Ki characters) is cut visibly for every kind: the text ends with
`[output truncated]`, the data has `output_truncated: true` and the reason says so.

## How an action definition runs

When a run reaches an action that is linked to a definition, the engine walks the definition:

1. It starts at the **trigger** and records a step for it.
2. It follows the connection leaving the current node. A node with an executor (timer, Code, HTTP, If, Switch) runs; the
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

Stopping a run cancels the node that is running: a Code node's process group is killed, an HTTP request is
abandoned.

## Results

Every executed node leaves one step with these fields (all visible in the History tab and the flow view, and
returned by the API under the execution):

| Field | Timer | Code | HTTP |
|-------|-------|------|------|
| `outcome` | always `pass` | `pass` or `fail` | `pass` or `fail` |
| `port` | `out` | `pass` or `fail` | `pass` or `fail` |
| `exit_code` | none | the process exit code (negative: ended by a signal) | none |
| `output` | none | stdout, then `[stderr]` and stderr | the response body |
| `reason` | none | why it failed; may come from the code | why it failed |
| `data` | none | an object the code reported, at most 16384 characters of JSON | `status`, `content_type`, `truncated` |
| duration | the wait | wall time | wall time |

A `reason` is a sentence for people, cut at 1000 characters. Output is text: anything the code prints or the
server answers ends up in it (and in the history, and in whatever agent reads it), so treat it as untrusted.
Used secrets are masked in all of these ([Credentials](credentials.md)).

## The run context and references

Every execution has a **context**: the variables Code nodes set and the latest result of every node that ran. A later
node can use it, however many steps earlier the value was produced. It is stored with the execution, so it survives a
server restart and is shown in the History tab ([Execution history](execution-history.md)).

```json
{"vars": {"user": "bob"},
 "card": {"urgency": "high", "tier": "gold"},
 "nodes": {"Fetch_user": {"name": "Fetch user", "kind": "http", "outcome": "pass", "port": "pass",
                          "exit_code": null, "output": "{\"id\": 7}", "reason": null,
                          "data": {"status": 200, "content_type": "application/json", "truncated": false},
                          "at": "2026-11-22T10:00:00.000Z"}}}
```

**References.** In an HTTP node's URL, headers and body:

| Reference | Value |
|-----------|-------|
| `${node.NAME.output}` | the node's output (a node keeps at most 4 KiB of it in the context; the step has all) |
| `${node.NAME.exit_code}`, `.outcome`, `.reason` | exit code, `pass` or `fail`, the reason (`null` text when there is none) |
| `${node.NAME.data}` | the node's data as compact JSON |
| `${node.NAME.data.key.sub.0}` | one value in the data; numbers index lists |
| `${var.name}` | a variable |
| `${card.name}` | a parameter of the artifact (see [below](#card-parameters-card)) |

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

### Card parameters (`card`)

If the artifact has a type ([concepts](concepts.md#terms)), the parameters its type defines are copied into the context
when the execution starts, under `card`: every parameter of the type is a key with its value, else its default,
else `null` (rendered as `null` like other empty values). An untyped artifact has an empty `card`.
`${card.urgency}` is replaced like `${var.urgency}`: text as it is, numbers and yes/no as JSON (`3`, `true`), percent-encoded
in a URL. The name is the parameter's name (`[a-z][a-z0-9_]{0,31}`), not its label. A parameter the artifact does not
have fails the node: `${card.x}: the artifact has no parameter "x"`. Code nodes read `card` in `context.json`. The
context holds a **copy**: changing the artifact's parameters later never changes an execution that exists, and the
History shows what that run saw. Parameters are plain data: do not put secrets in them
([Security](security.md)).

**Setting variables.** A Code node ends with a result line (see the *Result protocol* below). Add `"vars"`:

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
`output` of the node, or a Code node that reads `context.json` and sets the variable).

**Code nodes read `context.json`.** The text of a Code node is never interpolated. The file `context.json` in the
node's working directory holds the whole context, written (read-only) just before the script starts:
`json.load(open("context.json"))["vars"]["user"]`. It is a temporary file in the node's own temporary directory
(`/tmp`, usually memory) and is removed with it when the node ends; nothing about it is written to disk
permanently. Changes the script makes to it are not read back.

**Limits and safety.** The whole context is at most 64 KiB (when it grows, the oldest node results lose their
output, then their data, then are dropped; variables are never dropped). It is built from the masked results, so
a secret a node printed is `***` in it and in `context.json`. The values are text from outside (responses, script
output), so treat them as untrusted, like any output.

## Code node

Runs shell or Python text stored in the node.

| Setting | Values | Default |
|---------|--------|---------|
| Language | `sh` or `python` | `sh` |
| Code | up to 20000 characters | empty (an empty program fails with "The code is empty") |
| Secrets | one secret name per line, up to 32 | none |
| Timeout (seconds) | 1 to 600 | 30 |

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

**Switches.** `OPENARTIFACT_CODE_NODES_ENABLED=false` makes every Code node fail with "Code nodes are
disabled". Code nodes also require `OPENARTIFACT_API_TOKEN`: an open application (no token) refuses them
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

Comparison rules: both sides are trimmed of white space first (so the newline at the end of a Code node's output does
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

A Code node *Classify* reads the text of the ticket from `context.json`, prints
`{"ok": true, "vars": {"priority": "high", "score": 7}}` and declares `priority` and `score` under *Sets variables*.
An **If** node *Is urgent* with `${var.priority}` equals `high` and `${var.score}` greater than `5` (all) leads by
**Yes** to an HTTP node that pages on-call, by **No** to a Code node that queues the ticket, and by **Else** (the
variable was not set, the score is no number) to the Output's **On Fail**. A **Switch** on `${var.tier}` with the
cases `silver`, `gold`, `platinum` sends each tier to its own handling and everything else by **Else**.

### Suggestions while typing

In every text field that takes references (HTTP URL, headers and body; the If and Switch values and cases; the
fields of Edit Fields; the inputs of an Agent node) typing `${` (or
pressing Ctrl+Space inside an open `${`) opens a list under the caret: `node.NAME.output`, `exit_code`, `outcome`,
`reason` and `data.` for the nodes of the action being edited, `var.name` for the variables the Code nodes declare and
the Edit Fields nodes set, and
the names of your secrets (`secret:NAME`) in the fields that allow them (not in conditions). Arrow keys move, Enter or
Tab insert (the closing `}` is added), Escape closes the list and keeps the text, typing narrows it. Suggestions are
hints; nothing is checked in the browser and the Code text gets none (it is never interpolated).

## What a failure does to the way on

Both nodes leave by **On Pass** or **On Fail**. The setting **If the node fails** (`on_failure`) chooses what a
failure means for the way on:

- `fail` (the default, closed): the node leaves by On Fail. If nothing is connected there, the action fails and
  so does the run.
- `continue` (fail open): the node leaves by On Pass although it failed. The step is still recorded as a failure
  with its reason, followed by "(continued through On Pass)", so the history and the flow view show what happened.
  A node that passes is not affected.

The Code node ends when the shell ends: a background process that keeps the output open (`sleep 300 &` without a
redirect) does not hold the node until the timeout. Whatever the code left running is killed with the process
group when the node ends.

## When something fails

| Reason shown | Cause |
|--------------|-------|
| `The code is empty` / `The URL is empty` | Nothing to run |
| `Code nodes are disabled` | `OPENARTIFACT_CODE_NODES_ENABLED=false` |
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
