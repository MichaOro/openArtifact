"""A small fake of the GitHub REST API for the GitHub node tests: the objects are as large and as full of URLs as
GitHub's, so that the tests can see what the node keeps of them. Served by a thread on the loopback address."""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

TOKEN = "ghp_fake_token_0123456789abcdef"
URLS = {
    f"{k}_url": f"https://api.example/{k}" for k in ("events", "hooks", "forks", "keys", "teams")
}
USER = {"login": "octo", "id": 1, "node_id": "U_1", "avatar_url": "https://a.example/1", **URLS}
LABEL = {"id": 5, "name": "bug", "color": "d73a4a", "url": "https://api.example/labels/bug"}
README = "# Tool\n\nHello from the repository.\n"


def issue(number: int, **more: Any) -> dict[str, Any]:
    return {
        "url": f"https://api.example/issues/{number}",
        "node_id": f"I_{number}",
        "number": number,
        "title": f"Issue {number}",
        "state": "open",
        "user": USER,
        "labels": [LABEL],
        "assignees": [USER],
        "comments": 2,
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "closed_at": None,
        "html_url": f"https://github.example/acme/tool/issues/{number}",
        "body": f"Body of issue {number}",
        "reactions": {"url": "x", "total_count": 0},
        **more,
    }


def pull(number: int, **more: Any) -> dict[str, Any]:
    return {
        "url": f"https://api.example/pulls/{number}",
        "node_id": f"PR_{number}",
        "number": number,
        "title": f"Pull {number}",
        "state": "open",
        "draft": False,
        "merged": False,
        "mergeable": True,
        "user": USER,
        "labels": [],
        "assignees": [],
        "head": {
            "ref": "feature",
            "sha": "abc123",
            "repo": {"full_name": "acme/tool"},
            "user": USER,
        },
        "base": {"ref": "main", "sha": "def456", "repo": {"full_name": "acme/tool"}, "user": USER},
        "additions": 10,
        "deletions": 2,
        "changed_files": 3,
        "commits": 1,
        "comments": 0,
        "created_at": "2026-11-03T10:00:00Z",
        "updated_at": "2026-11-04T10:00:00Z",
        "closed_at": None,
        "merged_at": None,
        "html_url": f"https://github.example/acme/tool/pull/{number}",
        "body": f"Body of pull {number}",
        "_links": {"self": {"href": "x"}},
        **more,
    }


REPO = {
    "id": 42,
    "node_id": "R_42",
    "name": "tool",
    "full_name": "acme/tool",
    "private": False,
    "owner": USER,
    "html_url": "https://github.example/acme/tool",
    "description": "A tool",
    "fork": False,
    "language": "Python",
    "forks_count": 3,
    "stargazers_count": 99,
    "open_issues_count": 4,
    "default_branch": "main",
    "archived": False,
    "topics": ["cli", "python"],
    "license": {"key": "apache-2.0", "name": "Apache License 2.0", "spdx_id": "Apache-2.0"},
    "visibility": "public",
    "created_at": "2020-01-01T00:00:00Z",
    "pushed_at": "2026-11-05T00:00:00Z",
    **URLS,
}
COMMENTS = [
    {
        "id": 101,
        "node_id": "C_101",
        "user": USER,
        "body": "First comment",
        "created_at": "2026-11-02T11:00:00Z",
        "updated_at": "2026-11-02T11:00:00Z",
        "html_url": "https://github.example/acme/tool/issues/7#issuecomment-101",
        "reactions": {"total_count": 0},
    },
    {
        "id": 102,
        "node_id": "C_102",
        "user": USER,
        "body": "Second comment",
        "created_at": "2026-11-02T12:00:00Z",
        "updated_at": "2026-11-02T12:00:00Z",
        "html_url": "https://github.example/acme/tool/issues/7#issuecomment-102",
        "reactions": {"total_count": 0},
    },
]
DIFF = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new\n"


@dataclass
class Request:
    method: str
    path: str  # with the query string
    headers: dict[str, str]
    body: bytes

    @property
    def route(self) -> str:
        return urlsplit(self.path).path

    @property
    def query(self) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class FakeGithub:
    port: int
    hits: list[Request] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"


def _route(request: Request) -> tuple[int, Any, dict[str, str]]:
    path, query, accept = request.route, request.query, request.headers.get("Accept", "")
    auth = request.headers.get("Authorization")
    if auth and auth != f"Bearer {TOKEN}":
        return 401, {"message": "Bad credentials"}, {}
    prefix = "/api/v3" if path.startswith("/api/v3/") else ""
    path = path.removeprefix(prefix)
    if path == "/repos/acme/limited":
        return (
            403,
            {"message": "API rate limit exceeded"},
            {
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "1795000000",
            },
        )
    if path == "/repos/acme/private":
        return 403, {"message": "Resource not accessible by personal access token"}, {}
    if path == "/repos/acme/moved":
        return 301, {"message": "Moved Permanently"}, {"Location": "/repositories/1"}
    if path == "/repos/acme/broken":
        return 500, {"message": "Server Error"}, {}
    if path == "/repos/acme/slow":
        time.sleep(3)
    if path == "/repos/acme/not-json":
        return 200, "<html>maintenance</html>", {"Content-Type": "text/html"}
    if path == "/repos/acme/huge":
        return 200, [{"filler": "x" * 200}] * 3000, {}
    if path == "/repos/acme/many/issues":
        return 200, [issue(n, body="y" * 20000) for n in range(1, 41)], {}
    if not path.startswith("/repos/acme/tool"):
        return 404, {"message": "Not Found"}, {}
    rest = path.removeprefix("/repos/acme/tool")
    if request.method == "POST":
        if rest == "/issues/7/comments":
            made = {**COMMENTS[0], "id": 201, "body": request.json()["body"]}
            return 201, made, {}
        return 404, {"message": "Not Found"}, {}
    if rest == "":
        return 200, REPO, {}
    per_page = int(query.get("per_page", "30"))
    if rest == "/issues":
        everything = [issue(1), issue(2, state="closed"), issue(3, pull_request={"url": "x"})]
        wanted = [i for i in everything if query.get("state", "open") in ("all", i["state"])]
        return 200, wanted[:per_page], {}
    if rest == "/issues/7":
        return 200, issue(7), {}
    if rest == "/issues/7/comments":
        return 200, COMMENTS[:per_page], {}
    if rest == "/pulls":
        return 200, [pull(9), pull(10, draft=True)][:per_page], {}
    if rest == "/pulls/9":
        if "diff" in accept:
            return 200, DIFF, {"Content-Type": "application/vnd.github.diff"}
        return 200, pull(9), {}
    if rest == "/pulls/9/files":
        return (
            200,
            [
                {
                    "sha": "s1",
                    "filename": "a.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "changes": 2,
                    "blob_url": "https://github.example/blob/a.py",
                    "patch": "@@ -1 +1 @@\n-old\n+new",
                    "contents_url": "https://api.example/contents/a.py",
                },
                {
                    "sha": "s2",
                    "filename": "big.txt",
                    "status": "added",
                    "additions": 9000,
                    "deletions": 0,
                    "changes": 9000,
                    "patch": "+" + "z" * 9000,
                },
            ][:per_page],
            {},
        )
    if rest == "/contents/docs/README.md" or rest == "/contents/docs/My file.md":
        content = base64.encodebytes(README.encode()).decode()
        return (
            200,
            {
                "type": "file",
                "encoding": "base64",
                "size": len(README),
                "name": "README.md",
                "path": "docs/README.md",
                "content": content,
                "sha": "f1",
                "html_url": "https://github.example/blob/docs/README.md",
                "git_url": "x",
                "download_url": "x",
                "_links": {"self": "x"},
                "ref_seen": query.get("ref"),
            },
            {},
        )
    if rest == "/contents/docs":
        return (
            200,
            [
                {
                    "type": "file",
                    "name": "README.md",
                    "path": "docs/README.md",
                    "size": 35,
                    "sha": "f1",
                    "html_url": "https://github.example/blob/docs/README.md",
                    "git_url": "x",
                },
                {
                    "type": "dir",
                    "name": "guides",
                    "path": "docs/guides",
                    "size": 0,
                    "sha": "d1",
                    "html_url": "https://github.example/tree/docs/guides",
                    "git_url": "x",
                },
            ],
            {},
        )
    if rest == "/contents/big.bin":
        return (
            200,
            {
                "type": "file",
                "encoding": "none",
                "size": 5_000_000,
                "name": "big.bin",
                "path": "big.bin",
                "content": "",
                "sha": "b1",
            },
            {},
        )
    return 404, {"message": "Not Found"}, {}


class _Handler(BaseHTTPRequestHandler):
    server: Any

    def _answer(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        request = Request(self.command, self.path, dict(self.headers.items()), body)
        self.server.state.hits.append(request)
        status, payload, headers = _route(request)
        raw = payload.encode() if isinstance(payload, str) else json.dumps(payload).encode()
        self.send_response(status)
        content_type = headers.pop("Content-Type", "application/json")
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    do_GET = do_POST = _answer  # noqa: N815

    def log_message(self, *args: Any) -> None:
        pass


class _Server(ThreadingHTTPServer):
    def handle_error(self, request: Any, client_address: Any) -> None:
        """A client that gave up (the time-limit test) is not worth a traceback on the console."""


@pytest.fixture
def github() -> Iterator[FakeGithub]:
    httpd = _Server(("127.0.0.1", 0), _Handler)
    httpd.block_on_close = False
    state = FakeGithub(httpd.server_address[1])
    httpd.state = state  # type: ignore[attr-defined]
    threading.Thread(
        target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
    ).start()
    yield state
    httpd.shutdown()
    httpd.server_close()
