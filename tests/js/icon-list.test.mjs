import assert from "node:assert/strict";
import { test } from "node:test";

const model = await import("../../openartifact/static/js/components/icon-list-model.js");
const { IconList } = await import("../../openartifact/static/js/components/icon-list.js");
const { STATUS_BAR } = await import("../../openartifact/static/js/components/status-bar.js");
const { CARD_ICONS, CARD_ORDER } = await import("../../openartifact/static/js/components/card-icons.js");

// a host-independent fake: an element is a plain object, the row records the order of its children (what the page would show)
function fakeElement() {
  return {
    dataset: {},
    style: {},
    hidden: false,
    attrs: {},
    setAttribute(name, value) {
      this.attrs[name] = value;
    },
    remove() {
      this.gone = true;
    },
  };
}
function fakeRow() {
  return {
    children: [],
    append(...els) {
      for (const el of els) el.gone = false;
      this.children = els;
    },
  };
}
const demo = model.defineVariant({ name: "demo", allow: ["a", "b", "c", "d"], order: { a: 10, b: 20, c: 30, d: model.LAST } });

test("a variant needs a name, a whitelist and a place for every allowed key", () => {
  assert.throws(() => model.defineVariant({ allow: ["a"], order: { a: 1 } }), /needs a name/);
  assert.throws(() => model.defineVariant({ name: "x", allow: [], order: {} }), /whitelist of keys is empty/);
  assert.throws(() => model.defineVariant({ name: "x", allow: ["a", "b"], order: { a: 1 } }), /"b" has no place in the order table/);
});

test("a key the variant does not allow is refused with the list of the allowed ones; an explicit place wins over the table", () => {
  assert.throws(() => model.placeOf(demo, "z"), /icon list "demo": "z" is not allowed here \(allowed: a, b, c, d\)/);
  assert.equal(model.placeOf(demo, "b"), 20);
  assert.equal(model.placeOf(demo, "b", 25), 25);
  const list = new IconList(fakeRow(), demo);
  assert.throws(() => list.add({ key: "typo", element: fakeElement() }), /not allowed here/);
  assert.equal(list.entries.size, 0, "nothing was added");
});

test("only the active entries are shown and they close up: four places, the second and the fourth active, no placeholder", () => {
  const row = fakeRow();
  const list = new IconList(row, demo);
  for (const key of ["a", "b", "c", "d"]) list.add({ key, element: fakeElement(), visible: key === "b" || key === "d" });
  assert.deepEqual(list.shown, ["b", "d"]);
  assert.deepEqual(row.children.filter((e) => !e.hidden).map((e) => e.dataset.iconKey), ["b", "d"]);
  assert.equal(row.children.find((e) => e.dataset.iconKey === "a").hidden, true, "an inactive entry takes no room (hidden)");
});

test("an entry that becomes active takes its place in the order, not the end, and one that becomes inactive lets the others close up", () => {
  const row = fakeRow();
  const list = new IconList(row, demo);
  for (const key of ["d", "c", "b", "a"]) list.add({ key, element: fakeElement(), visible: key === "d" });
  assert.deepEqual(list.shown, ["d"]);
  list.set("b", true);
  assert.deepEqual(list.shown, ["b", "d"], "b stands before d");
  list.set("a", true);
  assert.deepEqual(list.shown, ["a", "b", "d"]);
  list.set("b", false);
  assert.deepEqual(list.shown, ["a", "d"], "the others close up");
  assert.deepEqual(row.children.map((e) => e.dataset.iconKey), ["a", "b", "c", "d"], "the order in the page is the order of the places");
});

test("the variant decides what an inactive entry is: hidden in the page, or not in the page at all (and a variant's data attributes and CSS order)", () => {
  const detach = model.defineVariant({ name: "det", allow: ["a", "b"], order: { a: 1, b: 2 }, inactive: "detach", attrs: { key: "k", order: "o" }, cssOrder: true });
  const row = fakeRow();
  const list = new IconList(row, detach);
  const a = fakeElement();
  const b = fakeElement();
  list.add({ key: "b", element: b, visible: true });
  list.add({ key: "a", element: a, visible: false });
  assert.deepEqual(row.children, [b], "only the active one is in the page");
  assert.equal(a.gone, true);
  assert.equal(b.dataset.k, "b");
  assert.equal(b.dataset.o, "2");
  assert.equal(b.style.order, "2");
  list.set("a", true);
  assert.deepEqual(row.children.map((e) => e.dataset.k), ["a", "b"]);
  list.remove("a");
  assert.deepEqual(row.children.map((e) => e.dataset.k), ["b"]);
  assert.equal(list.element("a"), null);
});

test("the list does not care where its row is: with no row yet it only keeps the entries", () => {
  const list = new IconList(null, demo);
  list.add({ key: "a", element: fakeElement(), visible: true });
  assert.deepEqual(list.shown, ["a"]);
  const row = fakeRow();
  list.row = row;
  list.add({ key: "b", element: fakeElement(), visible: true });
  assert.deepEqual(row.children.map((e) => e.dataset.iconKey), ["a", "b"]);
});

test("the two variants: the canvas corner keeps the plus last, the card has the pin left of the shield; each refuses the other's keys", () => {
  assert.ok(STATUS_BAR.order.ended < STATUS_BAR.order.observe && STATUS_BAR.order.observe < STATUS_BAR.order.guard && STATUS_BAR.order.guard < STATUS_BAR.order.add);
  assert.equal(STATUS_BAR.order.add, model.LAST);
  assert.ok(CARD_ORDER.mock < CARD_ORDER.guard);
  assert.deepEqual([...CARD_ICONS.allow], ["skipped", "mock", "guard"]); // the skip marker of a dry run joined the card (ADR-086 addendum 3)
  assert.throws(() => model.placeOf(CARD_ICONS, "observe"), /icon list "node card": "observe" is not allowed here/);
  assert.throws(() => model.placeOf(STATUS_BAR, "mock"), /icon list "status bar": "mock" is not allowed here/);
});
