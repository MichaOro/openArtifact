"""The form manifests of the configuration windows (``/api/forms``, ADR-062): the sections, fields and layout the browser
draws, with their texts in the language of the request (cookie ``oa_lang``, else ``Accept-Language``) where a translation
exists, else English."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from openartifact.api.contract import GATED, errors
from openartifact.api.deps import SessionDep
from openartifact.i18n.web import language_for
from openartifact.ui import forms, layout

router = APIRouter(prefix="/api/forms", tags=["forms"], responses=GATED)


class FormRead(forms.FormManifest):
    """A form manifest as the browser gets it: with the saved arrangement of the instance put over it (ADR-063)."""

    layout_customised: bool | None = None


def _with_layout(form: forms.FormManifest, saved: dict[str, Any], language: str) -> dict[str, Any]:
    window = f"forms/{form.name}"
    return forms.localize(
        layout.apply_layout(window, forms.describe(form), saved.get(window)), language
    )


@router.get(
    "",
    response_model=list[FormRead],
    response_model_exclude_none=True,
    summary="List the form manifests",
)
async def list_forms(request: Request, session: SessionDep) -> list[dict[str, Any]]:
    """Every form manifest: its sections with their column, the fields with widget, label, help, options, limits and
    visibility. The stored values of a form (keys, options) never change with the language."""
    language = language_for(request)
    saved = await layout.load_all(session)
    return [_with_layout(f, saved, language) for f in forms.FORMS.values()]


@router.get(
    "/{name}",
    response_model=FormRead,
    response_model_exclude_none=True,
    summary="One form manifest",
    responses=errors(404, 422),
)
async def get_form(name: str, request: Request, session: SessionDep) -> dict[str, Any]:
    """One form by name; 404 for an unknown one."""
    form = forms.FORMS.get(name)
    if form is None:
        raise HTTPException(status_code=404, detail="Unknown form")
    return _with_layout(form, await layout.load_all(session), language_for(request))
