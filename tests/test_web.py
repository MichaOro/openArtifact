"""Tests for the web application shell."""

from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from openartifact.app import _create_app
from openartifact.config import Settings
from openartifact.version import __version__


@pytest.fixture
def db_client(migrated_settings: Settings) -> Generator[TestClient, None, None]:
    """Test client with the real lifespan on a migrated database, for pages that read it."""
    with TestClient(_create_app(migrated_settings)) as c:
        yield c


# ── Root path (web shell) ─────────────────────────────────────────────


def test_root_returns_200(client: TestClient) -> None:
    """Root path returns HTTP 200 with HTML."""
    response = client.get("/")
    assert response.status_code == 200


def test_root_contains_html(client: TestClient) -> None:
    """Root page contains OpenArtifact identity."""
    response = client.get("/")
    assert "OpenArtifact" in response.text


def test_root_contains_version(client: TestClient) -> None:
    """Root page displays version."""
    response = client.get("/")
    assert __version__ in response.text


def test_root_loads_no_external_scripts(client: TestClient) -> None:
    """All scripts are served locally from /static (no CDN, ADR-010)."""
    response = client.get("/")
    assert "htmx" not in response.text
    assert "https://" not in response.text.replace("https://www.w3.org", "")


# ── UI shell: layout, design system, kanban ───────────────────────────


def test_static_assets_served(client: TestClient) -> None:
    """CSS and JS assets are reachable under /static."""
    for path in (
        "/static/css/tokens.css",
        "/static/css/base.css",
        "/static/css/components.css",
        "/static/js/theme.js",
        "/static/js/main.js",
    ):
        assert client.get(path).status_code == 200, path


def test_root_links_assets(client: TestClient) -> None:
    """Page references the design-system assets."""
    html = client.get("/").text
    assert "/static/css/tokens.css" in html
    assert "/static/js/theme.js" in html


def test_the_artifact_rail_has_the_fields_group_built_from_the_same_navigation_markup(
    client: TestClient,
) -> None:
    """A group is a navigation entry kind like the others: the same section and list classes as the main
    navigation's sub-entries, filled by the page and hidden until artifact fields exist."""
    html = client.get("/").text
    rail = html[html.index("data-card-nav") :]
    assert 'class="nav-section nav-group" data-nav-group="fields"' in rail
    assert "data-nav-group-toggle" in rail and 'class="nav-list nav-group__list"' in rail
    assert "data-field-rail hidden" in rail  # nothing to show before fields are defined


def test_navigation_shows_the_pipeline_entries_only_inside_the_pipeline(client: TestClient) -> None:
    """Board, Pipeline and Executions are always there; Actions and Agents only once Pipeline is entered."""
    html = client.get("/").text
    # Board, Pipeline, Executions and Settings (artifact fields live in the board's menu, ADR-044)
    sidebar = html[
        html.index('class="sidebar"') : html.index("</aside>")
    ]  # the rail of the dialog has its own entries
    assert sidebar.count('class="nav-link"') == 4
    assert 'href="/artifact-types"' not in html
    assert 'href="/pipelines"' in html  # the Pipeline entry itself
    assert 'href="/actions"' not in html and 'href="/agents"' not in html
    assert 'href="/guards"' not in html
    for path, marked_as_section in (
        ("/pipelines", 0),
        ("/actions", 1),
        ("/guards", 1),
        ("/agents", 1),
        ("/agents/x", 1),
    ):
        inside = client.get(path).text
        # the sub-entries: Actions and Guards (the libraries), Agents
        assert (
            'href="/actions"' in inside
            and 'href="/guards"' in inside
            and 'href="/agents"' in inside
        )
        assert inside.count("nav-link--section") == marked_as_section
        assert inside.count('aria-current="page"') == 1


def test_pipeline_pages_render_and_mark_their_navigation_entry(db_client: TestClient) -> None:
    for path in ("/pipelines", "/pipelines/any-id"):
        response = db_client.get(path)
        assert response.status_code == 200
        assert 'href="/pipelines"' in response.text
        assert response.text.count('aria-current="page"') == 1


def test_action_pages_render_and_mark_their_navigation_entry(db_client: TestClient) -> None:
    for path in ("/actions", "/actions/any-id"):
        response = db_client.get(path)
        assert response.status_code == 200
        assert 'href="/actions"' in response.text
        assert response.text.count('aria-current="page"') == 1


def test_the_guards_page_renders_with_the_guard_editor_and_marks_its_entry(
    db_client: TestClient,
) -> None:
    response = db_client.get("/guards")
    assert response.status_code == 200
    assert (
        'aria-current="page"' in response.text and response.text.count('aria-current="page"') == 1
    )
    assert 'id="guard-modal"' in response.text and "data-guard-list" in response.text
    assert "/static/js/guards/library-page.js" in response.text


def test_board_has_three_empty_lanes(client: TestClient) -> None:
    """Board shows Backlog / In Progress / Done, empty, counters at 0."""
    html = client.get("/").text
    for title in ("Backlog", "In Progress", "Done"):
        assert f">{title}</span></h2>" in html
    assert html.count('class="lane__count"') == 4  # three lanes and the template for new ones
    assert html.count(">0</span>") == 4
    page = re.sub(
        r'<script type="application/json" id="i18n">.*?</script>', "", html, flags=re.S
    )  # the dictionary has the text too
    assert page.count("No artifacts yet") == 4
    assert "data-task-id" not in html  # cards are rendered client-side; none are baked in


def test_toggles_are_accessible(client: TestClient) -> None:
    """Theme and sidebar toggles are buttons with ARIA labels."""
    html = client.get("/").text
    assert "data-theme-toggle" in html
    assert "data-sidebar-toggle" in html
    assert 'aria-label="Collapse sidebar"' in html


def test_design_tokens_define_mandatory_colors() -> None:
    """Both themes define the mandatory palette in tokens.css."""
    css = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "tokens.css"
    ).read_text()
    for value in (
        # dark
        "#080519",
        "#110d29",
        "#1b1538",
        "#30205b",
        "#9665ff",
        "#aab3bf",
        "#ece7f8",
        # light (Sand Dune)
        "#f0ede5",
        "#e7e1d6",
        "#faf8f3",
        "#d5cec1",
        "#8050e8",
        "#110d29",
        "#514b43",
    ):
        assert value in css, value


def test_no_hex_colors_outside_tokens() -> None:
    """Raw colour values are only allowed in tokens.css."""
    import re

    base = Path(__file__).parent.parent / "openartifact"
    files = [
        *(base / "static" / "css").glob("*.css"),
        *(base / "static" / "js").rglob("*.js"),
        *(base / "templates").rglob("*.html"),
    ]
    for f in files:
        if f.name == "tokens.css":
            continue
        assert not re.search(r"#[0-9a-fA-F]{6}\b", f.read_text()), f.name


# ── Create-task UI markup ─────────────────────────────────────────────


def test_each_lane_has_an_add_button_with_its_status(client: TestClient) -> None:
    """Every lane gets a + button that carries the lane's API status."""
    html = client.get("/").text
    assert html.count("data-create-task") == 4  # three lanes and the template for new ones
    for status, title in (("backlog", "Backlog"), ("in_progress", "In Progress"), ("done", "Done")):
        assert f'data-status="{status}" data-lane-title="{title}"' in html
        assert f'aria-label="Add artifact to {title}"' in html


def test_create_task_modal_markup(client: TestClient) -> None:
    """The modal is an accessible dialog with the two specified fields and actions."""
    html = client.get("/").text
    assert '<dialog class="modal" id="create-task-modal" aria-labelledby=' in html
    assert ">Create Artifact</h2>" in html
    assert 'placeholder="Enter artifact title..."' in html
    assert 'placeholder="Describe your artifact..."' in html
    assert 'aria-label="Close dialog"' in html
    assert "Cancel</button>" in html
    assert 'type="submit"' in html
    assert "<span data-submit-label>Create</span>" in html


def test_task_modules_are_served(client: TestClient) -> None:
    """The ES modules of the task feature are reachable."""
    assert 'type="module" src="/static/js/tasks/main.js"' in client.get("/").text
    for path in (
        "/static/js/tasks/main.js",
        "/static/js/tasks/api.js",
        "/static/js/tasks/board.js",
        "/static/js/tasks/artifact-dialog.js",
        "/static/js/tasks/history-tab.js",
        "/static/js/tasks/history-list.js",
        "/static/js/tasks/history-detail.js",
        "/static/js/tasks/history-api.js",
        "/static/js/tasks/history-format.js",
        "/static/js/tasks/history-step.js",
        "/static/js/components/tabs.js",
        "/static/css/history.css",
        "/static/js/components/modal.js",
        "/static/js/components/action-dialog.js",
        "/static/js/components/form-dialog.js",
        "/static/css/forms.css",
        "/static/css/modal.css",
    ):
        assert client.get(path).status_code == 200, path


def test_light_theme_is_sand_dune_without_old_palettes() -> None:
    """Light tokens are the Sand Dune palette; old Lavender/Glacial Slate values are gone."""
    css = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "tokens.css"
    ).read_text()
    light = css[
        css.index("Semantic colour tokens: Light") : css.index("Semantic colour tokens: Dark")
    ]
    for old in (
        "#f5f2fc",
        "#ece7f8",
        "#dad1ed",
        "#c1c9d4",
        "#aab3bf",
        "#dce1e7",
        "#939daa",
        "#3b4550",
    ):
        assert old not in light, old


def test_static_assets_are_revalidated_not_heuristically_cached(client: TestClient) -> None:
    """Assets are not fingerprinted, so browsers must revalidate (ETag -> 304)."""
    first = client.get("/static/js/tasks/main.js")
    assert first.headers["cache-control"] == "no-cache"
    assert first.headers["etag"]
    again = client.get("/static/js/tasks/main.js", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@pytest.mark.parametrize("page", ["/", "/pipelines", "/actions", "/executions", "/login"])
def test_pages_are_revalidated_so_a_new_build_is_never_shown_as_the_old_one(
    client: TestClient, page: str
) -> None:
    """A page (HTML) carries the markup, language and dictionary of its build: it must not be reused from the cache."""
    response = client.get(page)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    # an API answer is not a page: it keeps whatever the endpoint says (nothing)
    assert "cache-control" not in client.get("/api/tasks").headers


def test_task_modal_supports_create_and_edit_modes(client: TestClient) -> None:
    """The same dialog is reused for editing: its title and submit label are switchable."""
    html = client.get("/").text
    assert "data-submit-label" in html
    assert 'class="modal__title"' in html
    assert "data-delete-task" in html  # card template carries the delete button
    assert 'id="delete-task-modal"' in html
    assert "data-live-region" in html


def test_task_dialog_has_collapsed_card_navigation_with_delete(client: TestClient) -> None:
    """Right-hand rail in the task dialog: collapsed by default, only action is Delete."""
    html = client.get("/").text
    assert 'data-card-nav data-state="collapsed"' in html
    assert "data-card-nav-toggle" in html
    assert 'aria-label="Expand artifact details"' in html
    assert (
        html.count('data-card-action="delete"') == 1
    )  # the rail's only command (Start/Stop is in the footer)
    assert html.count("data-card-action=") == 2
    assert "collapsible-nav.js" in client.get("/static/js/tasks/main.js").text
    assert client.get("/static/js/components/collapsible-nav.js").status_code == 200


# ── Lanes are configuration, not markup ───────────────────────────────


def test_board_renders_lanes_from_the_database(client: TestClient) -> None:
    """Lane order, titles and API status come from the ``lanes`` table."""
    html = client.get("/").text
    lanes = client.get("/api/lanes").json()
    assert [lane["key"] for lane in lanes] == ["backlog", "in-progress", "done"]
    positions = [html.index(f'data-status="{lane["status"]}"') for lane in lanes]
    assert positions == sorted(positions)
    for lane in lanes:
        assert f'data-lane="{lane["key"]}" data-status="{lane["status"]}"' in html
        assert f">{lane['title']}</span></h2>" in html


def test_task_dialog_offers_lane_switch(client: TestClient) -> None:
    """Lane chip (no icon, a button) and the Lane field of the rail both open the lane menu."""
    html = client.get("/").text
    assert (
        '<button type="button" class="modal__subtitle" data-ui="custom" '
        'data-ui-reason="lane chip tinted with the lane hue" data-modal-subtitle '
        'aria-haspopup="listbox" aria-expanded="false"></button>'
    ) in html
    assert 'data-card-field="lane"' in html
    assert "data-lane-value" in html
    assert client.get("/static/js/components/lane-picker.js").status_code == 200


# ── Lane colours (palette tokens, lane N = hue N) ─────────────────────


def test_each_lane_gets_its_own_hue(client: TestClient) -> None:
    from openartifact.tasks.lanes import LANE_HUES

    html = client.get("/").text
    for index, lane in enumerate(client.get("/api/lanes").json()):
        hue = index % LANE_HUES + 1
        assert (
            f'data-lane="{lane["key"]}" data-status="{lane["status"]}" data-lane-hue="{hue}"'
            in html
        )


def test_palette_tokens_exist_for_both_themes_and_every_hue() -> None:
    import re

    from openartifact.tasks.lanes import LANE_HUES

    css = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "tokens.css"
    ).read_text()
    light = css[
        css.index("Semantic colour tokens: Light") : css.index("Semantic colour tokens: Dark")
    ]
    dark = css[css.index("Semantic colour tokens: Dark") :]
    for theme in (light, dark):
        for n in range(1, LANE_HUES + 1):
            assert re.search(rf"--lane-hue-{n}:\s*#[0-9a-f]{{6}};", theme), n
    components = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "components.css"
    ).read_text()
    for n in range(1, LANE_HUES + 1):
        assert f'[data-lane-hue="{n}"] {{ --lane-color: var(--lane-hue-{n}); }}' in components


def test_task_dialog_has_inline_lane_chip_row(client: TestClient) -> None:
    """The lane chip unrolls an inline row (no popup); it starts closed and inert."""
    html = client.get("/").text
    assert 'class="lane-chips" data-lane-chips inert aria-hidden="true"' in html
    assert 'class="lane-chips__inner" role="listbox"' in html


def test_tasks_can_be_reordered_by_keyboard_and_pointer_markup(client: TestClient) -> None:
    html = client.get("/").text
    assert "Alt+ArrowUp Alt+ArrowDown" in html


# ── Parent artifacts, rail layout, sidebar toggle ─────────────────────


def test_dialog_rail_has_lane_and_parent_fields_and_delete(client: TestClient) -> None:
    html = client.get("/").text
    assert 'data-card-field="lane"' in html
    assert 'data-card-field="parent"' in html
    assert "data-parent-value" in html
    assert html.count('data-card-action="delete"') == 1  # Delete is the rail's only action


def test_card_template_has_a_relations_line_and_delete_dialog_a_children_note(
    client: TestClient,
) -> None:
    html = client.get("/").text
    assert 'class="task-card__meta" hidden' in html
    assert "data-children-note" in html


def test_sidebar_toggle_comes_first_in_the_footer_so_it_never_moves(client: TestClient) -> None:
    html = client.get("/").text
    footer = html[html.index('class="sidebar__footer"') :]
    assert footer.index("data-sidebar-toggle") < footer.index("sidebar__footer-text")


def test_rail_grows_the_card_instead_of_shrinking_the_form() -> None:
    css = (
        Path(__file__).parent.parent / "openartifact" / "static" / "css" / "modal.css"
    ).read_text()
    assert "--form-w" in css and "--rail-w" in css
    assert "grid-template-columns: var(--form-w) var(--rail-w)" in css


def test_stage_pages_use_the_name_of_the_stage(db_client: TestClient) -> None:
    created = db_client.post("/api/pipelines", json={"name": "Gap Analyses"}).json()
    assert created["slug"] == "gap-analyses"
    page = db_client.get("/pipelines/gap-analyses")
    assert page.status_code == 200
    assert f'data-graph-id="{created["id"]}"' in page.text
    assert 'data-kind="pipeline"' in page.text
    assert (
        db_client.get("/actions/gap-analyses").status_code == 200
    )  # unknown here: the editor says so
    assert db_client.get("/workflows").status_code == 404  # the earlier URL is gone


def test_name_dialogs_are_the_shared_form_dialog(client: TestClient) -> None:
    """Pipeline/action lists and the editor render the same form_modal with one Name field."""
    for path in ("/pipelines", "/actions"):
        html = client.get(path).text
        assert 'id="name-modal-field-name"' in html
        assert 'id="name-modal-field-name-error"' in html
        assert "<span data-submit-label>Create</span>" in html
        assert "data-cancel" in html


def test_the_execution_flow_page_and_its_modules_are_served(client: TestClient) -> None:
    """The flow page of an execution is a sub-page of the board; whether the execution exists is the page's business."""
    page = client.get("/artifacts/7/executions/abc")
    assert page.status_code == 200
    assert 'data-task-ref="7"' in page.text and 'data-execution-id="abc"' in page.text
    assert 'type="module" src="/static/js/execution/flow-page.js"' in page.text
    assert 'id="history-step-template"' in page.text
    assert page.text.count('aria-current="page"') == 1  # the sidebar marks Executions
    assert 'href="/executions" title="Executions"' in page.text
    for path in (
        "/static/js/execution/flow-page.js",
        "/static/js/execution/flow-client.js",
        "/static/js/execution/flow-view.js",
        "/static/js/execution/flow-panel.js",
        "/static/js/execution/visit-model.js",
        "/static/js/execution/breadcrumb.js",
        "/static/css/execution.css",
        "/static/js/tasks/history-step.js",
    ):
        assert client.get(path).status_code == 200, path


def test_the_executions_page_and_its_modules_are_served(client: TestClient) -> None:
    """The global execution list: page, sidebar entry (marked on it and on the flow page), modules, styles."""
    page = client.get("/executions")
    assert page.status_code == 200
    assert 'type="module" src="/static/js/executions/page.js"' in page.text
    assert 'data-page-size="50"' in page.text and 'id="ex-row-template"' in page.text
    assert page.text.count('aria-current="page"') == 1
    assert 'href="/executions" title="Executions"' in page.text
    assert '<caption class="visually-hidden">' in page.text and page.text.count('scope="col"') == 11
    assert 'data-page-size="2"' in client.get("/executions?page_size=2").text
    assert 'data-page-size="200"' in client.get("/executions?page_size=9999").text
    assert 'data-page-size="1"' in client.get("/executions?page_size=0").text
    for path in (
        "/static/js/executions/page.js",
        "/static/js/executions/api.js",
        "/static/js/executions/filters.js",
        "/static/js/executions/filter-bar.js",
        "/static/js/executions/summary.js",
        "/static/js/executions/table.js",
        "/static/js/tasks/history-row.js",
        "/static/css/executions.css",
    ):
        assert client.get(path).status_code == 200, path


def test_the_board_opens_an_artifact_given_in_the_url(client: TestClient) -> None:
    """``/?artifact=12`` is what the global execution list links to; the board's script handles it."""
    assert client.get("/?artifact=12").status_code == 200
    script = client.get("/static/js/tasks/main.js").text
    assert 'get("artifact")' in script


def test_the_history_tab_links_to_the_flow_page(client: TestClient) -> None:
    html = client.get("/").text
    assert "data-detail-flow" in html and ">Open flow</a>" in html
    assert html.count('id="history-step-template"') == 1


# ── the sign-in form body ─────────────────────────────────────────────


def test_a_sign_in_body_without_a_declared_length_above_the_limit_gets_413_before_any_check(
    migrated_settings: Settings,
) -> None:
    token = "web-token-" + "x" * 30
    settings = migrated_settings.model_copy(update={"api_token": token, "secret_key": "k" * 40})

    def chunks() -> Generator[bytes, None, None]:
        yield b"token=" + token.encode() + b"&next=/"  # the right token ...
        for _ in range(5):
            yield b"&pad=" + b"a" * 1000  # ... but a body no sign-in form needs

    with TestClient(_create_app(settings)) as app:
        response = app.post(
            "/login",
            content=chunks(),  # a generator is sent chunked, with no Content-Length
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert (response.status_code, response.text) == (413, "The request is too large")
        assert "set-cookie" not in response.headers
        assert app.get("/api/tasks").status_code == 401  # it did not sign in
