/* The pure part of the avatar (static/js/components/avatar.js): what the circle shows. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { faceOf, MAX_INITIALS } from "../../openartifact/static/js/components/avatar.js";

test("without initials the circle shows the icon of the kind", () => {
  assert.deepEqual(faceOf({ icon: "plug" }), { icon: "plug" });
  assert.deepEqual(faceOf(), { icon: "user" });
  assert.deepEqual(faceOf({ icon: "play", initials: "   " }), { icon: "play" }); // blank initials are none
  assert.deepEqual(faceOf({ icon: "play", initials: null }), { icon: "play" });
});

test("initials replace the icon, in capitals, at most two letters", () => {
  assert.equal(MAX_INITIALS, 2);
  assert.deepEqual(faceOf({ icon: "user", initials: "mc" }), { initials: "MC" });
  assert.deepEqual(faceOf({ icon: "user", initials: " simone " }), { initials: "SI" });
  assert.deepEqual(faceOf({ initials: "é" }), { initials: "É" });
});
