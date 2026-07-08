/**
 * skill-reflect — opencode plugin adapter (Tier B).
 *
 * Hooks the `session.idle` event (turn-end, not true process-exit) to stage
 * a pending-review marker when a distributed skill was used AND friction
 * crossed the configured threshold.
 *
 * Tier B behaviour:
 *   - Throttle: only stage once per session per STAGE_INTERVAL_MS.
 *   - Dedupe: if a marker for this session already exists, update counts
 *     in-place instead of overwriting.
 *   - No true SessionEnd — marker may be written multiple times per session
 *     as friction accumulates; later writes update the existing file.
 *
 * Hard constraints (CONTRACT §§8,9):
 *   - No AI, no network calls.
 *   - Never write transcript content, values, or PII into the marker.
 *   - Always excludes skill-reflect and skill-reflect-auto.
 *   - No runtime deps beyond what opencode provides.
 *   - All paths wrap in try/catch; never throw into the host.
 *
 * # ASSUMPTION: opencode plugin API shape. Verify against opencode plugin
 * # documentation. The plugin is expected to export a default object with
 * # a `setup(api)` method. `api.on(event, handler)` subscribes to events.
 * # `session.idle` fires between agent turns with a session context object.
 * # Verify: event name, handler signature, available session context fields.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// ─── CONTRACT §9: always-excluded skills ─────────────────────────────────────
const ALWAYS_EXCLUDE = new Set(["skill-reflect", "skill-reflect-auto"]);

// Throttle: minimum ms between staging writes for the same session
const STAGE_INTERVAL_MS = 5 * 60 * 1000; // 5 minutes

// ─── PATHS ────────────────────────────────────────────────────────────────────

function srHome() {
  const e = process.env.SKILL_REFLECT_HOME;
  return e ? path.resolve(e) : path.join(os.homedir(), ".skill-reflect");
}

// ─── CONFIG ───────────────────────────────────────────────────────────────────

const DEFAULT_CONFIG = {
  version: 1,
  scope: { skills: [], excludeSkills: ["skill-reflect", "skill-reflect-auto"] },
  nudge: {
    enabled: true,
    frictionThreshold: 2,
    throttleHours: 12,
    neverForSkills: [],
    neverForRepos: [],
  },
};

function findConfigFile(startDir) {
  let dir = path.resolve(startDir);
  while (true) {
    const candidate = path.join(dir, "skill-reflect.config.json");
    if (fs.existsSync(candidate)) return candidate;
    const parent = path.dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

function loadConfig(workingDir) {
  const cfg = JSON.parse(JSON.stringify(DEFAULT_CONFIG));
  const candidates = [];
  if (workingDir) {
    const found = findConfigFile(workingDir);
    if (found) candidates.push(found);
  }
  const homeConf = path.join(srHome(), "skill-reflect.config.json");
  if (!candidates.includes(homeConf)) candidates.push(homeConf);
  for (const p of candidates) {
    try {
      if (fs.existsSync(p)) {
        const raw = JSON.parse(fs.readFileSync(p, "utf-8"));
        for (const [k, v] of Object.entries(raw)) {
          if (v !== null && typeof v === "object" && !Array.isArray(v) &&
              typeof cfg[k] === "object" && !Array.isArray(cfg[k])) {
            cfg[k] = { ...cfg[k], ...v };
          } else if (v !== undefined) {
            cfg[k] = v;
          }
        }
        break;
      }
    } catch { /* ignore */ }
  }
  return cfg;
}

function isInScope(skillName, cfg) {
  const exclude = new Set([
    ...(cfg.scope?.excludeSkills ?? []),
    ...ALWAYS_EXCLUDE,
  ]);
  if (exclude.has(skillName)) return false;
  const allow = cfg.scope?.skills ?? [];
  if (allow.length === 0) return true;
  return allow.some((p) => {
    if (p.includes("*")) {
      const re = new RegExp(
        "^" + p.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*") + "$"
      );
      return re.test(skillName);
    }
    return p === skillName;
  });
}

// ─── DISK HELPERS ─────────────────────────────────────────────────────────────

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

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

function readMarkerIfExists(markerPath) {
  try {
    if (fs.existsSync(markerPath)) {
      return JSON.parse(fs.readFileSync(markerPath, "utf-8"));
    }
  } catch {}
  return null;
}

// ─── TRANSCRIPT / MESSAGE EXTRACTION ─────────────────────────────────────────

/**
 * Extract skill names and friction signals from a messages array.
 *
 * # ASSUMPTION: `messages` is an array of message objects from the opencode
 * # session context, each with a `role` (user/assistant/tool) and `content`
 * # (string or array of content blocks). Tool calls appear as content blocks
 * # with type="tool_use" and name/input fields. Tool results have type="tool_result".
 * # Verify against opencode's session context API.
 */
function extractFromMessages(messages, cfg) {
  const skillWindows = new Set();
  const frictionBySkill = {};

  function addFriction() {
    for (const s of skillWindows) {
      frictionBySkill[s] = (frictionBySkill[s] ?? 0) + 1;
    }
  }

  const CORRECTION_RE =
    /\b(that['']?s wrong|try again|didn['']?t work|not working|failed again|fix this|no[,.]?\s+i meant|that['']?s not right|incorrect|redo that|start over|wrong (?:file|approach|command|path)|please fix|that failed|it['']?s broken)\b/i;

  let lastCallSig = null;
  let repeatCount = 0;

  for (const msg of (messages ?? [])) {
    const role = msg.role ?? "";
    const rawContent = msg.content ?? msg.message?.content ?? msg.parts ?? "";

    // Normalise content to an array of blocks
    const blocks = [];
    if (typeof rawContent === "string") {
      blocks.push({ type: "text", text: rawContent });
    } else if (Array.isArray(rawContent)) {
      blocks.push(...rawContent);
    }

    let textForCorrection = "";

    for (const blk of blocks) {
      if (typeof blk !== "object" || !blk) continue;
      const btype = blk.type ?? "";

      if (btype === "tool_use") {
        const name = blk.name ?? "";
        const inp = blk.input ?? {};

        // Explicit skill invocation
        if (name === "skill" && typeof inp === "object") {
          const skillName = String(inp.skill ?? "").trim();
          if (skillName && isInScope(skillName, cfg)) {
            skillWindows.add(skillName);
          }
        }

        // SKILL.md file-load
        for (const key of ["path", "file_path", "filename", "file"]) {
          const fpath = String(inp[key] ?? "");
          if (fpath.toUpperCase().endsWith("SKILL.MD") && fpath) {
            const parts = fpath.split(/[\\/]/);
            if (parts.length >= 2) {
              const skillDir = parts[parts.length - 2];
              if (isInScope(skillDir, cfg)) skillWindows.add(skillDir);
            }
          }
        }

        // Repeated tool call → friction
        const sig = `${name}:${JSON.stringify(inp)}`;
        if (sig === lastCallSig) {
          repeatCount++;
          if (repeatCount >= 2 && skillWindows.size > 0) addFriction();
        } else {
          lastCallSig = sig;
          repeatCount = 0;
        }
      } else if (btype === "tool_result") {
        if ((blk.is_error || blk.error) && skillWindows.size > 0) addFriction();
      } else if (btype === "text") {
        textForCorrection += (blk.text ?? "") + " ";
      }
    }

    // User correction language
    if (role === "user" && textForCorrection && skillWindows.size > 0) {
      if (CORRECTION_RE.test(textForCorrection)) addFriction();
    }
  }

  return {
    skillWindows,
    frictionBySkill: Object.fromEntries(
      Object.entries(frictionBySkill).filter(([s]) => skillWindows.has(s))
    ),
  };
}

// ─── PER-SESSION STATE ────────────────────────────────────────────────────────

// Map<sessionId, { lastStagedAt: number }>
const sessionStagingState = new Map();

// ─── PLUGIN EXPORT ────────────────────────────────────────────────────────────

/**
 * opencode plugin export.
 *
 * # ASSUMPTION: opencode plugins export a default object with a `setup(api)`
 * # method. `api` provides at minimum `api.on(eventName, handler)`.
 * # The `session.idle` event fires between agent turns with a context object
 * # that includes session id, working directory, and message history.
 * # Verify the exact plugin export shape and event payload against opencode docs.
 */
export default {
  name: "skill-reflect",
  version: "1.0.0",

  setup(api) {
    // # ASSUMPTION: api.on is the event subscription method.
    api.on("session.idle", (context) => {
      try {
        // # ASSUMPTION: context.sessionId (or context.session_id) is the session id.
        // # ASSUMPTION: context.workingDirectory (or context.cwd) is the cwd.
        // # ASSUMPTION: context.messages is the message history array.
        const sessionId =
          context?.sessionId ?? context?.session_id ?? "unknown";
        const cwd =
          context?.workingDirectory ?? context?.cwd ?? context?.working_directory ?? null;
        const messages = context?.messages ?? context?.history ?? [];

        const cfg = loadConfig(cwd);
        if (!cfg.nudge?.enabled) return;

        // ── Throttle per session ───────────────────────────────────────────
        const stagingState = sessionStagingState.get(sessionId) ?? { lastStagedAt: 0 };
        const now = Date.now();
        if (now - stagingState.lastStagedAt < STAGE_INTERVAL_MS) return;

        // ── Extract skills and friction ────────────────────────────────────
        const { skillWindows, frictionBySkill } = extractFromMessages(messages, cfg);
        const threshold = cfg.nudge?.frictionThreshold ?? 2;

        const qualifying = [...skillWindows].filter(
          (s) => (frictionBySkill[s] ?? 0) >= threshold
        );
        if (qualifying.length === 0) return;

        const frictionSnapshot = Object.fromEntries(
          qualifying.map((s) => [s, frictionBySkill[s]])
        );

        // ── Dedupe: merge with existing marker if present ─────────────────
        const pendingDir = path.join(srHome(), "pending");
        ensureDir(pendingDir);
        const markerPath = path.join(pendingDir, `${sessionId}.json`);
        const existing = readMarkerIfExists(markerPath);

        let mergedSkills = qualifying;
        let mergedFriction = frictionSnapshot;

        if (existing && existing.sessionId === sessionId) {
          // Union skills and take the higher friction count per skill
          const allSkills = new Set([...(existing.skills ?? []), ...qualifying]);
          mergedSkills = [...allSkills];
          mergedFriction = {};
          for (const s of allSkills) {
            mergedFriction[s] = Math.max(
              existing.friction?.[s] ?? 0,
              frictionSnapshot[s] ?? 0
            );
          }
        }

        // CONTRACT §8 marker shape
        const marker = {
          sessionId,
          endedAt: new Date().toISOString(),
          skills: mergedSkills,
          friction: mergedFriction,
          reason: "complete",
        };

        atomicWrite(markerPath, marker);

        // Update throttle state
        stagingState.lastStagedAt = now;
        sessionStagingState.set(sessionId, stagingState);
      } catch {
        // Never throw into opencode
      }
    });
  },
};
