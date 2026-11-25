"""The GitHub node (ADR-041): its operations against a fake GitHub, what it keeps, the rules around it."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.engine.context import NodeIndex, RunContext, RunView
from openartifact.engine.github_runner import run_github
from openartifact.engine.results import NodeResult
from tests.github_support import README, TOKEN, FakeGithub, github
from tests.helpers import build_pipeline as _pipeline
from tests.helpers import make_task as _make_task
from tests.helpers import wait_for_run as _wait
from tests.test_execution_nodes import Make, _definition, _start, _use, make_client

__all__ = ["github", "make_client"]  # fixtures, used by name

VIEW = RunView(
    RunContext({"vars": {"number": "7", "repo": "acme/tool", "text": 'He said "hi"\nbye'}}),
    NodeIndex(),
)


async def _run(
    github: FakeGithub,
    operation: str,
    *,
    token: str | None = TOKEN,
    private: bool = True,
    limit_bytes: int = 1024 * 1024,
    **config: Any,
) -> NodeResult:
    config = {
        "operation": operation,
        "repository": "acme/tool",
        "api_url": github.url,
        "timeout_seconds": 5,
        **config,
    }
    return await run_github(
        config,
        token=token,
        view=VIEW,
        operator_allows_private=private,
        response_limit_bytes=limit_bytes,
    )


# ── what is asked, and as whom ───────────────────────────────────────


async def test_a_request_says_who_asks_and_what_it_accepts(github: FakeGithub) -> None:
    await _run(github, "Get repository")
    (hit,) = github.hits
    assert (hit.method, hit.route) == ("GET", "/repos/acme/tool")
    assert hit.headers["Authorization"] == f"Bearer {TOKEN}"
    assert hit.headers["Accept"] == "application/vnd.github+json"
    assert hit.headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert hit.headers["User-Agent"].startswith("OpenArtifact")


async def test_without_a_token_no_authorization_is_sent(github: FakeGithub) -> None:
    result = await _run(github, "Get repository", token=None)
    assert result.outcome == "pass"
    assert "Authorization" not in github.hits[0].headers


async def test_a_base_path_of_the_api_address_is_kept_for_github_enterprise(
    github: FakeGithub,
) -> None:
    result = await _run(github, "Get repository", api_url=f"{github.url}/api/v3/")
    assert result.outcome == "pass"
    assert github.hits[0].route == "/api/v3/repos/acme/tool"


# ── what comes back ──────────────────────────────────────────────────


async def test_a_repository_is_kept_as_its_useful_facts_only(github: FakeGithub) -> None:
    result = await _run(github, "Get repository")
    assert result.outcome == "pass"
    assert result.data == {
        "full_name": "acme/tool",
        "description": "A tool",
        "private": False,
        "archived": False,
        "default_branch": "main",
        "language": "Python",
        "topics": ["cli", "python"],
        "stars": 99,
        "forks": 3,
        "open_issues": 4,
        "license": "Apache-2.0",
        "html_url": "https://github.example/acme/tool",
        "created_at": "2020-01-01T00:00:00Z",
        "pushed_at": "2026-11-05T00:00:00Z",
    }
    assert json.loads(result.output) == result.data


async def test_issues_come_back_as_a_list_without_the_pull_requests_github_mixes_in(
    github: FakeGithub,
) -> None:
    result = await _run(github, "List issues", state="all", limit=10)
    assert result.outcome == "pass"
    assert github.hits[0].query == {"state": "all", "per_page": "10"}
    assert result.data is not None
    assert [i["number"] for i in result.data["items"]] == [1, 2]  # #3 is a pull request
    assert result.data["count"] == 2 and result.data["truncated"] is False
    assert result.data["items"][0] == {
        "number": 1,
        "title": "Issue 1",
        "state": "open",
        "author": "octo",
        "labels": ["bug"],
        "assignees": ["octo"],
        "comments": 2,
        "created_at": "2026-11-01T10:00:00Z",
        "updated_at": "2026-11-02T10:00:00Z",
        "closed_at": None,
        "html_url": "https://github.example/acme/tool/issues/1",
        "body": "Body of issue 1",
    }
    assert json.loads(result.output) == result.data["items"]


async def test_the_state_filters_a_list(github: FakeGithub) -> None:
    result = await _run(github, "List issues", state="closed")
    assert result.data is not None and [i["number"] for i in result.data["items"]] == [2]


async def test_one_issue_is_the_object_itself_in_data(github: FakeGithub) -> None:
    result = await _run(github, "Get issue", number="7")
    assert github.hits[0].route == "/repos/acme/tool/issues/7"
    assert result.data is not None
    assert (result.data["number"], result.data["title"], result.data["author"]) == (
        7,
        "Issue 7",
        "octo",
    )
    assert "items" not in result.data


async def test_pull_requests_are_listed_and_read(github: FakeGithub) -> None:
    listed = await _run(github, "List pull requests", limit=1)
    assert listed.data is not None and [p["number"] for p in listed.data["items"]] == [9]
    one = await _run(github, "Get pull request", number="9")
    assert one.data is not None
    assert one.data["head"] == "feature" and one.data["base"] == "main"
    assert (one.data["additions"], one.data["deletions"], one.data["changed_files"]) == (10, 2, 3)
    assert one.data["merged"] is False and one.data["draft"] is False


async def test_the_diff_of_a_pull_request_is_text(github: FakeGithub) -> None:
    result = await _run(github, "Get pull request diff", number="9")
    assert result.output.startswith("diff --git a/a.py b/a.py")
    assert result.data == {"diff": result.output, "truncated": False}
    assert "diff" in github.hits[0].headers["Accept"]


async def test_the_files_of_a_pull_request_keep_a_cut_patch(github: FakeGithub) -> None:
    result = await _run(github, "List pull request files", number="9")
    assert result.data is not None
    first, big = result.data["items"]
    assert first == {
        "filename": "a.py",
        "status": "modified",
        "additions": 1,
        "deletions": 1,
        "changes": 2,
        "patch": "@@ -1 +1 @@\n-old\n+new",
    }
    assert len(big["patch"]) < 4200 and big["patch"].endswith(
        "[cut]"
    )  # a long patch does not fill the run


async def test_a_file_is_decoded_and_its_text_is_the_output(github: FakeGithub) -> None:
    result = await _run(github, "Get file", path="docs/README.md", ref="main")
    assert result.output == README
    assert github.hits[0].query == {"ref": "main"}
    assert result.data is not None
    assert result.data["content"] == README
    assert (result.data["path"], result.data["size"], result.data["type"]) == (
        "docs/README.md",
        len(README),
        "file",
    )


async def test_a_folder_is_a_list_of_its_entries(github: FakeGithub) -> None:
    result = await _run(github, "Get file", path="docs")
    assert result.data is not None
    assert [(e["name"], e["type"]) for e in result.data["items"]] == [
        ("README.md", "file"),
        ("guides", "dir"),
    ]


async def test_a_path_is_encoded_segment_by_segment(github: FakeGithub) -> None:
    await _run(github, "Get file", path="docs/My file.md")
    assert github.hits[0].path.split("?")[0] == "/repos/acme/tool/contents/docs/My%20file.md"


async def test_a_file_github_does_not_return_is_said_so(github: FakeGithub) -> None:
    result = await _run(github, "Get file", path="big.bin")
    assert result.outcome == "fail"
    assert result.reason == "GitHub does not return files over 1 MB through the contents API"


async def test_comments_are_listed(github: FakeGithub) -> None:
    result = await _run(github, "List comments", number="7", limit=1)
    assert result.data is not None
    assert result.data["items"] == [
        {
            "id": 101,
            "author": "octo",
            "body": "First comment",
            "created_at": "2026-11-02T11:00:00Z",
            "updated_at": "2026-11-02T11:00:00Z",
            "html_url": "https://github.example/acme/tool/issues/7#issuecomment-101",
        }
    ]


async def test_a_long_list_is_cut_to_what_the_run_can_hold_and_says_so(github: FakeGithub) -> None:
    result = await _run(github, "List issues", repository="acme/many", limit=100)
    assert result.outcome == "pass" and result.data is not None
    data = result.data
    assert data["truncated"] is True and 0 < data["count"] < 40
    assert len(json.dumps(data).encode()) <= 48 * 1024 + 200
    assert all(item["body"].endswith("…[cut]") for item in data["items"])  # a long body is cut too


# ── a comment, the one thing it writes ───────────────────────────────


async def test_a_comment_is_posted_only_when_comments_are_allowed(github: FakeGithub) -> None:
    refused = await _run(github, "Create comment", number="7", comment="Hello")
    assert refused.outcome == "fail"
    assert refused.reason == "Create comment is off: turn on 'Allow comments' on the node"
    assert github.hits == []  # nothing was sent
    made = await _run(github, "Create comment", number="7", comment="Hello", allow_comments=True)
    assert made.outcome == "pass"
    (hit,) = github.hits
    assert (hit.method, hit.route) == ("POST", "/repos/acme/tool/issues/7/comments")
    assert hit.json() == {"body": "Hello"}
    assert made.data is not None and made.data["id"] == 201
    assert made.output == "https://github.example/acme/tool/issues/7#issuecomment-101"


async def test_a_comment_is_sent_as_json_whatever_it_holds(github: FakeGithub) -> None:
    await _run(github, "Create comment", number="7", comment="${var.text}", allow_comments=True)
    assert github.hits[0].json() == {"body": 'He said "hi"\nbye'}


@pytest.mark.parametrize(
    ("comment", "message"),
    [("", "The comment is empty"), ("  \n", "The comment is empty"), ("x" * 65537, "too long")],
)
async def test_an_empty_or_huge_comment_is_not_sent(
    github: FakeGithub, comment: str, message: str
) -> None:
    result = await _run(github, "Create comment", number="7", comment=comment, allow_comments=True)
    assert result.outcome == "fail" and message in (result.reason or "")
    assert github.hits == []


# ── references and what they may become ──────────────────────────────


async def test_repository_and_number_may_come_from_earlier_results(github: FakeGithub) -> None:
    result = await _run(github, "Get issue", repository="${var.repo}", number="${var.number}")
    assert result.outcome == "pass"
    assert github.hits[0].route == "/repos/acme/tool/issues/7"


@pytest.mark.parametrize(
    ("operation", "config", "message"),
    [
        ("Get repository", {"repository": "acme"}, "owner/name"),
        ("Get repository", {"repository": "acme/tool/extra"}, "owner/name"),
        ("Get repository", {"repository": "acme/."}, "owner/name"),
        ("Get repository", {"repository": "./tool"}, "owner/name"),
        ("Get repository", {"repository": "../other/repo"}, "owner/name"),
        ("Get repository", {"repository": "acme/to ol"}, "owner/name"),
        ("Get repository", {"repository": ""}, "The repository is not set"),
        ("Get issue", {"number": ""}, "The number is not set"),
        ("Get issue", {"number": "7/../../user"}, "whole number"),
        ("Get issue", {"number": "7?x=1"}, "whole number"),
        ("Get file", {"path": "docs/../../etc"}, "'..'"),
        ("Get file", {"path": "/docs"}, "must not start with"),
    ],
)
async def test_a_value_that_would_change_the_address_is_refused_before_any_request(
    github: FakeGithub, operation: str, config: dict[str, Any], message: str
) -> None:
    result = await _run(github, operation, **{"number": "7", **config})
    assert result.outcome == "fail" and message in (result.reason or "")
    assert github.hits == []


async def test_a_reference_that_cannot_be_resolved_fails_naming_it(github: FakeGithub) -> None:
    result = await _run(github, "Get issue", number="${var.nothing}")
    assert result.outcome == "fail" and "${var.nothing}" in (result.reason or "")


# ── what GitHub answers instead ──────────────────────────────────────


@pytest.mark.parametrize(
    ("repository", "message"),
    [
        ("acme/missing", "Not found, or the token has no access: acme/missing"),
        (
            "acme/private",
            "GitHub refused the request (HTTP 403): Resource not accessible by personal access token",
        ),
        ("acme/limited", "GitHub rate limit reached; it resets at 2026-"),
        ("acme/broken", "GitHub answered HTTP 500: Server Error"),
        ("acme/moved", "GitHub redirected the request (HTTP 301)"),
        ("acme/not-json", "GitHub did not answer with JSON"),
    ],
)
async def test_a_failure_of_github_is_reported_in_words(
    github: FakeGithub, repository: str, message: str
) -> None:
    result = await _run(github, "Get repository", repository=repository)
    assert result.outcome == "fail"
    assert (result.reason or "").startswith(message)


async def test_a_refused_token_is_reported_without_the_token(github: FakeGithub) -> None:
    result = await _run(github, "Get repository", token="ghp_wrong_token_value")
    assert result.reason == "GitHub refused the token (HTTP 401)"
    assert "ghp_wrong_token_value" not in json.dumps(result.__dict__)


async def test_an_answer_over_the_limit_of_the_node_fails_instead_of_being_half_read(
    github: FakeGithub,
) -> None:
    result = await _run(github, "Get repository", repository="acme/huge", limit_bytes=2000)
    assert result.outcome == "fail"
    assert result.reason == "The answer of GitHub is larger than the limit of 2000 bytes"


async def test_a_slow_github_hits_the_time_limit(github: FakeGithub) -> None:
    result = await _run(github, "Get repository", repository="acme/slow", timeout_seconds=1)
    assert result.reason == "Timeout after 1 s"


# ── the network rules of the HTTP node ───────────────────────────────


async def test_a_private_api_address_needs_the_operators_switch(github: FakeGithub) -> None:
    result = await _run(github, "Get repository", private=False)
    assert result.outcome == "fail" and "private network address" in (result.reason or "")
    assert github.hits == []


async def test_the_metadata_address_is_never_called(github: FakeGithub) -> None:
    result = await _run(github, "Get repository", api_url="http://169.254.169.254")
    assert result.outcome == "fail" and "cloud metadata address" in (result.reason or "")


@pytest.mark.parametrize("url", ["ftp://example.org", "https://user:pw@example.org", "not a url"])
async def test_the_api_address_must_be_a_plain_http_address(github: FakeGithub, url: str) -> None:
    result = await _run(github, "Get repository", api_url=url)
    assert result.outcome == "fail" and "pw" not in (result.reason or "")
    assert github.hits == []


# ── in a run ─────────────────────────────────────────────────────────


def _client(make: Make, github: FakeGithub, token: str = TOKEN) -> TestClient:
    client = make(api_token="t" * 40, secret_key="s" * 40, http_allow_private_networks=True)
    client.headers.update({"Authorization": "Bearer " + "t" * 40})
    made = client.post(
        "/api/credentials/external",
        json={
            "type": "github_pat",
            "name": "GITHUB_TOKEN",
            "fields": {
                "value": token,
                "base_url": github.url,
            },  # the address is kept with the credential
        },
    )
    assert made.status_code == 201, made.text
    return client


def _flow(client: TestClient, github: FakeGithub, status: str, **config: Any) -> dict[str, Any]:
    pipeline, task = _pipeline(client, stages=1), _make_task(client)
    config = {"secret": "GITHUB_TOKEN", "repository": "acme/tool", **config}
    _use(client, pipeline, _definition(client, "github", **config))
    _start(client, pipeline, task)
    run = _wait(client, task, status)
    (step,) = [r for r in run["node_results"] if r["kind"] == "github"]
    result: dict[str, Any] = step
    return result


def test_the_token_comes_from_the_secret_store_and_is_nowhere_stored(
    make_client: Make, github: FakeGithub
) -> None:
    client = _client(make_client, github)
    step = _flow(client, github, "done", operation="Get issue", number="7")
    assert step["outcome"] == "pass" and step["data"]["title"] == "Issue 7"
    assert github.hits[0].headers["Authorization"] == f"Bearer {TOKEN}"
    settings = client.app.state.settings  # type: ignore[attr-defined]
    with sqlite3.connect(settings.data_dir / settings.database_filename) as db:
        dump = "\n".join(db.iterdump())
    assert TOKEN not in dump  # the snapshot holds the secret's name only


def test_an_unknown_secret_fails_naming_it(make_client: Make, github: FakeGithub) -> None:
    client = _client(make_client, github)
    step = _flow(client, github, "failed", secret="NOT_STORED", operation="Get repository")
    assert "NOT_STORED" in step["reason"] and github.hits == []


def test_a_token_a_github_error_might_echo_is_masked_in_the_step(
    make_client: Make, github: FakeGithub
) -> None:
    client = _client(make_client, github, token="stored-but-rejected-token")
    step = _flow(client, github, "failed", operation="Get repository")
    assert step["reason"] == "GitHub refused the token (HTTP 401)"
    assert "stored-but-rejected-token" not in json.dumps(step)


def test_the_comment_switch_decides_in_a_run_too(make_client: Make, github: FakeGithub) -> None:
    client = _client(make_client, github)
    off = _flow(
        client, github, "failed", operation="Create comment", number="7", comment="Hi from a flow"
    )
    assert "Allow comments" in off["reason"]
    assert [h.method for h in github.hits] == []
    on = _flow(
        client,
        github,
        "done",
        operation="Create comment",
        number="7",
        comment="Hi from a flow",
        allow_comments=True,
    )
    assert on["data"]["id"] == 201
    assert [(h.method, h.json()) for h in github.hits] == [("POST", {"body": "Hi from a flow"})]


def test_a_list_is_in_data_for_a_later_step(make_client: Make, github: FakeGithub) -> None:
    client = _client(make_client, github)
    step = _flow(client, github, "done", operation="List issues", state="all")
    assert [i["number"] for i in step["data"]["items"]] == [1, 2]
    assert step["data"]["count"] == 2


def test_the_address_of_the_server_is_a_plain_http_address_kept_with_the_credential(
    make_client: Make, github: FakeGithub
) -> None:
    client = _client(make_client, github)
    for address, message in (
        ("ftp://example.org", "http:// or https://"),
        ("https://user:pw@example.org", "no user name or password"),
    ):
        refused = client.post(
            "/api/credentials/external",
            json={
                "type": "github_pat",
                "name": "OTHER_TOKEN",
                "fields": {"value": "x", "base_url": address},
            },
        )
        assert refused.status_code == 422 and message in refused.text, address
        assert "pw" not in refused.text.replace("password", "")
