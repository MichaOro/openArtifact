"""Builders and waiting helpers shared by the API tests and the browser tests.

Everything takes a ``client`` that has ``get``/``post``/``patch``/``delete`` returning a response with
``status_code`` and ``json()``: a Starlette ``TestClient`` and an ``httpx.Client`` both qualify.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic.config import Config
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from openartifact.config import Settings
from openartifact.database import create_engine_for


def alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    return cfg


def bare_settings(**changes: Any) -> Settings:
    """Settings from the arguments alone: no ``.env`` file is read."""
    return Settings(_env_file=None, **changes)  # type: ignore[call-arg]


def graph_url(graph: dict[str, Any]) -> str:
    """The API path of a pipeline or an action definition."""
    return f"/api/{'actions' if graph['kind'] == 'action' else 'pipelines'}/{graph['id']}"


def post(client: Any, url: str, **body: Any) -> dict[str, Any]:
    """POST a JSON body, insist on success, return the JSON."""
    response = client.post(url, json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()  # type: ignore[no-any-return]


def node(client: Any, graph: dict[str, Any], kind: str, **extra: Any) -> dict[str, Any]:
    return post(client, f"{graph_url(graph)}/nodes", kind=kind, **extra)


def connect(
    client: Any, graph: dict[str, Any], a: dict[str, Any], ap: str, b: dict[str, Any], bp: str
) -> None:
    post(
        client,
        f"{graph_url(graph)}/edges",
        source_id=a["id"],
        source_port=ap,
        target_id=b["id"],
        target_port=bp,
    )


def kind_of(client: Any, graph: dict[str, Any], kind: str) -> dict[str, Any]:
    """The (first) node of this kind of a graph, e.g. its trigger or its complete."""
    nodes = client.get(graph_url(graph)).json()["nodes"]
    return next(n for n in nodes if n["kind"] == kind)


def build_pipeline(
    client: Any, stages: int = 2, name: str = "Flow", stage_name: str = "Stage {}"
) -> dict[str, Any]:
    """Trigger -> stage 1 -> ... -> complete, each stage with one empty action.

    The result is the pipeline with ``stages``: a list of ``(stage, action)`` nodes.
    """
    pipeline = post(client, "/api/pipelines", name=name)
    previous, port = kind_of(client, pipeline, "trigger"), "out"
    complete = kind_of(client, pipeline, "complete")
    made = []
    for i in range(stages):
        stage = node(client, pipeline, "stage", name=stage_name.format(i + 1))
        action = node(client, pipeline, "action", stage_id=stage["id"], x=24, y=48)
        connect(client, pipeline, previous, port, stage, "start")
        connect(client, pipeline, stage, "start", action, "in")
        connect(client, pipeline, action, "pass", stage, "end")
        previous, port = stage, "end"
        made.append((stage, action))
    connect(client, pipeline, previous, port, complete, "in")
    pipeline["stages"] = made
    return pipeline


def build_definition(
    client: Any,
    name: str = "Definition",
    *,
    seconds: int | None = None,
    output: str | None = "pass",
    fail_enabled: bool = False,
) -> dict[str, Any]:
    """An action definition: trigger -> [timer] -> the output port ``output`` ('pass' or 'fail').

    ``output=None`` leaves the trigger unconnected (a dead end).
    """
    definition = post(client, "/api/actions", name=name)
    trigger = kind_of(client, definition, "trigger")
    out = kind_of(client, definition, "output")
    graph = client.get(graph_url(definition)).json()
    for edge in graph["edges"]:  # the default trigger -> output connection
        client.delete(f"{graph_url(definition)}/edges/{edge['id']}")
    if fail_enabled:
        response = client.patch(
            f"{graph_url(definition)}/nodes/{out['id']}", json={"fail_enabled": True}
        )
        assert response.status_code == 200, response.text
    if output is None:
        return definition
    source, port = trigger, "out"
    if seconds is not None:
        timer = node(client, definition, "timer", seconds=seconds)
        connect(client, definition, trigger, "out", timer, "in")
        source = timer
    connect(client, definition, source, port, out, output)
    return definition


def link(
    client: Any, pipeline: dict[str, Any], action: dict[str, Any], definition: dict[str, Any]
) -> None:
    """Let an action of a pipeline run an action definition."""
    response = client.patch(
        f"{graph_url(pipeline)}/nodes/{action['id']}", json={"definition_id": definition["id"]}
    )
    assert response.status_code == 200, response.text


def slow_pipeline(client: Any, seconds: int = 30, stage_name: str = "Stage {}") -> dict[str, Any]:
    """A pipeline whose only action waits ``seconds`` (a timer in its definition): a run that stays running."""
    pipeline = build_pipeline(client, stages=1, stage_name=stage_name)
    link(
        client,
        pipeline,
        pipeline["stages"][0][1],
        build_definition(client, "Wait", seconds=seconds),
    )
    return pipeline


def make_task(client: Any, title: str = "Item") -> dict[str, Any]:
    return post(client, "/api/tasks", title=title, status="backlog")


def run_of(client: Any, task: dict[str, Any]) -> dict[str, Any]:
    runs = [r for r in client.get("/api/runs").json() if r["task_id"] == task["id"]]
    return runs[0]  # type: ignore[no-any-return]


def wait_until[T](
    read: Callable[[], T], predicate: Callable[[T], bool], timeout: float = 10.0
) -> T:
    """Poll ``read`` until ``predicate`` holds (for what has no event to wait for); fail at the timeout."""
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if predicate(value):
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"still {value!r} after {timeout} s")
        time.sleep(0.02)


def wait_for_run(
    client: Any,
    task: dict[str, Any],
    status: str,
    where: Callable[[dict[str, Any]], bool] = lambda run: True,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Wait until the artifact's run has ``status`` (and satisfies ``where``) by awaiting the
    ``run.updated`` events of the application, not by polling. In-process ``TestClient`` only."""
    bus = client.app.state.event_bus
    queue = bus.subscribe()  # before the first look: nothing can slip in between

    def reached(run: dict[str, Any]) -> bool:
        return bool(run["status"] == status and where(run))

    async def next_event() -> None:
        async with asyncio.timeout(timeout):
            while True:
                event = await queue.get()
                if event is None:
                    raise AssertionError("the event stream ended")
                is_mine = event.type == "run.updated" and event.data["task_id"] == task["id"]
                if is_mine and reached(event.data):
                    return

    try:
        runs = [r for r in client.get("/api/runs").json() if r["task_id"] == task["id"]]
        if not (runs and reached(runs[0])):
            try:
                client.portal.call(next_event)
            except TimeoutError:
                raise AssertionError(f"run is {run_of(client, task)}, not {status}") from None
    finally:
        bus.unsubscribe(queue)
    return run_of(client, task)


@asynccontextmanager
async def db_session_context(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """A session on its own engine (not the shared one), committed on success, for tests."""
    engine = create_engine_for(settings)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
    finally:
        await engine.dispose()
