import assert from "node:assert/strict";
import test from "node:test";

import {
  ATTRIBUTION_TIME_WINDOW_MS,
  ATTRIBUTION_TOOL_WINDOW,
  createAttributionState,
  incrementFrictionForLatestSkill,
  opaqueSessionId,
  observeSkill,
  recordTool,
  resetAttribution,
} from "./attribution.mjs";

test("attributes friction only to the latest skill", () => {
  const state = createAttributionState();
  recordTool(state);
  observeSkill(state, "first-skill", 1000);
  recordTool(state);
  observeSkill(state, "second-skill", 1100);

  assert.equal(incrementFrictionForLatestSkill(state, 1200), "second-skill");
  assert.equal(state.frictionBySkill.get("first-skill"), undefined);
  assert.equal(state.frictionBySkill.get("second-skill"), 1);
});

test("expires attribution after the tool proximity window", () => {
  const state = createAttributionState();
  recordTool(state);
  observeSkill(state, "bounded-skill", 1000);
  for (let i = 0; i <= ATTRIBUTION_TOOL_WINDOW; i += 1) {
    recordTool(state);
  }

  assert.equal(incrementFrictionForLatestSkill(state, 1200), null);
  assert.equal(state.frictionBySkill.size, 0);
});

test("expires attribution after the time window", () => {
  const state = createAttributionState();
  recordTool(state);
  observeSkill(state, "bounded-skill", 1000);

  assert.equal(
    incrementFrictionForLatestSkill(
      state,
      1000 + ATTRIBUTION_TIME_WINDOW_MS + 1
    ),
    null
  );
});

test("reset clears all per-session attribution", () => {
  const state = createAttributionState();
  recordTool(state);
  observeSkill(state, "example-skill", 1000);
  incrementFrictionForLatestSkill(state, 1100);

  resetAttribution(state);

  assert.equal(state.observedSkills.size, 0);
  assert.equal(state.frictionBySkill.size, 0);
  assert.equal(state.latestSkill, null);
  assert.equal(state.toolSequence, 0);
});

test("normalizes unsafe session ids to opaque hashes", () => {
  assert.equal(opaqueSessionId("safe-session_123"), "safe-session_123");
  const normalized = opaqueSessionId("../../private/path");
  assert.match(normalized, /^session-[a-f0-9]{24}$/);
  assert.doesNotMatch(normalized, /private|path/);
  assert.equal(opaqueSessionId(""), null);
});
