"""A fake OpenID Connect provider for the tests: discovery, JWKS, token and userinfo endpoints.

It signs ID tokens with a key of its own (RS256 by default) so that a test can issue a good token, a token
for another audience or issuer, an expired one, one signed by a stranger or one with a forbidden algorithm.
It records what the application sent to its token endpoint.
"""

from __future__ import annotations

import base64
import json
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

CLIENT_ID = "openartifact"
CLIENT_SECRET = "oidc-client-secret-" + "s" * 12


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    raw = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return {**raw, "kid": kid, "use": "sig", "alg": "RS256"}


class FakeIdp:
    """The provider and what it saw."""

    def __init__(self) -> None:
        self.key = _key()
        self.stranger = _key()  # a key the application does not know
        self.kid = "key-1"
        self.token_hits: list[dict[str, Any]] = []
        self.userinfo_hits: list[str] = []
        self.id_token: str | None = None
        self.access_token = "access-token-1"
        self.userinfo: dict[str, Any] = {}
        self.discovery_changes: dict[str, Any] = {}
        self.token_status = 200
        #: When set, ``/authorize`` signs the user in at once (a browser test): these claims change the token.
        self.auto_claims: dict[str, Any] | None = None
        idp = self

        class Handler(BaseHTTPRequestHandler):
            def _json(self, status: int, body: Any) -> None:
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:
                if self.path.startswith("/authorize") and idp.auto_claims is not None:
                    asked = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
                    idp.prepare(asked["nonce"], **idp.auto_claims)
                    back = f"{asked['redirect_uri']}?{urlencode({'code': 'auto', 'state': asked['state']})}"
                    self.send_response(302)
                    self.send_header("Location", back)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                elif self.path == "/.well-known/openid-configuration":
                    base = idp.issuer
                    self._json(
                        200,
                        {
                            "issuer": base,
                            "authorization_endpoint": f"{base}/authorize",
                            "token_endpoint": f"{base}/token",
                            "jwks_uri": f"{base}/jwks",
                            "userinfo_endpoint": f"{base}/userinfo",
                            "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                            **idp.discovery_changes,
                        },
                    )
                elif self.path == "/jwks":
                    self._json(200, {"keys": [_jwk(idp.key, idp.kid)]})
                elif self.path == "/userinfo":
                    idp.userinfo_hits.append(self.headers.get("Authorization", ""))
                    self._json(200, idp.userinfo)
                else:
                    self._json(404, {})

            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(size).decode())
                idp.token_hits.append(
                    {
                        "path": self.path,
                        "authorization": self.headers.get("Authorization", ""),
                        "form": {k: v[0] for k, v in form.items()},
                    }
                )
                if self.path != "/token":
                    self._json(404, {})
                    return
                if idp.token_status != 200:
                    self._json(idp.token_status, {"error": "invalid_grant"})
                    return
                self._json(
                    200,
                    {
                        "access_token": idp.access_token,
                        "token_type": "Bearer",
                        "id_token": idp.id_token,
                    },
                )

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def issuer(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def prepare(
        self,
        asked_nonce: str,
        *,
        key: rsa.RSAPrivateKey | None = None,
        algorithm: str = "RS256",
        **changes: Any,
    ) -> str:
        """The ID token the token endpoint will hand out next; ``changes`` set or (``None``) drop claims."""
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": CLIENT_ID,
            "sub": "user-1",
            "iat": now,
            "exp": now + 300,
            "nonce": asked_nonce,
            "email": "owner@example.org",
            "email_verified": True,
            "preferred_username": "owner",
            "groups": ["admins"],
        }
        for name, value in changes.items():
            if value is None:
                claims.pop(name, None)
            else:
                claims[name] = value
        if algorithm.startswith("HS"):
            self.id_token = jwt.encode(
                claims, "x" * 64, algorithm=algorithm, headers={"kid": self.kid}
            )
        elif algorithm == "none":
            header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
            body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
            self.id_token = f"{header}.{body}."
        else:
            self.id_token = jwt.encode(
                claims, key or self.key, algorithm=algorithm, headers={"kid": self.kid}
            )
        return self.id_token

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)


@contextmanager
def fake_idp() -> Iterator[FakeIdp]:
    idp = FakeIdp()
    try:
        yield idp
    finally:
        idp.close()
