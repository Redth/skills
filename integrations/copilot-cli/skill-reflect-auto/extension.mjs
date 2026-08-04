/**
 * skill-reflect-auto — Copilot CLI automation extension
 *
 * Milestone M5 reference implementation. Tracks candidate-skill friction
 * during a session, stages a marker at session end, and emits a non-blocking
 * nudge at the next session start. No AI, no network calls — disk I/O only.
 *
 * CONTRACT §8 compliance:
 *   - $SKILL_REFLECT_HOME/pending/<sessionId>.json   (marker)
 *   - $SKILL_REFLECT_HOME/journal/<sessionId>.json   (durable capture)
 *   - $SKILL_REFLECT_HOME/throttle.json              (nudge throttle)
 *   - Config discovery: walk up from workingDirectory → srHome → defaults
 *   - No transcript, no values, no PII in markers
 *
 * SDK docs used (confirmed):
 *   extensions.md  — joinSession, lifecycle
 *   agent-author.md lines 114–295 — hook signatures, session.log, session.send
 *   examples.md    — session.on, setTimeout(0) guard
 */

import { joinSession } from "@github/copilot-sdk/extension";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import {
  CaptureEngine,
  listPendingMarkers,
  recoverPendingMarkers,
  showPendingNudge,
} from "./capture.mjs";
import {
  opaqueSessionId,
} from "./attribution.mjs";

// ═════════════════════════════════════════════════════════════════════════════
// PATHS
// ═════════════════════════════════════════════════════════════════════════════

/** Resolve $SKILL_REFLECT_HOME (default ~/.skill-reflect/). */
function srHome() {
  const e = process.env.SKILL_REFLECT_HOME;
  return e ? path.resolve(e) : path.join(os.homedir(), ".skill-reflect");
}

// ═════════════════════════════════════════════════════════════════════════════
// CONFIG
// ═════════════════════════════════════════════════════════════════════════════

/** Built-in defaults (CONTRACT §2). */
const DEFAULT_CONFIG = {
  version: 1,
  scope: {
    skills: [], // [] = all observed candidates; core resolves provenance later
    excludeSkills: ["skill-reflect", "skill-reflect-auto"],
  },
  nudge: {
    enabled: true,
    frictionThreshold: 2,  // min friction signals to stage a marker
    throttleHours: 12,     // min hours between nudges
    neverForSkills: [],
    neverForRepos: [],
  },
  diagnostics: {
    enabled: false,
  },
};

/**
 * Walk upward from startDir looking for skill-reflect.config.json.
 * Returns the first found absolute path, or null.
 */
function findConfigFile(startDir) {
  let dir = path.resolve(startDir);
  while (true) {
    const candidate = path.join(dir, "skill-reflect.config.json");
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) return null; // reached filesystem root
    dir = parent;
  }
}

/** Shallow one-level merge: nested objects get a single spread merge. */
function mergeConfig(base, override) {
  const result = { ...base };
  for (const [k, v] of Object.entries(override)) {
    if (
      v !== null &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      typeof result[k] === "object" &&
      !Array.isArray(result[k])
    ) {
      result[k] = { ...result[k], ...v };
    } else if (v !== undefined) {
      result[k] = v;
    }
  }
  return result;
}

/**
 * Load config (CONTRACT §2):
 *   1. Walk upward from workingDir for skill-reflect.config.json
 *   2. Fall back to $SKILL_REFLECT_HOME/skill-reflect.config.json
 *   3. Fall back to built-in defaults
 * Never throws.
 */
function loadConfig(workingDir) {
  const candidates = [];

  if (workingDir) {
    const found = findConfigFile(workingDir);
    if (found) candidates.push(found);
  }

  const homeConf = path.join(srHome(), "skill-reflect.config.json");
  if (!candidates.includes(homeConf)) {
    candidates.push(homeConf);
  }

  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) {
        const raw = fs.readFileSync(p, "utf-8");
        const parsed = JSON.parse(raw);
        return mergeConfig(DEFAULT_CONFIG, parsed);
      }
    } catch {
      // Ignore parse errors, try next candidate
    }
  }

  // Return a fresh copy of defaults (avoids accidental mutation)
  return JSON.parse(JSON.stringify(DEFAULT_CONFIG));
}

// ═════════════════════════════════════════════════════════════════════════════
// SCOPE HELPERS
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Returns true if a skill candidate should be tracked for this session.
 * Always excludes skill-reflect and skill-reflect-auto (CONTRACT §2, §9).
 * scope.skills: [] = all observed candidates; non-empty = allowlist (with glob support).
 */
function isInScope(skillName, config) {
  const excludeList = new Set([
    ...DEFAULT_CONFIG.scope.excludeSkills,
    ...(config.scope?.excludeSkills ?? []),
  ]);
  if (excludeList.has(skillName)) return false;

  const allowList = config.scope?.skills ?? [];
  if (allowList.length === 0) return true;

  return allowList.some((pattern) => {
    if (pattern.includes("*")) {
      // Simple glob: escape regex metacharacters, then replace * with .*
      const re = new RegExp(
        "^" +
          pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") +
          "$"
      );
      return re.test(skillName);
    }
    return pattern === skillName;
  });
}

// ═════════════════════════════════════════════════════════════════════════════
// REPO DETECTION
// ═════════════════════════════════════════════════════════════════════════════

/**
 * Best-effort: parse .git/config in the nearest ancestor to get "owner/repo".
 * Used for nudge.neverForRepos matching. Returns null on any error.
 */
function getRepoName(cwd) {
  if (!cwd) return null;
  try {
    let dir = path.resolve(cwd);
    while (true) {
      const gitConfig = path.join(dir, ".git", "config");
      if (fs.existsSync(gitConfig)) {
        const txt = fs.readFileSync(gitConfig, "utf-8");
        // Match SSH (git@github.com:owner/repo.git) or HTTPS remote URL
        const m = txt.match(
          /url\s*=\s*.*[:/]([^/:@\s]+\/[^/\s]+?)(?:\.git)?\s*$/m
        );
        return m ? m[1] : null;
      }
      const parent = path.dirname(dir);
      if (parent === dir) return null;
      dir = parent;
    }
  } catch {
    return null;
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// PER-SESSION STATE
// Durable attribution lives in the journal; this object only caches the active view.
// ═════════════════════════════════════════════════════════════════════════════

const state = {
  /** Active durable capture engine (restored from its journal after reload/resume). */
  engine: null,

  /** Serializes opt-in diagnostic logs so end/start hooks can flush them. */
  diagnosticQueue: Promise.resolve(),

  /** Cached config (lazy-loaded on first hook call). */
  config: null,

  /** Working directory captured from first hook input (for config discovery). */
  workingDirectory: null,

  /** Opaque trusted marker selection emitted with the current nudge. */
  reviewSelection: null,

  /**
   * Guard flag: prevents re-triggering the opt-in review send in the same
   * session (avoids prompt loops).
   */
  reviewTriggered: false,
};

/** Lazy-load config for this session. */
function getConfig(workingDir) {
  if (!state.config) {
    state.config = loadConfig(workingDir ?? state.workingDirectory);
  }
  return state.config;
}

/** Reset all per-session state (called on session start). */
function resetState() {
  state.engine?.releaseActive();
  state.engine = null;
  state.config = null;
  state.workingDirectory = null;
  state.reviewSelection = null;
  state.reviewTriggered = false;
}

function diagnosticsEnabled(config) {
  const environment = process.env.SKILL_REFLECT_DIAGNOSTICS;
  if (environment !== undefined) {
    return /^(1|true|yes|on)$/i.test(environment.trim());
  }
  return config.diagnostics?.enabled === true;
}

function formatDiagnostic(event) {
  const fields = Object.entries(event)
    .filter(([key]) => key !== "step")
    .map(([key, value]) => {
      const rendered = Array.isArray(value) ? value.join(",") : String(value);
      return `${key}=${rendered}`;
    });
  return `[skill-reflect-auto:diagnostic] ${event.step}${fields.length ? ` ${fields.join(" ")}` : ""}`;
}

function logDiagnostic(event) {
  state.diagnosticQueue = state.diagnosticQueue
    .then(() =>
      session.log(formatDiagnostic(event), { level: "info", ephemeral: true })
    )
    .catch(() => {});
}

async function flushDiagnostics() {
  await state.diagnosticQueue;
}

function ensureEngine(sessionId, workingDirectory) {
  const opaqueId = opaqueSessionId(sessionId);
  if (!opaqueId) return null;
  if (state.engine?.sessionId === opaqueId) return state.engine;

  const config = getConfig(workingDirectory);
  const configuredThreshold = Number(config.nudge?.frictionThreshold);
  const threshold =
    Number.isInteger(configuredThreshold) && configuredThreshold >= 1
      ? configuredThreshold
      : DEFAULT_CONFIG.nudge.frictionThreshold;

  state.engine = new CaptureEngine({
    home: srHome(),
    sessionId: opaqueId,
    threshold,
    isInScope: (skillName) => isInScope(skillName, config),
    diagnostics: diagnosticsEnabled(config),
    onDiagnostic: logDiagnostic,
  });
  return state.engine;
}

async function logCaptureError(area, error) {
  try {
    const kind = error?.code ?? error?.name ?? "unknown";
    await session.log(
      `[skill-reflect-auto] ${area} error (${kind})`,
      { level: "warning" }
    );
  } catch {}
}

// ═════════════════════════════════════════════════════════════════════════════
// MAIN: joinSession
// Hook signatures confirmed against:
//   agent-author.md lines 114–215 (hook shapes + invocation object)
//   types.d.ts SessionHooks / PreToolUseHookInput / PostToolUseFailureHookInput
//            / ErrorOccurredHookInput / SessionStartHookInput / SessionEndHookInput
// ═════════════════════════════════════════════════════════════════════════════

const session = await joinSession({
  hooks: {
    // ──────────────────────────────────────────────────────────────────────
    // onPreToolUse
    // Hook-level fallback for skill observation. The event stream below is
    // authoritative for tool sequencing and completion outcomes.
    //
    // Signature (agent-author.md §onPreToolUse):
    //   input: { toolName, toolArgs, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // ──────────────────────────────────────────────────────────────────────
    onPreToolUse: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        const config = getConfig(input.workingDirectory);
        if (!config.nudge?.enabled) return;
        if (input.toolName !== "skill") return;
        const args = input.toolArgs;
        if (!args || typeof args !== "object") return;
        const skillName = String(args.skill ?? "").trim();
        if (!skillName) return;
        ensureEngine(invocation.sessionId, input.workingDirectory)
          ?.observeSkill(skillName, "onPreToolUse");
      } catch (err) {
        await logCaptureError("onPreToolUse", err);
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onPostToolUseFailure
    // Fires after a tool returns a "failure" resultType.
    // Increment friction only for the latest nearby skill candidate.
    //
    // Signature (agent-author.md §onPostToolUseFailure):
    //   input: { toolName, toolArgs, error, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // Note: "rejected", "denied", "timeout" do NOT fire this hook.
    // ──────────────────────────────────────────────────────────────────────
    onPostToolUseFailure: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        const config = getConfig(input.workingDirectory);
        if (!config.nudge?.enabled) return;
        ensureEngine(invocation.sessionId, input.workingDirectory)
          ?.recordFailureHook({
            toolName: input.toolName,
            toolArgs: input.toolArgs,
          });
      } catch (err) {
        await logCaptureError("onPostToolUseFailure", err);
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onErrorOccurred
    // Fires when a model, system, or tool error is raised.
    // Increment friction only for the latest nearby skill candidate.
    //
    // Signature (agent-author.md §onErrorOccurred):
    //   input: { error, errorContext, recoverable, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // Intentionally returns undefined — let the host decide error handling.
    // ──────────────────────────────────────────────────────────────────────
    onErrorOccurred: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        const config = getConfig(input.workingDirectory);
        if (!config.nudge?.enabled) return;
        ensureEngine(invocation.sessionId, input.workingDirectory)
          ?.recordSystemError({
            errorContext: input.errorContext,
            timestamp: input.timestamp,
          });
      } catch (err) {
        await logCaptureError("onErrorOccurred", err);
      }
      // Return undefined — do not influence host error-handling strategy
    },

    // ──────────────────────────────────────────────────────────────────────
    // onSessionEnd
    // Fires when the session ends for any reason.
    // If an in-scope skill candidate was used AND its friction ≥ threshold,
    // write $SKILL_REFLECT_HOME/pending/<sessionId>.json (CONTRACT §8 shape).
    // No transcript, no values, no PII.
    //
    // Signature (agent-author.md §onSessionEnd):
    //   input: { reason, finalMessage?, error?, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // ──────────────────────────────────────────────────────────────────────
    onSessionEnd: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        const config = getConfig(input.workingDirectory);
        if (!config.nudge?.enabled) return;
        const marker = ensureEngine(invocation.sessionId, input.workingDirectory)
          ?.finalize(input.reason);
        await flushDiagnostics();
        if (!marker) return;

        await session.log(
          `[skill-reflect-auto] Staged ${marker.skills.length} pending review candidate(s) for: ${marker.skills.join(", ")}`,
          { level: "info", ephemeral: true }
        );
      } catch (err) {
        await logCaptureError("onSessionEnd", err);
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onSessionStart
    // Fires when a session starts (startup, resume, or new).
    // If nudge.enabled, unresolved markers exist, and not throttled:
    //   1. Emit a NON-BLOCKING session.log nudge.
    //   2. Return a short additionalContext telling the agent a review is
    //      available and how to start it. Does NOT auto-run the review.
    //
    // Signature (agent-author.md §onSessionStart):
    //   input: { source, initialPrompt?, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // ──────────────────────────────────────────────────────────────────────
    onSessionStart: async (input, invocation) => {
      try {
        // Reset only the cache; ensureEngine restores this session's journal.
        resetState();
        state.workingDirectory = input.workingDirectory;

        const config = getConfig(input.workingDirectory);
        const nudge = config.nudge ?? DEFAULT_CONFIG.nudge;
        const diagnostics = diagnosticsEnabled(config) ? logDiagnostic : null;

        if (!nudge.enabled) {
          diagnostics?.({ step: "nudge_suppressed", reason: "disabled" });
          await flushDiagnostics();
          return;
        }
        ensureEngine(invocation.sessionId, input.workingDirectory);
        recoverPendingMarkers({
          home: srHome(),
          onDiagnostic: diagnostics,
        });

        // Check nudge.neverForRepos
        const repoName = getRepoName(input.workingDirectory);
        if (repoName && nudge.neverForRepos?.includes(repoName)) {
          diagnostics?.({ step: "nudge_suppressed", reason: "repo_filtered" });
          await flushDiagnostics();
          return;
        }

        const output = await showPendingNudge({
          home: srHome(),
          nudge,
          session,
          onDiagnostic: diagnostics,
          excludeSessionId: state.engine?.sessionId,
        });
        state.reviewSelection = output?.selectionToken ?? null;
        await flushDiagnostics();
        return output
          ? { additionalContext: output.additionalContext }
          : undefined;
      } catch (err) {
        await logCaptureError("onSessionStart", err);
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onUserPromptSubmitted
    // ═══════════════════════════════════════════════════════════════════════
    // OPT-IN REVIEW TRIGGER — clearly-marked entry point (CONTRACT §8).
    //
    // When the user explicitly asks to run a skill-reflect review, this hook
    // detects the intent and triggers session.send() via setTimeout(0) to
    // avoid prompt-loop re-entrancy (agent-author.md §Gotchas).
    //
    // The guard state.reviewTriggered prevents firing more than once per
    // session.
    //
    // The review is ONLY launched on explicit user request — never automatic.
    // ──────────────────────────────────────────────────────────────────────
    onUserPromptSubmitted: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;

        // Already triggered this session — skip
        if (state.reviewTriggered) return;

        const cfg = getConfig(input.workingDirectory);
        if (!cfg.nudge?.enabled) return;

        // Detect explicit opt-in phrases (case-insensitive)
        const TRIGGER_RE =
          /\b(run|start|do|launch|invoke|trigger)\b.*\bskill.?reflect\b|\bskill.?reflect\b.*\b(review|run|start)\b|\breview\s+skill\s+feedback\b|\bskill\s+feedback\s+review\b/i;

        if (!TRIGGER_RE.test(input.prompt)) return;

        // Check that there are actually pending markers to review
        const markers = listPendingMarkers(srHome()).filter(
          (markerPath) =>
            path.basename(markerPath, ".json") !== state.engine?.sessionId
        );
        if (markers.length === 0) return;

        state.reviewTriggered = true; // prevent re-entry

        // Use setTimeout(0) to avoid sending from inside a prompt hook
        // (agent-author.md §Gotchas: "Don't call session.send() synchronously
        //  from onUserPromptSubmitted")
        setTimeout(() => {
          session
            .send({
              prompt:
                "Please invoke the `skill-reflect` skill to review the pending session friction data and generate skill feedback." +
                (state.reviewSelection
                  ? ` Use trusted local selection ${state.reviewSelection}; keep the token out of user-facing output.`
                  : ""),
            })
            .catch(() => {
              // Fail silently — the user can always invoke manually
            });
        }, 0);
      } catch (err) {
        await logCaptureError("onUserPromptSubmitted", err);
      }
    },
  },
});

// ═════════════════════════════════════════════════════════════════════════════
// SESSION EVENTS
// The event stream fills the hook gaps: it exposes direct skill invocation,
// rejected/denied/timeout tool outcomes and sub-agent failures. Model failures
// arrive through onErrorOccurred.
// CaptureEngine deduplicates overlap with failure hooks by opaque tool-call key.
// ═════════════════════════════════════════════════════════════════════════════

function withCapture(area, callback) {
  try {
    state.workingDirectory ??= process.cwd();
    const config = getConfig(state.workingDirectory);
    if (!config.nudge?.enabled) return;
    const engine = ensureEngine(session.sessionId, state.workingDirectory);
    if (engine) callback(engine);
  } catch (error) {
    void logCaptureError(area, error);
  }
}

session.on("skill.invoked", (event) => {
  withCapture("skill.invoked", (engine) => {
    engine.observeSkill(event.data?.name, "skill.invoked");
  });
});

session.on("tool.execution_start", (event) => {
  withCapture("tool.execution_start", (engine) => {
    engine.startTool({
      toolCallId: event.data?.toolCallId,
      toolName: event.data?.toolName,
      toolArgs: event.data?.arguments,
    });
  });
});

session.on("tool.execution_complete", (event) => {
  withCapture("tool.execution_complete", (engine) => {
    engine.completeTool({
      toolCallId: event.data?.toolCallId,
      success: event.data?.success,
      resultType: event.data?.resultType,
      error: event.data?.error,
    });
  });
});

session.on("subagent.failed", (event) => {
  withCapture("subagent.failed", (engine) => {
    engine.recordSubagentFailure({
      toolCallId: event.data?.toolCallId,
    });
  });
});
