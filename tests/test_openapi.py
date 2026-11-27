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
DELETE /api/agents/{ref} -> -
DELETE /api/credentials/{ref} -> -
DELETE /api/guard-attachments/{attachment_id} -> -
DELETE /api/guards/{guard_id} -> -
DELETE /api/lanes/{status} -> LaneRead[]
DELETE /api/pipelines/{graph_id} -> -
DELETE /api/pipelines/{graph_id}/edges/{edge_id} -> -
DELETE /api/pipelines/{graph_id}/nodes/{node_id} -> -
DELETE /api/providers/{ref} -> -
DELETE /api/providers/{ref}/models/{model_id} -> -
DELETE /api/secrets/{name} -> -
DELETE /api/tasks/{ref}/comments/{comment_id} -> -
DELETE /api/tasks/{task_id} -> -
DELETE /api/tasks/{task_id}/executions -> DeletedCount
DELETE /api/tasks/{task_id}/executions/{execution_id} -> -
DELETE /api/ui-layouts/{kind}/{name} -> LayoutRead
DELETE /api/v1/agents/{ref} -> -
DELETE /api/v1/artifacts/{ref} -> -
DELETE /api/v1/artifacts/{ref}/comments/{comment_id} -> -
DELETE /api/v1/artifacts/{ref}/executions/{execution_id} -> -
DELETE /api/v1/guard-attachments/{attachment_id} -> -
DELETE /api/v1/guards/{guard_id} -> -
DELETE /api/v1/lanes/{status} -> LaneRead[]
DELETE /api/v1/providers/{ref} -> -
DELETE /api/v1/providers/{ref}/models/{model_id} -> -
DELETE /api/v1/secrets/{name} -> -
DELETE /api/v1/ui-layouts/{kind}/{name} -> LayoutRead
GET /api/actions -> GraphListRead[]
GET /api/actions/{graph_id} -> GraphDetail
GET /api/actions/{graph_id}/neighbours -> GraphNeighbours
GET /api/actions/{graph_id}/uses -> GraphUses
GET /api/actions/{graph_id}/versions -> GraphVersionRead[]
GET /api/actions/{graph_id}/versions/{number} -> GraphVersionDetail
GET /api/agents -> AgentRead[]
GET /api/agents/{ref} -> AgentDetail
GET /api/agents/{ref}/uses -> AgentUse[]
GET /api/agents/{ref}/versions -> VersionRead[]
GET /api/agents/{ref}/versions/{number} -> VersionRead
GET /api/artifact-fields -> ArtifactFieldsRead
GET /api/board/rules -> RulesAnswer
GET /api/board/rules/deletions -> DeletionRead[]
GET /api/credentials -> CredentialRead[]
GET /api/credentials/types -> inline {'items': {'additionalProperties': True, 'type': 'object'}, 'type': 'array', 'title': 'Response Credential Types Api Credentials Types Get'}
GET /api/credentials/{ref} -> CredentialRead
GET /api/credentials/{ref}/events -> CredentialEventRead[]
GET /api/credentials/{ref}/uses -> CredentialUse[]
GET /api/events -> -
GET /api/executions -> ExecutionsPage
GET /api/forms -> FormRead[]
GET /api/forms/{name} -> FormRead
GET /api/guard-attachments -> AttachmentRead[]
GET /api/guard-attachments/{attachment_id} -> AttachmentRead
GET /api/guards -> GuardDefinitionRead[]
GET /api/guards/templates -> TemplateRead[]
GET /api/guards/{guard_id} -> GuardDefinitionRead
GET /api/info -> InfoRead
GET /api/lanes -> LaneRead[]
GET /api/lanes/{status}/rules -> RulesAnswer
GET /api/node-types -> NodeTypeRead[]
GET /api/pipelines -> GraphListRead[]
GET /api/pipelines/{graph_id} -> GraphDetail
GET /api/pipelines/{graph_id}/neighbours -> GraphNeighbours
GET /api/pipelines/{graph_id}/stages -> ChainEntryRead[]
GET /api/pipelines/{graph_id}/uses -> GraphUses
GET /api/pipelines/{graph_id}/versions -> GraphVersionRead[]
GET /api/pipelines/{graph_id}/versions/{number} -> GraphVersionDetail
GET /api/providers -> ProviderRead[]
GET /api/providers/{ref} -> ProviderRead
GET /api/rules/schemas -> RuleSchemaRead[]
GET /api/rules/schemas/{purpose} -> RuleSchemaRead
GET /api/runs -> RunRead[]
GET /api/runs/{task_id}/results -> NodeResultRead[]
GET /api/secrets -> SecretRead[]
GET /api/secrets/{name}/uses -> SecretUse[]
GET /api/settings/personal -> PersonalSettingsRead
GET /api/settings/retention -> RulesRead
GET /api/settings/run-limits -> RunLimitsRead
GET /api/settings/stop -> StopState
GET /api/tasks -> TaskRead[]
GET /api/tasks/{ref}/activity -> ActivityPage
GET /api/tasks/{ref}/comments -> CommentRead[]
GET /api/tasks/{task_id} -> TaskRead
GET /api/tasks/{task_id}/executions -> ExecutionList
GET /api/tasks/{task_id}/executions/{execution_id} -> ExecutionDetail
GET /api/tasks/{task_id}/executions/{execution_id}/context -> RunContextRead
GET /api/tasks/{task_id}/executions/{execution_id}/flow -> ExecutionFlow
GET /api/tasks/{task_id}/executions/{execution_id}/position -> ExecutionPosition
GET /api/tasks/{task_id}/executions/{execution_id}/steps/{step_id} -> ExecutionStepRead
GET /api/ui-layouts/{kind}/{name} -> LayoutRead
GET /api/ui-layouts/{kind}/{name}/export -> -
GET /api/v1/actions/{ref}/neighbours -> GraphNeighbours
GET /api/v1/agents -> AgentRead[]
GET /api/v1/agents/{ref} -> AgentDetail
GET /api/v1/agents/{ref}/uses -> AgentUse[]
GET /api/v1/agents/{ref}/versions -> VersionRead[]
GET /api/v1/agents/{ref}/versions/{number} -> VersionRead
GET /api/v1/artifact-fields -> ArtifactFieldsRead
GET /api/v1/artifacts -> TaskRead[]
GET /api/v1/artifacts/{ref} -> TaskRead
GET /api/v1/artifacts/{ref}/activity -> ActivityPage
GET /api/v1/artifacts/{ref}/comments -> CommentRead[]
GET /api/v1/artifacts/{ref}/executions -> ExecutionList
GET /api/v1/artifacts/{ref}/executions/{execution_id} -> ExecutionDetail
GET /api/v1/artifacts/{ref}/executions/{execution_id}/context -> RunContextRead
GET /api/v1/artifacts/{ref}/executions/{execution_id}/flow -> ExecutionFlow
GET /api/v1/artifacts/{ref}/executions/{execution_id}/position -> ExecutionPosition
GET /api/v1/artifacts/{ref}/executions/{execution_id}/steps/{step_id} -> ExecutionStepRead
GET /api/v1/artifacts/{ref}/run -> RunRead
GET /api/v1/artifacts/{ref}/run/results -> NodeResultRead[]
GET /api/v1/executions -> ExecutionsPage
GET /api/v1/guard-attachments -> AttachmentRead[]
GET /api/v1/guard-attachments/{attachment_id} -> AttachmentRead
GET /api/v1/guards -> GuardDefinitionRead[]
GET /api/v1/guards/templates -> TemplateRead[]
GET /api/v1/guards/{guard_id} -> GuardDefinitionRead
GET /api/v1/lanes -> LaneRead[]
GET /api/v1/pipelines -> PipelineChainRead[]
GET /api/v1/pipelines/{ref}/neighbours -> GraphNeighbours
GET /api/v1/providers -> ProviderRead[]
GET /api/v1/providers/{ref} -> ProviderRead
GET /api/v1/secrets -> SecretRead[]
GET /api/v1/settings/personal -> PersonalSettingsRead
GET /api/v1/settings/retention -> RulesRead
GET /api/v1/settings/run-limits -> RunLimitsRead
GET /api/v1/settings/stop -> StopState
GET /api/v1/ui-layouts/{kind}/{name} -> LayoutRead
GET /api/v1/ui-layouts/{kind}/{name}/export -> -
GET /health -> HealthRead
PATCH /api/actions/{graph_id} -> GraphRead
PATCH /api/actions/{graph_id}/edges/{edge_id} -> EdgeRead
PATCH /api/actions/{graph_id}/nodes/{node_id} -> NodeRead
PATCH /api/agents/{ref} -> AgentDetail
PATCH /api/credentials/{ref} -> CredentialRead
PATCH /api/guards/{guard_id} -> GuardDefinitionRead
PATCH /api/pipelines/{graph_id} -> GraphRead
PATCH /api/pipelines/{graph_id}/edges/{edge_id} -> EdgeRead
PATCH /api/pipelines/{graph_id}/nodes/{node_id} -> NodeRead
PATCH /api/providers/{ref} -> ProviderRead
PATCH /api/providers/{ref}/models/{model_id} -> ProviderRead
PATCH /api/tasks/{ref}/comments/{comment_id} -> CommentRead
PATCH /api/tasks/{task_id} -> TaskRead
PATCH /api/v1/agents/{ref} -> AgentDetail
PATCH /api/v1/artifacts/{ref} -> TaskRead
PATCH /api/v1/artifacts/{ref}/comments/{comment_id} -> CommentRead
PATCH /api/v1/guards/{guard_id} -> GuardDefinitionRead
PATCH /api/v1/providers/{ref} -> ProviderRead
PATCH /api/v1/providers/{ref}/models/{model_id} -> ProviderRead
POST /api/actions -> GraphRead
POST /api/actions/{graph_id}/draft/discard -> GraphDetail
POST /api/actions/{graph_id}/edges -> EdgeRead
POST /api/actions/{graph_id}/nodes -> NodeRead
POST /api/actions/{graph_id}/publish -> PublishedGraph
POST /api/actions/{graph_id}/versions/{number}/republish -> PublishedGraph
POST /api/agents -> AgentDetail
POST /api/agents/{ref}/draft/discard -> AgentDetail
POST /api/agents/{ref}/preview -> PreviewRead
POST /api/agents/{ref}/publish -> PublishResult
POST /api/agents/{ref}/versions/{number}/republish -> PublishResult
POST /api/board/rules/preview -> CardPreviewRead
POST /api/board/rules/sweep -> SweepRead
POST /api/credentials/external -> CredentialRead
POST /api/credentials/internal -> CredentialCreated
POST /api/credentials/{ref}/revoke -> CredentialRead
POST /api/credentials/{ref}/rotate -> CredentialCreated
POST /api/credentials/{ref}/test -> CredentialRead
POST /api/executions/delete -> ExecutionsDeleted
POST /api/guard-attachments -> AttachmentRead
POST /api/guards -> GuardDefinitionRead
POST /api/guards/from-template -> GuardDefinitionRead
POST /api/guards/preview -> GuardPreview
POST /api/lanes -> LaneRead[]
POST /api/lanes/{status}/rules/preview -> CardPreviewRead
POST /api/pipelines -> GraphRead
POST /api/pipelines/{graph_id}/draft/discard -> GraphDetail
POST /api/pipelines/{graph_id}/edges -> EdgeRead
POST /api/pipelines/{graph_id}/nodes -> NodeRead
POST /api/pipelines/{graph_id}/publish -> PublishedGraph
POST /api/pipelines/{graph_id}/versions/{number}/republish -> PublishedGraph
POST /api/providers -> ProviderRead
POST /api/providers/test -> CheckResult
POST /api/providers/{ref}/models -> ProviderRead
POST /api/providers/{ref}/models/refresh -> ProviderRead
POST /api/providers/{ref}/test -> CheckResult
POST /api/settings/retention/preview -> RulesPreview
POST /api/tasks -> TaskRead
POST /api/tasks/{ref}/comments -> CommentRead
POST /api/tasks/{task_id}/archive -> TaskRead
POST /api/tasks/{task_id}/run -> RunRead
POST /api/tasks/{task_id}/run/stop -> RunRead
POST /api/tasks/{task_id}/unarchive -> TaskRead
POST /api/v1/agents -> AgentDetail
POST /api/v1/agents/{ref}/draft/discard -> AgentDetail
POST /api/v1/agents/{ref}/preview -> PreviewRead
POST /api/v1/agents/{ref}/publish -> PublishResult
POST /api/v1/agents/{ref}/versions/{number}/republish -> PublishResult
POST /api/v1/artifacts -> TaskRead
POST /api/v1/artifacts/{ref}/archive -> TaskRead
POST /api/v1/artifacts/{ref}/comments -> CommentRead
POST /api/v1/artifacts/{ref}/run -> RunRead
POST /api/v1/artifacts/{ref}/run/stop -> RunRead
POST /api/v1/artifacts/{ref}/unarchive -> TaskRead
POST /api/v1/executions/{execution_id}/heartbeat -> HeartbeatRead
POST /api/v1/guard-attachments -> AttachmentRead
POST /api/v1/guards -> GuardDefinitionRead
POST /api/v1/guards/from-template -> GuardDefinitionRead
POST /api/v1/lanes -> LaneRead[]
POST /api/v1/providers -> ProviderRead
POST /api/v1/providers/test -> CheckResult
POST /api/v1/providers/{ref}/models -> ProviderRead
POST /api/v1/providers/{ref}/models/refresh -> ProviderRead
POST /api/v1/providers/{ref}/test -> CheckResult
POST /api/v1/settings/retention/preview -> RulesPreview
PUT /api/agents/{ref}/draft -> AgentDetail
PUT /api/artifact-fields -> ArtifactFieldsRead
PUT /api/board/rules -> RulesAnswer
PUT /api/credentials/{ref}/enabled -> CredentialRead
PUT /api/guard-attachments/{attachment_id}/enabled -> AttachmentRead
PUT /api/lanes/{status} -> LaneRead[]
PUT /api/lanes/{status}/rules -> RulesAnswer
PUT /api/secrets/{name} -> SecretRead
PUT /api/settings/personal -> PersonalSettingsRead
PUT /api/settings/retention -> RulesSaved
PUT /api/settings/run-limits -> RunLimitsRead
PUT /api/settings/stop -> StopState
PUT /api/ui-layouts/{kind}/{name} -> LayoutRead
PUT /api/v1/agents/{ref}/draft -> AgentDetail
PUT /api/v1/artifact-fields -> ArtifactFieldsRead
PUT /api/v1/guard-attachments/{attachment_id}/enabled -> AttachmentRead
PUT /api/v1/lanes/{status} -> LaneRead[]
PUT /api/v1/secrets/{name} -> SecretRead
PUT /api/v1/settings/personal -> PersonalSettingsRead
PUT /api/v1/settings/retention -> RulesSaved
PUT /api/v1/settings/run-limits -> RunLimitsRead
PUT /api/v1/settings/stop -> StopState
PUT /api/v1/ui-layouts/{kind}/{name} -> LayoutRead
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
