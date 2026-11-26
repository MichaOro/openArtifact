import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

const { ApiError, request } = await import("../../openartifact/static/js/http.js");

const realFetch = globalThis.fetch;
let assigned;
beforeEach(() => {
  assigned = [];
  globalThis.window = { location: { pathname: "/pipelines/flow", search: "?x=1", assign: (url) => assigned.push(url) } };
});
afterEach(() => {
  globalThis.fetch = realFetch;
  delete globalThis.window;
});

const answer = (status, body, { json = true } = {}) => {
  globalThis.fetch = async () => ({
    status,
    ok: status >= 200 && status < 300,
    json: async () => {
      if (!json) throw new SyntaxError("not json");
      return body;
    },
  });
};

// first of the 401 tests: the module remembers once it has navigated
test("on the login page itself a 401 does not navigate", async () => {
  globalThis.window.location.pathname = "/login";
  answer(401, {});
  await assert.rejects(request("/x"), (e) => e.status === 401);
  assert.deepEqual(assigned, []);
});

test("a successful answer is parsed; 204 is null", async () => {
  answer(200, { a: 1 });
  assert.deepEqual(await request("/x"), { a: 1 });
  answer(204);
  assert.equal(await request("/x"), null);
});

test("requests ask for JSON, and the caller's headers and options win", async () => {
  let seen;
  globalThis.fetch = async (url, options) => {
    seen = [url, options];
    return { status: 200, ok: true, json: async () => ({}) };
  };
  await request("/x", { method: "PATCH", body: "{}", headers: { Accept: "text/plain", "X-Y": "1" } });
  assert.deepEqual(seen, ["/x", { method: "PATCH", body: "{}", headers: { Accept: "text/plain", "Content-Type": "application/json", "X-Y": "1" } }]);
});

test("a lost connection is status 0 with a readable message", async () => {
  globalThis.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(request("/x"), (e) => e instanceof ApiError && e.status === 0 && /Could not reach the server/.test(e.message) && e.detail === null);
});

test("422 with a list becomes field errors, the first message per field, the last path element as name", async () => {
  answer(422, {
    detail: [
      { loc: ["body", "name"], msg: "too short" },
      { loc: ["body", "name"], msg: "second message" },
      { loc: ["body", "config", "url"], msg: "bad url" },
      { loc: "weird", msg: "ignored" },
      { loc: ["body", 3], msg: "numeric position is ignored" },
    ],
  });
  await assert.rejects(request("/x"), (e) => {
    assert.equal(e.status, 422);
    assert.equal(e.message, "Please check your input.");
    assert.deepEqual(e.fieldErrors, { name: "too short", url: "bad url" });
    return true;
  });
});

test("a refusal with a text keeps it as the detail and the message", async () => {
  answer(409, { detail: "Already linked." });
  await assert.rejects(request("/x"), (e) => e.status === 409 && e.message === "Already linked." && e.detail === "Already linked.");
  answer(422, { detail: "This change is not allowed." });
  await assert.rejects(request("/x"), (e) => e.status === 422 && e.detail === "This change is not allowed." && Object.keys(e.fieldErrors).length === 0);
});

test("a refusal without a usable text gets the generic message and no detail", async () => {
  for (const body of [{}, { detail: "" }, { detail: { nested: true } }]) {
    answer(400, body);
    await assert.rejects(request("/x"), (e) => e.status === 400 && e.message === "The request was not accepted." && e.detail === null);
  }
  answer(404, null, { json: false });
  await assert.rejects(request("/x"), (e) => e.status === 404 && e.detail === null);
});

test("server errors say so, with the server's text when there is one", async () => {
  answer(500, { detail: "disk full" });
  await assert.rejects(request("/x"), (e) => e.status === 500 && /Something went wrong/.test(e.message) && e.detail === "disk full");
  answer(502, null, { json: false });
  await assert.rejects(request("/x"), (e) => e.status === 502 && e.detail === null);
});

test("401 sends the browser to the login page once, remembering where it was", async () => {
  answer(401, {});
  await assert.rejects(request("/x"), (e) => e.status === 401 && /sign-in has expired/.test(e.message));
  assert.deepEqual(assigned, ["/login?next=%2Fpipelines%2Fflow%3Fx%3D1"]);
  await assert.rejects(request("/y"), (e) => e.status === 401);
  assert.equal(assigned.length, 1, "a second 401 does not navigate again");
});

