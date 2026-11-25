"""The UI catalog (ADR-059): the button variants are readable in every state and both themes, and every button of the
main pages comes from the catalog. Contrast is computed from the colours the browser really paints (the effective
background is the stack of translucent layers over the page), not read from tokens."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.helpers import Board, echo_pipeline
from tests.helpers import graph_url

TEXT_MIN = 4.5  # WCAG AA for text
DISABLED_TEXT_MIN = 3.0  # WCAG exempts disabled controls; the catalog does not: they stay readable
BORDER_MIN = 3.0  # an outline that makes a control visible, and the focus ring

# Components a <button> may be: one list, documented in docs/guides/ui-catalog.md.
CATALOG_CLASSES = {
    "button",  # .button--primary / --ghost / --danger (+ --sm), .is-danger
    "icon-button",
    "chip-button",  # a toggle pill (aria-pressed): filters
    "ge-switch",  # an on/off switch (switch.js)
    "task-tab",  # a tab of a tab list
    "nav-link",  # an entry of a navigation
    "menu__item",  # an item of a menu
    "popover__option",  # an option of a popover list
    "info-tip",  # the (i) that opens the explanation of a field (components/info-tip.js)
    "layout-handle",  # the handle on the top edge of a manifest window (components/window-layout.js, ADR-063)
    "lw-grip",  # the grip of a section or field in the arrange view (components/layout-arrange.js)
}

MEASURE = """
(el) => {
  const parse = (c) => {
    const m = c.match(/color\\(srgb ([\\d.]+) ([\\d.]+) ([\\d.]+)(?: \\/ ([\\d.]+))?\\)|rgba?\\(([\\d.]+), ([\\d.]+), ([\\d.]+)(?:, ([\\d.]+))?\\)/);
    if (!m) {
      const x = document.createElement('canvas').getContext('2d'); x.fillStyle = '#000'; x.fillStyle = c;
      x.fillRect(0, 0, 1, 1); const d = x.getImageData(0, 0, 1, 1).data; return [d[0], d[1], d[2], d[3] / 255];
    }
    if (m[1]) return [m[1] * 255, m[2] * 255, m[3] * 255, m[4] === undefined ? 1 : +m[4]];
    return [+m[5], +m[6], +m[7], m[8] === undefined ? 1 : +m[8]];
  };
  const over = (top, bottom) => {
    const a = top[3] + bottom[3] * (1 - top[3]);
    if (a === 0) return [0, 0, 0, 0];
    return [0, 1, 2].map((i) => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / a).concat([a]);
  };
  const backdrop = (start) => {
    const layers = [];
    for (let e = start; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c[3] > 0) layers.push(c);
      if (c[3] >= 1) break;
    }
    // the page behind everything is the --color-background token (the body paints a gradient over it)
    const probe = document.createElement('div');
    probe.style.background = 'var(--color-background)';
    document.body.append(probe);
    const base = parse(getComputedStyle(probe).backgroundColor);
    probe.remove();
    let out = [base[0], base[1], base[2], 1];
    for (const l of layers.reverse()) out = over(l, out);
    return out;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
  const cs = getComputedStyle(el);
  const outside = backdrop(el.parentElement);          // what is behind the control
  const own = backdrop(el);                            // behind its text (its own fill included)
  const text = over(parse(cs.color), own);
  const border = over(parse(cs.borderTopColor), outside);
  const outline = over(parse(cs.outlineColor), outside);
  return {
    text: ratio(text, own),
    border: parseFloat(cs.borderTopWidth) > 0 ? ratio(border, outside) : null,
    outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0 ? ratio(outline, outside) : null,
    fill: ratio(own, outside),
    opacity: parseFloat(cs.opacity),
  };
}
"""

# The page-wide audit: every visible button-like element, its catalog class and its readability.
AUDIT = (
    """
() => {
  const measure = """
    + MEASURE
    + """;
  const out = [];
  for (const el of document.querySelectorAll('button, [role=button], a.button')) {
    const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) continue;  // (a control revealed on hover is not on the page until then)
    const m = measure(el);
    out.push({
      classes: [...el.classList], custom: el.dataset.ui || null, reason: el.dataset.uiReason || null,
      text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 30),
      disabled: el.disabled || el.getAttribute('aria-disabled') === 'true', ratio: m.text, opacity: m.opacity,
    });
  }
  return out;
}
"""
)


def _theme(page: Page, theme: str) -> None:
    """Switch the theme and stop all transitions, so the colours read are the settled ones, not a fade."""
    page.evaluate(
        """(theme) => {
          document.documentElement.dataset.theme = theme;
          if (!document.getElementById('no-motion')) {
            const s = document.createElement('style');
            s.id = 'no-motion';
            s.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; }';
            document.head.append(s);
          }
        }""",
        theme,
    )


def _measure(page: Page, el: Locator) -> dict[str, Any]:
    return page.evaluate(f"({MEASURE})", el.element_handle())  # type: ignore[no-any-return]


def _stage(page: Page, html: str) -> Locator:
    """One control in a container painted like a dialog (the glass card colour); returns the control."""
    page.evaluate(
        """(html) => {
          document.querySelector('#catalog-stage')?.remove();
          const box = document.createElement('div');
          box.id = 'catalog-stage';
          box.style.cssText = 'position:fixed;left:40px;top:40px;z-index:9999;padding:24px;background:var(--color-glass-card)';
          box.innerHTML = '<style>#catalog-stage * { transition: none !important; }</style>' + html;
          document.body.append(box);
        }""",
        html,
    )
    return page.locator("#catalog-stage > :not(style)").first


VARIANTS = {
    "primary": '<button class="button button--primary">Comment</button>',
    "primary small": '<button class="button button--primary button--sm">Add lane</button>',
    "ghost": '<button class="button button--ghost">Close</button>',
    "ghost small": '<button class="button button--ghost button--sm">Start processing</button>',
    "danger": '<button class="button button--danger">Delete</button>',
    "ghost danger": '<button class="button button--ghost is-danger">Clear finished</button>',
    "icon": '<button class="icon-button" aria-label="Menu"><svg class="icon" width="16" height="16" viewBox="0 0 16 16"><path d="M2 8h12" stroke="currentColor" stroke-width="2"/></svg></button>',
    "icon danger": '<button class="icon-button is-danger" aria-label="Delete"><svg class="icon" width="16" height="16" viewBox="0 0 16 16"><path d="M2 8h12" stroke="currentColor" stroke-width="2"/></svg></button>',
    "icon quiet": '<button class="icon-button icon-button--quiet icon-button--xs" aria-label="Guards"><svg class="icon" width="16" height="16" viewBox="0 0 16 16"><path d="M2 8h12" stroke="currentColor" stroke-width="2"/></svg></button>',
    "layout handle": '<button class="layout-handle" aria-label="Window layout"><svg class="icon" width="16" height="16" viewBox="0 0 16 16"><path d="M2 8h12" stroke="currentColor" stroke-width="2"/></svg></button>',
    "layout grip": '<button class="lw-grip" aria-label="Move"><svg class="icon" width="16" height="16" viewBox="0 0 16 16"><path d="M2 8h12" stroke="currentColor" stroke-width="2"/></svg></button>',
    "chip off": '<button class="chip-button" aria-pressed="false">Comments</button>',
    "chip on": '<button class="chip-button" aria-pressed="true">Comments</button>',
}
OUTLINED = {"ghost", "ghost small", "ghost danger", "chip off"}


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("variant", list(VARIANTS))
def test_a_button_variant_is_readable_in_every_state(
    page: Page, base_url: str, theme: str, variant: str
) -> None:
    page.goto(base_url)
    _theme(page, theme)
    button = _stage(page, VARIANTS[variant])
    found: dict[str, dict[str, Any]] = {"default": _measure(page, button)}
    button.hover()
    found["hover"] = _measure(page, button)
    page.mouse.move(0, 0)
    page.keyboard.press("Shift")  # keyboard modality: the focus ring shows (:focus-visible)
    button.focus()
    found["focus"] = _measure(page, button)
    button.evaluate("el => el.blur()")
    button.evaluate("el => el.setAttribute('aria-busy', 'true')")
    found["busy"] = _measure(page, button)
    button.evaluate("el => { el.removeAttribute('aria-busy'); el.disabled = true; }")
    found["disabled"] = _measure(page, button)
    for state, m in found.items():
        floor = DISABLED_TEXT_MIN if state == "disabled" else TEXT_MIN
        assert m["text"] >= floor, (
            f"{variant} / {theme} / {state}: text contrast {m['text']:.2f} < {floor}"
        )
        assert m["opacity"] == 1, (
            f"{variant} / {theme} / {state}: opacity {m['opacity']} (disabled looks come from tokens, not opacity)"
        )
        if variant in OUTLINED:
            assert m["border"] is not None and m["border"] >= BORDER_MIN, (
                f"{variant} / {theme} / {state}: outline contrast {m['border']} < {BORDER_MIN}"
            )
    ring = found["focus"]["outline"]
    assert ring is not None and ring >= BORDER_MIN, (
        f"{variant} / {theme}: focus ring contrast {ring} < {BORDER_MIN}"
    )


def _audit(page: Page, theme: str, where: str) -> list[str]:
    problems: list[str] = []
    for b in page.evaluate(AUDIT):
        owned = CATALOG_CLASSES.intersection(b["classes"])
        label = f"{where} [{theme}] <{'.'.join(b['classes']) or 'no class'}> {b['text']!r}"
        if not owned and not (b["custom"] == "custom" and b["reason"]):
            problems.append(
                f"{label}: not a catalog component (add a class from the catalog, or data-ui=custom with data-ui-reason)"
            )
        floor = DISABLED_TEXT_MIN if b["disabled"] else TEXT_MIN
        if b["ratio"] < floor:
            problems.append(
                f"{label}: text contrast {b['ratio']:.2f} < {floor}{' (disabled)' if b['disabled'] else ''}"
            )
        if b["opacity"] < 1:
            problems.append(
                f"{label}: opacity {b['opacity']} (states come from tokens, not opacity)"
            )
    return problems


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_button_of_the_main_pages_comes_from_the_catalog_and_is_readable(
    page: Page, base_url: str, api: httpx.Client, board: Board, theme: str
) -> None:
    board.create("Item")
    pipeline = echo_pipeline(api)
    problems: list[str] = []
    when = {
        "type": "group",
        "mode": "all",
        "items": [{"type": "condition", "field": "status", "op": "is", "value": ["failed"]}],
    }
    api.put(  # one rule that is on and one that is off: both looks of a row (nothing exists yet to delete)
        "/api/settings/retention",
        json={
            "rules": [
                {"when": when, "action": "delete", "name": "Failed ones"},
                {"when": when, "action": "delete", "enabled": False},
            ]
        },
    ).raise_for_status()

    # a guard of the library, attached to the stage and switched off there: the shield, its popup with a muted row,
    # and the guard editor with its Delete refused while it is used (ADR-060)
    guard = api.post(
        "/api/guards",
        json={
            "name": "Stall guard",
            "trigger": {"type": "event", "events": ["enter"]},
            "when": when | {"items": []},
        },
    ).json()
    placed = api.post(
        "/api/guard-attachments",
        json={
            "guard_id": guard["id"],
            "pipeline_id": pipeline["id"],
            "scope_type": "stage",
            "scope_id": pipeline["stages"][0][0]["id"],
            "enabled": False,
        },
    )
    placed.raise_for_status()
    other = api.post(  # one that hangs nowhere: the attach dialog's combobox offers it
        "/api/guards",
        json={
            "name": "Health guard",
            "trigger": {"type": "event", "events": ["enter"]},
            "when": when | {"items": []},
            "scope_types": ["pipeline", "stage", "action"],
        },
    )
    other.raise_for_status()

    def check(where: str) -> None:
        problems.extend(_audit(page, theme, where))

    board.open()
    _theme(page, theme)
    check("board")
    dialog = board.open().open_card("Item")
    _theme(page, theme)
    for tab in ("details", "comments", "history"):
        dialog.root.locator(f'[role=tab][id$="-{tab}"]').click()
        check(f"artifact dialog / {tab}")
    dialog.root.locator("[data-modal-close]").first.click()
    page.locator('[data-create-task][data-status="backlog"]').click()
    check("create dialog")
    page.keyboard.press("Escape")
    for path in (
        "/executions",
        "/pipelines",
        "/actions",
        "/guards",
        "/agents",
        "/settings/providers",
        "/settings/credentials",
        "/settings/run-limits",
    ):
        page.goto(base_url + path)
        _theme(page, theme)
        check(path)
        if (
            path == "/executions"
        ):  # the retention dialog: the list of rules, then one rule in the same frame
            page.get_by_role("button", name="Retention").click()
            dialog = page.locator("#retention-modal")
            expect(dialog.locator(".rl-row")).to_have_count(2)
            check("retention dialog / list")
            dialog.get_by_role("button", name="Open Failed ones").click()
            check("retention dialog / rule")
            page.keyboard.press("Escape")
            page.keyboard.press("Escape")
            expect(dialog).to_be_hidden()
        if path == "/guards":  # the guard editor: Settings and Logic, the title renamed in place
            page.locator(".mg-card [data-edit]").first.click()
            expect(page.locator("#guard-modal")).to_be_visible()
            check("guard editor")
            page.keyboard.press("Escape")
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    expect(page.locator(".ge-node").first).to_be_visible()
    _theme(page, theme)
    check("editor")
    page.locator(".ge-stage__header [data-guard-shield]").click()
    expect(page.locator("[data-guard-popover]")).to_be_visible()
    check("editor / shield popup")
    page.keyboard.press("Escape")
    # "Add a guard": the two buttons, the attach dialog with its combobox and the list under it (name and description)
    page.locator("[data-stage-add]").click()
    page.get_by_role("menuitem", name="Guard").click()
    popup = page.locator("[data-guard-popover]")
    expect(popup).to_be_visible()
    check("editor / add a guard popup")
    popup.get_by_role("button", name="Attach guard").click()
    attach = page.locator("#guard-attach-modal")
    expect(attach).to_be_visible()
    attach.get_by_role("button", name="Show all choices").click()
    expect(attach.locator(".combobox__option")).to_have_count(1)
    check("editor / attach dialog")
    for part in attach.locator(".combobox__name, .combobox__description").all():
        text = _measure(page, part)["text"]
        if text < TEXT_MIN:
            problems.append(
                f"combobox option [{theme}] {part.inner_text()!r}: text contrast {text:.2f} < {TEXT_MIN}"
            )
    page.keyboard.press("Escape")  # the list
    page.keyboard.press("Escape")  # the dialog
    expect(attach).to_be_hidden()
    # a double click opens the action itself (when it has a definition): its settings are the menu's Settings
    page.locator(".ge-node--action").first.click(button="right", position={"x": 30, "y": 5})
    page.get_by_role("menuitem", name="Settings").click()
    expect(page.locator("#node-modal")).to_be_visible()
    check("editor / node dialog")
    page.keyboard.press("Escape")
    # guards INSIDE the action the pipeline's action card runs: the card's shield mirrors them (its popup has the group "In
    # the action" and the link to the action), and the action editor has its own shield next to the "+" and on a node
    graph = api.get(graph_url(pipeline)).json()
    action_node = next(n for n in graph["nodes"] if n["kind"] == "action")
    definition = api.get(f"/api/actions/{action_node['definition_id']}").json()
    code = next(n for n in definition["nodes"] if n["kind"] == "code")
    inner = api.post(
        "/api/guards",
        json={
            "name": "Inner guard",
            "trigger": {"type": "event", "events": ["enter"]},
            "when": when | {"items": []},
        },
    ).json()
    for scope, scope_id in (("definition", None), ("node", code["id"])):
        api.post(
            "/api/guard-attachments",
            json={
                "guard_id": inner["id"],
                "graph_id": definition["graph"]["id"],
                "scope_type": scope,
                "scope_id": scope_id,
            },
        ).raise_for_status()
    page.goto(f"{base_url}/pipelines/{pipeline['slug']}")
    _theme(page, theme)
    page.locator(".ge-node--action [data-guard-shield]").first.click()
    expect(page.locator("[data-guard-popover] .gd-popover__inner")).to_be_visible()
    check("editor / action card shield popup (guards inside)")
    page.goto(f"{base_url}/actions/{definition['graph']['slug']}")
    _theme(page, theme)
    expect(page.locator("[data-pipeline-shield]")).to_be_visible()
    expect(page.locator(".ge-node--code [data-guard-shield]")).to_be_visible()
    check("action editor / shields")
    page.locator("[data-pipeline-shield]").click()
    expect(page.locator("[data-guard-popover]")).to_be_visible()
    check("action editor / shield popup")
    assert not problems, "\n" + "\n".join(sorted(set(problems)))
