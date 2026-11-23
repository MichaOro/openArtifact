/* "#12" references in artifact text. An artifact is referenced by its number; whether the
 * number exists is only known at display time, so unknown numbers stay plain text. */

import { t } from "../i18n.js";
const REFERENCE = /(^|[^\w#&])#(\d{1,9})\b/g;

/**
 * Render text with references turned into links.
 * @param {string} text
 * @param {(number: number) => {title: string}|undefined} find the artifact with that number
 * @returns {DocumentFragment}
 */
export function renderReferences(text, find) {
  const fragment = document.createDocumentFragment();
  let last = 0;
  for (const match of text.matchAll(REFERENCE)) {
    const number = Number(match[2]);
    const start = match.index + match[1].length;
    fragment.append(text.slice(last, start));
    const target = find(number);
    const node = document.createElement(target ? "a" : "span");
    node.className = target ? "ref" : "ref ref--missing";
    node.textContent = `#${number}`;
    if (target) {
      node.href = `#${number}`;
      node.dataset.number = String(number);
      node.title = target.title;
    } else {
      node.title = t("tasks.references.no_artifact_number", { number });
    }
    fragment.append(node);
    last = start + match[0].length - match[1].length;
  }
  fragment.append(text.slice(last));
  return fragment;
}
