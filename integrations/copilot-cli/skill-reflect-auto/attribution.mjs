import { createHash } from "node:crypto";

export const ATTRIBUTION_TOOL_WINDOW = 6;
export const ATTRIBUTION_TIME_WINDOW_MS = 10 * 60 * 1000;
export const RETRY_TOOL_WINDOW = 2;
export const JOURNAL_KEY_LIMIT = 64;
export const OBSERVED_SKILL_LIMIT = 64;
const SAFE_SESSION_ID_RE = /^[A-Za-z0-9._-]{1,160}$/;
const SAFE_SKILL_NAME_RE = /^[^\u0000-\u001f\u007f]{1,200}$/;

export function opaqueSessionId(value) {
  const candidate = String(value ?? "").trim();
  if (!candidate) return null;
  if (candidate !== "." && candidate !== ".." && SAFE_SESSION_ID_RE.test(candidate)) {
    return candidate;
  }
  const digest = createHash("sha256").update(candidate).digest("hex").slice(0, 24);
  return `session-${digest}`;
}

export function opaqueEventKey(value) {
  const candidate = String(value ?? "").trim();
  if (!candidate) return null;
  return createHash("sha256").update(candidate).digest("hex").slice(0, 24);
}

function argumentShape(value, depth = 0) {
  if (depth >= 3) return typeof value;
  if (Array.isArray(value)) {
    return {
      list: [...new Set(value.map((item) =>
        JSON.stringify(argumentShape(item, depth + 1))
      ))].sort(),
    };
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, child]) => [key, argumentShape(child, depth + 1)])
    );
  }
  if (value === null) return "null";
  return typeof value;
}

/**
 * Return an opaque fingerprint of a tool name plus argument keys/types.
 * Argument values never enter the fingerprint input.
 */
export function toolShapeFingerprint(toolName, toolArgs) {
  const payload = JSON.stringify({
    name: String(toolName ?? ""),
    shape: argumentShape(toolArgs),
  });
  return createHash("sha256").update(payload).digest("hex").slice(0, 24);
}

export function createAttributionState() {
  return {
    observedSkills: new Set(),
    frictionBySkill: new Map(),
    signalsBySkill: new Map(),
    latestSkill: null,
    toolSequence: 0,
    seenFrictionKeys: new Set(),
    inFlightTools: new Map(),
    lastFailedTool: null,
    unmatchedToolOutcomes: [],
    unmatchedFailureHooks: [],
  };
}

function trimSet(set, limit = JOURNAL_KEY_LIMIT) {
  while (set.size > limit) {
    set.delete(set.values().next().value);
  }
}

function trimMap(map, limit = JOURNAL_KEY_LIMIT) {
  while (map.size > limit) {
    map.delete(map.keys().next().value);
  }
}

export function recordTool(
  state,
  {
    callKey = null,
    shape = null,
    skillContext = null,
    now = Date.now(),
    retryToolWindow = RETRY_TOOL_WINDOW,
    timeWindowMs = ATTRIBUTION_TIME_WINDOW_MS,
  } = {}
) {
  state.toolSequence += 1;

  if (callKey && shape) {
    state.inFlightTools.set(callKey, {
      shape,
      skillContext: skillContext ? { ...skillContext } : null,
      toolSequence: state.toolSequence,
      startedAt: now,
    });
    trimMap(state.inFlightTools);
  }

  const failed = state.lastFailedTool;
  if (
    failed &&
    shape &&
    failed.shape === shape &&
    state.toolSequence - failed.toolSequence >= 1 &&
    state.toolSequence - failed.toolSequence <= retryToolWindow &&
    now - failed.observedAt >= 0 &&
    now - failed.observedAt <= timeWindowMs
  ) {
    state.lastFailedTool = null;
    return {
      signal: "tool_retry",
      key: `retry:${callKey ?? state.toolSequence}:${shape}`,
      skillContext: failed.skillContext
        ? { ...failed.skillContext }
        : null,
    };
  }

  return null;
}

export function observeSkill(state, skillName, now = Date.now()) {
  if (!SAFE_SKILL_NAME_RE.test(skillName)) return false;
  state.observedSkills.add(skillName);
  while (state.observedSkills.size > OBSERVED_SKILL_LIMIT) {
    const oldest = state.observedSkills.values().next().value;
    state.observedSkills.delete(oldest);
    state.frictionBySkill.delete(oldest);
    state.signalsBySkill.delete(oldest);
  }

  if (
    state.latestSkill?.name === skillName &&
    state.latestSkill.toolSequence === state.toolSequence
  ) {
    return false;
  }

  state.latestSkill = {
    name: skillName,
    toolSequence: state.toolSequence,
    observedAt: now,
  };
  return true;
}

export function recordFrictionForLatestSkill(
  state,
  {
    now = Date.now(),
    signal = "tool_failure",
    key = null,
    failedToolShape = null,
    skillContext = undefined,
    toolWindow = ATTRIBUTION_TOOL_WINDOW,
    timeWindowMs = ATTRIBUTION_TIME_WINDOW_MS,
  } = {}
) {
  if (key && state.seenFrictionKeys.has(key)) {
    return { attributed: false, reason: "duplicate", signal };
  }

  const latest =
    skillContext === undefined ? state.latestSkill : skillContext;
  if (!latest) {
    return { attributed: false, reason: "no_skill", signal };
  }
  if (!state.observedSkills.has(latest.name)) {
    return { attributed: false, reason: "no_skill", signal };
  }

  const toolDistance = state.toolSequence - latest.toolSequence;
  const elapsed = now - latest.observedAt;
  if (
    toolDistance < 0 ||
    toolDistance > toolWindow ||
    elapsed < 0 ||
    elapsed > timeWindowMs
  ) {
    return { attributed: false, reason: "outside_window", signal };
  }

  const previous = state.frictionBySkill.get(latest.name) ?? 0;
  const count = previous + 1;
  state.frictionBySkill.set(latest.name, count);

  const signals = state.signalsBySkill.get(latest.name) ?? new Map();
  signals.set(signal, (signals.get(signal) ?? 0) + 1);
  state.signalsBySkill.set(latest.name, signals);

  if (key) {
    state.seenFrictionKeys.add(key);
    trimSet(state.seenFrictionKeys);
  }
  if (failedToolShape) {
    state.lastFailedTool = {
      shape: failedToolShape,
      key,
      skillContext: { ...latest },
      toolSequence: state.toolSequence,
      observedAt: now,
    };
  }

  return {
    attributed: true,
    skill: latest.name,
    signal,
    count,
  };
}

export function incrementFrictionForLatestSkill(
  state,
  now = Date.now(),
  toolWindow = ATTRIBUTION_TOOL_WINDOW,
  timeWindowMs = ATTRIBUTION_TIME_WINDOW_MS
) {
  const result = recordFrictionForLatestSkill(state, {
    now,
    toolWindow,
    timeWindowMs,
  });
  return result.attributed ? result.skill : null;
}

export function completeTool(state, callKey) {
  if (!callKey) return null;
  const tool = state.inFlightTools.get(callKey) ?? null;
  state.inFlightTools.delete(callKey);
  return tool;
}

export function latestInFlightTool(state) {
  let latest = null;
  for (const [callKey, tool] of state.inFlightTools) {
    if (!latest || tool.toolSequence > latest.tool.toolSequence) {
      latest = { callKey, tool };
    }
  }
  return latest;
}

export function resetAttribution(state) {
  state.observedSkills.clear();
  state.frictionBySkill.clear();
  state.signalsBySkill.clear();
  state.latestSkill = null;
  state.toolSequence = 0;
  state.seenFrictionKeys.clear();
  state.inFlightTools.clear();
  state.lastFailedTool = null;
  state.unmatchedToolOutcomes.length = 0;
  state.unmatchedFailureHooks.length = 0;
}
