"""Persistence for workflow definitions. Receives an ``AsyncSession``; never creates its own."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.models import NodeKind, Workflow, WorkflowEdge, WorkflowNode
from openartifact.workflow.rules import Endpoint, validate_edge
from openartifact.workflow.schemas import EdgeCreate, EdgeUpdate, NodeCreate, NodeUpdate

DEFAULT_NAMES = {
    NodeKind.TRIGGER: "Trigger",
    NodeKind.STAGE: "Stage",
    NodeKind.ACTION: "Action",
    NodeKind.COMPLETE: "Complete",
    NodeKind.OUTPUT: "Output",
}
# what an action definition is made of: only these may be added by hand, the first two are fixed
WORKFLOW_KINDS = {NodeKind.TRIGGER, NodeKind.STAGE, NodeKind.ACTION, NodeKind.COMPLETE}
ACTION_KINDS = {NodeKind.TRIGGER, NodeKind.OUTPUT}
FIXED_KINDS = {NodeKind.TRIGGER, NodeKind.OUTPUT}
STAGE_SIZE = (360.0, 240.0)


class NodeError(ValueError):
    """The requested node (or change of it) is not valid."""


class WorkflowRepository:
    """Database access for workflows, their nodes and edges."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── workflows ─────────────────────────────────────────────────────

    async def create(self, name: str, kind: str = "workflow") -> Workflow:
        """Create a workflow with a trigger, because every workflow starts with one.

        An action definition also gets its output node: it always has an input and outcomes.
        """
        workflow = Workflow(id=str(uuid.uuid4()), name=name, kind=kind)
        self._session.add(workflow)
        kinds = [(NodeKind.TRIGGER, 60.0)] + (
            [(NodeKind.OUTPUT, 460.0)] if kind == "action" else []
        )
        for node_kind, x in kinds:
            self._session.add(
                WorkflowNode(
                    id=str(uuid.uuid4()),
                    workflow_id=workflow.id,
                    kind=node_kind.value,
                    name=DEFAULT_NAMES[node_kind],
                    x=x,
                    y=160.0,
                )
            )
        await self._session.flush()
        return workflow

    async def list_all(self, kind: str = "workflow") -> Sequence[Workflow]:
        """All workflows (or action definitions), most recently changed first."""
        result = await self._session.execute(
            select(Workflow)
            .where(Workflow.kind == kind)
            .order_by(Workflow.updated_at.desc(), Workflow.id)
        )
        return result.scalars().all()

    async def get(self, workflow_id: str) -> Workflow | None:
        """The workflow or ``None``."""
        return await self._session.get(Workflow, workflow_id)

    async def rename(self, workflow: Workflow, name: str) -> None:
        """Change the name."""
        workflow.name = name
        await self._session.flush()

    async def delete(self, workflow: Workflow) -> None:
        """Delete the workflow; its nodes and edges go with it (foreign key cascade)."""
        await self._session.delete(workflow)
        await self._session.flush()

    async def graph(
        self, workflow_id: str
    ) -> tuple[Sequence[WorkflowNode], Sequence[WorkflowEdge]]:
        """All nodes and edges of a workflow."""
        nodes = await self._session.execute(
            select(WorkflowNode)
            .where(WorkflowNode.workflow_id == workflow_id)
            .order_by(WorkflowNode.created_at, WorkflowNode.id)
        )
        edges = await self._session.execute(
            select(WorkflowEdge)
            .where(WorkflowEdge.workflow_id == workflow_id)
            .order_by(WorkflowEdge.id)
        )
        return nodes.scalars().all(), edges.scalars().all()

    async def touch(self, workflow: Workflow) -> None:
        """Mark the workflow as changed (its nodes or edges changed)."""
        workflow.updated_at = datetime.now(UTC)
        await self._session.flush()

    # ── nodes ─────────────────────────────────────────────────────────

    async def get_node(self, workflow_id: str, node_id: str) -> WorkflowNode | None:
        """The node if it belongs to the workflow."""
        node = await self._session.get(WorkflowNode, node_id)
        return node if node is not None and node.workflow_id == workflow_id else None

    async def add_node(self, workflow: Workflow, data: NodeCreate) -> WorkflowNode:
        """Add a node. Actions must name a stage of the same workflow."""
        if data.kind not in (ACTION_KINDS if workflow.kind == "action" else WORKFLOW_KINDS):
            raise NodeError(f"A {workflow.kind} cannot contain a {data.kind.value}")
        if data.kind in FIXED_KINDS and workflow.kind == "action":
            raise NodeError(f"An action definition has exactly one {data.kind.value}")
        if data.kind is NodeKind.ACTION:
            stage = data.stage_id and await self.get_node(workflow.id, data.stage_id)
            if not stage or stage.kind != NodeKind.STAGE.value:
                raise NodeError("An action needs a stage of this workflow")
        elif data.stage_id is not None:
            raise NodeError("Only actions belong to a stage")
        node = WorkflowNode(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            kind=data.kind.value,
            stage_id=data.stage_id,
            name=data.name or DEFAULT_NAMES[data.kind],
            x=data.x,
            y=data.y,
            width=STAGE_SIZE[0] if data.kind is NodeKind.STAGE else None,
            height=STAGE_SIZE[1] if data.kind is NodeKind.STAGE else None,
        )
        self._session.add(node)
        await self._session.flush()
        return node

    async def update_node(self, node: WorkflowNode, data: NodeUpdate) -> None:
        """Rename, move or (stages) resize a node."""
        sent = data.model_fields_set
        if {"width", "height"} & sent and node.kind != NodeKind.STAGE.value:
            raise NodeError("Only stages have a size")
        if "fail_enabled" in sent and node.kind != NodeKind.OUTPUT.value:
            raise NodeError("Only an output has On Fail")
        for field in ("name", "x", "y", "width", "height", "fail_enabled"):
            value = getattr(data, field)
            if field in sent and value is not None:
                setattr(node, field, value)
        await self._session.flush()

    async def delete_node(self, workflow: Workflow, node: WorkflowNode) -> None:
        """Delete a node; its actions (for a stage) and edges go with it (cascade)."""
        if workflow.kind == "action" and NodeKind(node.kind) in FIXED_KINDS:
            raise NodeError("The trigger and the output of an action definition stay")
        await self._session.delete(node)
        await self._session.flush()

    # ── edges ─────────────────────────────────────────────────────────

    async def connect(self, workflow: Workflow, data: EdgeCreate) -> WorkflowEdge:
        """Connect two ports; an existing edge on the same output is replaced."""
        source = await self.get_node(workflow.id, data.source_id)
        target = await self.get_node(workflow.id, data.target_id)
        if source is None or target is None:
            raise NodeError("Both ends of an edge must be nodes of this workflow")
        validate_edge(_endpoint(source), data.source_port, _endpoint(target), data.target_port)
        if (data.source_slot and source.kind != NodeKind.STAGE.value) or (
            data.target_slot and target.kind != NodeKind.STAGE.value
        ):
            raise NodeError("Only stages have more than one attachment point")
        await self._session.execute(
            delete(WorkflowEdge).where(
                WorkflowEdge.source_id == source.id, WorkflowEdge.source_port == data.source_port
            )
        )
        edge = WorkflowEdge(
            id=str(uuid.uuid4()),
            workflow_id=workflow.id,
            source_id=source.id,
            source_port=data.source_port,
            target_id=target.id,
            target_port=data.target_port,
            style=data.style,
            source_slot=data.source_slot,
            target_slot=data.target_slot,
        )
        self._session.add(edge)
        await self._session.flush()
        return edge

    async def get_edge(self, workflow_id: str, edge_id: str) -> WorkflowEdge | None:
        """The edge if it belongs to the workflow."""
        edge = await self._session.get(WorkflowEdge, edge_id)
        return edge if edge is not None and edge.workflow_id == workflow_id else None

    async def restyle(self, edge: WorkflowEdge, data: EdgeUpdate) -> None:
        """Change how an edge is drawn."""
        edge.style = data.style
        await self._session.flush()

    async def disconnect(self, edge: WorkflowEdge) -> None:
        """Remove an edge."""
        await self._session.delete(edge)
        await self._session.flush()


def _endpoint(node: WorkflowNode) -> Endpoint:
    return Endpoint(id=node.id, kind=NodeKind(node.kind), stage_id=node.stage_id)
