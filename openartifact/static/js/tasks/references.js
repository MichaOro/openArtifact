/* "#12" references in artifact text. An artifact is referenced by its number; whether the
 * number exists is only known at display time, so unknown numbers stay plain text. */

import { t } from "../i18n.js";
import { renderMarkdown } from "../components/markdown.js";
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

/**
 * Render body from resolved segments with highlighted resolved parts.
 * @param {Array<{text: string, resolved: boolean}>} segments - from body_resolved_segments API
 * @param {(number: number) => {title: string}|undefined} find - for #n references inside segments
 * @returns {DocumentFragment}
 */
export function renderResolvedBody(segments, find) {
  const fragment = document.createDocumentFragment();
  for (const segment of segments) {
    if (segment.resolved) {
      // Resolved text: wrap in mark with special class for highlighting
      const mark = document.createElement("mark");
      mark.className = "resolved-ref";
      // Recursively render any #n references inside the resolved segment
      mark.append(renderReferences(segment.text, find));
      fragment.append(mark);
    } else {
      // Original text: render #n references as links
      fragment.append(renderReferences(segment.text, find));
    }
  }
  return fragment;
}

/** The part [from, to) of a text that is given as marked segments: the pieces of it, filled in ones wrapped in a mark. */
function renderSlice(segments, from, to, find) {
  const fragment = document.createDocumentFragment();
  let offset = 0;
  for (const segment of segments) {
    const begin = Math.max(from, offset);
    const stop = Math.min(to, offset + segment.text.length);
    if (stop > begin) {
      const cut = segment.text.slice(begin - offset, stop - offset);
      const piece = find ? renderReferences(cut, find) : document.createTextNode(cut); // no `find`: literal text (code, the words of a link)
      if (segment.resolved) {
        const mark = document.createElement("mark");
        mark.className = "resolved-ref";
        mark.append(piece);
        fragment.append(mark);
      } else fragment.append(piece);
    }
    offset += segment.text.length;
  }
  return fragment;
}

/**
 * A body as it is read (ADR-077): the Markdown of the text (headings, bold, italic, strikethrough, code, quotes, lists, tables, links) with "#12"
 * turned into links and, when `segments` are given, the filled in references marked. The marks and links sit inside the formatting, in every kind of
 * block, wherever the text is cut. Code and the words of a link stay text: marks yes, "#12" links no.
 * @param {string} text the text as it is shown; with `segments` their texts joined
 * @param {(number: number) => {title: string}|undefined} find the artifact with that number
 * @param {{segments?: Array<{text: string, resolved: boolean}>|null, lists?: boolean, links?: boolean, plain?: boolean}} [options]
 *   `links` false leaves "#12" as text (a card on the board draws no links unless its references are marked);
 *   `plain` draws no blocks and no anchors, only the lines (the preview of a card on the board)
 * @returns {DocumentFragment}
 */
export function renderBody(text, find, { segments = null, lists = true, links = true, plain = false } = {}) {
  const source = segments ? segments.map((segment) => segment.text).join("") : text;
  const renderText = segments
    ? (piece, start) => renderSlice(segments, start, start + piece.length, find)
    : links
      ? (piece) => renderReferences(piece, find)
      : undefined;
  const renderLiteral = segments ? (piece, start) => renderSlice(segments, start, start + piece.length, null) : undefined;
  return renderMarkdown(source, { renderText, renderLiteral, lists, plain });
}
