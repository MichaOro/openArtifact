/* The pure rules of the copy button (components/copy-button.js), kept apart so they are tested without a browser. */

/** A text shorter than this, on one line, is quicker to select than to copy with a button: no button. */
export const MIN_LENGTH = 80;

/**
 * Whether a text gets a copy button: it is not empty, and it has more than one line or at least `minLength` characters (`always` for a block that
 * is never short, such as a prompt field the user fills). Short single lines (a name, a number) do not.
 * @param {string} text @param {{minLength?: number, always?: boolean}} [options]
 */
export function shouldOffer(text, { minLength = MIN_LENGTH, always = false } = {}) {
  const value = typeof text === "string" ? text : "";
  if (!value.trim()) return false;
  const trimmed = value.trim(); // the newline a command ends its output with does not make a second line
  return always || trimmed.includes("\n") || trimmed.length >= minLength;
}

/** The text a block holds as the page has it: the current value of a field, else the whole text content (never what is merely visible). */
export function blockText(block) {
  if (typeof block?.value === "string") return block.value;
  return block?.textContent ?? "";
}
