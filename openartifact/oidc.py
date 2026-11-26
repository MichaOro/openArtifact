"""Single sign-on through OpenID Connect: the authorization code flow with PKCE (ADR-043).

The application is the *relying party*: it sends the browser to the provider (Authelia, Keycloak, ...), takes
the code the browser brings back, exchanges it at the provider's token endpoint and trusts the answer only
after the ID token has been checked: signature (the provider's published keys, asymmetric algorithms only),
issuer, audience, expiry and the nonce of this very sign-in. Who may come in is decided by the lists of the
operator (``oidc_allowed_*``), never by the provider alone.

The provider's discovery document is the provider's word about *its* addresses, so the token endpoint, the
key set and the userinfo endpoint must be on the origin of the configured issuer: a document that points
the client secret somewhere else is refused. The authorization endpoint is only a redirect of the browser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlencode, urlsplit

import httpx
import jwt

from openartifact.config import Settings

logger = logging.getLogger("openartifact.oidc")

#: Asymmetric algorithms only: a token signed with a shared secret (HS*) or not at all (none) is refused.
ALGORITHMS = ("RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512")
STATE_MAX_AGE = 600
REQUEST_TIMEOUT = 10.0
LEEWAY_SECONDS = 30
STATE_COOKIE = "oa_sso"
CALLBACK_PATH = "/login/sso/callback"


class SsoError(Exception):
    """A sign-in that cannot go on: ``message`` is shown to the user, ``status`` is the HTTP status."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class Discovery:
    """The provider's addresses, read from its discovery document."""

    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    userinfo_endpoint: str | None
    post_auth: (
        bool  # the client secret goes in the body (the provider offers no basic authentication)
    )


@dataclass(frozen=True)
class Begin:
    """What starting a sign-in produces: where to send the browser and the signed state to keep."""

    url: str
    state_cookie: str


@dataclass(frozen=True)
class Identity:
    """Who the provider says signed in (already checked) and what it said about them."""

    subject: str
    email: str | None  # only a verified address
    username: str | None
    groups: tuple[str, ...]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _origin(url: str) -> tuple[str, str, int]:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return parts.scheme, (parts.hostname or "").lower(), port


class Oidc:
    """The sign-in of one configured provider."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._issuer = settings.oidc_issuer.rstrip("/")
        self._state_key = hashlib.sha256(f"oa-sso-state\0{settings.secret_key}".encode()).digest()

    # ── the signed state cookie (state, nonce, verifier and target of one sign-in) ──

    def _seal(self, payload: dict[str, Any]) -> str:
        body = _b64(json.dumps(payload, separators=(",", ":")).encode())
        mac = hmac.new(self._state_key, body.encode(), hashlib.sha256).digest()
        return f"{body}.{_b64(mac)}"

    def _open(self, value: str | None) -> dict[str, Any]:
        expired = SsoError(401, "The sign-in expired or did not start here. Please start again.")
        if not value or value.count(".") != 1:
            raise expired
        body, mac = value.split(".")
        wanted = _b64(hmac.new(self._state_key, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(mac, wanted):
            raise expired
        try:
            padded = body + "=" * (-len(body) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
        except ValueError:
            raise expired from None
        if (
            not isinstance(payload, dict)
            or time.time() - float(payload.get("i", 0)) > STATE_MAX_AGE
        ):
            raise expired
        return payload

    # ── the provider's document ──

    async def _get_json(self, client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
        try:
            response = await client.get(url, **kwargs)
            if response.status_code != 200:
                raise SsoError(502, "The sign-in provider answered with an error.")
            return response.json()
        except (httpx.HTTPError, ValueError):
            raise SsoError(
                502, "The sign-in provider could not be reached or answered wrongly."
            ) from None

    def _own(self, document: dict[str, Any], name: str, *, required: bool = True) -> str | None:
        value = document.get(name)
        if not value:
            if required:
                raise SsoError(502, "The sign-in provider's document is incomplete.")
            return None
        if not isinstance(value, str) or _origin(value) != _origin(self._issuer):
            logger.warning("OIDC discovery: %s is not on the origin of the issuer", name)
            raise SsoError(502, "The sign-in provider's document points to another address.")
        return value

    async def discover(self, client: httpx.AsyncClient) -> Discovery:
        document = await self._get_json(client, f"{self._issuer}/.well-known/openid-configuration")
        if (
            not isinstance(document, dict)
            or str(document.get("issuer", "")).rstrip("/") != self._issuer
        ):
            raise SsoError(502, "The sign-in provider's document is for another issuer.")
        authorization = document.get("authorization_endpoint")
        if not isinstance(authorization, str) or not authorization.startswith(
            ("http://", "https://")
        ):
            raise SsoError(502, "The sign-in provider's document is incomplete.")
        methods = document.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
        return Discovery(
            authorization,
            str(self._own(document, "token_endpoint")),
            str(self._own(document, "jwks_uri")),
            self._own(document, "userinfo_endpoint", required=False),
            "client_secret_basic" not in methods and "client_secret_post" in methods,
        )

    # ── step 1: send the browser away ──

    async def begin(self, redirect_uri: str, target: str) -> Begin:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
            found = await self.discover(client)
        state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.oidc_client_id,
                "redirect_uri": redirect_uri,
                "scope": self._settings.oidc_scopes,
                "state": state,
                "nonce": nonce,
                "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
                "code_challenge_method": "S256",
            }
        )
        separator = "&" if "?" in found.authorization_endpoint else "?"
        cookie = self._seal(
            {
                "s": state,
                "n": nonce,
                "v": verifier,
                "t": target,
                "r": redirect_uri,
                "i": time.time(),
            }
        )
        return Begin(f"{found.authorization_endpoint}{separator}{query}", cookie)

    # ── step 2: what the browser brings back ──

    async def finish(
        self, cookie: str | None, state: str | None, code: str | None
    ) -> tuple[Identity, str]:
        """The checked identity and the target of the sign-in; :class:`SsoError` when anything is wrong."""
        sealed = self._open(cookie)
        if not state or not hmac.compare_digest(state, str(sealed["s"])):
            raise SsoError(401, "The sign-in does not belong to this browser. Please start again.")
        if not code:
            raise SsoError(401, "The provider sent no code.")
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, trust_env=False) as client:
            found = await self.discover(client)
            tokens = await self._exchange(client, found, code, str(sealed["v"]), str(sealed["r"]))
            claims = await self._check(
                client, found, str(tokens.get("id_token") or ""), str(sealed["n"])
            )
            access = tokens.get("access_token")
            claims = await self._complete(
                client, found, claims, access if isinstance(access, str) else None
            )
        return _identity(claims), str(sealed["t"])

    async def _exchange(
        self,
        client: httpx.AsyncClient,
        found: Discovery,
        code: str,
        verifier: str,
        redirect_uri: str,
    ) -> dict[str, Any]:
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "client_id": self._settings.oidc_client_id,
        }
        headers: dict[str, str] = {}
        if found.post_auth:
            form["client_secret"] = self._settings.oidc_client_secret
        else:  # RFC 6749 2.3.1: the id and the secret form-encoded, then Base64
            pair = f"{quote_plus(self._settings.oidc_client_id)}:{quote_plus(self._settings.oidc_client_secret)}"
            headers["Authorization"] = f"Basic {base64.b64encode(pair.encode()).decode()}"
        try:
            response = await client.post(found.token_endpoint, data=form, headers=headers)
            body = response.json()
        except (httpx.HTTPError, ValueError):
            raise SsoError(
                502, "The sign-in provider could not be reached or answered wrongly."
            ) from None
        if response.status_code != 200 or not isinstance(body, dict):
            logger.warning("OIDC token endpoint answered %s", response.status_code)
            raise SsoError(401, "The provider did not accept the sign-in.")
        return body

    async def _check(
        self, client: httpx.AsyncClient, found: Discovery, token: str, nonce: str
    ) -> dict[str, Any]:
        invalid = SsoError(401, "The provider's ID token is not valid.")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            raise invalid from None
        algorithm = header.get("alg")
        if algorithm not in ALGORITHMS:
            logger.warning("OIDC ID token with the algorithm %r refused", algorithm)
            raise invalid
        keys = (await self._get_json(client, found.jwks_uri)).get("keys") or []
        kid = header.get("kid")
        candidates = [
            k for k in keys if isinstance(k, dict) and (kid is None or k.get("kid") == kid)
        ]
        if not candidates:
            raise invalid
        try:
            key = jwt.PyJWK(candidates[0]).key
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._settings.oidc_client_id,
                issuer=self._issuer,
                leeway=LEEWAY_SECONDS,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
        except (jwt.PyJWTError, ValueError) as error:
            logger.warning("OIDC ID token refused: %s", type(error).__name__)
            raise invalid from None
        if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(
            claims["nonce"], nonce
        ):
            raise invalid
        return dict(claims)

    async def _complete(
        self,
        client: httpx.AsyncClient,
        found: Discovery,
        claims: dict[str, Any],
        access: str | None,
    ) -> dict[str, Any]:
        """The claims the ID token lacks, from the userinfo endpoint (Authelia keeps them there)."""
        lacking = [n for n in ("email", "preferred_username", "groups") if n not in claims]
        if not lacking or not found.userinfo_endpoint or not access:
            return claims
        info = await self._get_json(
            client, found.userinfo_endpoint, headers={"Authorization": f"Bearer {access}"}
        )
        if not isinstance(info, dict) or info.get("sub") != claims.get("sub"):
            return claims  # another subject's claims are never merged
        return {
            **{k: v for k, v in info.items() if k in lacking or k == "email_verified"},
            **claims,
        }

    # ── who may come in ──

    def allowed(self, who: Identity) -> bool:
        emails, users, groups = self._settings.oidc_allowed
        return bool(
            (who.email and who.email.lower() in emails)
            or (who.username and who.username in users)
            or who.subject in users
            or set(who.groups) & set(groups)
        )


def _identity(claims: dict[str, Any]) -> Identity:
    email = claims.get("email")
    groups = claims.get("groups")
    username = claims.get("preferred_username")
    return Identity(
        subject=str(claims["sub"]),
        email=email if isinstance(email, str) and claims.get("email_verified") is True else None,
        username=username if isinstance(username, str) else None,
        groups=tuple(g for g in groups if isinstance(g, str))
        if isinstance(groups, list)
        else ((groups,) if isinstance(groups, str) else ()),
    )
