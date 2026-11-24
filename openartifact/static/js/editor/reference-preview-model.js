/* The pure parts of the resolved preview (ADR-064): when a field shows one, which card it is previewed with, how the choice
 * of cards is listed and how the server's answer is read. No DOM here; reference-preview.js draws it. */

export const STORAGE_KEY = "oa.previewCard";

/** Whether a field with this text shows a preview: a card is chosen and the text holds a reference. */
export function needsPreview(text, card) {
  return Boolean(card) && /\$\{[^}\r\n]/.test(String(text ?? ""));
}

/** The card the URL names (`?card=98`: a number or an id), else null. */
export function cardFromLocation(search) {
  const value = new URLSearchParams(search ?? "").get("card");
  return value && /^(?:\d{1,9}|[0-9a-f-]{36})$/.test(value) ? value : null;
}

/** The choices of the "Preview with card" field: newest first, by number and title. */
export function cardOptions(tasks) {
  return [...tasks]
    .sort((a, b) => b.number - a.number)
    .map((task) => ({ value: String(task.number), label: `#${task.number} ${task.title}`, description: task.status ?? "", keywords: String(task.number) }));
}

/** What the server answered as the lines to show: the resolved text, and what could not be resolved. */
export function previewLines(result, noteFor) {
  if (!result) return [];
  const lines = [result.resolved];
  if (result.unresolved?.length) lines.push(noteFor(result.unresolved.join(", ")));
  return lines;
}
