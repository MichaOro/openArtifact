/* The Versions tab of the detail panel of pipelines and actions (ADR-070, ADR-069): where a definition stands (nothing published, a
 * version in use, a draft that differs from it) and its published versions, newest first, each with "Show" (the Graph tab shows that
 * version read-only) and "Publish again"; "Publish" on top makes the draft a new version. The versions are handled here, not in the graph
 * editor. A long list folds its middle (components/fold-list.js): the newest two and the first stay.
 *
 *   publicationOf(graph)                      -> (versions-model.js, pure) {state: "draft" | "published" | "changed", number}
 *   publicationChip(graph)                    -> the chip of the card and of the panel
 *   editorChip(graph)                         -> the mark in the toolbar of the graph editor ("Draft" or "v3 published")
 *   renderVersions(body, graph, hooks)        -> fills the tab
 *
 * The tab and the mark also serve the guard library (ADR-081): `hooks.api` ({versions, publish, republish}) replaces the calls of a
 * graph and `texts` (a function `(key, params) -> text or null`, null for the graph's own words) the words that differ ("executions run
 * the draft" is not true of a guard that was never published).
 */
import { foldEntries, foldSeparator } from "../components/fold-list.js";
import { chip, make } from "../components/management-page.js";
import { checkGraph, publishGraph, republishGraph, versionsOf } from "./api.js";
import { findingsConfirm } from "./findings.js";
import { canPublish, publicationOf } from "./versions-model.js";
import { t } from "../i18n.js";

export { publicationOf };

const ORIGINS = { user: t("agents.editor_page.browser"), api: t("agents.editor_page.through_api") };

/** The words of that state ("Draft", "v3 published", "Draft has changes"). */
export function publicationText({ state, number }) {
  if (state === "published") return t("graph_versions.chip_published", { number });
  if (state === "changed") return t("graph_versions.chip_changed");
  return t("common.draft");
}

export function publicationChip(graph) {
  const where = publicationOf(graph);
  const el = chip(publicationText(where), { glyph: where.state === "published" ? "check" : "undo" });
  el.dataset.publication = where.state;
  return el;
}

/**
 * The mark in the toolbar of the editor: "Draft" while nothing is published or the draft differs from the published version, "v3 published"
 * while they are equal. The tooltip says what executions run.
 */
export function editorChip(graph, texts = null) {
  const where = publicationOf(graph);
  const published = where.state === "published";
  const el = chip(published ? t("graph_versions.chip_published", { number: where.number }) : t("common.draft"), { glyph: published ? "check" : "undo" });
  el.dataset.publication = where.state;
  const key = where.state === "draft" ? "note_nothing_published" : published ? "note_equal" : "note_changed";
  el.title = words(texts)(key, { number: where.number });
  return el;
}

/** The text for `key` of this tab: the one `texts` gives, else the graph's words. */
const words = (texts) => (key, params) => texts?.(key, params) ?? t(`graph_versions.${key}`, params);

/** The calls of a pipeline or an action (`kind`), in the shape `hooks.api` has. */
const graphCalls = (kind) => ({
  versions: (id) => versionsOf(kind, id),
  check: (id) => checkGraph(kind, id),
  publish: (id, acknowledge = false) => publishGraph(kind, id, acknowledge),
  republish: (id, number) => republishGraph(kind, id, number),
});

const when = (iso) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * @param {HTMLElement} body the tab
 * @param {object} graph the definition (with `published_version` and `draft_changed`)
 * @param {{kind: string, confirm: (options: object) => void, shown: number|null, onShow: (number: number) => void,
 *   onChanged: () => Promise<void>|void}} hooks `shown`: the version the Graph tab shows now; `onShow` makes it show another;
 *   `onChanged` is called after a publication (the page reads the list again)
 */
export function renderVersions(body, graph, { kind, api, texts, confirm, shown, onShow, onChanged }) {
  const hooks = { calls: api ?? graphCalls(kind), tr: words(texts), confirm, shown, onShow, onChanged };
  body.replaceChildren(make("p", "mg-card__facts", t("graph_list.loading")));
  hooks.calls
    .versions(graph.id)
    .then((versions) => draw(body, graph, versions, hooks))
    .catch(() => body.replaceChildren(make("p", "mg-card__facts", hooks.tr("load_error"))));
}

function draw(body, graph, versions, hooks) {
  const where = publicationOf(graph);
  const top = make("section", "mg-section mg-versions__top");
  const publish = make("button", "button button--primary button--sm", hooks.tr("publish"));
  publish.type = "button";
  publish.dataset.publish = "";
  const equal = where.state === "published";
  publish.disabled = !canPublish(graph);
  publish.addEventListener("click", async () => {
    // the check before publishing (ADR-082): with findings the window lists them and says "Publish anyway"
    const found = hooks.calls.check ? ((await hooks.calls.check(graph.id).catch(() => null))?.findings ?? []) : [];
    hooks.confirm({
      ...(found.length ? findingsConfirm(found) : { message: hooks.tr("publish_confirm"), confirmLabel: hooks.tr("publish"), tone: "primary" }),
      onConfirm: async () => {
        await hooks.calls.publish(graph.id, found.length > 0);
        await hooks.onChanged();
      },
    });
  });
  const note = make("p", "mg-card__facts mg-versions__note");
  note.textContent = where.state === "draft" ? hooks.tr("note_nothing_published") : equal ? hooks.tr("note_equal", { number: where.number }) : hooks.tr("note_changed", { number: where.number });
  top.append(publish, note);

  const list = make("ul", "mg-versions");
  let expanded = false;
  const drawList = () => {
    list.replaceChildren(
      ...foldEntries(versions, { head: 2, tail: 1, expanded }).map((entry) => {
        if (entry.fold) {
          return foldSeparator({
            count: entry.fold,
            expanded,
            label: expanded ? t("agents.editor_page.hide_versions", { count: entry.fold }) : t("agents.editor_page.show_more_versions", { count: entry.fold }),
            onToggle: () => {
              expanded = !expanded;
              drawList();
              list.querySelector(".fold-separator__button")?.focus();
            },
          });
        }
        return row(entry.item, graph, hooks);
      }),
    );
  };
  drawList();
  const empty = make("p", "mg-card__facts", hooks.tr("none"));
  empty.hidden = versions.length > 0;
  body.replaceChildren(top, list, empty);
}

function row(version, graph, hooks) {
  const item = make("li", "mg-version");
  item.dataset.version = String(version.number);
  const head = make("div", "mg-version__head");
  head.append(make("strong", "", t("agents.editor_page.version_number", { number: version.number })));
  if (version.current) head.append(chip(t("agents.editor_page.use"), { tone: "use" }));
  if (hooks.shown === version.number) head.append(chip(hooks.tr("shown")));
  const origin = version.source_number != null ? t("agents.editor_page.rollback_version_source_number", { source_number: version.source_number }) : t("agents.editor_page.published_word");
  const meta = make("span", "mg-version__meta", `${when(version.published_at)} · ${origin} ${ORIGINS[version.published_via] ?? version.published_via}`);
  const buttons = make("div", "mg-version__buttons");
  const show = make("button", "button button--ghost button--sm", t("agents.editor_page.show"));
  show.type = "button";
  show.setAttribute("aria-label", t("agents.editor_page.show_version_number", { number: version.number }));
  show.addEventListener("click", () => hooks.onShow(version.number));
  buttons.append(show);
  if (!version.current) {
    const again = make("button", "button button--ghost button--sm", t("agent_editor.publish_again"));
    again.type = "button";
    again.setAttribute("aria-label", t("agents.editor_page.publish_version_number_again", { number: version.number }));
    again.addEventListener("click", () =>
      hooks.confirm({
        message: hooks.tr("publish_again_confirm", { number: version.number }),
        confirmLabel: t("agent_editor.publish_again"),
        tone: "primary",
        onConfirm: async () => {
          await hooks.calls.republish(graph.id, version.number);
          await hooks.onChanged();
        },
      }),
    );
    buttons.append(again);
  }
  item.append(head, meta, buttons);
  return item;
}
