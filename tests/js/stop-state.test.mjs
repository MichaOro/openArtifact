/* The STOP switch's state in the browser (components/stop-state.js, ADR-076): what the banner and the switch share. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const JS = "../../openartifact/static/js/";
const { currentStop, loadStop, resetStop, setStop, subscribeStop } = await import(`${JS}components/stop-state.js`);

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
  resetStop();
});

const OFF = { active: false, since: null, available: true, running: 2, aborted: 0 };
const ON = { ...OFF, active: true, since: "2026-11-26T12:00:00Z", running: 0, aborted: 2 };

function answer(body) {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push([options.method ?? "GET", url, options.body === undefined ? undefined : JSON.parse(options.body)]);
    return { status: 200, ok: true, json: async () => body };
  };
  return calls;
}

test("a subscriber hears the state at once when there is one, and every change after it", async () => {
  const heard = [];
  const stop = subscribeStop((state) => heard.push(state.active));
  assert.deepEqual(heard, []); // nothing is known before the first answer
  assert.equal(currentStop(), null);
  answer(OFF);
  await loadStop();
  subscribeStop((state) => heard.push(`late:${state.active}`));
  assert.deepEqual(heard, [false, "late:false"]);
  answer(ON);
  await setStop(true);
  assert.deepEqual(heard, [false, "late:false", true, "late:true"]);
  stop();
  await loadStop();
  assert.deepEqual(heard.slice(4), ["late:true"]); // the one that was stopped hears nothing more
});

test("reading asks GET, switching sends the wanted state, and the answer is the new state", async () => {
  const calls = answer(OFF);
  assert.equal((await loadStop()).running, 2);
  answer(ON);
  const second = answer(ON);
  const state = await setStop(true);
  assert.deepEqual(second, [["PUT", "/api/settings/stop", { active: true }]]);
  assert.deepEqual([state.active, state.aborted], [true, 2]);
  assert.deepEqual(calls, [["GET", "/api/settings/stop", undefined]]);
});

test("a refusal of the server reaches the caller and leaves the state as it was", async () => {
  answer(OFF);
  await loadStop();
  globalThis.fetch = async () => ({
    status: 409,
    ok: false,
    json: async () => ({ detail: 'The STOP switch is switched off: switch on "Show the STOP switch"', code: "stop_unavailable" }),
  });
  await assert.rejects(setStop(true), (error) => error.status === 409 && error.code === "stop_unavailable" && error.detail.includes("Show the STOP switch"));
  assert.equal(currentStop().active, false);
});
