"""The credentials page (ADR-051): a token is shown once and works until it is revoked; an external value is stored,
listed without it and deleted."""

from __future__ import annotations

import httpx
from playwright.sync_api import Page, expect

from tests.e2e.conftest import SECURED_TOKEN


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
