/* When the node dialog saves what the user did (ADR-059 addendum, ui-catalog "Persist on the user's act"). One policy for
 * every control of the dialog, here and nowhere else:
 *   - a text field (one line) saves when it is left (focusout) and on Enter,
 *   - a textarea saves when it is left and on Ctrl+Enter (Enter is a new line),
 *   - a choice (select, switch, checkbox, chip) saves once at the moment it changes,
 *   - never on a keystroke, never after a delay, never by an interval,
 *   - nothing is drawn again under a focused text field: the draw waits until the field is left,
 *   - closing the dialog or switching the node saves every field with unsaved text first.
 * The pure parts (persistsOn, isTextEditing) are unit tested without a browser. */

/** The kinds of control: `text` (one line), `multiline` (textarea), `choice` (select, checkbox, chip), `toggle` (switch). */
export const KINDS = ["text", "multiline", "choice", "toggle"];

/**
 * Whether an event saves the value of a control of `kind`.
 * @param {"text"|"multiline"|"choice"|"toggle"} kind
 * @param {{type: string, key?: string, ctrlKey?: boolean, metaKey?: boolean, shiftKey?: boolean}} event type is a DOM event type
 */
export function persistsOn(kind, { type, key = "", ctrlKey = false, metaKey = false, shiftKey = false }) {
  if (kind === "choice") return type === "change";
  if (kind === "toggle") return type === "click";
  if (type === "focusout") return true;
  if (type !== "keydown" || key !== "Enter") return false;
  return kind === "multiline" ? ctrlKey || metaKey : !shiftKey;
}

/** Whether an element takes typed text (the caret lives in it), by its tag and input type. */
export function isTextEditing(tagName, inputType = "") {
  const tag = String(tagName).toLowerCase();
  if (tag === "textarea") return true;
  return tag === "input" && !["checkbox", "radio", "button", "submit", "range", "color", "file"].includes(String(inputType).toLowerCase());
}

const dirty = new Set(); // {isDirty(), commit()} of every field that has text not saved yet
const inflight = new Set();

/** Remember a save so that a draw waiting for the field can wait for the save as well. */
export function trackSave(promise) {
  inflight.add(promise);
  const done = () => inflight.delete(promise);
  promise.then(done, done);
  return promise;
}

/** Register a field's unsaved state: `isDirty()`, `commit()` (which saves) and the `element` (to forget a field that was drawn away). Returns a function that forgets it. */
export function registerDirty(entry) {
  dirty.add(entry);
  return () => dirty.delete(entry);
}

/** Save every field with unsaved text now (closing the dialog, switching the node): the requests start at once. */
export function flushDirty() {
  for (const entry of dirty) if (entry.element && !entry.element.isConnected) dirty.delete(entry); // drawn away
  const pending = [...dirty].filter((entry) => entry.isDirty()).map((entry) => entry.commit());
  return Promise.allSettled(pending);
}

/** Bind the policy's events to an element. `commit(event)` saves; `onEnter` marks that a draw after this save may restore the caret. */
export function bindPersist(element, kind, commit) {
  const names = { text: ["focusout", "keydown"], multiline: ["focusout", "keydown"], choice: ["change"], toggle: ["click"] }[kind];
  for (const name of names) {
    element.addEventListener(name, (event) => {
      if (!persistsOn(kind, event)) return;
      if (event.type === "keydown") element.dataset.enter = "1"; // the draw after this may keep the caret (the field is settled)
      else delete element.dataset.enter;
      commit(event);
    });
  }
  if (kind === "text" || kind === "multiline") {
    element.addEventListener("input", () => delete element.dataset.enter);
  }
}

/**
 * A field settled with Enter keeps the focus when the dialog is drawn again meanwhile (a draw that comes after the save may
 * replace the field): for a moment, when the focus has fallen to the page, the field of the same place gets it back. A focus
 * the user moved to another control is left alone.
 */
function keepFocus(place, tries = 10) {
  const back = document.querySelector(`[data-focus-key="${place}"]`);
  const active = document.activeElement;
  if (back && active !== back && (!active || active === document.body)) {
    back.focus();
    if (typeof back.setSelectionRange === "function") back.setSelectionRange(back.value.length, back.value.length);
  }
  if (tries > 0) window.setTimeout(() => keepFocus(place, tries - 1), 100);
}

/**
 * A text field of a block that is not a setting control (the input mapping): it saves by the policy and shows the
 * "not saved" marker while its text is typed and not saved. `save(text)` resolves to null, or to why it was refused
 * (the text stays then and counts as unsaved).
 * @param {HTMLInputElement|HTMLTextAreaElement} input
 * @param {(text: string) => Promise<string|null>} save
 * @param {{kind?: "text"|"multiline", unsavedText?: string}} [options]
 */
export function persistText(input, save, { kind = "text", unsavedText = "" } = {}) {
  let baseline = input.value;
  let inFlight = null; // the text on its way: leaving the field meanwhile must not send it a second time
  const isDirty = () => input.value !== baseline;
  const mark = () => {
    const box = input.closest(".field");
    if (!box) return;
    box.classList.toggle("is-dirty", isDirty());
    const label = box.querySelector(".field__label");
    if (label) label.dataset.unsaved = unsavedText; // the marker after the label reads it (forms.css)
  };
  const commit = (settledWithEnter = false) => {
    const sent = input.value;
    const place = input.dataset.focusKey;
    inFlight = sent;
    const saving = Promise.resolve(save(sent)).then((message) => {
      if (!message) baseline = sent;
      if (inFlight === sent) inFlight = null;
      mark();
      if (settledWithEnter && place) keepFocus(place);
      return message;
    });
    return trackSave(saving);
  };
  bindPersist(input, kind, (event) => {
    if (event.type === "focusout" && (!isDirty() || input.value === inFlight)) return;
    commit(event.type === "keydown");
  });
  input.addEventListener("input", mark);
  registerDirty({ isDirty, commit, element: input });
  return { isDirty, commit };
}

/** The text field with the focus inside `container`, or null. A field just settled with Enter does not hold the draw. */
export function holdingField(container) {
  const active = document.activeElement;
  if (!active || !container.contains(active)) return null;
  if (!isTextEditing(active.tagName, active.type)) return null;
  return active.dataset.enter === "1" ? null : active;
}

const waiting = new WeakMap();
const listening = new WeakSet();

/**
 * Run `draw` now, or, when a text field of `container` has the focus, once it is left (and the saves it caused are done).
 * Several requests while waiting are one: the last `draw` runs.
 */
export function whenFieldFree(container, draw) {
  if (!holdingField(container)) {
    waiting.delete(container);
    return draw();
  }
  if (!listening.has(container)) {
    listening.add(container);
    container.addEventListener(
      "focusout",
      () => {
        // the next field the focus goes to inside the container holds the draw again: wait for focus to settle
        window.setTimeout(async () => {
          await Promise.allSettled([...inflight]);
          const run = waiting.get(container);
          if (!run) return;
          if (holdingField(container)) return; // the user moved into another field: wait again, a new focusout comes
          waiting.delete(container);
          run();
        });
      },
    );
  }
  waiting.set(container, draw);
  return null;
}
