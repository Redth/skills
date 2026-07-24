import { createHash } from "node:crypto";

export const ATTRIBUTION_TOOL_WINDOW = 6;
export const ATTRIBUTION_TIME_WINDOW_MS = 10 * 60 * 1000;
const SAFE_SESSION_ID_RE = /^[A-Za-z0-9._-]{1,160}$/;

export function opaqueSessionId(value) {
  const candidate = String(value ?? "").trim();
  if (!candidate) return null;
  if (candidate !== "." && candidate !== ".." && SAFE_SESSION_ID_RE.test(candidate)) {
    return candidate;
  }
  const digest = createHash("sha256").update(candidate).digest("hex").slice(0, 24);
  return `session-${digest}`;
}

export function createAttributionState() {
  return {
    observedSkills: new Set(),
    frictionBySkill: new Map(),
    latestSkill: null,
    toolSequence: 0,
  };
}

export function recordTool(state) {
  state.toolSequence += 1;
}

export function observeSkill(state, skillName, now = Date.now()) {
  state.observedSkills.add(skillName);
  state.latestSkill = {
    name: skillName,
    toolSequence: state.toolSequence,
    observedAt: now,
  };
}

export function incrementFrictionForLatestSkill(
  state,
  now = Date.now(),
  toolWindow = ATTRIBUTION_TOOL_WINDOW,
  timeWindowMs = ATTRIBUTION_TIME_WINDOW_MS
) {
  const latest = state.latestSkill;
  if (!latest) return null;

  const toolDistance = state.toolSequence - latest.toolSequence;
  const elapsed = now - latest.observedAt;
  if (
    toolDistance < 0 ||
    toolDistance > toolWindow ||
    elapsed < 0 ||
    elapsed > timeWindowMs
  ) {
    return null;
  }

  const previous = state.frictionBySkill.get(latest.name) ?? 0;
  state.frictionBySkill.set(latest.name, previous + 1);
  return latest.name;
}

export function resetAttribution(state) {
  state.observedSkills.clear();
  state.frictionBySkill.clear();
  state.latestSkill = null;
  state.toolSequence = 0;
}
