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

from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents import client
from openartifact.agents.resolve import ProviderInfo, freeze
from openartifact.agents.schemas import AgentConfig
from openartifact.agents.tool_config import default_tool_name
from openartifact.graph.node_types import Ports
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
            allow_http=p.allow_http,
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
            # what is switched off is not in effect (ADR-045)
            found[agent.id]["config"] = (
                AgentConfig.loads(config).effective().model_dump(mode="json") if config else None
            )
    return found


def _agent_nodes(snapshot: Mapping[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Every agent node of the snapshot's action definitions, with its definition."""
    return [
        (node, definition)
        for definition in snapshot.get("definitions", {}).values()
        for node in definition["nodes"]
        if node["kind"] == NodeKind.AGENT
    ]


def _tools(agent: Mapping[str, Any], definition: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The tool nodes attached to ``agent`` (edges to its Tools port), left to right as they are drawn, then by
    name (ADR-040): the order the model sees them in does not depend on how the edges were stored."""
    nodes = {n["id"]: n for n in definition["nodes"]}
    found = []
    for edge in definition["edges"]:
        if edge["target_id"] != agent["id"] or edge["target_port"] != Ports.TOOLS:
            continue
        tool = nodes.get(edge["source_id"])
        if tool is None:
            continue
        config = tool.get("config") or {}
        found.append(
            {
                "node_id": tool["id"],
                "name": tool["name"],
                "kind": str(tool["kind"]),
                "tool_name": str(config.get("tool_name") or "") or default_tool_name(tool["name"]),
                "config": config,
                "_at": (tool.get("x") or 0.0, tool["name"]),
            }
        )
    found.sort(key=lambda t: t["_at"])
    for tool in found:
        del tool["_at"]
    return found


async def freeze_agents(session: AsyncSession, snapshot: dict[str, Any]) -> None:
    """Put the resolved agent on every agent node of the snapshot's action definitions."""
    nodes = _agent_nodes(snapshot)
    if not nodes:
        return
    wanted = {str(n["config"].get("agent_id")) for n, _ in nodes if n["config"].get("agent_id")}
    agents = await published(session, wanted)
    providers = await load_providers(session)
    for node, definition in nodes:
        agent = agents.get(str(node["config"].get("agent_id") or ""))
        node["agent"] = freeze(agent, node["config"], providers)
        node["agent"]["tools"] = _tools(node, definition)
