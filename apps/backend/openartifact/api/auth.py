"""Authentication of the integration API and the MCP server: one bearer token from the settings."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request, status
from fastapi.security import HTTPBearer

BEARER = "bearer "
#: Makes Swagger UI offer an "Authorize" button for the token.
bearer_scheme = HTTPBearer(auto_error=False, description="The API token (OPENARTIFACT_API_TOKEN)")


def token_error(configured: str, header: str | None) -> str | None:
    """Why a request with this ``Authorization`` header is refused (``None``: it is accepted)."""
    if not configured:
        return "The API token is not configured (set OPENARTIFACT_API_TOKEN)"
    if not header or not header.lower().startswith(BEARER):
        return "Send the API token as 'Authorization: Bearer <token>'"
    if not secrets.compare_digest(header[len(BEARER) :].strip(), configured):
        return "Invalid API token"
    return None


async def require_api_token(request: Request) -> None:
    """Dependency of the integration API: 401 unless the request carries the configured token."""
    message = token_error(
        request.app.state.settings.api_token, request.headers.get("authorization")
    )
    if message is not None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=message,
            headers={"WWW-Authenticate": "Bearer"},
        )
