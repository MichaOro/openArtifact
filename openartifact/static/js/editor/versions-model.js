/* Where a pipeline or an action stands between its draft and its published versions (ADR-070): no DOM, so it is unit-tested. */

/** Nothing published (the draft runs), a version in use that the draft equals, or a draft that differs from the version in use. */
export function publicationOf(graph) {
  const number = graph.published_version ?? null;
  if (number === null) return { state: "draft", number: null };
  return { state: graph.draft_changed ? "changed" : "published", number };
}

/** Whether "Publish" has something to publish: a draft nobody published yet, or one that differs from the published version. */
export const canPublish = (graph) => publicationOf(graph).state !== "published";

/** Whether "Discard draft" has something to go back to: a published version that the draft differs from. */
export const canDiscard = (graph) => publicationOf(graph).state === "changed";

/** What the popup of the mark in the toolbar offers: nothing once the draft equals the published version (the mark is then no
 * control), "Publish" for a draft nobody published, "Publish" and "Discard draft" for a draft that differs from the published version. */
export function publicationOffer(graph) {
  return { publish: canPublish(graph), discard: canDiscard(graph) };
}
