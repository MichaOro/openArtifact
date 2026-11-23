"""Single sign-on in the browser: the button on the sign-in page and a whole sign-in through a provider.

The provider is a local stand-in that signs the user in at once. The application keeps its API token, so the
token form must stay next to the button.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import _serve
from tests.oidc_support import CLIENT_ID, CLIENT_SECRET, FakeIdp, fake_idp

TOKEN = "sso-e2e-token-" + "x" * 24


@pytest.fixture(scope="module")
def idp() -> Iterator[FakeIdp]:
    with fake_idp() as server:
        server.auto_claims = {}
        yield server


@pytest.fixture(scope="module")
def sso_url(tmp_path_factory: pytest.TempPathFactory, idp: FakeIdp) -> Iterator[str]:
    data: Path = tmp_path_factory.mktemp("sso")
    yield from _serve(
        data,
        api_token=TOKEN,
        secret_key="k" * 40,
        oidc_issuer=idp.issuer,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret=CLIENT_SECRET,
        oidc_allowed_emails="owner@example.org",
        oidc_button_label="Sign in with Authelia",
    )


def test_the_sign_in_page_has_the_token_form_and_the_sso_button(page: Page, sso_url: str) -> None:
    page.goto(f"{sso_url}/login")
    expect(page.get_by_label("API token")).to_be_visible()
    expect(page.get_by_role("link", name="Sign in with Authelia")).to_be_visible()


def test_the_button_signs_the_user_in_through_the_provider_and_lands_where_they_wanted(
    page: Page, sso_url: str, idp: FakeIdp
) -> None:
    idp.auto_claims = {}
    page.goto(
        f"{sso_url}/settings/providers"
    )  # a protected page: the gate sends the browser to sign in
    expect(page).to_have_url(f"{sso_url}/login?next=%2Fsettings%2Fproviders")
    page.get_by_role("link", name="Sign in with Authelia").click()
    expect(page).to_have_url(f"{sso_url}/settings/providers")
    expect(page.locator("[data-new-provider]")).to_be_visible()


def test_someone_who_is_not_on_the_list_stays_out_with_a_clear_message(
    page: Page, sso_url: str, idp: FakeIdp
) -> None:
    idp.auto_claims = {"email": "intruder@example.org"}
    try:
        page.goto(f"{sso_url}/login")
        page.get_by_role("link", name="Sign in with Authelia").click()
        expect(page.get_by_text("This account is not allowed to sign in here.")).to_be_visible()
        page.goto(f"{sso_url}/settings/providers")
        expect(page).to_have_url(f"{sso_url}/login?next=%2Fsettings%2Fproviders")
    finally:
        idp.auto_claims = {}
