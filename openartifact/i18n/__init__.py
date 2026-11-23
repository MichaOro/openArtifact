"""Internationalisation (ADR-056): English is the source language, every other language is a file of translations.

``locales/<code>.json`` holds flat, dot-namespaced keys (``board.add_lane``) with text that may contain ``{name}``
placeholders; a key with plural forms has one entry per category (``key.one``, ``key.other``, and ``zero``, ``two``,
``few``, ``many`` for languages that need them). The languages that exist are the files that exist.

* :func:`t` gives the text of a key in a language with the variables put in; a key missing in the language falls back to
  English and a key missing there is returned as it is: a missing translation is never an error.
* :func:`plural` picks the form by the number.
* :func:`language_of` decides the language of a request: the cookie of the language switch, else ``Accept-Language``
  (the first visit), else English.

The browser has the same functions in ``static/js/i18n.js`` and receives the dictionary of its language with the page.
API error messages are not translated (they are part of the API contract, ADR-056).
"""

from __future__ import annotations

import json
import re
from functools import cache
from pathlib import Path
from typing import Any

DEFAULT_LANGUAGE = "en"
LOCALES_DIR = Path(__file__).parent / "locales"
COOKIE = "oa_lang"
COOKIE_MAX_AGE = 365 * 24 * 3600
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
_CODE = re.compile(r"[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?")


@cache
def _load(code: str) -> dict[str, str]:
    path = LOCALES_DIR / f"{code}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError(f"{path.name}: a locale is one flat object of text")
    return data


def reload() -> None:
    """Forget what was read (tests change files)."""
    _load.cache_clear()


def languages() -> list[str]:
    """The codes of the languages that exist, English first."""
    found = sorted(p.stem for p in LOCALES_DIR.glob("*.json") if _CODE.fullmatch(p.stem))
    return [DEFAULT_LANGUAGE, *(c for c in found if c != DEFAULT_LANGUAGE)]


def language_name(code: str) -> str:
    """The language's own name (``Deutsch``): the file's ``_name`` entry, else the code."""
    return _load(code).get("_name", code) if code in languages() else code


def messages(code: str) -> dict[str, str]:
    """The dictionary of a language over English: every English key, the language's text where it has one."""
    merged = dict(_load(DEFAULT_LANGUAGE))
    if code != DEFAULT_LANGUAGE and code in languages():
        merged.update(_load(code))
    return {k: v for k, v in merged.items() if not k.startswith("_")}


def lookup(code: str, key: str) -> str | None:
    """The text of ``key`` in ``code``, else in English, else ``None`` (no interpolation)."""
    if code in languages():
        found = _load(code).get(key)
        if found is not None:
            return found
    return _load(DEFAULT_LANGUAGE).get(key)


def fill(text: str, variables: dict[str, Any]) -> str:
    """``{name}`` replaced by the variable of that name; an unknown placeholder stays as it is."""
    if not variables:
        return text
    return _PLACEHOLDER.sub(lambda m: str(variables[m[1]]) if m[1] in variables else m[0], text)


def t(key: str, language: str = DEFAULT_LANGUAGE, **variables: Any) -> str:
    """The text of ``key`` in ``language`` (fallback: English, then the key itself) with the variables put in."""
    found = lookup(language, key)
    return fill(found if found is not None else key, variables)


def plural_category(language: str, count: int) -> str:
    """The plural category of ``count``: ``one`` or ``other`` (English, German and the other Western languages).

    A language with more forms (Russian, Arabic, ...) adds its rule here and its forms to its file.
    """
    return "one" if count == 1 else "other"


def plural(key: str, count: int, language: str = DEFAULT_LANGUAGE, **variables: Any) -> str:
    """``key.<category>`` for ``count`` (``{count}`` is put in as well), falling back to ``key.other``, then the key."""
    variables = {"count": count, **variables}
    for suffix in (plural_category(language, count), "other"):
        found = lookup(language, f"{key}.{suffix}")
        if found is not None:
            return fill(found, variables)
    return fill(key, variables)


def parse_accept_language(header: str | None) -> list[str]:
    """The language tags of an ``Accept-Language`` header by preference, lowercase (``de-AT`` and ``de``)."""
    ranked: list[tuple[float, int, str]] = []
    for index, part in enumerate((header or "").split(",")):
        tag, _, params = part.strip().partition(";")
        tag = tag.strip().lower()
        if not tag or tag == "*":
            continue
        weight = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", params)
        if match:
            try:
                weight = float(match[1])
            except ValueError:
                weight = 0.0
        if weight > 0:
            ranked.append((-weight, index, tag))
    return [tag for _, _, tag in sorted(ranked)]


def negotiate(header: str | None) -> str:
    """The first supported language of an ``Accept-Language`` header (``de-AT`` matches ``de``), else English."""
    supported = languages()
    for tag in parse_accept_language(header):
        if tag in supported:
            return tag
        if tag.split("-")[0] in supported:
            return tag.split("-")[0]
    return DEFAULT_LANGUAGE


def language_of(cookie: str | None, accept_language: str | None) -> str:
    """The language of a request: the chosen one (cookie) if it still exists, else the browser's, else English."""
    if cookie and cookie in languages():
        return cookie
    return negotiate(accept_language)
