/* What marks a step a dry run (or an observed run) skipped (ADR-086 addendum 3): pure, so it is tested on its own. A skipped step passes and carries
 * `data.dry_run` and `data.would_have` (what it would have done). A node that handed over a mock was processed, not skipped (`data.mock`), and a step
 * that could not be observed (`data.not_observable`, ADR-088) is another thing: neither gets the marker, so the skip marker and the mock pin never
 * meet on one node. */

/** What the skipped step would have done ("waited 3 s"), or null when the step was not skipped. */
export function skippedWhat(step) {
  const data = step?.data;
  if (!data || !data.dry_run || data.mock || data.not_observable) return null;
  const what = typeof data.would_have === "string" ? data.would_have.trim() : "";
  return what || null;
}

/** The entries a card's corner shows for a step, as `{key, what?}`: at most one of the skip marker and the mock pin (`mocked` is the editor's
 * view, where the pin is the card's own; on the flow page a mock shows as the step's Mock flag). */
export function cornerMarks(step, { mocked = false } = {}) {
  if (mocked) return [{ key: "mock" }];
  const what = skippedWhat(step);
  return what ? [{ key: "skipped", what }] : [];
}
