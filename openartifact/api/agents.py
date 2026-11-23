"""Agent and LLM provider routes: ``/api/agents`` and ``/api/providers`` for the browser, and the same
operations under ``/api/v1`` for scripts (see :func:`build_agents_router`, :func:`build_providers_router`).

An agent has a draft and published versions; only publishing changes what executions use. A provider is
saved only after its connection test passed. No route ever returns an API key: a provider carries the
name of its secret.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Response, status
from fastapi.params import Depends

from openartifact.agents.schemas import (
    AgentConfig,
    AgentCreate,
    AgentDetail,
    AgentRead,
    AgentUpdate,
    AgentUse,
    CheckResult,
    ModelCreate,
    ModelUpdate,
    PreviewRead,
    PreviewRequest,
    ProviderRead,
    ProviderUpdate,
    ProviderWrite,
    PublishResult,
    VersionRead,
)
from openartifact.api.contract import GATED, errors
from openartifact.api.deps import AgentsDep, ProvidersDep

DRAFT_DESCRIPTION = (
    "Replace the draft. ``user_prompt`` and ``system_prompt`` take only ``${input.NAME}`` "
    "placeholders of the declared ``inputs`` (``name``: ``[a-z][a-z0-9_]{0,31}``, ``type``: "
    "``string``, ``number`` or ``boolean``, ``required``, ``default`` for an optional one). "
    "``provider_id`` and ``model`` are optional (the default provider and its default model "
    "apply), ``temperature`` 0 to 2, ``max_tokens`` 1 to 8192, ``request_timeout_seconds`` 1 to 300 "
    "(default 60), ``total_timeout_seconds`` 1 to 1800 (default 600), ``retries`` 0 to 4 (default "
    "3). Saving a draft changes no execution; ``problems`` in the answer lists what publishing "
    "would refuse. Publishes ``agents.changed``."
)
PUBLISH_DESCRIPTION = (
    "Publish the draft as a new version (numbers count up, a version is never changed). Executions "
    "that start afterwards use it; running ones keep what they started with. ``changed`` lists the "
    "fields that differ from the version before, ``overriding`` the agent nodes that set one of those "
    "fields themselves and so keep their own value. 422 with one line per problem if the draft is "
    "not complete."
)
PROVIDER_DESCRIPTION = (
    "``kind`` is ``openrouter`` (fixed address, needs ``secret_name``, at most one) or "
    "``openai_compatible`` (``base_url``: http or https, no user name or password). ``secret_name`` "
    "is the name of a stored secret, never the key. The provider is tested before it is saved and "
    "refused with 422 when the test fails: the address is checked like an HTTP node's (no cloud "
    "metadata address, no redirects; a public, local or private address is fine), an ``http`` address "
    "needs ``allow_http`` (the confirmation that the unencrypted connection is fine), and the endpoint must "
    "answer in the OpenAI format: its ``/models``, or, when it has none, one minimal chat completion "
    "with the first of ``models`` (models defined by hand). ``warnings`` in the answer says when the "
    "address is ``http``."
)


def build_agents_router(
    prefix: str, tags: Sequence[str], via: str, dependencies: Sequence[Depends] = ()
) -> APIRouter:
    """The agent routes under ``prefix``; ``via`` is recorded as the origin of a published version."""
    router = APIRouter(
        prefix=f"{prefix}/agents", tags=list(tags), dependencies=list(dependencies), responses=GATED
    )
    tag = "v1_" if "v1" in prefix else ""

    @router.get("", response_model=list[AgentRead], name=f"{tag}list_agents", summary="List agents")
    async def list_agents(agents: AgentsDep) -> list[AgentRead]:
        """The agents by name: status, published version, whether the draft differs from it and how
        many agent nodes refer to each."""
        return await agents.list_all()

    @router.post(
        "",
        response_model=AgentDetail,
        status_code=status.HTTP_201_CREATED,
        name=f"{tag}create_agent",
        summary="Create an agent",
        responses=errors(409, 422, write=True, body=True),
    )
    async def create_agent(payload: AgentCreate, agents: AgentsDep) -> AgentDetail:
        """Create an agent with a draft (optional). Nothing is published yet, so no node can run it."""
        return await agents.create(payload)

    @router.get(
        "/{ref}",
        response_model=AgentDetail,
        name=f"{tag}get_agent",
        summary="Get an agent",
        responses=errors(404, 422),
    )
    async def get_agent(ref: str, agents: AgentsDep) -> AgentDetail:
        """One agent by id or name: draft, published configuration, versions (newest first)."""
        return await agents.get(ref)

    @router.patch(
        "/{ref}",
        response_model=AgentDetail,
        name=f"{tag}update_agent",
        summary="Rename an agent or switch it on or off",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def update_agent(ref: str, payload: AgentUpdate, agents: AgentsDep) -> AgentDetail:
        """``name``, ``description``, ``active``. An inactive agent is not run: a node that refers to
        it fails in every execution that starts while it is inactive (a running one is not affected)."""
        return await agents.update(ref, payload)

    @router.delete(
        "/{ref}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{tag}delete_agent",
        summary="Delete an agent",
        responses=errors(404, 409, 422, write=True),
    )
    async def delete_agent(ref: str, agents: AgentsDep) -> Response:
        """Delete an agent with its versions; 409 (naming the nodes) while agent nodes refer to it."""
        await agents.delete(ref)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.put(
        "/{ref}/draft",
        response_model=AgentDetail,
        name=f"{tag}save_agent_draft",
        summary="Save the draft of an agent",
        description=DRAFT_DESCRIPTION,
        responses=errors(404, 422, write=True, body=True),
    )
    async def save_draft(ref: str, payload: AgentConfig, agents: AgentsDep) -> AgentDetail:
        return await agents.save_draft(ref, payload)

    @router.post(
        "/{ref}/draft/discard",
        response_model=AgentDetail,
        name=f"{tag}discard_agent_draft",
        summary="Discard the draft of an agent",
        responses=errors(404, 409, 422, write=True),
    )
    async def discard_draft(ref: str, agents: AgentsDep) -> AgentDetail:
        """Make the draft equal to the published version again (409 if nothing is published)."""
        return await agents.discard_draft(ref)

    @router.post(
        "/{ref}/publish",
        response_model=PublishResult,
        name=f"{tag}publish_agent",
        summary="Publish the draft of an agent",
        description=PUBLISH_DESCRIPTION,
        responses=errors(404, 422, write=True),
    )
    async def publish(ref: str, agents: AgentsDep) -> PublishResult:
        return await agents.publish(ref, via)

    @router.get(
        "/{ref}/versions",
        response_model=list[VersionRead],
        name=f"{tag}list_agent_versions",
        summary="List the versions of an agent",
        responses=errors(404, 422),
    )
    async def list_versions(ref: str, agents: AgentsDep) -> list[VersionRead]:
        """Every published version with its configuration, newest first."""
        return await agents.versions(ref)

    @router.get(
        "/{ref}/versions/{number}",
        response_model=VersionRead,
        name=f"{tag}get_agent_version",
        summary="Get a version of an agent",
        responses=errors(404, 422),
    )
    async def get_version(ref: str, number: int, agents: AgentsDep) -> VersionRead:
        return await agents.version(ref, number)

    @router.post(
        "/{ref}/versions/{number}/republish",
        response_model=PublishResult,
        name=f"{tag}republish_agent_version",
        summary="Publish an earlier version again (rollback)",
        responses=errors(404, 409, 422, write=True),
    )
    async def republish(ref: str, number: int, agents: AgentsDep) -> PublishResult:
        """A rollback: a **new** version whose content is that of version ``number`` (its
        ``source_number`` says so). No version is changed or removed. 409 if ``number`` is the
        published one already."""
        return await agents.republish(ref, number, via)

    @router.get(
        "/{ref}/uses",
        response_model=list[AgentUse],
        name=f"{tag}list_agent_uses",
        summary="List the nodes that use an agent",
        responses=errors(404, 422),
    )
    async def uses(ref: str, agents: AgentsDep) -> list[AgentUse]:
        """The agent nodes that refer to the agent, the action each is in and the fields it overrides."""
        return await agents.uses(ref)

    @router.post(
        "/{ref}/preview",
        response_model=PreviewRead,
        name=f"{tag}preview_agent",
        summary="Preview the prompts of an agent",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def preview(ref: str, payload: PreviewRequest, agents: AgentsDep) -> PreviewRead:
        """The prompts as they would be sent, the inputs with where each value comes from and the
        settings in effect. **No request is sent to a model.** ``values`` are example values for the
        inputs; with ``node_id`` the overrides and the input mapping of that agent node are applied
        (an input whose mapping reads the run is ``pending`` unless an example is given)."""
        return await agents.preview(ref, payload)

    return router


def build_providers_router(
    prefix: str, tags: Sequence[str], dependencies: Sequence[Depends] = ()
) -> APIRouter:
    """The provider and model routes under ``prefix``."""
    router = APIRouter(
        prefix=f"{prefix}/providers",
        tags=list(tags),
        dependencies=list(dependencies),
        responses=GATED,
    )
    tag = "v1_" if "v1" in prefix else ""

    @router.get(
        "", response_model=list[ProviderRead], name=f"{tag}list_providers", summary="List providers"
    )
    async def list_providers(providers: ProvidersDep) -> list[ProviderRead]:
        """The LLM providers with their models. Never an API key: ``secret_name`` and ``secret_exists``."""
        return await providers.list_all()

    @router.post(
        "/test",
        response_model=CheckResult,
        name=f"{tag}test_provider",
        summary="Test a provider without saving it",
        description=PROVIDER_DESCRIPTION,
        responses=errors(422, write=True, body=True),
    )
    async def test_provider(payload: ProviderWrite, providers: ProvidersDep) -> CheckResult:
        return await providers.test(payload)

    @router.post(
        "",
        response_model=ProviderRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{tag}create_provider",
        summary="Create a provider",
        description=PROVIDER_DESCRIPTION,
        responses=errors(409, 422, write=True, body=True),
    )
    async def create_provider(payload: ProviderWrite, providers: ProvidersDep) -> ProviderRead:
        return await providers.create(payload)

    @router.get(
        "/{ref}",
        response_model=ProviderRead,
        name=f"{tag}get_provider",
        summary="Get a provider",
        responses=errors(404, 422),
    )
    async def get_provider(ref: str, providers: ProvidersDep) -> ProviderRead:
        return await providers.get(ref)

    @router.patch(
        "/{ref}",
        response_model=ProviderRead,
        name=f"{tag}update_provider",
        summary="Change a provider",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def update_provider(
        ref: str, payload: ProviderUpdate, providers: ProvidersDep
    ) -> ProviderRead:
        """Change a provider. A new ``base_url``, ``secret_name`` or ``allow_http`` is tested like
        a new provider and saved only when the test passes (422 otherwise). ``is_default`` makes it
        the provider of agents that name none (at most one is)."""
        return await providers.update(ref, payload)

    @router.delete(
        "/{ref}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{tag}delete_provider",
        summary="Delete a provider",
        responses=errors(404, 409, 422, write=True),
    )
    async def delete_provider(ref: str, providers: ProvidersDep) -> Response:
        """Delete a provider with its models; 409 while an agent's draft, any of its published
        versions or an agent node's override names it."""
        await providers.delete(ref)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post(
        "/{ref}/test",
        response_model=CheckResult,
        name=f"{tag}check_provider",
        summary="Test a saved provider",
        responses=errors(404, 422, write=True),
    )
    async def check_provider(ref: str, providers: ProvidersDep) -> CheckResult:
        """Run the connection test again; the outcome is kept with the provider (``check_ok``)."""
        return await providers.check(ref)

    @router.post(
        "/{ref}/models/refresh",
        response_model=ProviderRead,
        name=f"{tag}refresh_provider_models",
        summary="Fetch the model list of a provider again",
        responses=errors(404, 409, 422, 502, write=True),
    )
    async def refresh_models(ref: str, providers: ProvidersDep) -> ProviderRead:
        """New models are added switched off; a model the provider no longer lists stays and is
        marked ``available: false``. 409 if the endpoint has no ``/models``."""
        return await providers.refresh_models(ref)

    @router.post(
        "/{ref}/models",
        response_model=ProviderRead,
        status_code=status.HTTP_201_CREATED,
        name=f"{tag}add_provider_model",
        summary="Define a model by hand",
        responses=errors(404, 409, 422, write=True, body=True),
    )
    async def add_model(ref: str, payload: ModelCreate, providers: ProvidersDep) -> ProviderRead:
        """For an OpenAI-compatible provider (409 for OpenRouter, whose models come from its list)."""
        return await providers.add_model(ref, payload)

    @router.patch(
        "/{ref}/models/{model_id}",
        response_model=ProviderRead,
        name=f"{tag}update_provider_model",
        summary="Switch a model on or off",
        responses=errors(404, 422, write=True, body=True),
    )
    async def update_model(
        ref: str, model_id: str, payload: ModelUpdate, providers: ProvidersDep
    ) -> ProviderRead:
        """``enabled`` and ``label``. ``model_id`` is the ``id`` of the model row, not the model's
        name. Only an enabled model can be chosen for an agent."""
        return await providers.update_model(ref, model_id, payload)

    @router.delete(
        "/{ref}/models/{model_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        name=f"{tag}delete_provider_model",
        summary="Delete a model defined by hand",
        responses=errors(404, 409, 422, write=True),
    )
    async def delete_model(ref: str, model_id: str, providers: ProvidersDep) -> Response:
        """409 for a model of the provider's own list (switch it off instead) and while a
        configuration names the model."""
        await providers.delete_model(ref, model_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router


def routers(v1_dependencies: Sequence[Any]) -> list[APIRouter]:
    """The four routers: agents and providers for the browser and for ``/api/v1``."""
    return [
        build_agents_router("/api", ["agents"], "user"),
        build_providers_router("/api", ["providers"]),
        build_agents_router("/api/v1", ["integration API"], "api", v1_dependencies),
        build_providers_router("/api/v1", ["integration API"], v1_dependencies),
    ]
