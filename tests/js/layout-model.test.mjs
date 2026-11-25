/* Arranging a manifest window (components/layout-model.js, ADR-063): the structure of a form and of a node's settings, the
 * moves of a section or a field by drop and by key, and the document that is saved. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_CUSTOM, addArea, blocksOf, deleteArea, fieldPlace, formStructure, moveFieldBy, moveSectionBy, movedText, newAreaKey, nodeStructure, placeField, placeSection, renameArea, sameLayout, sectionOfField, sectionPlace, slotAmong, toLayout } from "../../openartifact/static/js/components/layout-model.js";

const field = (key, extra = {}) => ({ key, widget: "text", label: key.toUpperCase(), ...extra });
const manifest = {
  name: "demo",
  columns: 2,
  sections: [
    { key: "a", title: "A", column: 1, fields: [field("a1"), field("a2", { advanced: true }), field("a3", { visible_when: { field: "a1", equals: "x" } })] },
    { key: "b", title: "B", column: 2, fields: [field("b1", { required: true }), field("b2")] },
    { key: "wide", title: "Wide", column: "full", fields: [field("w1")] },
    { key: "c", title: "C", column: "auto", fields: [field("c1")] },
    { key: "d", title: "D", column: 1, fields: [field("d1")] },
  ],
};
const keys = (structure) => structure.sections.map((s) => s.key);
const lanes = (structure) => blocksOf(structure).map((b) => (b.full ? [b.full.key] : b.lanes.map((l) => l.map((s) => s.key))));

test("a form's structure holds every field, also the ones a condition hides, and resolves auto columns", () => {
  const s = formStructure(manifest);
  assert.deepEqual(keys(s), ["a", "b", "wide", "c", "d"]);
  assert.deepEqual(s.sections.find((x) => x.key === "a").fields.map((f) => f.key), ["a1", "a2", "a3"]);
  assert.equal(s.sections.find((x) => x.key === "a").fields[2].condition, true);
  assert.equal(s.sections.find((x) => x.key === "wide").column, "full");
  assert.ok([1, 2].includes(s.sections.find((x) => x.key === "c").column)); // auto became a column
});

test("the saved document lists shown and folded fields apart", () => {
  const layout = toLayout(formStructure(manifest));
  assert.deepEqual(layout.sections[0], { key: "a", column: 1, fields: ["a1", "a3"], advanced: ["a2"] });
});

test("a section moves to the other column and within a lane, a full one only among the rows", () => {
  const s = formStructure(manifest);
  const moved = placeSection(s, "a", { block: 0, lane: 1, index: 0 });
  assert.deepEqual(lanes(moved)[0], [[], ["a", "b"]]);
  assert.equal(sectionPlace(moved, "a").lane, 1);
  const first = placeSection(s, "wide", { block: 0 }); // a full row only changes its place among the blocks, and stays full
  assert.equal(keys(first)[0], "wide");
  assert.equal(first.sections[0].column, "full");
  // the original is untouched
  assert.deepEqual(lanes(s)[0][0].includes("a"), true);
  const below = placeSection(s, "d", { block: 2, lane: 1, index: 0 });
  assert.ok(lanes(below)[2][1].includes("d"));
});

test("the keys move a section by one: up and down in its lane, left and right between the columns", () => {
  const s = formStructure(manifest);
  const right = moveSectionBy(s, "a", "right");
  assert.equal(sectionPlace(right, "a").lane, 1);
  assert.equal(moveSectionBy(s, "a", "left"), null); // already in the first column
  const lane = placeSection(s, "c", { block: 2, lane: 0, index: 0 });
  const down = moveSectionBy(lane, "c", "down");
  assert.ok(down === null || sectionPlace(down, "c").index === 1);
  const row = moveSectionBy(s, "wide", "up");
  assert.deepEqual(keys(row).slice(0, 3).sort(), ["a", "b", "wide"].sort());
  assert.equal(sectionPlace(row, "wide").block, 0);
});

test("a field moves within its section, into the folded group and back, and a required one is never folded", () => {
  const s = formStructure(manifest);
  const up = placeField(s, "a", "a3", { advanced: false, index: 0 });
  assert.deepEqual(up.sections[0].fields.map((f) => f.key), ["a3", "a1", "a2"]);
  const folded = placeField(s, "a", "a1", { advanced: true, index: 0 });
  assert.deepEqual(folded.sections[0].fields.map((f) => [f.key, f.advanced]), [["a3", false], ["a1", true], ["a2", true]]);
  assert.equal(placeField(s, "b", "b1", { advanced: true, index: 0 }), null);
  assert.equal(fieldPlace(folded, "a", "a1").advanced, true);
});

test("down from the last shown field goes into the folded group, up from its start comes back", () => {
  const s = formStructure(manifest);
  const into = moveFieldBy(s, "a", "a3", "down");
  assert.equal(fieldPlace(into, "a", "a3").advanced, true);
  assert.equal(fieldPlace(into, "a", "a3").index, 0);
  const back = moveFieldBy(into, "a", "a3", "up");
  assert.equal(fieldPlace(back, "a", "a3").advanced, false);
  assert.equal(fieldPlace(back, "a", "a3").index, 1); // at the end of the shown ones
  assert.equal(moveFieldBy(s, "a", "a1", "up"), null); // the first field of the first section: nothing before it
  assert.equal(moveFieldBy(s, "b", "b2", "down")?.sections[1].fields.find((f) => f.key === "b2").advanced, true);
  assert.equal(moveFieldBy(s, "a", "a1", "left"), null);
});

const settings = [
  { key: "language", label: "Language", section: "definition", level: "core" },
  { key: "left_1", label: "Left", section: "definition", level: "core", group: "Condition 1" },
  { key: "right_1", label: "Right", section: "definition", level: "core", group: "Condition 1" },
  { key: "secrets", label: "Secrets", section: "definition", level: "advanced" },
  { key: "timeout", label: "Timeout", section: "behaviour", level: "optional" },
  { key: "agent_id", label: "Agent", section: "definition", level: "core" },
];
const titles = { definition: "Definition", behaviour: "Behaviour" };

test("a node's window has its two sides, a group is one entry and what the kind draws itself is left out", () => {
  const s = nodeStructure({ settings }, { titles, skip: ["agent_id"], fixed: ["Agent"] });
  assert.deepEqual(keys(s), ["definition", "behaviour"]);
  assert.deepEqual(s.sections[0].fields.map((f) => f.key), ["language", "group:Condition 1", "secrets"]);
  assert.deepEqual(s.fixed, ["Agent"]);
  assert.deepEqual(toLayout(s).sections[1], { key: "behaviour", fields: ["timeout"] });
});

test("a node's areas swap and its entries reorder", () => {
  const s = nodeStructure({ settings }, { titles });
  const swapped = moveSectionBy(s, "behaviour", "left");
  assert.deepEqual(keys(swapped), ["behaviour", "definition"]);
  assert.equal(moveSectionBy(s, "definition", "left"), null);
  const reordered = placeField(s, "definition", "secrets", { index: 0 });
  assert.deepEqual(reordered.sections[0].fields.map((f) => f.key), ["secrets", "language", "group:Condition 1", "agent_id"]);
  assert.equal(moveFieldBy(s, "definition", "language", "up"), null);
  assert.equal(moveFieldBy(s, "behaviour", "timeout", "down"), null); // the last one of the last area: nowhere to go
  assert.deepEqual(keys(nodeStructure({ settings, layout: { sections: ["behaviour", "definition"] } }, { titles })), ["behaviour", "definition"]);
});

test("a layout that did not change is the same layout", () => {
  const s = formStructure(manifest);
  assert.equal(sameLayout(s, formStructure(manifest)), true);
  assert.equal(sameLayout(s, moveSectionBy(s, "a", "right")), false);
});

test("a move is announced with its place", () => {
  const labels = {
    column: ({ title, column, position }) => `${title}: column ${column}, ${position}`,
    row: ({ title, position }) => `${title}: row ${position}`,
    side: ({ title, position }) => `${title}: side ${position}`,
    field: ({ title, position }) => `${title}: ${position}`,
    folded: ({ title, position }) => `${title}: folded ${position}`,
  };
  const s = moveSectionBy(formStructure(manifest), "a", "right");
  assert.equal(movedText(s, "section", { section: "a" }, labels), "A: column 2, 1");
  const f = moveFieldBy(formStructure(manifest), "a", "a3", "down");
  assert.equal(movedText(f, "field", { section: "a", field: "a3" }, labels), "A3: folded 1");
});


// ── a setting in any area, areas of one's own ─────────────────────────

const labels = {
  column: ({ title, column, position }) => `${title}: column ${column}, ${position}`,
  row: ({ title, position }) => `${title}: row ${position}`,
  side: ({ title, position }) => `${title}: side ${position}`,
  field: ({ title, position }) => `${title}: ${position}`,
  folded: ({ title, position }) => `${title}: folded ${position}`,
  fieldArea: ({ title, area, position }) => `${title}: ${area}, ${position}`,
};

test("a setting moves into another area, keeps its entry and leaves the first one", () => {
  const s = nodeStructure({ settings }, { titles });
  const moved = placeField(s, "definition", "language", { toSection: "behaviour", index: 0 });
  assert.deepEqual(moved.sections[1].fields.map((f) => f.key), ["language", "timeout"]);
  assert.deepEqual(moved.sections[0].fields.map((f) => f.key), ["group:Condition 1", "secrets", "agent_id"]);
  assert.equal(sectionOfField(moved, "language"), "behaviour");
  assert.deepEqual(s.sections[1].fields.map((f) => f.key), ["timeout"]); // the original is untouched
  const back = placeField(moved, "behaviour", "timeout", { toSection: "definition", index: 1 });
  assert.deepEqual(back.sections[0].fields.map((f) => f.key), ["group:Condition 1", "timeout", "secrets", "agent_id"]);
  assert.deepEqual(toLayout(back).sections[1], { key: "behaviour", fields: ["language"] });
});

test("a field of a form moves to another section too, a required one stays shown there", () => {
  const s = formStructure(manifest);
  const moved = placeField(s, "a", "a1", { toSection: "b", index: 1 });
  assert.deepEqual(moved.sections.find((x) => x.key === "b").fields.map((f) => f.key), ["b1", "a1", "b2"]);
  assert.equal(placeField(s, "b", "b1", { toSection: "a", advanced: true, index: 0 }), null);
  const folded = placeField(s, "a", "a1", { toSection: "b", advanced: true, index: 0 });
  assert.equal(fieldPlace(folded, "b", "a1").advanced, true);
});

test("the keys carry a setting into the next or previous area, at the ends and with left and right", () => {
  const s = nodeStructure({ settings }, { titles });
  const down = moveFieldBy(s, "definition", "agent_id", "down"); // the last one of Definition falls into Behaviour, at its start
  assert.equal(sectionOfField(down, "agent_id"), "behaviour");
  assert.equal(fieldPlace(down, "behaviour", "agent_id").index, 0);
  const up = moveFieldBy(s, "behaviour", "timeout", "up"); // the first of Behaviour climbs to the end of Definition
  assert.equal(sectionOfField(up, "timeout"), "definition");
  assert.equal(fieldPlace(up, "definition", "timeout").index, 4); // after the four entries of Definition
  const right = moveFieldBy(s, "definition", "secrets", "right"); // same position in the next area, clamped to its size
  assert.equal(sectionOfField(right, "secrets"), "behaviour");
  assert.equal(fieldPlace(right, "behaviour", "secrets").index, 1);
  assert.equal(moveFieldBy(s, "definition", "language", "left"), null); // no area before the first
  const text = movedText(right, "field", { section: "behaviour", field: "secrets", from: "definition" }, labels);
  assert.equal(text, "Secrets: Behaviour, 2");
});

test("an area of one's own is added at the end, renamed, filled and deleted only while it is empty", () => {
  const s = nodeStructure({ settings }, { titles });
  const added = addArea(s, "  Mine  ", "custom_a1");
  assert.deepEqual(keys(added), ["definition", "behaviour", "custom_a1"]);
  assert.deepEqual(added.sections[2], { key: "custom_a1", title: "Mine", custom: true, column: 3, fields: [] });
  assert.deepEqual(toLayout(added).sections[2], { key: "custom_a1", fields: [], title: "Mine" });
  assert.equal("title" in toLayout(added).sections[0], false); // a shipped area has no title in the document
  const filled = placeField(added, "definition", "secrets", { toSection: "custom_a1", index: 0 });
  assert.equal(deleteArea(filled, "custom_a1"), null); // it holds something
  const renamed = renameArea(filled, "custom_a1", "Fresh");
  assert.equal(renamed.sections[2].title, "Fresh");
  const emptied = placeField(renamed, "custom_a1", "secrets", { toSection: "definition", index: 0 });
  assert.deepEqual(keys(deleteArea(emptied, "custom_a1")), ["definition", "behaviour"]);
  assert.equal(deleteArea(s, "definition"), null); // a shipped area is never deleted
  assert.equal(renameArea(s, "behaviour", "Other"), null); // nor renamed
});

test("an area needs a title of 1 to 40 characters and there are at most twelve of one's own", () => {
  const s = nodeStructure({ settings }, { titles });
  assert.equal(addArea(s, "   "), null);
  assert.equal(addArea(s, "x".repeat(41)), null);
  assert.ok(addArea(s, "x".repeat(40), "custom_ok"));
  assert.equal(renameArea(addArea(s, "A", "custom_b1"), "custom_b1", ""), null);
  let next = s;
  for (let i = 0; i < MAX_CUSTOM; i += 1) next = addArea(next, `Area ${i}`, `custom_${i}`);
  assert.equal(next.sections.filter((x) => x.custom).length, MAX_CUSTOM);
  assert.equal(addArea(next, "One too many", "custom_x"), null);
  assert.match(newAreaKey(() => 0.5), /^custom_[a-z0-9]{6}$/);
});

test("a saved area comes back: custom titles of a node, areas of a form with the empty one", () => {
  const node = nodeStructure({ settings: settings.map((x) => (x.key === "timeout" ? { ...x, section: "custom_a1" } : x)), layout: { sections: ["definition", "behaviour", "custom_a1"], titles: { custom_a1: "Mine" } } }, { titles });
  assert.deepEqual(node.sections.map((x) => [x.key, x.title, x.custom, x.fields.length]), [
    ["definition", "Definition", false, 4],
    ["behaviour", "Behaviour", false, 0], // empty, but there to drop into
    ["custom_a1", "Mine", true, 1],
  ]);
  const plain = nodeStructure({ settings: settings.filter((x) => x.section === "definition") }, { titles });
  assert.deepEqual(keys(plain), ["definition", "behaviour"]); // a kind without behaviour settings still has the area
  const withAreas = { ...manifest, sections: manifest.sections.filter((x) => x.key !== "d"), layout: { areas: [...manifest.sections.filter((x) => x.key !== "d").map((x) => ({ key: x.key, title: x.title, column: x.column, custom: false })), { key: "custom_f1", title: "Spare", column: "auto", custom: true }] } };
  const form = formStructure(withAreas);
  assert.deepEqual(form.sections.at(-1), { key: "custom_f1", title: "Spare", custom: true, column: 1, fields: [] });
  assert.equal(form.sections.find((x) => x.key === "a").custom, false);
  assert.deepEqual(toLayout(form).sections.at(-1), { key: "custom_f1", column: 1, fields: [], advanced: [], title: "Spare" });
});

test("a drop finds its slot in reading order: side by side and stacked", () => {
  const box = (left, top, right, bottom) => ({ left, top, right, bottom });
  const row = [box(0, 0, 100, 200), box(110, 0, 210, 200)];
  assert.equal(slotAmong(row, 20, 100), 0); // left half of the first box
  assert.equal(slotAmong(row, 80, 100), 1); // right half of the first box
  assert.equal(slotAmong(row, 200, 100), 2); // right half of the second
  assert.equal(slotAmong(row, 50, 300), 2); // below both
  const column = [box(0, 0, 200, 100), box(0, 110, 200, 210), box(0, 220, 200, 320)];
  assert.equal(slotAmong(column, 100, 20), 0);
  assert.equal(slotAmong(column, 100, 80), 1);
  assert.equal(slotAmong(column, 100, 150), 1);
  assert.equal(slotAmong(column, 10, 400), 3);
  const grid = [box(0, 0, 100, 100), box(110, 0, 210, 100), box(0, 110, 100, 210)];
  assert.equal(slotAmong(grid, 20, 160), 2); // second row, left half: after the first row
});


test("a conditional field says what it waits for, and a one-column form is arranged in one column", () => {
  const manifest = {
    name: "credential",
    columns: 1,
    sections: [
      { key: "general", title: "General", fields: [{ key: "type", label: "Type", widget: "select" }] },
      { key: "access", title: "Access", fields: [{ key: "a.value", label: "Token", widget: "text", visible_when: { field: "type", equals: "github_pat" } }, { key: "b.value", label: "Key", widget: "text", visible_when: { field: "type", in: ["x", "y"] } }] },
    ],
  };
  const structure = formStructure(manifest);
  assert.equal(structure.columns, 1);
  assert.deepEqual(structure.sections.map((s) => s.column), [1, 1], "all in the one column");
  const access = structure.sections.find((s) => s.key === "access");
  assert.deepEqual(access.fields.map((f) => f.when), ["type: github_pat", "type: x, y"]);
  assert.equal(structure.sections[0].fields[0].when, undefined);
});
