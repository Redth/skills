/**
 * skill-reflect-auto — Copilot CLI automation extension
 *
 * Milestone M5 reference implementation. Tracks distributed-skill friction
 * during a session, stages a marker at session end, and emits a non-blocking
 * nudge at the next session start. No AI, no network calls — disk I/O only.
 *
 * CONTRACT §8 compliance:
 *   - $SKILL_REFLECT_HOME/pending/<sessionId>.json   (marker)
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
    skills: [], // [] = all distributed skills
    excludeSkills: ["skill-reflect", "skill-reflect-auto"],
  },
  nudge: {
    enabled: true,
    frictionThreshold: 2,  // min friction signals to stage a marker
    throttleHours: 12,     // min hours between nudges
    neverForSkills: [],
    neverForRepos: [],
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
 * Returns true if skillName should be tracked for this session.
 * Always excludes skill-reflect and skill-reflect-auto (CONTRACT §2, §9).
 * scope.skills: [] = all distributed skills; non-empty = allowlist (with glob support).
 */
function isInScope(skillName, config) {
  const excludeList =
    config.scope?.excludeSkills ?? DEFAULT_CONFIG.scope.excludeSkills;
  if (excludeList.includes(skillName)) return false;

  const allowList = config.scope?.skills ?? [];
  if (allowList.length === 0) return true; // empty = all distributed skills

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
// DISK HELPERS
// ═════════════════════════════════════════════════════════════════════════════

/** Ensure a directory tree exists (mkdir -p equivalent). */
function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

/**
 * Atomic-ish write: write to <path>.tmp.<pid>, then rename into place.
 * Prevents partial reads from concurrent processes.
 */
function atomicWrite(filePath, data) {
  const tmp = `${filePath}.tmp.${process.pid}`;
  try {
    fs.writeFileSync(tmp, JSON.stringify(data, null, 2), "utf-8");
    fs.renameSync(tmp, filePath);
  } catch (err) {
    try { fs.unlinkSync(tmp); } catch {}
    throw err;
  }
}

/** Return paths of all pending marker files in $SKILL_REFLECT_HOME/pending/. */
function listPendingMarkers() {
  const dir = path.join(srHome(), "pending");
  if (!fs.existsSync(dir)) return [];
  try {
    return fs
      .readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => path.join(dir, f));
  } catch {
    return [];
  }
}

// ═════════════════════════════════════════════════════════════════════════════
// THROTTLE HELPERS
// ═════════════════════════════════════════════════════════════════════════════

function readThrottle() {
  const p = path.join(srHome(), "throttle.json");
  try {
    if (fs.existsSync(p)) {
      return JSON.parse(fs.readFileSync(p, "utf-8"));
    }
  } catch {}
  return {};
}

function writeThrottle(data) {
  ensureDir(srHome());
  atomicWrite(path.join(srHome(), "throttle.json"), data);
}

/**
 * Returns true if the last nudge was within throttleHours.
 * throttleHours: 0 = always nudge.
 */
function isThrottled(throttleData, throttleHours) {
  if (!throttleHours) return false;
  const last = throttleData.lastNudgeAt;
  if (!last) return false;
  const elapsedHours =
    (Date.now() - new Date(last).getTime()) / (1000 * 60 * 60);
  return elapsedHours < throttleHours;
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
// PER-SESSION IN-MEMORY STATE
// The extension is reloaded on /clear, so this is always fresh per session.
// ═════════════════════════════════════════════════════════════════════════════

const state = {
  /**
   * Active skill windows.
   * Map<skillName, { openedAt: Date }>
   * "Window" = the skill was invoked at least once in this session.
   */
  activeSkillWindows: new Map(),

  /**
   * Friction signal count per skill.
   * Map<skillName, number>
   */
  frictionBySkill: new Map(),

  /** Cached config (lazy-loaded on first hook call). */
  config: null,

  /** Working directory captured from first hook input (for config discovery). */
  workingDirectory: null,

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

/** Mark a skill as active (open its tracking window). */
function openSkillWindow(skillName) {
  if (!state.activeSkillWindows.has(skillName)) {
    state.activeSkillWindows.set(skillName, { openedAt: new Date() });
  }
}

/** Increment friction count for every currently-open skill window. */
function incrementFrictionForActiveSkills() {
  for (const skillName of state.activeSkillWindows.keys()) {
    const prev = state.frictionBySkill.get(skillName) ?? 0;
    state.frictionBySkill.set(skillName, prev + 1);
  }
}

/** Reset all per-session state (called on session start). */
function resetState() {
  state.activeSkillWindows.clear();
  state.frictionBySkill.clear();
  state.config = null;
  state.workingDirectory = null;
  state.reviewTriggered = false;
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
    // Fires before any tool executes. When the tool is "skill", open/refresh
    // the active window for that skill so friction can be attributed to it.
    //
    // Signature (agent-author.md §onPreToolUse):
    //   input: { toolName, toolArgs, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // ──────────────────────────────────────────────────────────────────────
    onPreToolUse: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;

        // Only track "skill" tool invocations (Copilot CLI skill dispatch)
        if (input.toolName !== "skill") return;

        const args = input.toolArgs;
        if (!args || typeof args !== "object") return;

        // toolArgs shape: { skill: "<skill-name>" }  (CONTRACT §8)
        const skillName = String(args.skill ?? "").trim();
        if (!skillName) return;

        const cfg = getConfig(input.workingDirectory);
        if (!isInScope(skillName, cfg)) return;

        openSkillWindow(skillName);
      } catch (err) {
        // Never throw into the host
        try {
          await session.log(
            `[skill-reflect-auto] onPreToolUse error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onPostToolUseFailure
    // Fires after a tool returns a "failure" resultType.
    // Increment friction for all currently-open skill windows.
    //
    // Signature (agent-author.md §onPostToolUseFailure):
    //   input: { toolName, toolArgs, error, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // Note: "rejected", "denied", "timeout" do NOT fire this hook.
    // ──────────────────────────────────────────────────────────────────────
    onPostToolUseFailure: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        if (state.activeSkillWindows.size > 0) {
          incrementFrictionForActiveSkills();
        }
      } catch (err) {
        try {
          await session.log(
            `[skill-reflect-auto] onPostToolUseFailure error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    // onErrorOccurred
    // Fires when a model, system, or tool error is raised.
    // Increment friction for all currently-open skill windows.
    //
    // Signature (agent-author.md §onErrorOccurred):
    //   input: { error, errorContext, recoverable, timestamp, workingDirectory, sessionId }
    //   invocation: { sessionId }
    // Intentionally returns undefined — let the host decide error handling.
    // ──────────────────────────────────────────────────────────────────────
    onErrorOccurred: async (input, invocation) => {
      try {
        state.workingDirectory ??= input.workingDirectory;
        if (state.activeSkillWindows.size > 0) {
          incrementFrictionForActiveSkills();
        }
      } catch (err) {
        try {
          await session.log(
            `[skill-reflect-auto] onErrorOccurred error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
      }
      // Return undefined — do not influence host error-handling strategy
    },

    // ──────────────────────────────────────────────────────────────────────
    // onSessionEnd
    // Fires when the session ends for any reason.
    // If a distributed, in-scope skill was used AND its friction ≥ threshold,
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
        const sessionId = invocation.sessionId;
        const cfg = getConfig(input.workingDirectory);
        const threshold =
          cfg.nudge?.frictionThreshold ??
          DEFAULT_CONFIG.nudge.frictionThreshold;

        // Collect qualifying skills: in-scope AND friction ≥ threshold
        const qualifyingSkills = [];
        const frictionSnapshot = {};

        for (const skillName of state.activeSkillWindows.keys()) {
          const friction = state.frictionBySkill.get(skillName) ?? 0;
          if (friction >= threshold && isInScope(skillName, cfg)) {
            qualifyingSkills.push(skillName);
            frictionSnapshot[skillName] = friction;
          }
        }

        if (qualifyingSkills.length === 0) return;

        // Write marker (CONTRACT §8):
        // { sessionId, endedAt, skills[], friction{}, reason }
        const marker = {
          sessionId,
          endedAt: new Date().toISOString(),
          skills: qualifyingSkills,
          friction: frictionSnapshot,
          reason: input.reason,
        };

        const pendingDir = path.join(srHome(), "pending");
        ensureDir(pendingDir);
        atomicWrite(path.join(pendingDir, `${sessionId}.json`), marker);

        await session.log(
          `[skill-reflect-auto] Staged ${qualifyingSkills.length} pending review(s) for: ${qualifyingSkills.join(", ")}`,
          { level: "info", ephemeral: true }
        );
      } catch (err) {
        try {
          await session.log(
            `[skill-reflect-auto] onSessionEnd error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
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
        // Always reset in-memory state on session start
        resetState();
        state.workingDirectory = input.workingDirectory;

        const cfg = getConfig(input.workingDirectory);
        const nudge = cfg.nudge ?? DEFAULT_CONFIG.nudge;

        if (!nudge.enabled) return;

        // Check nudge.neverForRepos
        const repoName = getRepoName(input.workingDirectory);
        if (repoName && nudge.neverForRepos?.includes(repoName)) return;

        // Check for unresolved markers
        const markers = listPendingMarkers();
        if (markers.length === 0) return;

        // Collect pending skills (respecting nudge.neverForSkills)
        const pendingSkills = new Set();
        for (const markerPath of markers) {
          try {
            const marker = JSON.parse(
              fs.readFileSync(markerPath, "utf-8")
            );
            for (const s of marker.skills ?? []) {
              if (!nudge.neverForSkills?.includes(s)) {
                pendingSkills.add(s);
              }
            }
          } catch {}
        }
        if (pendingSkills.size === 0) return;

        // Check throttle
        const throttleData = readThrottle();
        const throttleHours =
          nudge.throttleHours ?? DEFAULT_CONFIG.nudge.throttleHours;
        if (isThrottled(throttleData, throttleHours)) return;

        // Update throttle BEFORE emitting nudge (prevents double-nudge on restart)
        writeThrottle({
          ...throttleData,
          lastNudgeAt: new Date().toISOString(),
        });

        const skillList = [...pendingSkills].join(", ");
        const count = markers.length;

        // Non-blocking nudge log (agent-author.md: session.log is non-blocking)
        await session.log(
          `📋 skill-reflect: ${count} pending review${count !== 1 ? "s" : ""} ` +
            `for: ${skillList}. ` +
            `Say "run skill-reflect" to review (optional, no auto-run).`,
          { level: "info" }
        );

        // Short additionalContext: informs the agent, kept optional
        // (agent-author.md §onSessionStart output: additionalContext)
        return {
          additionalContext:
            `[skill-reflect-auto] ${count} pending skill-feedback ` +
            `session${count !== 1 ? "s" : ""} for: ${skillList}. ` +
            `If the user explicitly asks to review feedback, run a retrospective, ` +
            `or says "run skill-reflect", invoke the \`skill-reflect\` skill. ` +
            `Do NOT run it automatically.`,
        };
      } catch (err) {
        try {
          await session.log(
            `[skill-reflect-auto] onSessionStart error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
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
        const markers = listPendingMarkers();
        if (markers.length === 0) return;

        state.reviewTriggered = true; // prevent re-entry

        // Use setTimeout(0) to avoid sending from inside a prompt hook
        // (agent-author.md §Gotchas: "Don't call session.send() synchronously
        //  from onUserPromptSubmitted")
        setTimeout(() => {
          session
            .send({
              prompt:
                "Please invoke the `skill-reflect` skill to review the pending session friction data and generate skill feedback.",
            })
            .catch(() => {
              // Fail silently — the user can always invoke manually
            });
        }, 0);
      } catch (err) {
        try {
          await session.log(
            `[skill-reflect-auto] onUserPromptSubmitted error: ${err?.message}`,
            { level: "warning" }
          );
        } catch {}
      }
    },
  },
});

// ═════════════════════════════════════════════════════════════════════════════
// SESSION EVENT: tool.execution_complete
// Optionally track friction via the event bus.
//
// Note on double-counting: onPostToolUseFailure fires for "failure" resultType.
// tool.execution_complete with success===false also fires for "failure" AND for
// "rejected"/"denied"/"timeout" which the hook does not catch.
// We intentionally do NOT count both to avoid inflating friction scores.
// The two dedicated hooks (onPostToolUseFailure + onErrorOccurred) are the
// authoritative friction sources. Uncomment the block below only if you want
// to also count rejected/denied/timeout outcomes as friction signals.
//
// session.on("tool.execution_complete", (event) => {
//   try {
//     if (event.data?.success === false && state.activeSkillWindows.size > 0) {
//       incrementFrictionForActiveSkills();
//     }
//   } catch {}
// });
// ═════════════════════════════════════════════════════════════════════════════
