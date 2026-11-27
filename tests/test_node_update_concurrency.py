"""Two settings of one node saved at the same time both stay (F-76 of the architecture remediation).

The inspector saves each setting with its own request (``{"config": {key: value}}``), and two controls can have a
request in flight at once (a choice and a text field left right after it). The server merges the key into the stored
config; both merges must survive.
"""

from __future__ import annotations

from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from tests.helpers import graph_url
from tests.test_execution_nodes import _definition


@pytest.fixture
def api(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    with TestClient(_create_app(migrated_settings)) as client:
        yield client


def test_two_settings_of_a_node_saved_at_the_same_time_both_stay(api: TestClient) -> None:
    action = _definition(api, "http", url="http://example.invalid/a")
    url = f"{graph_url(action)}/nodes/{action['node']['id']}"

    def patch(config: dict[str, Any]) -> int:
        return api.patch(url, json={"config": config}).status_code

    lost = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        for i in range(25):
            first = {"url": f"http://example.invalid/{i}"}
            second = {"timeout_seconds": 10 + i}
            statuses = list(pool.map(patch, [first, second]))
            assert statuses == [200, 200]
            config = api.get(url.rsplit("/nodes/", 1)[0]).json()["nodes"]
            stored = next(n for n in config if n["id"] == action["node"]["id"])["config"]
            if (
                stored.get("url") != first["url"]
                or stored.get("timeout_seconds") != second["timeout_seconds"]
            ):
                lost.append((i, stored.get("url"), stored.get("timeout_seconds")))
    assert not lost, f"a concurrent save was lost (round, url, timeout): {lost}"
