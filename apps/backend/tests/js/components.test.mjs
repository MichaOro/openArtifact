/* Small components whose logic does not need a real DOM: icons, the server-sent events client,
 * the action dialog's lifecycle, the guarded storage. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { FakeNode, installDocument, uninstallDocument } from "./support.mjs";

const JS = "../../openartifact/static/js/";

afterEach(() => {
  uninstallDocument();
  delete globalThis.EventSource;
  delete globalThis.window;
});

test("icon clones the svg of the template and adds classes", async () => {
  installDocument(["check"]);
  const { icon } = await import(`${JS}components/icons.js`);
  const plain = icon("check");
  assert.equal(plain.tagName, "svg");
  assert.equal(plain.iconName, "check");
  assert.deepEqual([...plain.classes], []);
  assert.deepEqual([...icon("check", "a b").classes], ["a", "b"]);
});

test("an unknown icon is an error naming it; so is a page without the template", async () => {
  const { icon } = await import(`${JS}components/icons.js`);
  installDocument(["check"]);
  assert.throws(() => icon("nope"), { message: 'Unknown icon "nope"' });
  globalThis.document = { getElementById: () => null };
  assert.throws(() => icon("check"), { message: 'Unknown icon "check"' });
});

class FakeEventSource {
  static CLOSED = 2;
  static last = null;
  constructor(url) {
    this.url = url;
    this.readyState = 1;
    this.listeners = new Map();
    this.closed = false;
    FakeEventSource.last = this;
  }
  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }
  close() {
    this.closed = true;
  }
}

test("events: every type is forwarded parsed; a malformed frame is ignored; open and closed are reported", async () => {
  globalThis.EventSource = FakeEventSource;
  const { connectEvents } = await import(`${JS}tasks/events.js`);
  const seen = [];
  let opened = 0;
  let closed = 0;
  const disconnect = connectEvents({ onEvent: (t, d) => seen.push([t, d]), onOpen: () => (opened += 1), onClosed: () => (closed += 1) });
  const source = FakeEventSource.last;
  assert.equal(source.url, "/api/events");
  assert.deepEqual([...source.listeners.keys()].filter((k) => k.includes(".") || k === "board.resync").sort(), [
    "artifact_types.changed", "board.lanes", "board.resync", "execution.deleted", "execution.updated", "run.updated", "task.created", "task.deleted", "task.moved", "task.updated",
  ]);
  source.listeners.get("task.created")({ data: '{"id":"1"}' });
  source.listeners.get("execution.updated")({ data: "not json" });
  source.listeners.get("board.resync")({ data: "{}" });
  assert.deepEqual(seen, [["task.created", { id: "1" }], ["board.resync", {}]]);
  source.listeners.get("open")();
  assert.equal(opened, 1);
  source.readyState = 0; // reconnecting by itself: nothing to report
  source.listeners.get("error")();
  assert.equal(closed, 0);
  source.readyState = FakeEventSource.CLOSED;
  source.listeners.get("error")();
  assert.equal(closed, 1);
  disconnect();
  assert.equal(source.closed, true);
});

test("events: a custom URL; onClosed is optional", async () => {
  globalThis.EventSource = FakeEventSource;
  const { connectEvents } = await import(`${JS}tasks/events.js`);
  connectEvents({ onEvent() {}, onOpen() {}, url: "/other" });
  assert.equal(FakeEventSource.last.url, "/other");
  FakeEventSource.last.readyState = FakeEventSource.CLOSED;
  assert.doesNotThrow(() => FakeEventSource.last.listeners.get("error")());
});

function dialogParts({ withForm = true, withError = true } = {}) {
  const attributes = (el) => {
    el.attrs = {};
    el.setAttribute = (k, v) => (el.attrs[k] = v);
    return el;
  };
  const submit = attributes(new FakeNode("button"));
  const cancel = attributes(new FakeNode("button"));
  const form = attributes(new FakeNode("form"));
  const error = new FakeNode("p");
  const found = { ".modal__title": new FakeNode("h2"), "[data-form-error]": withError ? error : null, "[data-submit], [data-confirm]": submit, "[data-cancel]": cancel, "form.task-form": withForm ? form : null };
  const modal = { dialog: { querySelector: (s) => found[s] }, closed: 0, close() { this.closed += 1; } };
  return { modal, submit, cancel, form, error };
}

test("action dialog: a request runs with busy state, then closes; closing is blocked meanwhile", async () => {
  const { ActionDialog } = await import(`${JS}components/action-dialog.js`);
  const { modal, submit, cancel, form } = dialogParts();
  const dialog = new ActionDialog(modal);
  assert.equal(modal.canClose(), true);
  let during;
  const ok = await dialog.run(async () => {
    during = { closable: modal.canClose(), submit: submit.attrs["aria-disabled"], busy: submit.attrs["aria-busy"], form: form.attrs["aria-busy"] };
  });
  assert.deepEqual(during, { closable: false, submit: "true", busy: "true", form: "true" });
  assert.equal(ok, true);
  assert.equal(modal.canClose(), true);
  assert.deepEqual([submit.attrs["aria-disabled"], cancel.attrs["aria-disabled"], submit.attrs["aria-busy"]], ["false", "false", "false"]);
  assert.equal(modal.closed, 1);
});

test("action dialog: close: false keeps it open; no double submit", async () => {
  const { ActionDialog } = await import(`${JS}components/action-dialog.js`);
  const { modal } = dialogParts();
  const dialog = new ActionDialog(modal);
  await dialog.run(async () => {}, { close: false });
  assert.equal(modal.closed, 0);
  let release;
  const first = dialog.run(() => new Promise((resolve) => (release = resolve)));
  let calls = 0;
  assert.equal(await dialog.run(async () => (calls += 1)), false);
  assert.equal(calls, 0, "the second request never started");
  release();
  assert.equal(await first, true);
});

test("action dialog: a failure shows the server's text, or the message, or the fallback, and stays open", async () => {
  const { ActionDialog } = await import(`${JS}components/action-dialog.js`);
  const { modal, error } = dialogParts();
  const dialog = new ActionDialog(modal, "Custom fallback");
  for (const [thrown, shown] of [[{ detail: "Refused.", message: "x" }, "Refused."], [new Error("Boom"), "Boom"], [{}, "Custom fallback"]]) {
    assert.equal(await dialog.run(async () => { throw thrown; }), false);
    assert.equal(error.textContent, shown);
    assert.equal(error.hidden, false);
    assert.equal(dialog.busy, false);
  }
  assert.equal(modal.closed, 0);
  await dialog.run(async () => {}, { close: false });
  assert.equal(error.textContent, "", "a new run clears the old error");
  assert.equal(error.hidden, true);
  assert.equal(new ActionDialog(dialogParts().modal).fallbackError, "That did not work. Please try again.");
});

test("action dialog works without an error line, buttons or form", async () => {
  const { ActionDialog } = await import(`${JS}components/action-dialog.js`);
  const parts = dialogParts({ withForm: false, withError: false });
  const dialog = new ActionDialog(parts.modal);
  assert.equal(await dialog.run(async () => { throw new Error("x"); }), false);
  assert.equal(await dialog.run(async () => {}), true);
});

test("storage: guarded reads and writes, JSON that is unreadable is null", async () => {
  const values = new Map();
  let broken = false;
  const guard = (fn) => (...a) => {
    try {
      if (broken) throw new Error("blocked");
      return fn(...a);
    } catch {
      return null;
    }
  };
  globalThis.window = { OpenArtifact: { keys: { theme: "t" }, storage: { read: guard((k) => values.get(k) ?? null), write: guard((k, v) => values.set(k, v)), remove: guard((k) => values.delete(k)) } } };
  const store = await import(`${JS}storage.js`);
  assert.deepEqual(store.KEYS, { theme: "t" });
  store.writeJson("k", { a: [1, 2] });
  assert.equal(values.get("k"), '{"a":[1,2]}');
  assert.deepEqual(store.readJson("k"), { a: [1, 2] });
  assert.equal(store.readJson("missing"), null);
  store.writeStorage("bad", "{oops");
  assert.equal(store.readJson("bad"), null);
  assert.equal(store.readStorage("bad"), "{oops");
  store.removeStorage("bad");
  assert.equal(store.readStorage("bad"), null);
  broken = true;
  assert.equal(store.readJson("k"), null);
});
