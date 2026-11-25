/* What the body of an artifact shows where it is read (ADR-064 addendum): the text with its ${card.x} filled in by the
 * server, or the text as it was written; the first words on the board's card; the calm note about a reference that
 * names nothing. Pure: no DOM. The server fills the references in (artifact_fields/body.py), this only chooses. */

/** Whether the server filled something in (`body_resolved` is null when the body has nothing to fill). */
export function hasResolved(task) {
  return typeof task?.body_resolved === "string";
}

/** The text of the read view: the filled in one, or the original when nothing was filled in (Edit shows what was written). */
export function bodyText(task) {
  const original = task?.body ?? "";
  return hasResolved(task) ? task.body_resolved : original;
}

/** The text of a card on the board: the filled in first words when the body has references, else the original. */
export function cardPreview(task) {
  return task?.preview ?? task?.body ?? "";
}

/** A body with references whose filled in text the list did not carry (the list leaves `body_resolved` null and sets
 * `preview`): ask for the single artifact. A body whose references all name nothing asks too, once per opening. */
export function needsFullBody(task) {
  return task?.preview != null && task.body_resolved == null;
}

/** What the answer to a save said about references that name nothing, kept with the artifact it belongs to. */
export function rememberWarnings(saved) {
  const { warnings = [], ...artifact } = saved ?? {};
  return { artifact, warned: { id: artifact.id, warnings } };
}

/** The notes to show for this artifact (none for another one than the one that was saved). */
export function warningsFor(warned, task) {
  return warned && task && warned.id === task.id ? warned.warnings : [];
}

/** Whether the mark_resolved_references setting is enabled for this task. */
export function shouldMarkResolved(task) {
  return task?.mark_resolved_references === true;
}
