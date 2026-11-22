/* The thin API clients: which URL and body each call sends. */
import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

const JS = "../../openartifact/static/js/";
const tasks = await import(`${JS}tasks/api.js`);
const history = await import(`${JS}tasks/history-api.js`);
const { listAllExecutions } = await import(`${JS}executions/api.js`);

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

/** Record [method, url, body] of every call. */
function record() {
  const calls = [];
  globalThis.fetch = async (url, options = {}) => {
    calls.push([options.method ?? "GET", url, options.body === undefined ? undefined : JSON.parse(options.body)]);
    return { status: 200, ok: true, json: async () => ({}) };
  };
  return calls;
}

test("tasks", async () => {
  const calls = record();
  await tasks.listTasks();
  await tasks.createTask({ title: "T", body: "", status: "backlog" });
  await tasks.updateTask("a/b", { title: "New" });
  await tasks.deleteTask("a b");
  await tasks.listRuns();
  await tasks.listStages("p 1");
  assert.deepEqual(calls, [
    ["GET", "/api/tasks", undefined],
    ["POST", "/api/tasks", { title: "T", body: "", status: "backlog" }],
    ["PATCH", "/api/tasks/a%2Fb", { title: "New" }],
    ["DELETE", "/api/tasks/a%20b", undefined],
    ["GET", "/api/runs", undefined],
    ["GET", "/api/pipelines/p%201/stages", undefined],
  ]);
});

test("placeTask sends only what is given; beforeId null means the end of the lane", async () => {
  const calls = record();
  await tasks.placeTask("1", { status: "done", beforeId: "2" });
  await tasks.placeTask("1", { beforeId: null });
  await tasks.placeTask("1", { status: "backlog" });
  await tasks.placeTask("1");
  assert.deepEqual(calls.map((c) => c[2]), [{ status: "done", before_id: "2" }, { before_id: null }, { status: "backlog" }, {}]);
});

test("runs: start sends the start point, stop sends no body", async () => {
  const calls = record();
  await tasks.startRun("t1", { pipeline_id: "p", stage_id: "s", action_id: null });
  await tasks.stopRun("t1");
  assert.deepEqual(calls, [
    ["POST", "/api/tasks/t1/run", { pipeline_id: "p", stage_id: "s", action_id: null }],
    ["POST", "/api/tasks/t1/run/stop", undefined],
  ]);
});

test("history of one artifact", async () => {
  const calls = record();
  await history.listExecutions("t1");
  await history.listExecutions("t1", 5);
  await history.getExecution("t1", "e/1");
  await history.deleteExecution("t1", "e1");
  await history.clearExecutions("t1");
  await history.saveHistoryPolicy("t1", { keep_last: 10, keep_hours: null, ignored: true });
  assert.deepEqual(calls, [
    ["GET", "/api/tasks/t1/executions?limit=100", undefined],
    ["GET", "/api/tasks/t1/executions?limit=5", undefined],
    ["GET", "/api/tasks/t1/executions/e%2F1", undefined],
    ["DELETE", "/api/tasks/t1/executions/e1", undefined],
    ["DELETE", "/api/tasks/t1/executions", undefined],
    ["PUT", "/api/tasks/t1/history-policy", { keep_last: 10, keep_hours: null }],
  ]);
});

test("the global execution list takes the query as built by the filters", async () => {
  const calls = record();
  await listAllExecutions(new URLSearchParams({ status: "failed", limit: "50" }));
  assert.deepEqual(calls, [["GET", "/api/executions?status=failed&limit=50", undefined]]);
});
