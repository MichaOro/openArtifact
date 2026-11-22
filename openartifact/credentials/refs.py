"""The syntax of secret references and what is done with them: find, substitute, mask.

A node never holds a secret, only a reference ``${secret:NAME}`` (HTTP: in the URL path or query, the
headers and the body) or, for a Code node, a list of names in its ``secrets`` setting. The value is put in
at run time by the executor (see ``engine/executors.py``); afterwards every trace of it is removed from the
node's result with :func:`mask_text` and :func:`mask_data`.

Masking is by value, so it covers what the node printed, an echoed response and an error text, in the
forms a value usually takes on the way (as it is, percent-encoded, Base64, JSON-escaped). It cannot find a
value that was transformed in another way (hashed, reversed, split over several lines or chopped into
single characters): a node that is allowed to read a secret can always leak it on purpose.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote, quote_plus, urlsplit

NAME_PATTERN = r"[A-Z][A-Z0-9_]{0,63}"
NAME = re.compile(NAME_PATTERN)
REFERENCE = re.compile(r"\$\{secret:([^}\r\n]{0,80})\}")
MASK = "***"
MAX_SECRETS_PER_NODE = 32
#: Names a Code node may not receive as a variable: the process's own ones and everything of ours.
RESERVED_ENV = frozenset({"PATH", "HOME", "LANG"})
RESERVED_ENV_PREFIX = "OPENARTIFACT_"


class SecretReferenceError(ValueError):
    """A reference or a name is malformed (the message never repeats a value)."""


def is_name(text: str) -> bool:
    return NAME.fullmatch(text) is not None


def names_in(*texts: str) -> list[str]:
    """The secret names referenced in the texts, in order of appearance, without repeats.

    Raises :class:`SecretReferenceError` for a reference whose name is not a valid secret name.
    """
    found: list[str] = []
    for text in texts:
        for match in REFERENCE.finditer(text):
            name = match[1]
            if not is_name(name):
                raise SecretReferenceError(
                    "A secret reference must look like ${secret:NAME} with NAME in capitals, "
                    "digits and underscores, starting with a letter"
                )
            if name not in found:
                found.append(name)
    return found


def substitute(text: str, values: Mapping[str, str], *, percent_encode: bool = False) -> str:
    """``text`` with every reference replaced by its value (in a URL: percent-encoded)."""

    def put(match: re.Match[str]) -> str:
        value = values.get(match[1])
        if value is None:
            return match[0]
        return quote(value, safe="") if percent_encode else value

    return REFERENCE.sub(put, text)


def in_scheme_or_host(url: str, pattern: re.Pattern[str]) -> bool:
    """Whether ``pattern`` matches in the scheme or the authority of ``url`` (or ``url`` has no scheme).

    A reference is allowed in the path and the query, never before them: it could change where the
    request goes. ``urlsplit`` raises :class:`ValueError` for an address that cannot be taken apart.
    """
    head = url.strip()
    scheme_end = head.find("://")
    rest = head[scheme_end + 3 :] if scheme_end >= 0 else head
    authority_end = min((i for i in (rest.find(c) for c in "/?#") if i >= 0), default=len(rest))
    if scheme_end < 0 or pattern.search(head[: scheme_end + 3] + rest[:authority_end]):
        return True
    urlsplit(head)
    return False


def check_url_references(url: str) -> None:
    """References are allowed in the path and query of a URL, not before them (scheme, host, port).

    Raises :class:`SecretReferenceError`.
    """
    names_in(url)
    if REFERENCE.search(url) is None:
        return
    if in_scheme_or_host(url, REFERENCE):
        raise SecretReferenceError(
            "A secret reference is allowed in the path, the query, the headers and the body, "
            "not in the scheme or the host of the address"
        )


def check_env_names(names: Iterable[str]) -> None:
    """The names a Code node may receive as environment variables; raises :class:`SecretReferenceError`."""
    for name in names:
        if name in RESERVED_ENV or name.startswith(RESERVED_ENV_PREFIX):
            raise SecretReferenceError(f"'{name}' cannot be used as an environment variable")


def parse_name_lines(text: str) -> list[str]:
    """One secret name per line (empty lines are skipped); raises :class:`SecretReferenceError`."""
    names: list[str] = []
    for line in text.splitlines():
        name = line.strip()
        if not name:
            continue
        if not is_name(name):
            raise SecretReferenceError(
                "Each line is one secret name: capitals, digits and underscores, starting with a letter"
            )
        if name not in names:
            names.append(name)
    if len(names) > MAX_SECRETS_PER_NODE:
        raise SecretReferenceError(f"At most {MAX_SECRETS_PER_NODE} secrets per node")
    check_env_names(names)
    return names


def forms_of(value: str) -> list[str]:
    """The ways ``value`` may show up in a result: as it is, percent-encoded, Base64, JSON-escaped.

    Longest first, so that a form that contains a shorter one is replaced as a whole.
    """
    raw = value.encode("utf-8")
    base64_standard = base64.b64encode(raw).decode()
    base64_url = base64.urlsafe_b64encode(raw).decode()
    forms = {
        value,
        quote(value, safe=""),
        quote_plus(value),
        base64_standard,
        base64_standard.rstrip("="),
        base64_url,
        base64_url.rstrip("="),
        json.dumps(value)[1:-1],
    }
    return sorted((f for f in forms if f), key=len, reverse=True)


def mask_text(text: str, values: Iterable[str]) -> str:
    """``text`` with every form of every value replaced by ``***``."""
    forms = sorted({f for value in values for f in forms_of(value)}, key=len, reverse=True)
    for form in forms:
        text = text.replace(form, MASK)
    return text


def mask_data(data: Any, values: Iterable[str]) -> Any:
    """``data`` (parsed JSON) with the values masked in every string, key included."""
    values = list(values)
    if isinstance(data, str):
        return mask_text(data, values)
    if isinstance(data, list):
        return [mask_data(item, values) for item in data]
    if isinstance(data, dict):
        return {mask_text(str(k), values): mask_data(v, values) for k, v in data.items()}
    return data
