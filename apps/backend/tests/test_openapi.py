"""The OpenAPI document is the public contract: every operation is described, the gated ones declare
401, only the API (no HTML page) is in it, every JSON answer has a model, and the contract does not
change by accident (update ``CONTRACT`` when you change a route on purpose)."""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from fastapi.routing import APIRoute

from openartifact.app import _create_app
from tests.helpers import bare_settings

METHODS = ("get", "put", "post", "delete", "patch")
#: Operations without a response model on purpose: an event stream.
NO_MODEL_ALLOWED = {("GET", "/api/events")}
#: Open without a token (the access gate lets them through).
OPEN_OPERATIONS = {("GET", "/health")}
HTML_PATHS = {"/", "/pipelines", "/actions", "/executions", "/login", "/logout"}

# "METHOD path -> model of the success answer" (``[]``: a list, ``-``: no body or a stream)
CONTRACT = """\
DELETE /api/actions/{graph_id} -> -
DELETE /api/actions/{graph_id}/edges/{edge_id} -> -
DELETE /api/actions/{graph_id}/nodes/{node_id} -> -
DELETE /api/lanes/{status} -> LaneRead[]
DELETE /api/pipelines/{graph_id} -> -
DELETE /api/pipelines/{graph_id}/edges/{edge_id} -> -
DELETE /api/pipelines/{graph_id}/nodes/{node_id} -> -
DELETE /api/secrets/{name} -> -
DELETE /api/tasks/{task_id} -> -
DELETE /api/tasks/{task_id}/executions -> DeletedCount
DELETE /api/tasks/{task_id}/executions/{execution_id} -> -
DELETE /api/v1/artifacts/{ref} -> -
DELETE /api/v1/artifacts/{ref}/executions/{execution_id} -> -
DELETE /api/v1/lanes/{status} -> LaneRead[]
DELETE /api/v1/secrets/{name} -> -
GET /api/actions -> GraphRead[]
GET /api/actions/{graph_id} -> GraphDetail
GET /api/events -> -
GET /api/executions -> ExecutionsPage
GET /api/info -> InfoRead
GET /api/lanes -> LaneRead[]
GET /api/node-types -> NodeTypeRead[]
GET /api/pipelines -> GraphRead[]
GET /api/pipelines/{graph_id} -> GraphDetail
GET /api/pipelines/{graph_id}/stages -> ChainEntryRead[]
GET /api/runs -> RunRead[]
GET /api/runs/{task_id}/results -> NodeResultRead[]
GET /api/secrets -> SecretRead[]
GET /api/secrets/{name}/uses -> SecretUse[]
GET /api/tasks -> TaskRead[]
GET /api/tasks/{task_id} -> TaskRead
GET /api/tasks/{task_id}/executions -> ExecutionList
GET /api/tasks/{task_id}/executions/{execution_id} -> ExecutionDetail
GET /api/tasks/{task_id}/executions/{execution_id}/context -> RunContextRead
GET /api/tasks/{task_id}/executions/{execution_id}/flow -> ExecutionFlow
GET /api/tasks/{task_id}/executions/{execution_id}/steps/{step_id} -> ExecutionStepRead
GET /api/v1/artifacts -> TaskRead[]
GET /api/v1/artifacts/{ref} -> TaskRead
GET /api/v1/artifacts/{ref}/executions -> ExecutionList
GET /api/v1/artifacts/{ref}/executions/{execution_id} -> ExecutionDetail
GET /api/v1/artifacts/{ref}/executions/{execution_id}/context -> RunContextRead
GET /api/v1/artifacts/{ref}/executions/{execution_id}/flow -> ExecutionFlow
GET /api/v1/artifacts/{ref}/executions/{execution_id}/steps/{step_id} -> ExecutionStepRead
GET /api/v1/artifacts/{ref}/run -> RunRead
GET /api/v1/artifacts/{ref}/run/results -> NodeResultRead[]
GET /api/v1/executions -> ExecutionsPage
GET /api/v1/lanes -> LaneRead[]
GET /api/v1/pipelines -> PipelineChainRead[]
GET /api/v1/secrets -> SecretRead[]
GET /health -> HealthRead
PATCH /api/actions/{graph_id} -> GraphRead
PATCH /api/actions/{graph_id}/edges/{edge_id} -> EdgeRead
PATCH /api/actions/{graph_id}/nodes/{node_id} -> NodeRead
PATCH /api/pipelines/{graph_id} -> GraphRead
PATCH /api/pipelines/{graph_id}/edges/{edge_id} -> EdgeRead
PATCH /api/pipelines/{graph_id}/nodes/{node_id} -> NodeRead
PATCH /api/tasks/{task_id} -> TaskRead
PATCH /api/v1/artifacts/{ref} -> TaskRead
POST /api/actions -> GraphRead
POST /api/actions/{graph_id}/edges -> EdgeRead
POST /api/actions/{graph_id}/nodes -> NodeRead
POST /api/lanes -> LaneRead[]
POST /api/pipelines -> GraphRead
POST /api/pipelines/{graph_id}/edges -> EdgeRead
POST /api/pipelines/{graph_id}/nodes -> NodeRead
POST /api/tasks -> TaskRead
POST /api/tasks/{task_id}/run -> RunRead
POST /api/tasks/{task_id}/run/stop -> RunRead
POST /api/v1/artifacts -> TaskRead
POST /api/v1/artifacts/{ref}/run -> RunRead
POST /api/v1/artifacts/{ref}/run/stop -> RunRead
POST /api/v1/lanes -> LaneRead[]
PUT /api/lanes/{status} -> LaneRead[]
PUT /api/secrets/{name} -> SecretRead
PUT /api/tasks/{task_id}/history-policy -> HistoryPolicyResult
PUT /api/v1/artifacts/{ref}/history-policy -> HistoryPolicyResult
PUT /api/v1/lanes/{status} -> LaneRead[]
PUT /api/v1/secrets/{name} -> SecretRead
""".splitlines()


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # the document is generated without a single warning
        return _create_app(bare_settings()).openapi()


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    return [
        (method.upper(), path, op)
        for path, ops in schema["paths"].items()
        for method, op in ops.items()
        if method in METHODS
    ]


def _model(op: dict[str, Any]) -> str:
    for code, response in op["responses"].items():
        if code.startswith("2"):
            content = response.get("content", {}).get("application/json", {}).get("schema")
            if not content:
                return "-"
            if "$ref" in content:
                return str(content["$ref"]).rsplit("/", 1)[1]
            if content.get("type") == "array" and "$ref" in content["items"]:
                return str(content["items"]["$ref"]).rsplit("/", 1)[1] + "[]"
            return f"inline {content}"
    return "-"


def test_the_contract_has_not_changed_by_accident(schema: dict[str, Any]) -> None:
    rows = sorted(f"{method} {path} -> {_model(op)}" for method, path, op in _operations(schema))
    assert rows == CONTRACT


def test_every_operation_has_a_summary_and_a_tag(schema: dict[str, Any]) -> None:
    for method, path, op in _operations(schema):
        assert op.get("summary") and not op["summary"].endswith("."), (method, path)
        assert op.get("tags"), (method, path)


def test_every_operation_but_the_open_ones_declares_401(schema: dict[str, Any]) -> None:
    for method, path, op in _operations(schema):
        if (method, path) not in OPEN_OPERATIONS:
            assert "401" in op["responses"], (method, path)
        else:
            assert "401" not in op["responses"], (method, path)


def test_a_state_changing_operation_declares_the_guards_of_the_middlewares(
    schema: dict[str, Any],
) -> None:
    for method, path, op in _operations(schema):
        if method != "GET":
            assert {"403", "413"} <= set(op["responses"]), (method, path)


def test_errors_have_the_shape_the_application_answers_with(schema: dict[str, Any]) -> None:
    for method, path, op in _operations(schema):
        for code, response in op["responses"].items():
            if code in ("401", "403", "404", "409", "415", "422", "429", "503"):
                ref = response["content"]["application/json"]["schema"]["$ref"]
                assert ref.endswith("/ErrorDetail"), (method, path, code)
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_no_html_page_is_in_the_schema(schema: dict[str, Any]) -> None:
    assert not HTML_PATHS & set(schema["paths"])
    assert not [
        p for p in schema["paths"] if p.startswith(("/artifacts/", "/pipelines/", "/actions/"))
    ]
    assert "text/html" not in str(schema)


def test_every_json_route_has_a_response_model() -> None:
    app = _create_app(bare_settings())
    missing = [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.include_in_schema
        for method in route.methods or ()
        if route.response_model is None
        and route.status_code != 204
        and (method, route.path) not in NO_MODEL_ALLOWED
    ]
    assert missing == []


def test_every_route_of_the_application_is_in_the_schema_or_a_page(schema: dict[str, Any]) -> None:
    app = _create_app(bare_settings())
    hidden = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and not route.include_in_schema
    }
    assert not [p for p in hidden if p.startswith("/api/")]
