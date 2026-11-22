"""Reading agents and providers for a run: what an execution freezes at its start.

:func:`freeze_agents` resolves every agent node of a snapshot once, when the execution starts: the
published version of its agent, whether the agent is active, the provider and the model in effect and
the node's overrides (``agents/resolve.py``). The result is stored on the node (``node["agent"]``) in
the snapshot, so an execution keeps what it started with: publishing a new version, switching an agent
off, changing or deleting a provider later does not touch it. Only the name of the provider's secret is
frozen; its value is read when the node runs.

A node that cannot be resolved (no agent, nothing published, inactive, no usable model) does not stop
the start: it is frozen with an ``error`` and fails with that reason when the run reaches it.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents import client
from openartifact.agents.resolve import ProviderInfo, freeze
from openartifact.models import Agent, AgentVersion, LlmModel, LlmProvider, NodeKind, ProviderKind


def base_url_of(provider: LlmProvider) -> str:
    """The address requests go to: fixed for OpenRouter, the stored one otherwise."""
    return (
        client.OPENROUTER_URL
        if provider.kind == ProviderKind.OPENROUTER
        else (provider.base_url or "")
    )


async def load_providers(session: AsyncSession) -> dict[str, ProviderInfo]:
    """Every provider with the models that may be used (enabled and still listed)."""
    usable: dict[str, set[str]] = {}
    for provider_id, model_id in await session.execute(
        select(LlmModel.provider_id, LlmModel.model_id).where(
            LlmModel.enabled.is_(True), LlmModel.available.is_(True)
        )
    ):
        usable.setdefault(provider_id, set()).add(model_id)
    return {
        p.id: ProviderInfo(
            id=p.id,
            kind=p.kind,
            name=p.name,
            base_url=base_url_of(p),
            secret_name=p.secret_name,
            allow_private=p.allow_private,
            default_model=p.default_model,
            is_default=p.is_default,
            models=frozenset(usable.get(p.id, ())),
        )
        for p in await session.scalars(select(LlmProvider))
    }


async def published(session: AsyncSession, agent_ids: set[str]) -> dict[str, dict[str, Any]]:
    """``{agent id: {"id", "name", "active", "version", "config"}}`` of the published versions."""
    found: dict[str, dict[str, Any]] = {}
    if not agent_ids:
        return found
    for agent in await session.scalars(select(Agent).where(Agent.id.in_(agent_ids))):
        found[agent.id] = {
            "id": agent.id,
            "name": agent.name,
            "active": agent.active,
            "version": agent.published_number,
            "config": None,
        }
        if agent.published_number is not None:
            config = await session.scalar(
                select(AgentVersion.config).where(
                    AgentVersion.agent_id == agent.id,
                    AgentVersion.number == agent.published_number,
                )
            )
            found[agent.id]["config"] = json.loads(config) if config else None
    return found


def _agent_nodes(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        node
        for definition in snapshot.get("definitions", {}).values()
        for node in definition["nodes"]
        if node["kind"] == NodeKind.AGENT
    ]


async def freeze_agents(session: AsyncSession, snapshot: dict[str, Any]) -> None:
    """Put the resolved agent on every agent node of the snapshot's action definitions."""
    nodes = _agent_nodes(snapshot)
    if not nodes:
        return
    wanted = {str(n["config"].get("agent_id")) for n in nodes if n["config"].get("agent_id")}
    agents = await published(session, wanted)
    providers = await load_providers(session)
    for node in nodes:
        agent = agents.get(str(node["config"].get("agent_id") or ""))
        node["agent"] = freeze(agent, node["config"], providers)
