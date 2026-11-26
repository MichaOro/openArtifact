"""Every window is a form manifest (ADR-065): each ``modal(...)`` of the templates is a window drawn from a manifest or a named
exception with its reason. A new window that is neither fails here, so the rule is kept by a check and not only by a document."""

from __future__ import annotations

import re
from pathlib import Path

from openartifact.graph.manifest import read_all
from openartifact.ui import forms

TEMPLATES = Path(__file__).resolve().parent.parent / "openartifact" / "templates"

#: Windows whose fields are a manifest: the id of the dialog -> the form (``ui/forms/<form>.yaml``) or "nodes" (the settings of a
#: node kind, ``graph/nodes/*.yaml``, ADR-053/054).
MANIFEST_WINDOWS = {
    "agent-modal": "agent",  # the window of the agents list
    "credential-modal": "credential",
    "graph-modal": "action",  # the window of the pipeline list and of the action list (form: pipeline or action)
    "guard-modal": "guard",
    "node-modal": "nodes",
}

#: Handmade windows that are allowed, each with why. A window moves out of this list when it becomes a manifest (the owner schedules
#: that, or a change that rebuilds it does); a new window is never added here without a reason that is one of the first three.
EXCEPTIONS = {
    # a question or a notice, no fields
    "confirm-modal": "a question (the shared confirm component)",
    "leave-modal": "a question (the shared leave component)",
    "token-modal": "shows a token once, no fields to fill in",
    "version-modal": "displays a published version of an agent, read-only",
    # one choice or one name (binding rule 3: the name is the title)
    "guard-attach-modal": "a picker: attach an existing guard or make a new one",
    "new-modal": "a name dialog (the name goes into the title when it is migrated)",
    # still handmade, waiting for a manifest (the owner schedules them; see the list in guides/extending.md)
    "provider-modal": "to migrate: the LLM provider dialog (text, a credential chooser and a model list)",
    "retention-modal": "to migrate: the retention rule (a rule tree and a select)",
    "card-rules-modal": "to migrate: the rules of a lane and of the board (a rule tree and a select; the frame of retention-modal)",
    "fields-modal": "to migrate: the artifact fields dialog (a rows widget with add, remove and order)",
    "create-task-modal": "to migrate: the create-artifact dialog (its fields are dynamic)",
}

MODAL = re.compile(r"\{%-?\s*call\s+modal\(\s*(?:\"([a-z0-9-]+)\"|([a-z_]+))")
#: A manifest window is made by the shared macro ``{{ manifest_modal("id", ...) }}`` (templates/components/manifest_modal.html).
MANIFEST_MODAL = re.compile(r"\{\{\s*manifest_modal\(\s*\"([a-z0-9-]+)\"")


def _windows() -> dict[str, list[str]]:
    """The windows the templates declare: id -> the files. A window whose id is a macro parameter (the shared dialogs) is named
    by the parameter and checked through the macro's own callers below."""
    found: dict[str, list[str]] = {}
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path.name == "modal.html":  # the macro itself (its usage example is a comment)
            continue
        text = path.read_text(encoding="utf-8")
        for literal, variable in MODAL.findall(text):
            found.setdefault(literal or f"<{variable}>", []).append(path.name)
        for literal in MANIFEST_MODAL.findall(text):
            found.setdefault(literal, []).append(path.name)
    return found


def test_every_window_is_a_form_manifest_or_a_named_exception() -> None:
    shared = {
        "<id>": "the macros of the shared dialogs (confirm, leave, name dialogs): exceptions above"
    }
    unknown = {
        window: files
        for window, files in _windows().items()
        if window not in MANIFEST_WINDOWS and window not in EXCEPTIONS and window not in shared
    }
    assert not unknown, (
        f"a window that is neither a form manifest nor a named exception: {unknown}. Describe it in ui/forms/<name>.yaml and draw it with "
        "FormView (ADR-065); only a question, a display-only window or a picker is an exception, with its reason in this test."
    )


def test_a_manifest_window_has_its_manifest_and_an_exception_is_still_a_window() -> None:
    windows = _windows()
    node_kinds = {m.kind for m in read_all()}
    assert node_kinds, "the node manifests exist"
    for window, form in MANIFEST_WINDOWS.items():
        assert window in windows, (
            f"{window} is no longer in a template: take it out of MANIFEST_WINDOWS"
        )
        if form != "nodes":
            assert form in forms.FORMS, f"{window}: no form manifest ui/forms/{form}.yaml"
    for window, why in EXCEPTIONS.items():
        assert why.strip(), window
        # shared dialogs are made by macros with a parameter id: their literal ids are in no template, so they are not checked here
        if window in {"confirm-modal", "leave-modal", "new-modal"}:
            continue
        assert window in windows, f"{window} is no longer in a template: take it out of EXCEPTIONS"
        assert window not in MANIFEST_WINDOWS
