"""Translations (ADR-056): t / plural / fallback, the language of a request, the dictionary in the page, the node texts in
a language, and the drift checks of tools/check_i18n.py."""

from __future__ import annotations

import importlib.util
import json
import re
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from openartifact import i18n
from openartifact.graph.localize import localize
from openartifact.graph.manifest import read_placeholders
from openartifact.graph.node_types import NODE_TYPES

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def locales(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """A locales directory of its own: English, German with gaps, and a file that is not a language."""
    (tmp_path / "en.json").write_text(
        json.dumps(
            {
                "hello": "Hello {name}",
                "only_en": "Only English",
                "files.one": "{count} file",
                "files.other": "{count} files",
                "braces": "Use {braces} as they are",
            }
        )
    )
    (tmp_path / "de.json").write_text(
        json.dumps(
            {
                "_name": "Deutsch",
                "hello": "Hallo {name}",
                "files.one": "{count} Datei",
                "files.other": "{count} Dateien",
            }
        )
    )
    (tmp_path / "README.json").write_text("{}")  # not a language code
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    i18n.reload()
    yield tmp_path
    i18n.reload()


@pytest.fixture
def german_with_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[None, None, None]:
    """The shipped English and German, with two German texts taken out: German is complete (a test below says so), so
    the fallback to English on a page needs a gap made on purpose."""
    real = ROOT / "openartifact/i18n/locales"
    (tmp_path / "en.json").write_text(
        (real / "en.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    german = json.loads((real / "de.json").read_text(encoding="utf-8"))
    for key in ("credentials.copy", "credentials.new_token"):
        assert german.pop(key)
    (tmp_path / "de.json").write_text(json.dumps(german, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "LOCALES_DIR", tmp_path)
    i18n.reload()
    yield
    i18n.reload()


def test_the_languages_are_the_files_that_exist_english_first(locales: Path) -> None:
    assert i18n.languages() == ["en", "de"]
    assert i18n.language_name("de") == "Deutsch" and i18n.language_name("en") == "en"


def test_t_interpolates_and_falls_back_to_english_then_to_the_key(locales: Path) -> None:
    assert i18n.t("hello", "de", name="Ann") == "Hallo Ann"
    assert i18n.t("hello", "en", name="Ann") == "Hello Ann"
    assert i18n.t("only_en", "de") == "Only English"  # not translated: English
    assert i18n.t("nothing.here", "de") == "nothing.here"  # nowhere: the key, never an error
    assert i18n.t("hello", "xx", name="Ann") == "Hello Ann"  # unknown language: English
    assert (
        i18n.t("braces", "en") == "Use {braces} as they are"
    )  # a placeholder without a value stays
    assert i18n.t("hello", "en") == "Hello {name}"


def test_plural_picks_the_form_by_the_number_and_falls_back(locales: Path) -> None:
    assert i18n.plural("files", 1, "de") == "1 Datei"
    assert i18n.plural("files", 0, "de") == "0 Dateien"
    assert i18n.plural("files", 3, "en") == "3 files"
    assert i18n.plural("files", 2, "xx") == "2 files"
    assert i18n.plural("missing", 2) == "missing"


def test_the_dictionary_of_a_language_is_laid_over_english(locales: Path) -> None:
    merged = i18n.messages("de")
    assert merged["hello"] == "Hallo {name}" and merged["only_en"] == "Only English"
    assert "_name" not in merged


def test_the_language_of_a_request_is_the_choice_else_the_browsers_else_english(
    locales: Path,
) -> None:
    assert i18n.language_of("de", "en") == "de"  # the chosen one wins
    assert i18n.language_of(None, "de-AT,de;q=0.9,en;q=0.5") == "de"  # the first visit: the browser
    assert (
        i18n.language_of("fr", "fr,de;q=0.5") == "de"
    )  # a language that does not exist is not chosen
    assert i18n.language_of(None, "fr, it;q=0.8") == "en"
    assert i18n.language_of("xx", None) == "en"
    assert i18n.parse_accept_language("en;q=0.3, de, *;q=0.1, fr;q=0") == ["de", "en"]


# ── in the application ──────────────────────────────────────────────────


def test_a_page_is_in_the_language_of_the_cookie_and_says_so(
    client: TestClient, german_with_a_gap: None
) -> None:
    english = client.get("/")
    assert '<html lang="en"' in english.text and "Add lane" in english.text
    german = client.get("/", cookies={"oa_lang": "de"})
    assert '<html lang="de"' in german.text
    assert "Spalte hinzufügen" in german.text and "Add lane" not in german.text
    # a key German does not have is English on the page (fallback); the rest of the page is German
    credentials = client.get("/settings/credentials", cookies={"oa_lang": "de"}).text
    assert "New token" in credentials and "Zugangsdaten" in credentials


def test_the_first_visit_follows_accept_language_and_the_cookie_wins_afterwards(
    client: TestClient,
) -> None:
    assert '<html lang="de"' in client.get("/", headers={"Accept-Language": "de-DE,de;q=0.9"}).text
    assert '<html lang="en"' in client.get("/", headers={"Accept-Language": "fr"}).text
    both = client.get("/", headers={"Accept-Language": "de"}, cookies={"oa_lang": "en"})
    assert '<html lang="en"' in both.text


def _dictionary(html: str) -> dict[str, Any]:
    match = re.search(r'<script type="application/json" id="i18n">(.*?)</script>', html, re.S)
    assert match, "the page carries its dictionary"
    data: dict[str, Any] = json.loads(match[1])
    return data


def test_the_page_carries_the_dictionary_as_data_and_it_cannot_break_out_of_its_tag(
    client: TestClient, german_with_a_gap: None
) -> None:
    html = client.get("/", cookies={"oa_lang": "de"}).text
    data = _dictionary(html)
    assert data["lang"] == "de" and {"code": "de", "name": "Deutsch"} in data["languages"]
    assert data["messages"]["common.save"] == "Speichern"  # German
    assert data["messages"]["common.retry"] == "Erneut versuchen"
    assert data["messages"]["credentials.copy"] == "Copy"  # English where German has nothing yet
    block = re.search(r'id="i18n">(.*?)</script>', html, re.S)
    assert (
        block and "<" not in block[1] and "</script" not in block[1]
    )  # "<token>" in a text is escaped
    assert any(
        "<" in text for text in data["messages"].values()
    )  # a text with an angle bracket exists ("Bearer <token>"), and is escaped above


def test_the_dictionary_block_is_not_a_script_for_the_csp(client: TestClient) -> None:
    policy = client.get("/").headers["content-security-policy"]
    assert (
        "script-src 'self'" in policy
        and "unsafe-inline" not in policy.split("script-src")[1].split(";")[0]
    )


def test_node_types_are_described_in_the_language_of_the_request(client: TestClient) -> None:
    english = {t["kind"]: t for t in client.get("/api/node-types").json()}
    german = {t["kind"]: t for t in client.get("/api/node-types", cookies={"oa_lang": "de"}).json()}
    assert english["artifact"]["label"] == "Artifact" and german["artifact"]["label"] == "Artefakt"
    assert (
        german["artifact"]["menu"]["group"] == "Daten"
        and english["artifact"]["menu"]["group"] == "Data"
    )
    assert (
        german["artifact"]["menu"]["group_index"] == english["artifact"]["menu"]["group_index"]
    )  # the order is kept
    op = next(s for s in german["artifact"]["settings"] if s["key"] == "operation")
    assert op["label"] == "Vorgang" and op["options"] == [
        "Get comments",
        "Add comment",
    ]  # the stored values stay
    assert op["option_labels"] == {
        "Get comments": "Kommentare lesen",
        "Add comment": "Kommentar hinzufügen",
    }
    assert (
        german["github"]["label"] == english["github"]["label"]
    )  # no override: the manifest's text
    assert "option_labels" not in next(
        s for s in english["artifact"]["settings"] if s["key"] == "operation"
    )


def test_english_node_descriptions_are_returned_untouched() -> None:
    description = [t.describe() for t in NODE_TYPES.values()]
    assert localize(description, "en") is description


def test_the_login_message_is_in_the_language_too(migrated_settings: Any) -> None:
    from openartifact.app import _create_app

    settings = migrated_settings.model_copy(update={"api_token": "t" * 40, "secret_key": "k" * 40})
    with TestClient(_create_app(settings)) as c:
        wrong = c.post(
            "/login",
            content="token=nope&next=/",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            cookies={"oa_lang": "de"},
        )
        assert "Dieses Token ist nicht richtig." in wrong.text


# ── the drift checks ──────────────────────────────────────────────────────


def _tool() -> Any:
    spec = importlib.util.spec_from_file_location("check_i18n", ROOT / "tools" / "check_i18n.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys

    sys.modules["check_i18n"] = module  # dataclasses look the module up
    spec.loader.exec_module(module)
    return module


def test_every_key_in_use_exists_and_every_key_is_used_and_placeholders_agree() -> None:
    report = _tool().scan()
    assert not report.missing, f"used but not in en.json: {sorted(report.missing)}"
    assert not report.unused, f"in en.json but not used: {report.unused}"
    assert not report.placeholders, report.placeholders
    assert not any(report.extra.values()), report.extra


def test_the_checker_finds_a_missing_key_a_stray_key_and_a_changed_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool = _tool()
    (tmp_path / "locales").mkdir()
    (tmp_path / "templates").mkdir()
    (tmp_path / "locales" / "en.json").write_text(
        json.dumps({"a.used": "Hi {name}", "a.unused": "x"})
    )
    (tmp_path / "locales" / "de.json").write_text(
        json.dumps({"a.used": "Hallo {wer}", "a.stray": "y"})
    )
    (tmp_path / "templates" / "p.html").write_text("{{ t('a.used') }} {{ t('a.absent') }}")
    monkeypatch.setattr(tool, "ROOT", tmp_path)
    monkeypatch.setattr(tool, "LOCALES", tmp_path / "locales")
    report = tool.scan()
    assert list(report.missing) == ["a.absent"]
    assert report.unused == ["a.unused"]
    assert report.extra["de"] == ["a.stray"]
    assert report.placeholders and "a.used" in report.placeholders[0]
    assert report.lacking["de"] == ["a.unused"]
    assert not report.ok


def test_the_overrides_of_node_texts_name_things_that_exist() -> None:
    kinds = {t["kind"]: t for t in (t.describe() for t in NODE_TYPES.values())}
    groups = {t["menu"]["group"] for t in kinds.values() if t.get("menu")}
    for code in i18n.languages():
        if code == "en":
            continue
        for key in json.loads((ROOT / "openartifact/i18n/locales" / f"{code}.json").read_text()):
            if not key.startswith("nodes."):
                continue
            parts = key.split(".", 2)
            if parts[1] == "menu":
                assert parts[2] in groups, f"{code}: {key}: no such cluster"
                continue
            if parts[1] == "placeholders":
                name = parts[2].removesuffix(".label")
                assert name in {p.key for p in read_placeholders()} and parts[2].endswith(
                    ".label"
                ), f"{code}: {key}: no such placeholder"
                continue
            kind = kinds.get(parts[1])
            assert kind is not None, f"{code}: {key}: no such kind"
            rest = parts[2]
            if rest in ("label", "caption"):
                continue
            if rest.startswith("ports."):
                assert rest[6:] in {p["name"] for p in (*kind["inputs"], *kind["outputs"])}, (
                    f"{code}: {key}"
                )
                continue
            m = re.fullmatch(r"settings\.([^.]+)\.(label|help|placeholder|options\.(.+))", rest)
            assert m, f"{code}: {key}: not a known override"
            setting = next((s for s in kind["settings"] if s["key"] == m[1]), None)
            assert setting is not None, f"{code}: {key}: no such setting"
            if m[3]:
                assert m[3] in (setting.get("options") or []), f"{code}: {key}: no such option"


def test_german_has_a_text_for_every_english_key() -> None:
    """German is shipped complete, so a new English key without its German text fails here. Other languages stay free to
    be partial (they fall back to English); only German is held to this."""
    report = _tool().scan()
    assert report.lacking.get("de", []) == [], "German lacks texts: add them to locales/de.json"
