/* The pure parts of the archive view (ADR-071): the orders of the list, the search text and the rows of the Context tab.
 * No document access: tests/js/archive-model.test.mjs. */
import { t } from "../i18n.js";

/** The orders: by the time a card came into the archive (the default, newest first) and by title. */
export const SORTS = [
  { key: "archived", label: () => t("archive.sort_newest"), compare: (a, b) => time(b) - time(a) || a.number - b.number },
  { key: "archived_asc", label: () => t("archive.sort_oldest"), compare: (a, b) => time(a) - time(b) || a.number - b.number },
  { key: "title", label: () => t("archive.sort_title"), compare: (a, b) => a.title.localeCompare(b.title) || a.number - b.number },
  { key: "title_desc", label: () => t("archive.sort_title_desc"), compare: (a, b) => b.title.localeCompare(a.title) || a.number - b.number },
];

const time = (task) => new Date(task.archived_at ?? 0).getTime();

/** What the search looks at: number, title and the first words of the text. */
export const searchText = (task) => `#${task.number} ${task.title} ${task.preview ?? task.body ?? ""}`;

/** The text of a field value as the Context tab says it (booleans in words, nothing as null). */
export function fieldText(value) {
  if (value === null || value === undefined || value === "") return null;
  if (value === true) return t("archive.yes");
  if (value === false) return t("archive.no");
  return String(value);
}

/**
 * The rows of the Context tab: the lane it was archived from, the parent and the artifact fields that are set. Pipeline,
 * stage and action are left out: an archived card is not processed.
 * @param {object} task
 * @param {{name: string, label: string}[]} fields the definitions of the artifact fields
 * @param {string|null} parentTitle
 * @returns {{label: string, value: string}[]}
 */
export function contextRows(task, fields, parentTitle) {
  const rows = [{ label: t("archive.lane"), value: task.archived_from_lane ?? t("archive.lane_gone") }];
  if (task.parent_id) rows.push({ label: t("archive.parent"), value: parentTitle ?? t("archive.parent_unknown") });
  const labelOf = new Map(fields.map((f) => [f.name, f.label ?? f.name]));
  for (const [name, value] of Object.entries(task.fields ?? {})) {
    const text = fieldText(value);
    if (text !== null) rows.push({ label: labelOf.get(name) ?? name, value: text });
  }
  return rows;
}
