"""The credential types (ADR-051): what a credential is made of and what it can be used for.

A type describes an authentication or connection mechanism, not the node that happens to use it:
``consumers`` names the kinds of consumers it fits (node kinds and ``provider``), so a picker can offer only what
fits, and ``testable`` says whether a connection test exists for it (a type without one is never shown as tested).
An external credential's value is one secret (``value``); further fields of a type are plain settings, stored beside
it. The registry is data: a new type is one entry here (and a test in ``credentials/testing.py`` if one exists).
"""

from __future__ import annotations

from dataclasses import dataclass

INTERNAL = "internal"
EXTERNAL = "external"


@dataclass(frozen=True)
class FieldDef:
    """One field of a type: ``secret`` fields are the stored value, the others are settings."""

    name: str
    label: str
    secret: bool = False
    required: bool = True
    placeholder: str = ""
    help: str = ""


@dataclass(frozen=True)
class CredentialType:
    id: str
    label: str
    category: str
    help: str = ""
    fields: tuple[FieldDef, ...] = ()
    testable: bool = False
    consumers: tuple[str, ...] = ()

    @property
    def secret_field(self) -> FieldDef | None:
        return next((f for f in self.fields if f.secret), None)

    def describe(self) -> dict[str, object]:
        """What the API and the pages know of a type."""
        return {
            "id": self.id,
            "label": self.label,
            "category": self.category,
            "help": self.help,
            "testable": self.testable,
            "consumers": list(self.consumers),
            "fields": [
                {
                    "name": f.name,
                    "label": f.label,
                    "secret": f.secret,
                    "required": f.required,
                    "placeholder": f.placeholder,
                    "help": f.help,
                }
                for f in self.fields
            ],
        }


def _value(label: str, placeholder: str = "", help: str = "") -> FieldDef:
    return FieldDef("value", label, secret=True, placeholder=placeholder, help=help)


TYPES: dict[str, CredentialType] = {
    t.id: t
    for t in (
        CredentialType(
            "api_access_token",
            "API access token",
            INTERNAL,
            "Opens the browser API, the integration API (/api/v1) and the MCP server, like OPENARTIFACT_API_TOKEN.",
        ),
        CredentialType(
            "mcp_access_token",
            "MCP access token",
            INTERNAL,
            "Opens the MCP server only, so an agent client can be cut off without touching anything else.",
        ),
        CredentialType(
            "github_pat",
            "GitHub access token",
            EXTERNAL,
            "A classic or fine-grained personal access token. For the GitHub node and the GitHub MCP server.",
            (
                _value("Token", "ghp_…"),
                FieldDef(
                    "base_url",
                    "GitHub server",
                    required=False,
                    placeholder="https://api.github.com",
                    help="Empty: github.com. GitHub Enterprise: https://HOST/api/v3",
                ),
            ),
            testable=True,
            consumers=("github", "mcp_tool"),
        ),
        CredentialType(
            "openrouter_api_key",
            "OpenRouter API key",
            EXTERNAL,
            "For an OpenRouter provider.",
            (_value("API key", "sk-or-…"),),
            testable=True,
            consumers=("provider",),
        ),
        CredentialType(
            "openai_compatible_api_key",
            "OpenAI-compatible API key",
            EXTERNAL,
            "For a provider with an OpenAI-compatible endpoint; the address is only used to test the key.",
            (
                _value("API key"),
                FieldDef(
                    "base_url",
                    "Address (for the test)",
                    required=False,
                    placeholder="https://llm.example/v1",
                ),
            ),
            testable=True,
            consumers=("provider",),
        ),
        CredentialType(
            "postgres_connection",
            "PostgreSQL connection",
            EXTERNAL,
            "A connection URL: postgresql://user:password@host:5432/database.",
            (_value("Connection URL", "postgresql://user:password@host:5432/database"),),
            testable=True,
            consumers=("postgres", "postgres_tool"),
        ),
        CredentialType(
            "bearer_token",
            "Bearer token",
            EXTERNAL,
            "For the HTTP nodes and tools: Authorization: Bearer ${secret:NAME}.",
            (_value("Token"),),
            consumers=("http", "http_tool", "mcp_tool"),
        ),
        CredentialType(
            "mcp_auth",
            "MCP authentication",
            EXTERNAL,
            "The token an MCP server expects from the MCP Client Tool.",
            (_value("Token"),),
            consumers=("mcp_tool",),
        ),
        CredentialType(
            "generic_api_key",
            "Generic API key",
            EXTERNAL,
            "Any other secret: a key, a password, a value for a Code node.",
            (_value("Value"),),
            consumers=(
                "http",
                "code",
                "http_tool",
                "code_tool",
                "github",
                "postgres",
                "postgres_tool",
                "mcp_tool",
                "provider",
            ),
        ),
    )
}


def credential_type(type_id: str) -> CredentialType | None:
    return TYPES.get(type_id)


def of_category(category: str) -> list[CredentialType]:
    return [t for t in TYPES.values() if t.category == category]


def compatible(type_id: str, consumer: str) -> bool:
    """Whether a credential of the type fits a consumer (a node kind or ``provider``)."""
    found = TYPES.get(type_id)
    return bool(found and found.category == EXTERNAL and consumer in found.consumers)
