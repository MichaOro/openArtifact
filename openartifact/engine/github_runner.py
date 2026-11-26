"""Runs a GitHub node: one call of GitHub's REST API, read-only except for a comment (ADR-041).

The node goes through the guarded HTTP path of the HTTP node (``http_runner.guarded_exchange``: every address of
the host vetted and pinned, no redirect, no proxy, a capped body), with the token of a secret as a bearer token.
Every value that becomes a part of the address (the repository, the number, the path of a file) is checked or
percent-encoded after the references are resolved, so an earlier result cannot change which address is called.

GitHub's objects are large and full of URLs; the node keeps the useful facts of each (see the ``_shape`` functions)
and puts them in ``data``: one object as the object itself, a list as ``{"items": [...], "count": n, "truncated":
bool}``, so that a later step (a loop) can take the list. The output is the same as JSON, or the text of a file or
of a diff.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlencode

import httpx

from openartifact.engine.context import ContextError, RunView
from openartifact.engine.http_runner import (
    AddressRefusedError,
    ConnectFailedError,
    Exchange,
    guarded_exchange,
)
from openartifact.engine.results import NodeResult, failed

#: What a node keeps of an answer in ``data`` (the run context holds 64 KiB in all).
DATA_LIMIT_BYTES = 48 * 1024
BODY_LIMIT_CHARS = 8000
PATCH_LIMIT_CHARS = 4000
COMMENT_LIMIT_CHARS = 65536
CUT_MARK = "…[cut]"
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}")
_NUMBER = re.compile(r"[0-9]{1,9}")
#: The operations that need the number of an issue or a pull request.
_NEEDS_NUMBER = frozenset(
    {
        "Get issue",
        "Get pull request",
        "Get pull request diff",
        "List pull request files",
        "List comments",
        "Create comment",
    }
)
_USER_AGENT = "OpenArtifact"


class GithubError(Exception):
    """The call cannot be made or did not work out (the message is the node's reason)."""


# ── shaping ──────────────────────────────────────────────────────────


def _cut(text: Any, limit: int) -> Any:
    if isinstance(text, str) and len(text) > limit:
        return text[:limit] + CUT_MARK
    return text


def _login(user: Any) -> str | None:
    return str(user["login"]) if isinstance(user, dict) and user.get("login") else None


def _shape_repository(o: Mapping[str, Any]) -> dict[str, Any]:
    license_ = o.get("license") or {}
    return {
        "full_name": o.get("full_name"),
        "description": o.get("description"),
        "private": o.get("private"),
        "archived": o.get("archived"),
        "default_branch": o.get("default_branch"),
        "language": o.get("language"),
        "topics": o.get("topics") or [],
        "stars": o.get("stargazers_count"),
        "forks": o.get("forks_count"),
        "open_issues": o.get("open_issues_count"),
        "license": license_.get("spdx_id") or license_.get("name"),
        "html_url": o.get("html_url"),
        "created_at": o.get("created_at"),
        "pushed_at": o.get("pushed_at"),
    }


def _shape_issue(o: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": o.get("number"),
        "title": o.get("title"),
        "state": o.get("state"),
        "author": _login(o.get("user")),
        "labels": [str(x.get("name")) for x in o.get("labels") or [] if isinstance(x, dict)],
        "assignees": [a for a in map(_login, o.get("assignees") or []) if a],
        "comments": o.get("comments"),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "closed_at": o.get("closed_at"),
        "html_url": o.get("html_url"),
        "body": _cut(o.get("body"), BODY_LIMIT_CHARS),
    }


def _shape_pull(o: Mapping[str, Any]) -> dict[str, Any]:
    head, base = o.get("head") or {}, o.get("base") or {}
    return {
        **_shape_issue(o),
        "draft": o.get("draft"),
        "merged": o.get("merged"),
        "mergeable": o.get("mergeable"),
        "head": head.get("ref"),
        "head_sha": head.get("sha"),
        "base": base.get("ref"),
        "additions": o.get("additions"),
        "deletions": o.get("deletions"),
        "changed_files": o.get("changed_files"),
        "commits": o.get("commits"),
        "merged_at": o.get("merged_at"),
    }


def _shape_pull_file(o: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "filename": o.get("filename"),
        "status": o.get("status"),
        "additions": o.get("additions"),
        "deletions": o.get("deletions"),
        "changes": o.get("changes"),
        "patch": _cut(o.get("patch"), PATCH_LIMIT_CHARS),
    }


def _shape_comment(o: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": o.get("id"),
        "author": _login(o.get("user")),
        "body": _cut(o.get("body"), BODY_LIMIT_CHARS),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "html_url": o.get("html_url"),
    }


def _shape_entry(o: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": o.get("name"),
        "path": o.get("path"),
        "type": o.get("type"),
        "size": o.get("size"),
        "html_url": o.get("html_url"),
    }


def _fit_items(items: list[Any], limit: int) -> tuple[list[Any], bool]:
    """The items that fit in ``limit`` bytes of JSON, and whether some were left out."""
    size = 2
    kept: list[Any] = []
    for item in items:
        cost = len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 1
        if size + cost > limit:
            return kept, True
        kept.append(item)
        size += cost
    return kept, False


# ── the request ──────────────────────────────────────────────────────


def _setting(config: Mapping[str, Any], key: str, view: RunView) -> str:
    return view.render(str(config.get(key) or "")).strip()


def _api_base(config: Mapping[str, Any]) -> str:
    base = str(config.get("api_url") or "https://api.github.com").strip().rstrip("/")
    return base


def _repository(config: Mapping[str, Any], view: RunView) -> str:
    text = _setting(config, "repository", view)
    if not text:
        raise GithubError("The repository is not set")
    if not _REPOSITORY.fullmatch(text) or any(part in (".", "..") for part in text.split("/")):
        raise GithubError("A repository is written owner/name")
    return text


def _number(config: Mapping[str, Any], view: RunView) -> str:
    text = _setting(config, "number", view)
    if not text:
        raise GithubError("The number is not set")
    if not _NUMBER.fullmatch(text):
        raise GithubError("A number is a whole number such as 42")
    return text


def _file_path(config: Mapping[str, Any], view: RunView) -> str:
    text = _setting(config, "path", view)
    if text.startswith("/"):
        raise GithubError("A path must not start with /")
    segments = [s for s in text.split("/") if s != ""]
    if any(s in (".", "..") for s in segments):
        raise GithubError("A path must not contain '..'")
    return "/".join(quote(s, safe="") for s in segments)


def _request(
    config: Mapping[str, Any], view: RunView, operation: str
) -> tuple[str, str, dict[str, str], bytes | None]:
    """(method, address, extra headers, body) of ``operation``; :class:`GithubError` when a value is not usable."""
    repo = _repository(config, view)
    base = f"{_api_base(config)}/repos/{repo}"
    state = str(config.get("state") or "open")
    limit = int(config.get("limit") or 30)
    page = urlencode({"state": state, "per_page": limit})
    only_page = urlencode({"per_page": limit})
    number = _number(config, view) if operation in _NEEDS_NUMBER else ""
    if operation == "Get repository":
        return "GET", base, {}, None
    if operation == "List issues":
        return "GET", f"{base}/issues?{page}", {}, None
    if operation == "Get issue":
        return "GET", f"{base}/issues/{number}", {}, None
    if operation == "List pull requests":
        return "GET", f"{base}/pulls?{page}", {}, None
    if operation == "Get pull request":
        return "GET", f"{base}/pulls/{number}", {}, None
    if operation == "Get pull request diff":
        return "GET", f"{base}/pulls/{number}", {"Accept": "application/vnd.github.diff"}, None
    if operation == "List pull request files":
        return "GET", f"{base}/pulls/{number}/files?{only_page}", {}, None
    if operation == "Get file":
        path = _file_path(config, view)
        ref = _setting(config, "ref", view)
        query = f"?{urlencode({'ref': ref})}" if ref else ""
        return "GET", f"{base}/contents/{path}{query}", {}, None
    if operation == "List comments":
        return "GET", f"{base}/issues/{number}/comments?{only_page}", {}, None
    if operation == "Create comment":
        if not config.get("allow_comments"):
            raise GithubError("Create comment is off: turn on 'Allow comments' on the node")
        text = view.render(str(config.get("comment") or ""))
        if not text.strip():
            raise GithubError("The comment is empty")
        if len(text) > COMMENT_LIMIT_CHARS:
            raise GithubError(f"The comment is too long (at most {COMMENT_LIMIT_CHARS} characters)")
        return (
            "POST",
            f"{base}/issues/{number}/comments",
            {"Content-Type": "application/json"},
            json.dumps({"body": text}).encode("utf-8"),
        )
    raise GithubError(f"The operation '{operation}' is not known")


def _message(got: Exchange) -> str:
    try:
        parsed = json.loads(got.text)
        text = str(parsed.get("message") or "") if isinstance(parsed, dict) else ""
    except ValueError:
        text = ""
    return text[:200]


def _refusal(got: Exchange, config: Mapping[str, Any], view: RunView) -> GithubError:
    status, message = got.status, _message(got)
    if status == 401:
        return GithubError("GitHub refused the token (HTTP 401)")
    if status in (403, 429) and got.headers.get("x-ratelimit-remaining") == "0":
        try:
            reset = datetime.fromtimestamp(int(got.headers.get("x-ratelimit-reset", "")), UTC)
            when = reset.isoformat(timespec="minutes").replace("+00:00", "Z")
        except (ValueError, OverflowError, OSError):
            when = "a later time"
        return GithubError(f"GitHub rate limit reached; it resets at {when}")
    if status == 403:
        return GithubError(f"GitHub refused the request (HTTP 403): {message or 'no reason given'}")
    if status == 404:
        try:
            where = _setting(config, "repository", view)
        except ContextError:
            where = "the repository"
        return GithubError(f"Not found, or the token has no access: {where}")
    if 300 <= status < 400:
        return GithubError(
            f"GitHub redirected the request (HTTP {status}), for example for a repository that "
            "was renamed: use its new name"
        )
    return GithubError(f"GitHub answered HTTP {status}: {message or 'no reason given'}")


# ── the answer ───────────────────────────────────────────────────────


def _json(got: Exchange, limit: int) -> Any:
    if got.truncated:
        raise GithubError(f"The answer of GitHub is larger than the limit of {limit} bytes")
    try:
        return json.loads(got.text)
    except ValueError:
        raise GithubError("GitHub did not answer with JSON") from None


def _list(items: Any, shape: Callable[[Mapping[str, Any]], dict[str, Any]]) -> NodeResult:
    if not isinstance(items, list):
        raise GithubError("GitHub did not answer with a list")
    kept, truncated = _fit_items([shape(i) for i in items if isinstance(i, dict)], DATA_LIMIT_BYTES)
    data = {"items": kept, "count": len(kept), "truncated": truncated}
    return NodeResult("pass", output=json.dumps(kept, ensure_ascii=False), data=data)


def _object(item: Any, shape: Callable[[Mapping[str, Any]], dict[str, Any]]) -> NodeResult:
    if not isinstance(item, dict):
        raise GithubError("GitHub did not answer with an object")
    data = shape(item)
    return NodeResult("pass", output=json.dumps(data, ensure_ascii=False), data=data)


def _text_of(item: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """The text of a file object of the contents API, with the facts about it."""
    if item.get("encoding") != "base64":
        raise GithubError("GitHub does not return files over 1 MB through the contents API")
    try:
        text = base64.b64decode(str(item.get("content") or "")).decode("utf-8", errors="replace")
    except (binascii.Error, ValueError):
        raise GithubError("The content of the file could not be read") from None
    kept = text.encode("utf-8")[:DATA_LIMIT_BYTES].decode("utf-8", errors="ignore")
    facts = {
        "name": item.get("name"),
        "path": item.get("path"),
        "type": item.get("type"),
        "size": item.get("size"),
        "sha": item.get("sha"),
        "html_url": item.get("html_url"),
        "content": kept,
        "truncated": kept != text,
    }
    return text, facts


def _file(item: Any) -> NodeResult:
    if isinstance(item, list):
        return _list(item, _shape_entry)
    if not isinstance(item, dict) or item.get("type") not in ("file", "symlink", "submodule"):
        raise GithubError("GitHub did not answer with a file")
    text, facts = _text_of(item)
    return NodeResult("pass", output=text, data=facts)


def _diff(got: Exchange) -> NodeResult:
    kept = got.text.encode("utf-8")[:DATA_LIMIT_BYTES].decode("utf-8", errors="ignore")
    return NodeResult(
        "pass",
        output=got.text,
        data={"diff": kept, "truncated": got.truncated or kept != got.text},
    )


def _comment_made(item: Any) -> NodeResult:
    data = _shape_comment(item if isinstance(item, dict) else {})
    return NodeResult("pass", output=str(data.get("html_url") or ""), data=data)


def _result(operation: str, got: Exchange, limit: int) -> NodeResult:
    if operation == "Get pull request diff":
        return _diff(got)
    parsed = _json(got, limit)
    if operation == "Get repository":
        return _object(parsed, _shape_repository)
    if operation == "List issues":
        # GitHub's list of issues holds pull requests too
        issues = (
            [i for i in parsed if isinstance(i, dict) and "pull_request" not in i]
            if isinstance(parsed, list)
            else parsed
        )
        return _list(issues, _shape_issue)
    if operation == "Get issue":
        return _object(parsed, _shape_issue)
    if operation == "List pull requests":
        return _list(parsed, _shape_pull)
    if operation == "Get pull request":
        return _object(parsed, _shape_pull)
    if operation == "List pull request files":
        return _list(parsed, _shape_pull_file)
    if operation == "Get file":
        return _file(parsed)
    if operation == "List comments":
        return _list(parsed, _shape_comment)
    return _comment_made(parsed)


async def run_github(
    config: Mapping[str, Any],
    *,
    token: str | None,
    view: RunView | None = None,
    operator_allows_private: bool,
    response_limit_bytes: int,
) -> NodeResult:
    """Do what the node's operation says; the result passes when GitHub answers with what was asked for."""
    view = view or RunView()
    operation = str(config.get("operation") or "Get repository")
    started = time.monotonic()
    timeout = float(config.get("timeout_seconds") or 30)
    try:
        method, url, extra, body = _request(config, view, operation)
    except (GithubError, ContextError) as error:
        return failed(str(error))
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": _USER_AGENT,
        **extra,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        async with asyncio.timeout(timeout):
            got = await guarded_exchange(
                method,
                url,
                headers,
                body,
                timeout=timeout,
                limit=response_limit_bytes,
                allow_private=operator_allows_private,
            )
        if not 200 <= got.status < 300:
            raise _refusal(got, config, view)
        result = _result(operation, got, response_limit_bytes)
    except GithubError as error:
        return failed(str(error), duration=time.monotonic() - started)
    except (AddressRefusedError, ConnectFailedError) as error:
        return failed(str(error), duration=time.monotonic() - started)
    except TimeoutError:
        return failed(f"Timeout after {timeout:g} s", duration=time.monotonic() - started)
    except ValueError:
        return failed("The API address is not valid", duration=time.monotonic() - started)
    except httpx.HTTPError as error:
        return failed(
            f"The request failed ({type(error).__name__})", duration=time.monotonic() - started
        )
    result.duration = time.monotonic() - started
    return result
