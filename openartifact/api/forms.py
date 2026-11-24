"""The form manifests of the configuration windows (``/api/forms``, ADR-062): the sections, fields and layout the browser
draws, with their texts in the language of the request (cookie ``oa_lang``, else ``Accept-Language``) where a translation
exists, else English."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from openartifact.api.contract import GATED, errors
from openartifact.i18n.web import language_for
from openartifact.ui import forms

router = APIRouter(prefix="/api/forms", tags=["forms"], responses=GATED)


@router.get(
    "",
    response_model=list[forms.FormManifest],
    response_model_exclude_none=True,
    summary="List the form manifests",
)
async def list_forms(request: Request) -> list[dict[str, Any]]:
    """Every form manifest: its sections with their column, the fields with widget, label, help, options, limits and
    visibility. The stored values of a form (keys, options) never change with the language."""
    language = language_for(request)
    return [forms.localize(forms.describe(f), language) for f in forms.FORMS.values()]


@router.get(
    "/{name}",
    response_model=forms.FormManifest,
    response_model_exclude_none=True,
    summary="One form manifest",
    responses=errors(404, 422),
)
async def get_form(name: str, request: Request) -> dict[str, Any]:
    """One form by name; 404 for an unknown one."""
    form = forms.FORMS.get(name)
    if form is None:
        raise HTTPException(status_code=404, detail="Unknown form")
    return forms.localize(forms.describe(form), language_for(request))
