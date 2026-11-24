"""Agents: the reusable definitions agent nodes refer to, their drafts and their published versions.

An agent has one editable draft and any number of published versions. Only a published version takes
part in a run: saving the draft changes nothing for any execution, publishing copies the draft into a
new version (numbers count up and are never reused) and makes it the one new executions use. Publishing
an earlier version again (a rollback) also makes a new version, whose content is that version's; no
version is ever changed or removed while its agent exists.

An agent cannot be deleted while an agent node refers to it (409, with the nodes). A refusal is an
``ArtifactError``; every change publishes ``agents.changed``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.agents.freeze import load_providers
from openartifact.agents.render import (
    MappingError,
    fill,
    input_problems,
    parse_mapping,
    prompt_problems,
    resolve_inputs,
    unused_inputs,
)
from openartifact.agents.resolve import (
    ProviderInfo,
    overrides_of,
    pick_provider,
    setting_states,
)
from openartifact.agents.schemas import (
    MAX_AGENTS,
    OVERRIDABLE,
    AgentConfig,
    AgentCreate,
    AgentDetail,
    AgentRead,
    AgentUpdate,
    AgentUse,
    PreviewRead,
    PreviewRequest,
    PublishResult,
    VersionRead,
)
from openartifact.artifact_fields.service import field_specs
from openartifact.database import SessionOpener
from openartifact.engine.context import card_problems
from openartifact.events import EventBus
from openartifact.exceptions import ArtifactError
from openartifact.graph.node_types import node_type
from openartifact.models import Agent, AgentVersion, Graph, GraphNode, NodeKind

_AGENT_OF_NODE = func.json_extract(GraphNode.config, "$.agent_id")


def publish_problems(config: AgentConfig, providers: Mapping[str, ProviderInfo]) -> list[str]:
    """Why a configuration cannot be published (empty: it can)."""
    problems: list[str] = []
    config = config.effective()  # what is switched off is not in effect (ADR-045)
    declared = [i.name for i in config.inputs]
    if not config.user_prompt.strip():
        problems.append("The user prompt is empty")
    problems += prompt_problems(config.user_prompt, declared, "User prompt")
    if config.system_prompt_enabled and not config.system_prompt.strip():
        problems.append("The system prompt is switched on but empty")
    problems += prompt_problems(config.system_prompt, declared, "System prompt")
    if config.provider_id and config.provider_id not in providers:
        problems.append("The chosen provider does not exist")
    elif config.model:
        provider, _, found = pick_provider(config.model_dump(), None, providers)
        if provider is None:
            problems.append("A model is chosen but no provider, and there is no default provider")
        else:
            problems += found
    return problems


class AgentService:
    """Everything the APIs do with agents."""

    def __init__(self, session: SessionOpener, bus: EventBus) -> None:
        self._session = session
        self._bus = bus

    # ── reading ───────────────────────────────────────────────────────

    @staticmethod
    async def _find(session: AsyncSession, ref: str) -> Agent:
        found = await session.get(Agent, ref)
        if found is None:
            found = await session.scalar(select(Agent).where(Agent.name == ref.strip()))
        if found is None:
            raise ArtifactError(404, "Agent not found")
        return found

    @staticmethod
    async def _node_counts(session: AsyncSession) -> dict[str, int]:
        rows = await session.execute(
            select(_AGENT_OF_NODE, func.count())
            .where(GraphNode.kind == NodeKind.AGENT.value)
            .group_by(_AGENT_OF_NODE)
        )
        return {str(agent_id): count for agent_id, count in rows if agent_id}

    @staticmethod
    async def _versions(session: AsyncSession, agent: Agent) -> list[AgentVersion]:
        rows = await session.scalars(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent.id)
            .order_by(AgentVersion.number.desc())
        )
        return list(rows)

    @staticmethod
    def _version_read(agent: Agent, row: AgentVersion, *, config: bool = False) -> VersionRead:
        return VersionRead(
            number=row.number,
            published_at=row.published_at,
            published_via=row.published_via,
            source_number=row.source_number,
            current=row.number == agent.published_number,
            config=AgentConfig.loads(row.config) if config else None,
        )

    @staticmethod
    def _read(agent: Agent, published: AgentConfig | None, count: int) -> AgentRead:
        draft = AgentConfig.loads(agent.draft)
        return AgentRead(
            id=agent.id,
            name=agent.name,
            description=agent.description,
            active=agent.active,
            published_number=agent.published_number,
            draft_changed=published is None or draft.dumps() != published.dumps(),
            node_count=count,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

    async def _detail(self, session: AsyncSession, agent: Agent) -> AgentDetail:
        versions = await self._versions(session, agent)
        current = next((v for v in versions if v.number == agent.published_number), None)
        published = AgentConfig.loads(current.config) if current else None
        counts = await self._node_counts(session)
        draft = AgentConfig.loads(agent.draft)
        return AgentDetail(
            **self._read(agent, published, counts.get(agent.id, 0)).model_dump(),
            draft=draft,
            published=published,
            versions=[self._version_read(agent, v) for v in versions],
            problems=publish_problems(draft, await load_providers(session)),
        )

    async def list_all(self) -> list[AgentRead]:
        """All agents by name."""
        async with self._session() as session:
            agents = (await session.scalars(select(Agent).order_by(Agent.name))).all()
            counts = await self._node_counts(session)
            current = {
                (v.agent_id, v.number): v.config
                for v in await session.scalars(select(AgentVersion))
            }
            return [
                self._read(
                    a,
                    AgentConfig.loads(current[(a.id, a.published_number or 0)])
                    if (a.id, a.published_number or 0) in current
                    else None,
                    counts.get(a.id, 0),
                )
                for a in agents
            ]

    async def get(self, ref: str) -> AgentDetail:
        """One agent by id or name, with its draft, its published configuration and its versions."""
        async with self._session() as session:
            return await self._detail(session, await self._find(session, ref))

    async def versions(self, ref: str) -> list[VersionRead]:
        """The published versions, newest first, each with its configuration."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            return [
                self._version_read(agent, v, config=True)
                for v in await self._versions(session, agent)
            ]

    async def version(self, ref: str, number: int) -> VersionRead:
        async with self._session() as session:
            agent = await self._find(session, ref)
            return self._version_read(
                agent, await self._version(session, agent, number), config=True
            )

    @staticmethod
    async def _version(session: AsyncSession, agent: Agent, number: int) -> AgentVersion:
        row = await session.scalar(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent.id, AgentVersion.number == number
            )
        )
        if row is None:
            raise ArtifactError(404, "Version not found")
        return row

    @staticmethod
    async def _uses(session: AsyncSession, agent_id: str) -> list[AgentUse]:
        rows = await session.execute(
            select(GraphNode, Graph)
            .join(Graph, Graph.id == GraphNode.graph_id)
            .where(GraphNode.kind == NodeKind.AGENT.value, _AGENT_OF_NODE == agent_id)  # noqa: SIM300
            .order_by(Graph.name, GraphNode.name)
        )
        return [
            AgentUse(
                node_id=node.id,
                node_name=node.name,
                graph_id=graph.id,
                graph_name=graph.name,
                graph_slug=graph.slug,
                overrides=sorted(overrides_of(node.config)),
            )
            for node, graph in rows
        ]

    async def uses(self, ref: str) -> list[AgentUse]:
        """The agent nodes that refer to the agent, with the fields each sets for itself."""
        async with self._session() as session:
            return await self._uses(session, (await self._find(session, ref)).id)

    # ── changing ──────────────────────────────────────────────────────

    def _changed(self) -> None:
        self._bus.publish("agents.changed", {})

    @staticmethod
    async def _free_name(session: AsyncSession, name: str, own_id: str | None = None) -> str:
        name = name.strip()
        if not name:
            raise ArtifactError(422, "An agent needs a name")
        taken = await session.scalar(select(Agent).where(Agent.name == name))
        if taken is not None and taken.id != own_id:
            raise ArtifactError(409, f'An agent named "{taken.name}" exists already')
        return name

    async def create(self, data: AgentCreate) -> AgentDetail:
        """Create an agent with a draft (nothing is published yet); 409 for a name that exists."""
        async with self._session() as session:
            count = await session.scalar(select(func.count()).select_from(Agent))
            if (count or 0) >= MAX_AGENTS:
                raise ArtifactError(409, f"At most {MAX_AGENTS} agents")
            agent = Agent(
                id=str(uuid.uuid4()),
                name=await self._free_name(session, data.name),
                description=data.description,
                active=data.active,
                draft=(data.draft or AgentConfig()).dumps(),
            )
            session.add(agent)
            try:
                await session.commit()
            except IntegrityError as error:  # two requests with the same name at once
                raise ArtifactError(409, "An agent with this name exists already") from error
            detail = await self._detail(session, agent)
        self._changed()
        return detail

    async def update(self, ref: str, data: AgentUpdate) -> AgentDetail:
        """Rename, describe, or switch an agent on or off. Switching it off takes effect for the
        executions that start from then on; one that is running keeps what it started with."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            if data.name is not None:
                agent.name = await self._free_name(session, data.name, agent.id)
            if data.description is not None:
                agent.description = data.description
            if data.active is not None:
                agent.active = data.active
            await session.commit()
            detail = await self._detail(session, agent)
        self._changed()
        return detail

    async def save_draft(self, ref: str, config: AgentConfig) -> AgentDetail:
        """Replace the draft. Nothing that runs reads it; ``problems`` says what publishing would refuse."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            agent.draft = config.dumps()
            agent.updated_at = datetime.now(UTC)
            await session.commit()
            detail = await self._detail(session, agent)
        self._changed()
        return detail

    async def discard_draft(self, ref: str) -> AgentDetail:
        """Make the draft equal to the published version again (409 if nothing is published)."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            if agent.published_number is None:
                raise ArtifactError(
                    409, "Nothing is published yet, so there is nothing to go back to"
                )
            current = await self._version(session, agent, agent.published_number)
            agent.draft = AgentConfig.loads(current.config).dumps()
            agent.updated_at = datetime.now(UTC)
            await session.commit()
            detail = await self._detail(session, agent)
        self._changed()
        return detail

    async def _new_version(
        self,
        session: AsyncSession,
        agent: Agent,
        config: AgentConfig,
        via: str,
        source_number: int | None,
    ) -> PublishResult:
        before = None
        if agent.published_number is not None:
            before = AgentConfig.loads(
                (await self._version(session, agent, agent.published_number)).config
            )
        agent.version_seq += 1
        row = AgentVersion(
            id=str(uuid.uuid4()),
            agent_id=agent.id,
            number=agent.version_seq,
            config=config.dumps(),
            source_number=source_number,
            published_via=via,
        )
        session.add(row)
        agent.published_number = row.number
        agent.updated_at = datetime.now(UTC)
        await session.flush()
        old: dict[str, Any] = before.model_dump() if before else {}
        new = config.model_dump()
        changed = [k for k in (*OVERRIDABLE, "inputs") if before and old.get(k) != new.get(k)]
        uses = await self._uses(session, agent.id)
        await session.commit()
        return PublishResult(
            agent=await self._detail(session, agent),
            version=self._version_read(agent, row, config=True),
            changed=changed,
            overriding=[u for u in uses if set(u.overrides) & set(changed)],
        )

    async def publish(self, ref: str, via: str) -> PublishResult:
        """Publish the draft as a new version (422 with the reasons if it is not complete).

        Executions that start from now on use it; nodes keep the fields they set for themselves
        (``overriding`` lists those that override a field this version changed)."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            config = AgentConfig.loads(agent.draft)
            if problems := publish_problems(config, await load_providers(session)):
                raise ArtifactError(422, "\n".join(problems))
            result = await self._new_version(session, agent, config, via, None)
        self._changed()
        return result

    async def republish(self, ref: str, number: int, via: str) -> PublishResult:
        """Publish an earlier version again (a rollback): a new version with that version's content.

        The history stays as it is. A draft without changes of its own follows to the republished
        content; a draft that was being edited is kept."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            source = await self._version(session, agent, number)
            if agent.published_number == number:
                raise ArtifactError(409, f"Version {number} is the published one already")
            config = AgentConfig.loads(source.config)
            if problems := publish_problems(config, await load_providers(session)):
                raise ArtifactError(
                    422, f"Version {number} cannot be published now:\n" + "\n".join(problems)
                )
            current = await self._version(session, agent, agent.published_number or number)
            if AgentConfig.loads(agent.draft).dumps() == AgentConfig.loads(current.config).dumps():
                agent.draft = config.dumps()
            result = await self._new_version(session, agent, config, via, number)
        self._changed()
        return result

    async def delete(self, ref: str) -> None:
        """Delete an agent with its versions; 409 (naming the nodes) while agent nodes refer to it."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            uses = await self._uses(session, agent.id)
            if uses:
                where = ", ".join(f'"{u.node_name}" in action "{u.graph_name}"' for u in uses[:5])
                more = f" and {len(uses) - 5} more" if len(uses) > 5 else ""
                nodes = (
                    "1 agent node refers" if len(uses) == 1 else f"{len(uses)} agent nodes refer"
                )
                raise ArtifactError(409, f"{nodes} to this agent: {where}{more}")
            await session.delete(agent)
            await session.commit()
        self._changed()

    # ── preview ───────────────────────────────────────────────────────

    async def preview(self, ref: str, request: PreviewRequest) -> PreviewRead:
        """The prompts as they would be sent, without sending anything.

        The same functions as a run: the node's overrides (with ``node_id``), the input mapping, the
        types and the placeholders. A mapping that reads the run context cannot be known here: such an
        input is ``pending`` and keeps its placeholder unless ``values`` gives an example for it."""
        async with self._session() as session:
            agent = await self._find(session, ref)
            if request.version is not None:
                number: int | None = request.version
                config = AgentConfig.loads(
                    (await self._version(session, agent, request.version)).config
                )
            elif request.source == "published":
                if agent.published_number is None:
                    raise ArtifactError(409, "Nothing is published yet")
                number = agent.published_number
                config = AgentConfig.loads((await self._version(session, agent, number)).config)
            else:
                number, config = None, AgentConfig.loads(agent.draft)
            node_config: dict[str, Any] = {}
            if request.node_id:
                node = await session.get(GraphNode, request.node_id)
                if node is None or node.kind != NodeKind.AGENT.value:
                    raise ArtifactError(404, "Agent node not found")
                node_config = node_type(node.kind).effective_config(node.config)
                if node_config.get("agent_id") != agent.id:
                    raise ArtifactError(422, "The node refers to another agent")
            providers = await load_providers(session)
            card_fields = {spec.name for spec in await field_specs(session)}
        config = config.effective()
        data = config.model_dump()
        problems: list[str] = []
        try:
            mapping = parse_mapping(str(node_config.get("inputs") or ""))
        except MappingError as error:
            mapping = {}
            problems.append(f"Input mapping: {error}")
        states = resolve_inputs(data["inputs"], mapping, None, samples=request.values)
        problems += input_problems(states)
        problems += card_problems("\n".join(mapping.values()), card_fields)
        settings = setting_states(data, node_config)
        value = {s.key: s.value for s in settings}
        declared = [i.name for i in config.inputs]
        user = str(value["user_prompt"] or "")
        system = str(value["system_prompt"] or "")
        problems += unused_inputs(
            mapping,
            [user, system if value["system_prompt_enabled"] else ""],
            declared,
            _artifact_names(config),
        )
        if not user.strip():
            problems.append("The user prompt is empty")
        problems += prompt_problems(user, declared, "User prompt")
        shown_system = None
        if value["system_prompt_enabled"] and system.strip():
            problems += prompt_problems(system, declared, "System prompt")
            shown_system = fill(system, states, preview=True)
        provider, model, found = pick_provider(data, node_config, providers)
        return PreviewRead(
            agent_id=agent.id,
            version=number,
            system_prompt=shown_system,
            user_prompt=fill(user, states, preview=True),
            inputs=states,
            settings=settings,
            provider=provider.name if provider else None,
            model=model,
            problems=list(dict.fromkeys(problems + found)),
        )


async def artifact_inputs_mapped(session: AsyncSession, agent_id: str, text: str) -> list[str]:
    """The inputs of the agent's published version (its draft when nothing is published) that come from the artifact
    and that the mapping ``text`` of a node maps anyway: a node cannot override them (ADR-064)."""
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return []
    if agent.published_number is None:
        config = AgentConfig.loads(agent.draft)
    else:
        config = AgentConfig.loads(
            await session.scalar(
                select(AgentVersion.config).where(
                    AgentVersion.agent_id == agent.id,
                    AgentVersion.number == agent.published_number,
                )
            )
        )
    try:
        mapped = parse_mapping(text)
    except MappingError:
        return []
    return [n for n in _artifact_names(config.effective()) if mapped.get(n, "").strip()]


def _artifact_names(config: AgentConfig) -> list[str]:
    """The inputs of the agent that come from the artifact (fixed by the definition, ADR-064)."""
    return [i.name for i in config.inputs if i.source == "artifact"]


async def node_hints(session: AsyncSession, node: GraphNode) -> list[str]:
    """Hints about an agent node when it is saved (it is saved anyway): an agent that is missing,
    unpublished or inactive, inputs that are not mapped or not declared, a model that cannot be used."""
    config = node_type(node.kind).effective_config(node.config)
    agent_id = str(config.get("agent_id") or "")
    if not agent_id:
        return ["No agent is chosen"]
    agent = await session.get(Agent, agent_id)
    if agent is None:
        return ["The chosen agent does not exist"]
    hints = []
    if not agent.active:
        hints.append(f'Agent "{agent.name}" is inactive: the node will fail')
    if agent.published_number is None:
        return [*hints, f'Agent "{agent.name}" has no published version: the node will fail']
    published = AgentConfig.loads(
        await session.scalar(
            select(AgentVersion.config).where(
                AgentVersion.agent_id == agent.id,
                AgentVersion.number == agent.published_number,
            )
        )
    ).effective()
    data = published.model_dump()
    try:
        mapping = parse_mapping(str(config.get("inputs") or ""))
    except MappingError as error:
        return [*hints, f"Input mapping: {error}"]
    hints += input_problems(resolve_inputs(data["inputs"], mapping, None))
    declared = [i.name for i in published.inputs]
    for key, what in (("user_prompt", "User prompt"), ("system_prompt", "System prompt")):
        if config.get(key) is not None:
            hints += prompt_problems(str(config[key]), declared, what)
    own = {k: config.get(k) for k in ("user_prompt", "system_prompt")}
    hints += unused_inputs(
        mapping,
        [str(own[k] if own[k] is not None else data[k] or "") for k in own],
        declared,
        _artifact_names(published),
    )
    hints += pick_provider(data, config, await load_providers(session))[2]
    return list(dict.fromkeys(hints))
