"""The arrangement of the manifest windows (``/api/ui-layouts``, ADR-063) and the same under ``/api/v1``: where the sections
and fields of a window sit, saved as a layer over its shipped YAML manifest. ``forms/<form>`` is a configuration window
(``ui/forms/*.yaml``), ``nodes/<kind>`` the settings of a node kind (``graph/nodes/*.yaml``). A change publishes
``settings.changed`` and applies to every window of that kind of this instance."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.graph.node_types import NODE_TYPES
from openartifact.ui import forms, layout

DESCRIPTION = (
    "The layout of a window: ``sections`` in order; a form's section has its ``column`` (1, 2, ``auto`` or ``full``) and the "
    "keys of its ``fields`` and the folded ``advanced`` ones, the window of a node kind has the sections ``definition`` and "
    "``behaviour`` (and areas of your own) with the settings each holds, in order (a group of settings is one entry "
    "``group:<name>``). A field or setting may sit in any area; an area of your own is ``custom_<id>`` with a ``title`` "
    "(1 to 40 characters, at most 12 per window) and is only a container. ``shipped`` is what the manifest says, "
    "``layout`` what applies now, ``customised`` whether they differ by a saved layout. Keys the manifest no longer has "
    "are ignored, new ones appear at their default place."
)


class LayoutWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[dict[str, Any]]


class LayoutRead(BaseModel):
    window: str
    customised: bool
    layout: dict[str, Any]
    shipped: dict[str, Any]


def _described(kind: str, name: str) -> tuple[str, dict[str, Any]]:
    window = f"{kind}/{name}"
    if not layout.WINDOW.fullmatch(window):
        raise HTTPException(status_code=404, detail="Unknown window")
    if kind == "forms":
        form = forms.FORMS.get(name)
        if form is None:
            raise HTTPException(status_code=404, detail="Unknown window")
        return window, forms.describe(form)
    node = NODE_TYPES.get(name)  # type: ignore[call-overload]
    if node is None:
        raise HTTPException(status_code=404, detail="Unknown window")
    return window, node.describe()


def _read(window: str, description: dict[str, Any], saved: Any) -> dict[str, Any]:
    shipped = layout.shipped_layout(window, description)
    merged = layout.apply_layout(window, description, saved)
    return {
        "window": window,
        "customised": saved is not None,
        "layout": layout.current_layout(window, merged) if saved is not None else shipped,
        "shipped": shipped,
    }


def build_ui_layouts_router(
    prefix: str, tags: Sequence[str], dependencies: Sequence[Any] = ()
) -> APIRouter:
    router = APIRouter(
        prefix=f"{prefix}/ui-layouts",
        tags=list(tags),
        dependencies=list(dependencies),
        responses=GATED,
    )
    tag = "v1_" if "v1" in prefix else ""

    @router.get(
        "/{kind}/{name}",
        response_model=LayoutRead,
        name=f"{tag}get_ui_layout",
        summary="Get the layout of a window",
        description=DESCRIPTION,
        responses=errors(404, 422),
    )
    async def get_layout(kind: str, name: str, session: SessionDep) -> dict[str, Any]:
        window, description = _described(kind, name)
        return _read(window, description, (await layout.load_all(session)).get(window))

    @router.put(
        "/{kind}/{name}",
        response_model=LayoutRead,
        name=f"{tag}put_ui_layout",
        summary="Save the layout of a window",
        description=DESCRIPTION
        + " Only known sections and fields are accepted (422 otherwise). Publishes ``settings.changed``.",
        responses=errors(404, 422, write=True, body=True),
    )
    async def put_layout(
        kind: str, name: str, payload: LayoutWrite, request: Request, session: SessionDep
    ) -> dict[str, Any]:
        window, description = _described(kind, name)
        try:
            checked = layout.check_layout(window, description, payload.model_dump())
        except layout.LayoutError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        await layout.save_raw(session, window, checked)
        await session.commit()
        request.app.state.event_bus.publish("settings.changed", {"ui_layout": window})
        return _read(window, description, checked)

    @router.delete(
        "/{kind}/{name}",
        response_model=LayoutRead,
        name=f"{tag}delete_ui_layout",
        summary="Reset the layout of a window to the shipped one",
        description=DESCRIPTION,
        responses=errors(404, 422, write=True),
    )
    async def delete_layout(
        kind: str, name: str, request: Request, session: SessionDep
    ) -> dict[str, Any]:
        window, description = _described(kind, name)
        await layout.save_raw(session, window, None)
        await session.commit()
        request.app.state.event_bus.publish("settings.changed", {"ui_layout": window})
        return _read(window, description, None)

    @router.get(
        "/{kind}/{name}/export",
        name=f"{tag}export_ui_layout",
        summary="Export the layout of a window as YAML",
        description="The layout that applies, as a YAML file to put into the repository as the new default (order only: no texts, no values).",
        responses={200: {"content": {"application/yaml": {}}}, **errors(404, 422)},
    )
    async def export_layout(kind: str, name: str, session: SessionDep) -> Response:
        window, description = _described(kind, name)
        data = _read(window, description, (await layout.load_all(session)).get(window))
        body = layout.export_yaml(window, data["layout"])
        return Response(
            content=body,
            media_type="application/yaml",
            headers={"Content-Disposition": f'attachment; filename="{name}.layout.yaml"'},
        )

    return router
