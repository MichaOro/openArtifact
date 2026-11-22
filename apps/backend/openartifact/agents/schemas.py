"""The configuration of an agent, its bounds, and the models of the agent and provider APIs.

:class:`AgentConfig` is what a draft and a published version hold. Its fields that a node may override
are listed in :data:`OVERRIDABLE`; their bounds are defined here once and used by the agent's own
validation and by the node's settings (``graph/node_types.py``).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openartifact.schemas_common import UtcDateTime

INPUT_NAME = re.compile(r"[a-z][a-z0-9_]{0,31}")
INPUT_TYPES = ("string", "number", "boolean")
MAX_INPUTS = 30
PROMPT_MAX_CHARS = 20000
NAME_MAX = 100
DESCRIPTION_MAX = 2000
MODEL_ID_MAX = 200
MAX_AGENTS = 500
MAX_PROVIDERS = 50
MAX_MODELS_PER_PROVIDER = 2000

TEMPERATURE_MIN, TEMPERATURE_MAX = 0, 2
MAX_TOKENS_MIN, MAX_TOKENS_MAX = 1, 8192
REQUEST_TIMEOUT_MIN, REQUEST_TIMEOUT_MAX, REQUEST_TIMEOUT_DEFAULT = 1, 300, 60
TOTAL_TIMEOUT_MIN, TOTAL_TIMEOUT_MAX, TOTAL_TIMEOUT_DEFAULT = 1, 1800, 600
RETRIES_MIN, RETRIES_MAX, RETRIES_DEFAULT = 0, 4, 3

#: The fields of an agent's configuration a node may set for itself (an override).
OVERRIDABLE = (
    "system_prompt_enabled",
    "system_prompt",
    "user_prompt",
    "provider_id",
    "model",
    "temperature",
    "max_tokens",
    "request_timeout_seconds",
    "total_timeout_seconds",
    "retries",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InputSpec(_Strict):
    """One declared input of an agent, used in its prompts as ``${input.NAME}``.

    A required input has no default: the node must map it. An optional input without a mapping is its
    default, or the empty text when it has none.
    """

    name: str
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = False
    default: str | float | bool | None = None
    description: str = Field(default="", max_length=200)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if not INPUT_NAME.fullmatch(value):
            raise ValueError(
                "an input name has lowercase letters, digits and underscores, starts with a letter "
                "and is at most 32 characters"
            )
        return value

    @model_validator(mode="after")
    def _default(self) -> InputSpec:
        value = self.default
        if value is None or value == "":
            self.default = None
            return self
        if self.required:
            raise ValueError(f"input '{self.name}' is required, so it cannot have a default")
        ok = (
            (self.type == "string" and isinstance(value, str))
            or (self.type == "boolean" and isinstance(value, bool))
            or (
                self.type == "number"
                and isinstance(value, int | float)
                and not isinstance(value, bool)
            )
        )
        if not ok:
            raise ValueError(f"the default of input '{self.name}' is not a {self.type}")
        if isinstance(value, str) and len(value) > PROMPT_MAX_CHARS:
            raise ValueError(f"the default of input '{self.name}' is too long")
        return self


class AgentConfig(_Strict):
    """What an agent is configured with: the content of a draft and of a published version."""

    system_prompt_enabled: bool = False
    system_prompt: str = Field(default="", max_length=PROMPT_MAX_CHARS)
    user_prompt: str = Field(default="", max_length=PROMPT_MAX_CHARS)
    inputs: list[InputSpec] = Field(default_factory=list, max_length=MAX_INPUTS)
    provider_id: str | None = Field(default=None, max_length=36)
    model: str | None = Field(default=None, max_length=MODEL_ID_MAX)
    temperature: float | None = Field(default=None, ge=TEMPERATURE_MIN, le=TEMPERATURE_MAX)
    max_tokens: int | None = Field(default=None, ge=MAX_TOKENS_MIN, le=MAX_TOKENS_MAX)
    request_timeout_seconds: int = Field(
        default=REQUEST_TIMEOUT_DEFAULT, ge=REQUEST_TIMEOUT_MIN, le=REQUEST_TIMEOUT_MAX
    )
    total_timeout_seconds: int = Field(
        default=TOTAL_TIMEOUT_DEFAULT, ge=TOTAL_TIMEOUT_MIN, le=TOTAL_TIMEOUT_MAX
    )
    retries: int = Field(default=RETRIES_DEFAULT, ge=RETRIES_MIN, le=RETRIES_MAX)

    @field_validator("system_prompt", "user_prompt")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("a prompt must not contain NUL characters")
        return value

    @field_validator("provider_id", "model")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def _unique_inputs(self) -> AgentConfig:
        names = [i.name for i in self.inputs]
        for name in names:
            if names.count(name) > 1:
                raise ValueError(f"input '{name}' is declared twice")
        return self

    @classmethod
    def loads(cls, text: str | None) -> AgentConfig:
        """The configuration of a stored JSON text (an empty or broken one is the default)."""
        try:
            data = json.loads(text or "{}")
        except ValueError:
            data = {}
        return cls.model_validate(data if isinstance(data, dict) else {})

    def dumps(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)


# ── agents ───────────────────────────────────────────────────────────


class AgentCreate(_Strict):
    name: str = Field(min_length=1, max_length=NAME_MAX)
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    active: bool = True
    draft: AgentConfig | None = None


class AgentUpdate(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=NAME_MAX)
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX)
    active: bool | None = None


class VersionRead(BaseModel):
    """A published version. ``source_number``: the version it repeats (a rollback), else ``None``."""

    number: int
    published_at: UtcDateTime
    published_via: str
    source_number: int | None
    current: bool
    config: AgentConfig | None = None


class AgentRead(BaseModel):
    """An agent in a list: no prompts, only what a list shows."""

    id: str
    name: str
    description: str
    active: bool
    published_number: int | None
    #: Whether the draft differs from the published version (or nothing is published yet).
    draft_changed: bool
    #: How many agent nodes refer to it.
    node_count: int
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AgentDetail(AgentRead):
    """An agent with its draft, the published configuration and its versions (newest first)."""

    draft: AgentConfig
    published: AgentConfig | None
    versions: list[VersionRead]
    #: Why the draft cannot be published as it is (empty: it can).
    problems: list[str] = Field(default_factory=list)


class AgentUse(BaseModel):
    """An agent node that refers to the agent, where it sits and what it sets for itself."""

    node_id: str
    node_name: str
    graph_id: str
    graph_name: str
    graph_slug: str
    overrides: list[str]


class PublishResult(BaseModel):
    """The agent after publishing: ``changed`` lists the fields that differ from the version before,
    ``overriding`` the nodes that set one of those fields themselves (they keep their own value)."""

    agent: AgentDetail
    version: VersionRead
    changed: list[str]
    overriding: list[AgentUse]


class PreviewRequest(_Strict):
    """What to preview: the draft (default), the published version or a numbered one, with example
    values for the inputs. With ``node_id`` the node's overrides and input mapping are applied."""

    source: Literal["draft", "published"] = "draft"
    version: int | None = Field(default=None, ge=1)
    values: dict[str, str] = Field(default_factory=dict)
    node_id: str | None = None


class InputState(BaseModel):
    """How one input got its value. ``state``: ``mapped`` (from the node's mapping), ``sample`` (an
    example value of a preview), ``default``, ``unset`` (optional, no value: empty text), ``pending``
    (a preview cannot know it: the mapping reads the run) or ``error``."""

    name: str
    type: str
    required: bool
    state: str
    source: str | None = None
    value: str | None = None
    error: str | None = None


class SettingState(BaseModel):
    """One setting as it takes effect: its value and whether the node overrides the agent's."""

    key: str
    value: Any
    inherited: Any
    overridden: bool


class PreviewRead(BaseModel):
    """The prompts as they would be sent (no request is made). ``system_prompt`` is ``None`` when the
    system prompt is switched off."""

    agent_id: str
    version: int | None
    system_prompt: str | None
    user_prompt: str
    inputs: list[InputState]
    settings: list[SettingState]
    provider: str | None
    model: str | None
    problems: list[str]


# ── providers ────────────────────────────────────────────────────────


class ModelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    model_id: str
    label: str
    source: str
    enabled: bool
    available: bool


class ModelCreate(_Strict):
    model_id: str = Field(min_length=1, max_length=MODEL_ID_MAX)
    label: str = Field(default="", max_length=MODEL_ID_MAX)
    enabled: bool = True

    @field_validator("model_id")
    @classmethod
    def _plain(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ord(c) < 33 or ord(c) == 127 for c in value):
            raise ValueError("a model id has no spaces or control characters")
        return value


class ModelUpdate(_Strict):
    label: str | None = Field(default=None, max_length=MODEL_ID_MAX)
    enabled: bool | None = None


class ProviderWrite(_Strict):
    """A provider as it is created. ``kind`` ``openrouter`` has a fixed address (``base_url`` must be
    absent); ``openai_compatible`` needs ``base_url``. ``models`` are models defined by hand (only for
    ``openai_compatible``); the first one is used for the test when the endpoint has no ``/models``."""

    kind: Literal["openrouter", "openai_compatible"]
    name: str = Field(min_length=1, max_length=60)
    base_url: str | None = Field(default=None, max_length=500)
    secret_name: str | None = Field(default=None, max_length=64)
    allow_private: bool = False
    default_model: str | None = Field(default=None, max_length=MODEL_ID_MAX)
    is_default: bool = False
    models: list[ModelCreate] = Field(default_factory=list, max_length=50)

    @field_validator("base_url", "secret_name", "default_model")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class ProviderUpdate(_Strict):
    """Changes of a provider; a change of ``base_url``, ``secret_name`` or ``allow_private`` is tested
    like a new provider before it is saved."""

    name: str | None = Field(default=None, min_length=1, max_length=60)
    base_url: str | None = Field(default=None, max_length=500)
    secret_name: str | None = Field(default=None, max_length=64)
    allow_private: bool | None = None
    default_model: str | None = Field(default=None, max_length=MODEL_ID_MAX)
    is_default: bool | None = None


class CheckStep(BaseModel):
    """One step of a connection test."""

    name: str
    ok: bool
    message: str


class CheckResult(BaseModel):
    """The result of a connection test. ``ok``: the endpoint is reachable under the safety rules and
    answers like an OpenAI-compatible API. ``models`` is what its ``/models`` lists (empty when it has
    none); ``warnings`` are things to know that do not fail the test (an ``http`` address)."""

    ok: bool
    steps: list[CheckStep]
    warnings: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    #: Whether the endpoint has a usable ``/models`` (false: models are defined by hand).
    lists_models: bool = False


class ProviderRead(BaseModel):
    """A provider with its models. The API key is never part of it, only the name of its secret and
    whether a secret of that name exists."""

    id: str
    kind: str
    name: str
    base_url: str
    secret_name: str | None
    secret_exists: bool
    allow_private: bool
    #: Whether private addresses are really reachable: the provider's switch and the operator's.
    private_effective: bool
    default_model: str | None
    is_default: bool
    checked_at: UtcDateTime | None
    check_ok: bool | None
    check_message: str | None
    models: list[ModelRead]
    warnings: list[str] = Field(default_factory=list)
    created_at: UtcDateTime
    updated_at: UtcDateTime
