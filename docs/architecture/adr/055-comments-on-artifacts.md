# ADR-055: Comments on artifacts

**Status:** Accepted  
**Date:** 2026-11-23  
**Supersedes:** —  
**Superseded by:** —  
**Amends:** [ADR-051](051-managed-credentials.md) (a managed token also says who is calling), [ADR-054](054-node-kinds-as-yaml-manifests.md) (a 20th kind)  
**Implemented in:** migrations 0041 (`task_comments`) and 0042 (kind `artifact`); `models/board.py` (`TaskComment`), `comments/` (`schemas.py`, `service.py`), `api/comments.py` (one router factory for `/api/tasks/{ref}/comments` and `/api/v1/artifacts/{ref}/comments`), `api/mcp.py` (`list_comments`, `add_comment`), `security.py` (`principal`, `managed_token_name`), `credentials/service.py` (`verify` returns the name), `engine/artifact_runner.py`, `graph/nodes/artifact.yaml`; `static/js/tasks/comments-tab.js`, `comment-format.js`, `comments-api.js`, `templates/components/comments_panel.html`, `static/css/comments.css`; tests `tests/test_comments.py`, `tests/test_artifact_node.py`, `tests/js/comment-format.test.mjs`, `tests/e2e/test_comments.py`  
**Affected chapters:** guides [concepts](../../guides/concepts.md), [execution nodes](../../guides/execution-nodes.md), [API reference](../../guides/api-reference.md), [integration](../../guides/integration.md), [credentials](../../guides/credentials.md)

## 1. Context

A card had a title and a body and nothing else: no place for a person, a script or an agent to say what it found, asked
or did. There is also no user management, so "who wrote this" cannot come from a login. Pipelines that hand work from one
agent to another need exactly such a place.

## 2. Decision

- **A comment** is plain text (1 to 65536 characters, line breaks kept) with a kind (`user`, `api`, `mcp`, `run`,
  `system`), an author name (at most 64 characters), and for a pipeline node the execution it came from. It belongs to one
  artifact and goes with it (`ON DELETE CASCADE`). The UI shows it with `textContent` and `white-space: pre-wrap`: never
  as markup (markdown may come later without a data change).
- **Who writes is decided by what authenticated the request, never by what the caller says:**
  the browser is kind `user`, name "You"; a request with a **managed token** (ADR-051) is written under the token's *name*
  (kind `api` or `mcp` by the way in) and an `author` in the body is ignored; only the **environment token** may pass
  `author` (1 to 64 characters), else the name is `api` or `mcp`. The gates (`AccessGate`, `TokenProtected`,
  `require_api_token`) put the principal into a context variable (`security.principal`); `CommentService` reads it.
  `CredentialService.verify` therefore returns the credential's name (or `None`) instead of a bool.
- **One service, four ways in:** `CommentService` (list, add, update, delete) is used by the browser's API, `/api/v1`,
  the MCP tools and the Artifact node. It publishes `comment.created`, `comment.updated`, `comment.deleted`; the artifact
  dialog follows them. Refusals use the usual 404/422. The owner may edit or delete any comment (there are no accounts to
  restrict it to); an edited one shows "edited" (`updated_at` differs from `created_at`).
- **The Artifact node** (`artifact`, label "Artifact", the label lives only in the manifest) has two operations on the
  artifact **the run belongs to and no other** (there is no setting for a target, and the executor takes the id from the
  run, not from the node): *Get comments* (the newest N, default 20, at most 100; every body cut to a number of characters
  and the transcript to a total, so the 4 KiB output of a node and the 64 KiB context hold; `data.comments` is a list of
  `{author, kind, body, at}`, and the output says how many older ones were left out) and *Add comment* (text with
  `${node...}`, `${var...}`, `${card...}`; `${secret...}` is refused when the node is saved; the author is the node's
  name, the kind `run`, the execution is recorded and the UI links to it).

## 3. Consequences

- Positive: a place for notes between people, scripts and agents with a trustworthy author for tokens; one code path; the
  node needs no new permissions (no secrets, no network).
- Negative: the browser's "You" is not a person; with no accounts, anyone who can open the board can edit any comment.
  A managed token's comments are only as attributable as the token is private. Renaming a token later does not rename the
  comments it wrote (the name is copied, like an execution's pipeline name).
- Not done: markdown, mentions, a badge on the board card, notifications, comment attachments, per-comment permissions.

## 4. Options considered

- **The caller names itself:** simplest, but any script could write as "You" or as another agent. Refused: the name must come from the credential.
- **A foreign key to the credential:** would break when a token is deleted; the name is copied instead.
- **Comments as an artifact field:** a field is one value; comments are a list with authors and times.
