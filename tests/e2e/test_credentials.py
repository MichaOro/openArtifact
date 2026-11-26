"""The credentials page (ADR-051): a token is shown once and works until it is revoked; an external value is stored,
listed without it and deleted."""

from __future__ import annotations

import re

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
    page.wait_for_load_state(
        "networkidle"
    )  # the page is wired (its scripts are loaded) before a tab is clicked


def test_a_token_is_shown_once_works_and_stops_when_revoked(page: Page, secured_url: str) -> None:
    _open(page, secured_url)
    page.get_by_role("button", name="New token").click()
    page.get_by_label("Name", exact=True).fill("e2e-job")
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
    page.get_by_label("Type", exact=True).select_option("generic_api_key")
    page.get_by_label("Name", exact=True).fill("E2E_KEY")
    page.get_by_label("Value", exact=True).fill("very-secret-e2e-value")
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
        # the order: the credential first, then Resource and Operation, then what the operation uses
        labels = dialog.locator(
            '.ge-settings__column[data-section="definition"] .field__label'
        ).all_inner_texts()
        assert [x.strip() for x in labels][:4] == [
            "Credential",
            "Resource",
            "Operation",
            "Repository",
        ]
        # no Advanced area and no server address in the node: that is kept with the credential
        expect(dialog.locator(".ge-advanced")).to_have_count(0)
        expect(dialog.get_by_label("API address")).to_have_count(0)
        # the icon says what the node is for when the pointer rests on it (nothing marks that it is there)
        expect(dialog.locator(".ge-inspector__icon")).to_have_attribute(
            "title", re.compile("GitHub")
        )
        tint = dialog.locator(".ge-inspector__icon").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        assert tint not in ("rgba(0, 0, 0, 0)", "transparent"), "the icon has its kind's colour"
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
        expect(window.get_by_label("Name", exact=True)).to_have_value("GH_ONE")
        # a manifest window: it has the layout handle every one has, so the owner can arrange it
        expect(window.locator("[data-layout-handle]")).to_have_count(1)
        # the name of an existing credential is shown, not changed
        expect(window.get_by_label("Name", exact=True)).to_have_attribute("readonly", "")
        # the explanations are tooltips after their labels, not lines under the fields
        expect(window.locator('.info-tip[data-about="GitHub server"]')).to_have_count(1)
        expect(window.locator('.info-tip[data-about="Name"]')).to_have_count(1)
        expect(window.locator(".field__help")).to_have_count(
            0
        )  # no explaining line under any field (the type's own help is a tooltip too)
        window.get_by_role("button", name="Cancel").click()
        expect(window).to_be_hidden()
        # a new one: only a GitHub access token fits, so no type to choose; it is chosen once stored
        credential.select_option("+ Create new credential")
        expect(window).to_be_visible()
        expect(window.get_by_label("Type", exact=True)).to_be_hidden()
        window.get_by_label("Name", exact=True).fill("GH_TWO")
        window.get_by_label("Token", exact=True).fill("ghp_test_two")
        window.locator("[data-submit]").click()
        expect(window).to_be_hidden()
        expect(credential).to_have_value("GH_TWO")
        eventually(stored, "GH_TWO")
        names = [c["name"] for c in api.get("/api/credentials?category=external").json()]
        assert "GH_TWO" in names, "the same data as the Credentials page"
        add_setting(page, "Timeout (seconds)")
        expect(dialog.get_by_label("Timeout (seconds)", exact=True)).to_be_visible()
        add_setting(page, "If the node fails")  # for every node: Stop the run until it is chosen
        expect(dialog.get_by_label("If the node fails", exact=True)).to_have_value("fail")


def test_the_credential_window_is_arranged_in_one_column_with_readable_rows(
    page: Page, secured_url: str
) -> None:
    from tests.e2e.test_window_layout import _item, _menu

    _open(page, secured_url)
    page.get_by_role("tab", name="External").click()
    page.get_by_role("button", name="New credential").click()
    window = page.locator("#credential-modal")
    expect(window).to_be_visible()
    _item(_menu(page, window), "Edit layout").click()
    arrange = window.locator(".lw-arrange")
    expect(arrange).to_be_visible()
    # a window of one column is arranged in one column, as it is drawn
    expect(arrange.locator('.lw-grid[data-columns="1"]')).to_have_count(1)
    expect(arrange.locator(".lw-lane")).to_have_count(1)
    # the name of a field stays readable: one line (not a letter per line), and a field of a kind says which kind it is for
    heights = arrange.locator(".lw-field__label").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().height)"
    )
    assert heights and max(heights) < 30, heights
    tags = arrange.locator(".lw-field__tag--when").all_inner_texts()
    assert "type: github_pat" in tags
    box = arrange.bounding_box()
    assert box and box["width"] < 560, "the arranged window is as narrow as the form"
