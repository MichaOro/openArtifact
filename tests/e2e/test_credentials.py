"""The credentials page (ADR-051): a token is shown once and works until it is revoked; an external value is stored,
listed without it and deleted."""

from __future__ import annotations

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SECURED_TOKEN
from tests.e2e.helpers import add_setting, eventually, pick_node
from tests.helpers import graph_url


def _open(page: Page, secured_url: str) -> None:
    page.goto(f"{secured_url}/settings/credentials")
    page.fill("#token", SECURED_TOKEN)
    page.click("button[type=submit]")
    expect(page.get_by_role("tab", name="Internal")).to_be_visible()


def test_a_token_is_shown_once_works_and_stops_when_revoked(page: Page, secured_url: str) -> None:
    _open(page, secured_url)
    page.get_by_role("button", name="New token").click()
    page.fill("#cr-name", "e2e-job")
    page.get_by_role("button", name="Generate token").click()
    token_el = page.locator("[data-token]")
    expect(token_el).to_contain_text("oa_")
    token = token_el.inner_text()
    page.get_by_role("button", name="I have copied it").click()

    row = page.locator('[data-credential="e2e-job"]')
    expect(row).to_contain_text("Active")
    expect(token_el).to_be_empty()
    assert token not in page.content()  # shown once, gone from the document with the dialog
    headers = {"Authorization": f"Bearer {token}"}
    assert httpx.get(f"{secured_url}/api/v1/secrets", headers=headers).status_code == 200

    row.get_by_role("button", name="Actions of e2e-job").click()
    page.get_by_role("menuitem", name="Revoke…").click()
    page.get_by_role("button", name="Revoke", exact=True).click()
    expect(row).to_contain_text("Revoked")
    assert httpx.get(f"{secured_url}/api/v1/secrets", headers=headers).status_code == 401

    row.get_by_role("button", name="Actions of e2e-job").click()
    page.get_by_role("menuitem", name="Delete…").click()
    page.get_by_role("button", name="Delete", exact=True).click()
    expect(row).to_have_count(0)


def test_an_external_credential_is_stored_listed_without_its_value_and_deleted(
    page: Page, secured_url: str
) -> None:
    _open(page, secured_url)
    page.get_by_role("tab", name="External").click()
    page.get_by_role("button", name="New credential").click()
    page.select_option("#cr-type", "generic_api_key")
    page.fill("#cr-name", "E2E_KEY")
    page.fill("#cr-f-value", "very-secret-e2e-value")
    page.get_by_role("button", name="Store").click()

    row = page.locator('[data-credential="E2E_KEY"]')
    expect(row).to_contain_text("Generic API key")
    expect(row).to_contain_text("No test for this type")
    assert "very-secret-e2e-value" not in page.content()

    row.get_by_role("button", name="Actions of E2E_KEY").click()
    page.get_by_role("menuitem", name="Delete…").click()
    expect(page.locator("#confirm-modal")).to_contain_text("No node or provider refers to it")
    page.get_by_role("button", name="Delete", exact=True).click()
    expect(row).to_have_count(0)


def test_the_github_node_chooses_makes_and_edits_its_credential_in_the_credentials_window(
    page: Page, secured_url: str
) -> None:
    headers = {"Authorization": f"Bearer {SECURED_TOKEN}"}
    with httpx.Client(base_url=secured_url, headers=headers) as api:
        api.post(
            "/api/credentials/external",
            json={"type": "github_pat", "name": "GH_ONE", "fields": {"value": "ghp_test_one"}},
        ).raise_for_status()
        definition = api.post("/api/actions", json={"name": "Hub"}).json()
        page.goto(f"{secured_url}/actions/{definition['slug']}")
        page.fill("#token", SECURED_TOKEN)
        page.click("button[type=submit]")
        expect(page.locator(".ge-node--output")).to_be_visible()
        page.click("[data-add-menu]")
        pick_node(page, "github")
        page.locator(".ge-node--github").dblclick(position={"x": 30, "y": 5})
        dialog = page.locator("#node-modal")
        expect(dialog).to_be_visible()

        def stored() -> object:
            nodes = api.get(graph_url(definition)).json()["nodes"]
            return next(n["config"].get("secret") for n in nodes if n["kind"] == "github")

        # Resource and Operation share a line without covering each other
        r = dialog.get_by_label("Resource").bounding_box()
        o = dialog.get_by_label("Operation").bounding_box()
        assert r and o and r["x"] + r["width"] <= o["x"] + 1, "side by side, not over each other"
        # the token is a credential, not a secret name; the timeout is offered through Add setting
        expect(dialog.get_by_label("Token secret")).to_have_count(0)
        expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_have_count(0)
        credential = dialog.get_by_label("Credential", exact=True)
        expect(credential.locator("option")).to_have_text(
            ["No credential", "GH_ONE", "+ Create new credential"]
        )
        edit = dialog.get_by_role("button", name="Edit this credential")
        expect(edit).to_be_hidden()
        credential.select_option("GH_ONE")
        eventually(stored, "GH_ONE")
        expect(edit).to_be_visible()
        # the pencil opens the window of the Credentials page on the same credential
        edit.click()
        window = page.locator("#credential-modal")
        expect(window).to_be_visible()
        expect(window.get_by_label("Name")).to_have_value("GH_ONE")
        window.get_by_role("button", name="Cancel").click()
        expect(window).to_be_hidden()
        # a new one: only a GitHub access token fits, so no type to choose; it is chosen once stored
        credential.select_option("+ Create new credential")
        expect(window).to_be_visible()
        expect(window.get_by_label("Type")).to_be_hidden()
        window.get_by_label("Name").fill("GH_TWO")
        window.get_by_label("Token").fill("ghp_test_two")
        window.locator("[data-submit]").click()
        expect(window).to_be_hidden()
        expect(credential).to_have_value("GH_TWO")
        eventually(stored, "GH_TWO")
        names = [c["name"] for c in api.get("/api/credentials?category=external").json()]
        assert "GH_TWO" in names, "the same data as the Credentials page"
        add_setting(page, "Timeout (seconds)")
        expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_be_visible()
