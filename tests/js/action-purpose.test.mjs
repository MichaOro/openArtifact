/* What an action is for (ADR-067): the "+" menu of an action offers only the kinds that may be used there; the client of the
 * list and the create/change calls carry the purpose. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { NODE_TYPES } from "./support.mjs";

const JS = new URL("../../openartifact/static/js/editor/", import.meta.url).href;
const { loadNodeTypes, addableIn } = await import(`${JS}node-types.js`);
const api = await import(`${JS}api.js`);

async function loadWith(change) {
  const types = structuredClone(NODE_TYPES);
  change(types);
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({ status: 200, ok: true, json: async () => types });
  try {
    await loadNodeTypes();
  } finally {
    globalThis.fetch = real;
  }
}

test("a kind for guards only is offered in an action for guards and not in one for pipelines", async () => {
  await loadWith((types) => {
    types.find((t) => t.kind === "code").purposes = ["guard"];
    types.find((t) => t.kind === "http").purposes = ["pipeline"];
  });
  const kinds = (purpose) => addableIn("action", purpose).map((t) => t.kind);
  assert.ok(kinds("guard").includes("code") && !kinds("guard").includes("http"));
  assert.ok(kinds("pipeline").includes("http") && !kinds("pipeline").includes("code"));
  assert.ok(kinds(null).includes("code") && kinds(null).includes("http"), "no purpose known yet: every kind of the scope");
  assert.ok(addableIn("pipeline", "guard").some((t) => t.kind === "stage" || t.kind === "timer"), "a pipeline has no purpose: nothing is taken away");
});

test("a kind without the field is in both, as an older server describes it", async () => {
  await loadWith((types) => {
    for (const t of types) delete t.purposes;
  });
  assert.ok(addableIn("action", "guard").some((t) => t.kind === "code"));
  assert.ok(addableIn("action", "pipeline").some((t) => t.kind === "code"));
});

test("the list asks for the actions of one purpose and a new or changed action carries it", async () => {
  const calls = [];
  const real = globalThis.fetch;
  globalThis.fetch = async (url, options = {}) => {
    calls.push([options.method ?? "GET", String(url), options.body ?? null]);
    return { status: 200, ok: true, headers: new Headers({ "content-type": "application/json" }), json: async () => [], text: async () => "[]" };
  };
  try {
    await api.listGraphs("action", "guard");
    await api.listGraphs("action");
    await api.createGraph("action", "Judge", "guard");
    await api.createGraph("pipeline", "Flow");
    await api.updateGraph("action", "a1", { name: "Judge", purpose: "pipeline" });
  } finally {
    globalThis.fetch = real;
  }
  assert.deepEqual(calls[0].slice(0, 2), ["GET", "/api/actions?purpose=guard"]);
  assert.deepEqual(calls[1].slice(0, 2), ["GET", "/api/actions"]);
  assert.deepEqual(JSON.parse(calls[2][2]), { name: "Judge", purpose: "guard" });
  assert.deepEqual(JSON.parse(calls[3][2]), { name: "Flow" }, "a pipeline has no purpose to send");
  assert.deepEqual([calls[4][0], calls[4][1], JSON.parse(calls[4][2])], ["PATCH", "/api/actions/a1", { name: "Judge", purpose: "pipeline" }]);
});
