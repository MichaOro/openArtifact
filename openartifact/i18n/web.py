"""The web side of the translations: the language of a request and what the templates get (ADR-056)."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from fastapi import Request
from markupsafe import Markup
from starlette.templating import Jinja2Templates

from openartifact import i18n

#: The language of the page being rendered. Set by :func:`context_processor` just before a template renders, so ``t`` also
#: works inside macros that were imported without the context (the request is not visible there).
current_language: ContextVar[str] = ContextVar("current_language", default=i18n.DEFAULT_LANGUAGE)


def language_for(request: Request) -> str:
    """The request's language (cached on the request): cookie of the switch, else ``Accept-Language``, else English."""
    cached = getattr(request.state, "language", None)
    if cached:
        return str(cached)
    code = i18n.language_of(
        request.cookies.get(i18n.COOKIE), request.headers.get("accept-language")
    )
    request.state.language = code
    return code


def payload(code: str) -> dict[str, Any]:
    """What the browser needs: the language, the languages that exist and the dictionary (the language over English)."""
    return {
        "lang": code,
        "languages": [{"code": c, "name": i18n.language_name(c)} for c in i18n.languages()],
        "messages": i18n.messages(code),
    }


def context_processor(request: Request) -> dict[str, Any]:
    """Remember the request's language for the render that follows (see ``current_language``); adds nothing."""
    current_language.set(language_for(request))
    return {}


def install(templates: Jinja2Templates) -> None:
    """Give the templates ``t``, ``plural``, ``lang`` and ``i18n_json`` for the language of the page being rendered."""

    def t(key: str, **variables: Any) -> str:
        return i18n.t(key, current_language.get(), **variables)

    def plural(key: str, count: int, **variables: Any) -> str:
        return i18n.plural(key, count, current_language.get(), **variables)

    def lang() -> str:
        return current_language.get()

    def i18n_json() -> Markup:
        """The dictionary as JSON for ``<script type="application/json">`` (``<`` escaped: no way to close the tag)."""
        text = json.dumps(payload(current_language.get()), ensure_ascii=False)
        return Markup(text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))

    templates.env.globals.update(t=t, plural=plural, lang=lang, i18n_json=i18n_json)
