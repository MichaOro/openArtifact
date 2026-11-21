"""Workflow definition API (prefix ``/api/workflows``).

Every change is saved at once (there is no separate "save"): the editor sends what the user did.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from openartifact.database import get_db_session
from openartifact.models import Workflow, WorkflowNode
from openartifact.workflow.repository import NodeError, WorkflowRepository
from openartifact.workflow.rules import EdgeError
from openartifact.workflow.schemas import (
    EdgeCreate,
    EdgeRead,
    EdgeUpdate,
    NodeCreate,
    NodeRead,
    NodeUpdate,
    WorkflowCreate,
    WorkflowDetail,
    WorkflowKind,
    WorkflowRead,
    WorkflowUpdate,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _invalid(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(error))


async def _node_reads(repo: WorkflowRepository, nodes: Sequence[WorkflowNode]) -> list[NodeRead]:
    """Nodes as the API returns them, linked actions with their definition's name and On Fail."""
    described = await repo.describe(nodes)
    reads = [NodeRead.model_validate(n) for n in nodes]
    for read in reads:
        if read.id in described:
            read.definition_name, read.definition_fail_enabled = described[read.id]
    return reads


async def _workflow(repo: WorkflowRepository, workflow_id: str) -> Workflow:
    workflow = await repo.get(workflow_id)
    if workflow is None:
        raise _not_found("Workflow")
    return workflow


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    session: SessionDep, kind: WorkflowKind = "workflow"
) -> list[WorkflowRead]:
    """List all workflows (``kind=action``: the action definitions), most recently changed first."""
    workflows = await WorkflowRepository(session).list_all(kind)
    return [WorkflowRead.model_validate(w) for w in workflows]


@router.post("", response_model=WorkflowRead, status_code=status.HTTP_201_CREATED)
async def create_workflow(payload: WorkflowCreate, session: SessionDep) -> WorkflowRead:
    """Create a workflow; it starts with a trigger (an action definition also with its output)."""
    workflow = await WorkflowRepository(session).create(payload.name, payload.kind)
    await session.commit()
    return WorkflowRead.model_validate(workflow)


@router.get("/{workflow_id}", response_model=WorkflowDetail)
async def get_workflow(workflow_id: str, session: SessionDep) -> WorkflowDetail:
    """A workflow with all its nodes and edges."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    nodes, edges = await repo.graph(workflow_id)
    return WorkflowDetail(
        workflow=WorkflowRead.model_validate(workflow),
        nodes=await _node_reads(repo, nodes),
        edges=[EdgeRead.model_validate(e) for e in edges],
    )


@router.patch("/{workflow_id}", response_model=WorkflowRead)
async def rename_workflow(
    workflow_id: str, payload: WorkflowUpdate, session: SessionDep
) -> WorkflowRead:
    """Rename a workflow."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    await repo.rename(workflow, payload.name)
    await session.commit()
    return WorkflowRead.model_validate(workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(workflow_id: str, session: SessionDep) -> Response:
    """Delete a workflow with everything in it."""
    repo = WorkflowRepository(session)
    await repo.delete(await _workflow(repo, workflow_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/nodes", response_model=NodeRead, status_code=status.HTTP_201_CREATED)
async def add_node(workflow_id: str, payload: NodeCreate, session: SessionDep) -> NodeRead:
    """Add a trigger, stage, action (inside a stage) or complete node."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    try:
        node = await repo.add_node(workflow, payload)
    except NodeError as error:
        raise _invalid(error) from error
    await repo.touch(workflow)
    await session.commit()
    return (await _node_reads(repo, [node]))[0]


@router.patch("/{workflow_id}/nodes/{node_id}", response_model=NodeRead)
async def update_node(
    workflow_id: str, node_id: str, payload: NodeUpdate, session: SessionDep
) -> NodeRead:
    """Rename, move or resize a node."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    node = await repo.get_node(workflow_id, node_id)
    if node is None:
        raise _not_found("Node")
    try:
        await repo.update_node(node, payload)
    except NodeError as error:
        raise _invalid(error) from error
    await repo.touch(workflow)
    await session.commit()
    return (await _node_reads(repo, [node]))[0]


@router.delete("/{workflow_id}/nodes/{node_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_node(workflow_id: str, node_id: str, session: SessionDep) -> Response:
    """Delete a node with its edges (and, for a stage, its actions)."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    node = await repo.get_node(workflow_id, node_id)
    if node is None:
        raise _not_found("Node")
    try:
        await repo.delete_node(workflow, node)
    except NodeError as error:
        raise _invalid(error) from error
    await repo.touch(workflow)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{workflow_id}/edges", response_model=EdgeRead, status_code=status.HTTP_201_CREATED)
async def connect(workflow_id: str, payload: EdgeCreate, session: SessionDep) -> EdgeRead:
    """Connect an output port to an input port; the output's previous edge is replaced."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    try:
        edge = await repo.connect(workflow, payload)
    except (NodeError, EdgeError) as error:
        raise _invalid(error) from error
    await repo.touch(workflow)
    await session.commit()
    return EdgeRead.model_validate(edge)


@router.patch("/{workflow_id}/edges/{edge_id}", response_model=EdgeRead)
async def restyle_edge(
    workflow_id: str, edge_id: str, payload: EdgeUpdate, session: SessionDep
) -> EdgeRead:
    """Change how a connection is drawn (curved, straight or elbow)."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    edge = await repo.get_edge(workflow_id, edge_id)
    if edge is None:
        raise _not_found("Edge")
    await repo.restyle(edge, payload)
    await repo.touch(workflow)
    await session.commit()
    return EdgeRead.model_validate(edge)


@router.delete("/{workflow_id}/edges/{edge_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(workflow_id: str, edge_id: str, session: SessionDep) -> Response:
    """Remove a connection."""
    repo = WorkflowRepository(session)
    workflow = await _workflow(repo, workflow_id)
    edge = await repo.get_edge(workflow_id, edge_id)
    if edge is None:
        raise _not_found("Edge")
    await repo.disconnect(edge)
    await repo.touch(workflow)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
