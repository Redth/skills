/**
 * skill-reflect — Amp adapter (Tier B).
 *
 * Hooks the `agent.end` event to stage a pending-review marker when a
 * distributed skill was used AND friction crossed the configured threshold.
 * Optionally emits a non-blocking nudge via an `agent.end` continue message.
 *
 * Tier B behaviour (same as opencode adapter):
 *   - Throttle: only stage once per agent-run per STAGE_INTERVAL_MS.
 *   - Dedupe: if a marker for this session already exists, update counts.
 *   - No true process-exit — marker staged on each agent.end event.
 *
 * Hard constraints (CONTRACT §§8,9):
 *   - No AI, no network calls.
 *   - Never write transcript content, values, or PII into the marker.
 *   - Always excludes skill-reflect and skill-reflect-auto.
 *   - No runtime deps beyond what Amp provides.
 *   - All paths wrap in try/catch; never throw into the host.
 *
 * # ASSUMPTION: Amp exposes an `agent.end` hook that can optionally `continue`
 * # with a follow-up message. The hook receives a context object with session id,
 * # working directory, and message/conversation history. Verify event name,
 * # payload shape, and how to emit a nudge (continue vs. log) against Amp docs.
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

function listPendingMarkers() {
  const dir = path.join(srHome(), "pending");
  if (!fs.existsSync(dir)) return [];
  try {
    return fs.readdirSync(dir)
      .filter((f) => f.endsWith(".json"))
      .map((f) => path.join(dir, f));
  } catch {
    return [];
  }
}

// ─── THROTTLE ─────────────────────────────────────────────────────────────────

function readThrottle() {
  const p = path.join(srHome(), "throttle.json");
  try {
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf-8"));
  } catch {}
  return {};
}

function writeThrottle(data) {
  ensureDir(srHome());
  atomicWrite(path.join(srHome(), "throttle.json"), data);
}

function isThrottled(throttleData, throttleHours) {
  if (!throttleHours) return false;
  const last = throttleData.lastNudgeAt;
  if (!last) return false;
  const elapsedHours = (Date.now() - new Date(last).getTime()) / (1000 * 60 * 60);
  return elapsedHours < throttleHours;
}

// ─── MESSAGE EXTRACTION ───────────────────────────────────────────────────────

/**
 * Extract skill names and friction signals from a messages/turns array.
 *
 * # ASSUMPTION: `messages` is an array of turn objects from Amp's agent.end
 * # context, each with role and content fields following Claude API conventions
 * # (or Amp's own format). Verify against Amp docs.
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
    const rawContent = msg.content ?? msg.parts ?? "";
    const blocks = typeof rawContent === "string"
      ? [{ type: "text", text: rawContent }]
      : (Array.isArray(rawContent) ? rawContent : []);

    let userText = "";

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

        // Repeated tool call
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
        userText += (blk.text ?? "") + " ";
      }
    }

    if (role === "user" && userText && skillWindows.size > 0) {
      if (CORRECTION_RE.test(userText)) addFriction();
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

const sessionStagingState = new Map();

// ─── MAIN HANDLER ─────────────────────────────────────────────────────────────

/**
 * Handle an `agent.end` event.
 *
 * # ASSUMPTION: Amp calls this function with a context object containing:
 * #   context.sessionId (or session_id) — session identifier
 * #   context.workingDirectory (or cwd) — working directory
 * #   context.messages (or turns/history) — conversation history array
 * # Returns either undefined (no nudge) or { continue: "nudge text" } to emit
 * # a follow-up message.
 * # Verify the return shape for "continue" messages against Amp docs.
 */
export async function onAgentEnd(context) {
  try {
    const sessionId =
      context?.sessionId ?? context?.session_id ?? "unknown";
    const cwd =
      context?.workingDirectory ?? context?.cwd ?? context?.working_directory ?? null;
    // # ASSUMPTION: conversation history field name
    const messages =
      context?.messages ?? context?.turns ?? context?.history ?? [];

    const cfg = loadConfig(cwd);
    if (!cfg.nudge?.enabled) return undefined;

    // ── Throttle per session ───────────────────────────────────────────────
    const stagingState = sessionStagingState.get(sessionId) ?? { lastStagedAt: 0 };
    const now = Date.now();
    if (now - stagingState.lastStagedAt < STAGE_INTERVAL_MS) return undefined;

    // ── Extract skills and friction ────────────────────────────────────────
    const { skillWindows, frictionBySkill } = extractFromMessages(messages, cfg);
    const threshold = cfg.nudge?.frictionThreshold ?? 2;

    const qualifying = [...skillWindows].filter(
      (s) => (frictionBySkill[s] ?? 0) >= threshold
    );
    if (qualifying.length === 0) return undefined;

    const frictionSnapshot = Object.fromEntries(
      qualifying.map((s) => [s, frictionBySkill[s]])
    );

    // ── Dedupe: merge with existing marker ────────────────────────────────
    const pendingDir = path.join(srHome(), "pending");
    ensureDir(pendingDir);
    const markerPath = path.join(pendingDir, `${sessionId}.json`);
    const existing = readMarkerIfExists(markerPath);

    let mergedSkills = qualifying;
    let mergedFriction = frictionSnapshot;

    if (existing && existing.sessionId === sessionId) {
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

    stagingState.lastStagedAt = now;
    sessionStagingState.set(sessionId, stagingState);

    // ── Optional nudge via agent.end continue ─────────────────────────────
    // Check global throttle before emitting nudge
    const throttleData = readThrottle();
    const throttleHours = cfg.nudge?.throttleHours ?? 12;
    if (isThrottled(throttleData, throttleHours)) return undefined;

    // Check neverForSkills
    const neverFor = new Set(cfg.nudge?.neverForSkills ?? []);
    const nudgeSkills = mergedSkills.filter((s) => !neverFor.has(s));
    if (nudgeSkills.length === 0) return undefined;

    writeThrottle({ ...throttleData, lastNudgeAt: new Date().toISOString() });

    const count = listPendingMarkers().length;
    const plural = count !== 1 ? "s" : "";
    const skillList = nudgeSkills.join(", ");

    // # ASSUMPTION: Amp's "continue" return shape for agent.end follow-up.
    // # Some platforms use { continue: "text" }, others { message: "text" }.
    // # Verify the correct shape against Amp's agent.end documentation.
    return {
      continue:
        `📋 skill-reflect: ${count} pending review${plural} for: ${skillList}. ` +
        `Say "run skill-reflect" to review (optional — never auto-runs). ` +
        `Nothing is sent anywhere without your explicit approval.`,
    };
  } catch {
    // Never throw into Amp
    return undefined;
  }
}

/**
 * Amp plugin registration.
 *
 * # ASSUMPTION: Amp discovers plugins via a default export with a `hooks`
 * # object mapping hook names to handler functions.
 * # Verify against Amp plugin/extension documentation.
 */
export default {
  name: "skill-reflect",
  version: "1.0.0",
  hooks: {
    "agent.end": onAgentEnd,
  },
};
