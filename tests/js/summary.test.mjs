import assert from "node:assert/strict";
import { test } from "node:test";

const JS = "../../openartifact/static/js/executions/";
const { SummaryStrip } = await import(`${JS}summary.js`);
const { Filters } = await import(`${JS}filters.js`);

/** A counter button: its value element, aria-pressed and the click handler. */
function button(key) {
  const value = { textContent: "" };
  return {
    dataset: { summary: key },
    value,
    pressed: null,
    click: null,
    addEventListener(type, handler) {
      if (type === "click") this.click = handler;
    },
    querySelector: () => value,
    setAttribute(name, v) {
      if (name === "aria-pressed") this.pressed = v;
    },
  };
}

function strip() {
  const buttons = ["running", "failed_24h", "done_24h", "total"].map(button);
  const chosen = [];
  const instance = new SummaryStrip({ querySelectorAll: () => buttons }, (filters) => chosen.push(filters));
  return { buttons, chosen, instance, by: (key) => buttons.find((b) => b.dataset.summary === key) };
}

test("render writes each counter", () => {
  const { instance, by } = strip();
  instance.render({ running: 2, failed_24h: 0, done_24h: 15, total: 40 });
  assert.deepEqual(["running", "failed_24h", "done_24h", "total"].map((k) => by(k).value.textContent), ["2", "0", "15", "40"]);
});

test("pressing a counter selects exactly its filter", () => {
  const { chosen, by } = strip();
  by("running").click();
  by("failed_24h").click();
  by("total").click();
  assert.deepEqual(chosen.map((f) => f.toSearch()), ["?status=running", "?status=failed&range=24h", ""]);
});

test("pressing the active counter again clears the filters; the page size is kept either way", () => {
  const { chosen, instance, by } = strip();
  instance.setFilters(new Filters({ status: ["running"], pageSize: "5" }));
  by("running").click();
  by("done_24h").click();
  assert.deepEqual(chosen.map((f) => f.toSearch()), ["?page_size=5", "?status=done&range=24h&page_size=5"]);
});

test("setFilters marks the counter whose filter is current; no counter is pressed when nothing is filtered", () => {
  const { instance, by } = strip();
  const pressed = () => ["running", "failed_24h", "done_24h", "total"].map((k) => by(k).pressed);
  instance.setFilters(new Filters());
  assert.deepEqual(pressed(), ["false", "false", "false", "false"], "no filter: nothing is pressed");
  instance.setFilters(new Filters({ status: ["failed"], range: "24h" }));
  assert.deepEqual(pressed(), ["false", "true", "false", "false"]);
  instance.setFilters(new Filters({ status: ["failed"], range: "7d" }));
  assert.deepEqual(pressed(), ["false", "false", "false", "false"], "a different range matches no counter");
  instance.setFilters(new Filters({ status: ["running"], pageSize: "5" }));
  assert.deepEqual(pressed(), ["true", "false", "false", "false"], "page size is not part of the match");
});
