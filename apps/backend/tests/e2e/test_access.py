"""Signing in with the access token in the browser, on a server that needs one."""

from __future__ import annotations

import re
from collections.abc import Iterator

import httpx
import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SECURED_TOKEN

TOKEN_FIELD = "#token"


@pytest.fixture
def secured_api(secured_url: str) -> Iterator[httpx.Client]:
    """REST client with the bearer token; the secured server is emptied before each test."""
    headers = {"Authorization": f"Bearer {SECURED_TOKEN}"}
    with httpx.Client(base_url=secured_url, headers=headers) as client:
        for task in client.get("/api/tasks").json():
            assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
        yield client


def _sign_in(page: Page, token: str) -> None:
    page.fill(TOKEN_FIELD, token)
    page.click("button[type=submit]")


def _signed_in(page: Page, secured_url: str) -> None:
    page.goto(secured_url)
    _sign_in(page, SECURED_TOKEN)
    expect(page.locator(".lane")).to_have_count(3)


def test_a_page_leads_to_the_sign_in_and_back_to_where_the_user_wanted_to_go(
    page: Page, secured_url: str, secured_api: httpx.Client
) -> None:
    page.goto(f"{secured_url}/pipelines?x=1")
    expect(page).to_have_url(re.compile(r"/login\?next=%2Fpipelines%3Fx%3D1$"))
    expect(page.locator("#signin-error")).to_be_hidden()

    _sign_in(page, "not the token")
    expect(page.locator("#signin-error")).to_contain_text("That token is not right.")
    expect(page).to_have_url(re.compile(r"/login$"))  # the answer of the POST, still the form

    _sign_in(page, SECURED_TOKEN)
    expect(page).to_have_url(f"{secured_url}/pipelines?x=1")
    expect(page.locator("main").first).to_be_visible()


def test_the_board_loads_and_stays_live_with_the_session_cookie(
    page: Page, secured_url: str, secured_api: httpx.Client
) -> None:
    secured_api.post("/api/tasks", json={"title": "Before sign-in"}).raise_for_status()
    _signed_in(page, secured_url)
    expect(page.locator(".task-card__title", has_text="Before sign-in")).to_be_visible()  # fetch

    secured_api.post("/api/tasks", json={"title": "After sign-in"}).raise_for_status()
    expect(page.locator(".task-card__title", has_text="After sign-in")).to_be_visible()  # SSE


def test_signing_out_ends_the_session(page: Page, secured_url: str) -> None:
    _signed_in(page, secured_url)
    page.click('button[aria-label="Sign out"]')
    expect(page).to_have_url(f"{secured_url}/login")
    page.goto(secured_url)
    expect(page).to_have_url(re.compile(r"/login\?next=%2F$"))
    assert not [
        c for c in page.context.cookies() if c["name"].endswith("oa_session") and c["value"]
    ]


@pytest.mark.parametrize("how", ["removed", "forged"])
def test_a_session_that_stops_working_on_a_live_page_sends_the_user_back_to_sign_in(
    page: Page, secured_url: str, secured_api: httpx.Client, how: str
) -> None:
    secured_api.post("/api/tasks", json={"title": "Doomed"}).raise_for_status()
    _signed_in(page, secured_url)
    card = page.locator(".task-card").filter(has_text="Doomed")
    expect(card).to_be_visible()

    page.context.clear_cookies()
    if how == "forged":
        page.context.add_cookies(
            [{"name": "oa_session", "value": "1.forged", "url": secured_url, "httpOnly": True}]
        )
    card.locator("[data-delete-task]").click()
    page.locator("#delete-task-modal [data-confirm]").click()

    expect(page).to_have_url(re.compile(r"/login\?next=%2F$"))
    assert secured_api.get("/api/tasks").json()[0]["title"] == "Doomed"  # nothing was deleted
