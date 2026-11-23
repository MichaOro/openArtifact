#!/usr/bin/env python3
"""Check the translations (ADR-056): keys used but not defined, keys defined but not used, keys a language lacks, and
placeholders that differ from English.

    python3 tools/check_i18n.py          # report; exit 1 when English is incomplete or a placeholder differs
    python3 tools/check_i18n.py --all    # also list the keys each language still lacks (they fall back to English)

``scan()`` is what ``tests/test_i18n.py`` runs, so drift fails the build. Keys are found as string literals in
``t("key")``, ``tn("key")`` and ``plural("key")`` calls of templates, JavaScript and Python. A key that is built at
run time (``t('nav.' ~ item.key ~ '.label')``, ``t(`graph.${noun}.load_error`)``) counts its literal prefix: every key
with that prefix counts as used. Plural keys are written ``base.one`` / ``base.other`` and are used through ``base``.
Node manifest overrides (``nodes.<kind>...``) are checked against the manifests by ``tests/test_i18n.py``.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "openartifact"
LOCALES = ROOT / "i18n" / "locales"
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
PLURAL_SUFFIXES = ("zero", "one", "two", "few", "many", "other")
#: ``t("key"`` / ``tn("key"`` / ``plural("key"`` in any of the three kinds of files; the key ends at the quote.
CALL = re.compile(
    r"""\b(?:t|tn|plural)\(\s*(["'`])((?:[a-z0-9_]+\.)+[a-z0-9_]*)(?:(\1)|(\$\{|["'`]\s*~|["'`]\s*\+))"""
)
#: Keys the code builds from other keys (the manifests' texts are overrides, not used by literal calls).
ALWAYS_USED = ("nodes.",)
SOURCES = (
    ("templates", "*.html"),
    ("static/js", "*.js"),
    (".", "*.py"),
)


@dataclass
class Report:
    used: set[str] = field(default_factory=set)
    prefixes: set[str] = field(default_factory=set)
    missing: dict[str, list[str]] = field(
        default_factory=dict
    )  # used but not in en.json: key -> files
    unused: list[str] = field(default_factory=list)
    lacking: dict[str, list[str]] = field(
        default_factory=dict
    )  # language -> keys English has and it lacks
    extra: dict[str, list[str]] = field(
        default_factory=dict
    )  # language -> keys it has and English lacks
    placeholders: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.unused or self.placeholders or any(self.extra.values()))


def load(code: str) -> dict[str, str]:
    data = json.loads((LOCALES / f"{code}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}


def languages() -> list[str]:
    return sorted(p.stem for p in LOCALES.glob("*.json"))


def _base(key: str) -> str:
    head, _, tail = key.rpartition(".")
    return head if tail in PLURAL_SUFFIXES and head else key


def scan() -> Report:
    report = Report()
    english = load("en")
    files: dict[str, str] = {}
    for folder, pattern in SOURCES:
        for path in sorted((ROOT / folder).rglob(pattern)):
            files[str(path.relative_to(ROOT))] = path.read_text(encoding="utf-8")
    for name, text in files.items():
        for match in CALL.finditer(text):
            key = match[2]
            if key.endswith("."):  # the literal start of a key built at run time
                report.prefixes.add(key)
            elif match[3]:  # a complete literal key
                report.used.add(key)
                if (
                    key not in english
                    and f"{key}.other" not in english
                    and f"{key}.one" not in english
                ):
                    report.missing.setdefault(key, []).append(name)
            else:  # the start of a key built at run time
                report.prefixes.add(key)
    bases = {_base(k) for k in english}
    for key in sorted(english):
        base = _base(key)
        if (
            base in report.used
            or key in report.used
            or any(key.startswith(p) for p in report.prefixes)
            or key.startswith(ALWAYS_USED)
        ):
            continue
        report.unused.append(key)
    del bases
    for code in languages():
        if code == "en":
            continue
        other = load(code)
        report.lacking[code] = sorted(set(english) - set(other))
        report.extra[code] = sorted(
            k for k in other if k not in english and not k.startswith(ALWAYS_USED)
        )
        for key, text in other.items():
            if key in english and set(PLACEHOLDER.findall(text)) != set(
                PLACEHOLDER.findall(english[key])
            ):
                report.placeholders.append(
                    f"{code}: {key}: {sorted(PLACEHOLDER.findall(text))} != {sorted(PLACEHOLDER.findall(english[key]))}"
                )
    return report


def main(argv: list[str]) -> int:
    report = scan()
    for key, where in sorted(report.missing.items()):
        print(f"used but not in en.json: {key}  ({', '.join(sorted(set(where)))})")
    for key in report.unused:
        print(f"in en.json but not used: {key}")
    for line in report.placeholders:
        print(f"placeholders differ: {line}")
    for code, keys in report.extra.items():
        for key in keys:
            print(f"{code}: key English does not have: {key}")
    english = len(load("en"))
    for code, keys in report.lacking.items():
        done = english - len(keys)
        print(f"{code}: {done} of {english} keys translated, {len(keys)} fall back to English")
        if "--all" in argv:
            for key in keys:
                print(f"  {code}: missing {key}")
    print("ok" if report.ok else "problems found")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
