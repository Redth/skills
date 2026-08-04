import { createHash, randomBytes } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import {
  completeTool,
  createAttributionState,
  JOURNAL_KEY_LIMIT,
  OBSERVED_SKILL_LIMIT,
  observeSkill,
  opaqueEventKey,
  recordFrictionForLatestSkill,
  recordTool,
  toolShapeFingerprint,
} from "./attribution.mjs";

export const JOURNAL_VERSION = 1;
const MAX_CONTROL_FILE_BYTES = 128 * 1024;
const MAX_SELECTION_SESSIONS = 256;
const MAX_LOCK_ACQUIRE_ATTEMPTS = 50;
const LOCK_RETRY_DELAY_MS = 10;
const SAFE_SKILL_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$/;
const SAFE_SESSION_ID_RE = /^[A-Za-z0-9._-]{1,160}$/;
const SAFE_SELECTION_TOKEN_RE = /^[a-f0-9]{32}$/;
const SAFE_SIGNAL_RE = /^(tool_failure|tool_rejected|tool_denied|tool_timeout|tool_retry|subagent_failure|model_failure|system_error)$/;
const SESSION_END_REASONS = new Set([
  "complete",
  "error",
  "abort",
  "timeout",
  "user_exit",
  "unknown",
]);
const OVERLAP_DEDUPE_WINDOW_MS = 5_000;

function directoryStatus(directory) {
  try {
    const stat = fs.lstatSync(directory);
    return stat.isSymbolicLink() || !stat.isDirectory() ? "invalid" : "ok";
  } catch (error) {
    return error?.code === "ENOENT" ? "missing" : "invalid";
  }
}

function ensureSafeDirectory(directory) {
  if (directoryStatus(directory) === "missing") {
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  }
  if (directoryStatus(directory) !== "ok") {
    throw new Error("unsafe control directory");
  }
}

function controlDirectory(home, name, { create = false } = {}) {
  if (create) {
    ensureSafeDirectory(home);
  } else if (directoryStatus(home) !== "ok") {
    return null;
  }

  const directory = path.join(home, name);
  if (create) {
    ensureSafeDirectory(directory);
    return directory;
  }
  return directoryStatus(directory) === "ok" ? directory : null;
}

function atomicWrite(filePath, data) {
  const temporary =
    `${filePath}.tmp.${process.pid}.` + randomBytes(8).toString("hex");
  let descriptor = null;
  try {
    const noFollow = fs.constants.O_NOFOLLOW ?? 0;
    descriptor = fs.openSync(
      temporary,
      fs.constants.O_WRONLY |
        fs.constants.O_CREAT |
        fs.constants.O_EXCL |
        noFollow,
      0o600
    );
    fs.writeFileSync(descriptor, JSON.stringify(data, null, 2), "utf-8");
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = null;
    fs.renameSync(temporary, filePath);
  } catch (error) {
    if (descriptor !== null) {
      try {
        fs.closeSync(descriptor);
      } catch {}
    }
    try {
      fs.unlinkSync(temporary);
    } catch {}
    throw error;
  }
}

function atomicCreate(filePath, data) {
  const temporary =
    `${filePath}.tmp.${process.pid}.` + randomBytes(8).toString("hex");
  let descriptor = null;
  try {
    const noFollow = fs.constants.O_NOFOLLOW ?? 0;
    descriptor = fs.openSync(
      temporary,
      fs.constants.O_WRONLY |
        fs.constants.O_CREAT |
        fs.constants.O_EXCL |
        noFollow,
      0o600
    );
    fs.writeFileSync(descriptor, JSON.stringify(data), "utf-8");
    fs.fsyncSync(descriptor);
    fs.closeSync(descriptor);
    descriptor = null;
    fs.linkSync(temporary, filePath);
    fs.unlinkSync(temporary);
    return true;
  } catch {
    if (descriptor !== null) {
      try {
        fs.closeSync(descriptor);
      } catch {}
    }
    try {
      fs.unlinkSync(temporary);
    } catch {}
    return false;
  }
}

function readSmallJson(filePath) {
  try {
    const stat = fs.lstatSync(filePath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_CONTROL_FILE_BYTES) {
      return null;
    }
    return JSON.parse(fs.readFileSync(filePath, "utf-8"));
  } catch {
    return null;
  }
}

function controlFileDigest(filePath) {
  try {
    const stat = fs.lstatSync(filePath);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > MAX_CONTROL_FILE_BYTES) {
      return null;
    }
    return createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  } catch {
    return null;
  }
}

function toIso(value) {
  const date = new Date(value);
  return Number.isFinite(date.getTime()) ? date.toISOString() : new Date().toISOString();
}

function normalizeSessionEndReason(reason) {
  return SESSION_END_REASONS.has(reason) ? reason : "unknown";
}

function fromIso(value, fallback = 0) {
  const parsed = Date.parse(String(value ?? ""));
  return Number.isFinite(parsed) ? parsed : fallback;
}

function safeNonNegativeInteger(value, fallback = 0) {
  return Number.isSafeInteger(value) && value >= 0 ? value : fallback;
}

function safeSkillName(value) {
  const candidate = String(value ?? "").trim();
  return SAFE_SKILL_NAME_RE.test(candidate) ? candidate : null;
}

function diagnostic(callback, step, fields = {}) {
  try {
    callback?.({ step, ...fields });
  } catch {
    // Diagnostics are observational and must never affect capture.
  }
}

export function journalPath(home, sessionId) {
  return path.join(home, "journal", `${sessionId}.json`);
}

function activeSessionPath(home, sessionId) {
  return path.join(home, "active", `${sessionId}.json`);
}

function writeReviewSelection(home, markers, now) {
  const token = randomBytes(16).toString("hex");
  const directory = controlDirectory(home, "selections", { create: true });
  atomicWrite(path.join(directory, `${token}.json`), {
    version: 1,
    token,
    createdAt: toIso(now),
    markers,
  });
  return token;
}

function processIsAlive(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

function readSessionLock(lockPath, sessionId) {
  const document = readSmallJson(lockPath);
  if (
    !document ||
    document.version !== 1 ||
    document.sessionId !== sessionId ||
    !Number.isInteger(document.pid) ||
    document.pid <= 0 ||
    typeof document.token !== "string" ||
    !SAFE_SELECTION_TOKEN_RE.test(document.token) ||
    typeof document.choosing !== "boolean" ||
    !Number.isSafeInteger(document.number) ||
    document.number < 0
  ) {
    return null;
  }
  return document;
}

function listSessionLockClaims(locksDirectory, sessionId) {
  let entries;
  try {
    entries = fs.readdirSync(locksDirectory, { withFileTypes: true });
  } catch {
    return null;
  }
  const prefix = `${sessionId}.`;
  const claims = [];
  for (const entry of entries) {
    if (!entry.name.startsWith(prefix) || !entry.name.endsWith(".json")) {
      continue;
    }
    if (!entry.isFile() || entry.isSymbolicLink()) return null;
    const lockPath = path.join(locksDirectory, entry.name);
    const claim = readSessionLock(lockPath, sessionId);
    if (
      !claim ||
      entry.name !==
        `${sessionId}.${claim.pid}.${claim.token}.json`
    ) {
      return null;
    }
    if (!processIsAlive(claim.pid)) {
      try {
        fs.unlinkSync(lockPath);
      } catch {}
      continue;
    }
    claims.push({ ...claim, lockPath });
  }
  return claims;
}

function abandonSessionLock(lock) {
  if (!lock) return;
  const owner = readSessionLock(lock.lockPath, lock.sessionId);
  if (owner?.token !== lock.token) return;
  try {
    fs.unlinkSync(lock.lockPath);
  } catch {}
}

function acquireSessionLock(home, sessionId) {
  if (!SAFE_SESSION_ID_RE.test(sessionId)) return null;
  const locksDirectory = controlDirectory(home, "locks", { create: true });
  const token = randomBytes(16).toString("hex");
  const lockPath = path.join(
    locksDirectory,
    `${sessionId}.${process.pid}.${token}.json`
  );
  const lock = { lockPath, sessionId, token };
  if (
    !atomicCreate(lockPath, {
      version: 1,
      sessionId,
      pid: process.pid,
      token,
      choosing: true,
      number: 0,
    })
  ) {
    return null;
  }

  const claims = listSessionLockClaims(locksDirectory, sessionId);
  if (claims === null) {
    abandonSessionLock(lock);
    return null;
  }
  const maxNumber = claims.reduce(
    (maximum, claim) => Math.max(maximum, claim.number),
    0
  );
  if (!Number.isSafeInteger(maxNumber + 1)) {
    abandonSessionLock(lock);
    return null;
  }
  const number = maxNumber + 1;
  try {
    atomicWrite(lockPath, {
      version: 1,
      sessionId,
      pid: process.pid,
      token,
      choosing: false,
      number,
    });
  } catch {
    abandonSessionLock(lock);
    return null;
  }

  for (let attempt = 0; attempt < MAX_LOCK_ACQUIRE_ATTEMPTS; attempt += 1) {
    const currentClaims = listSessionLockClaims(locksDirectory, sessionId);
    const owner = readSessionLock(lockPath, sessionId);
    if (
      currentClaims === null ||
      owner?.token !== token ||
      owner.number !== number ||
      owner.choosing
    ) {
      abandonSessionLock(lock);
      return null;
    }
    const blocked = currentClaims.some(
      (claim) =>
        claim.token !== token &&
        (claim.choosing ||
          (claim.number > 0 &&
            (claim.number < number ||
              (claim.number === number && claim.token < token))))
    );
    if (!blocked) return { ...lock, number };
    Atomics.wait(
      new Int32Array(new SharedArrayBuffer(4)),
      0,
      0,
      LOCK_RETRY_DELAY_MS
    );
  }
  abandonSessionLock(lock);
  return null;
}

function releaseSessionLock(lock) {
  abandonSessionLock(lock);
}

function withSessionLock(home, sessionId, callback) {
  const lock = acquireSessionLock(home, sessionId);
  if (!lock) return { acquired: false, value: null };
  try {
    const owner = readSessionLock(lock.lockPath, sessionId);
    if (
      owner?.token !== lock.token ||
      owner.number !== lock.number ||
      owner.choosing
    ) {
      return { acquired: false, value: null };
    }
    return { acquired: true, value: callback() };
  } finally {
    releaseSessionLock(lock);
  }
}

function liveSessionIds(home) {
  const activeDirectory = path.join(home, "active");
  const status = directoryStatus(activeDirectory);
  if (status === "missing") return new Set();
  if (status !== "ok") return null;
  const directory = activeDirectory;
  const live = new Set();
  let entries;
  try {
    entries = fs.readdirSync(directory, { withFileTypes: true });
  } catch {
    return live;
  }
  for (const entry of entries) {
    if (!entry.isFile() || entry.isSymbolicLink() || !entry.name.endsWith(".json")) {
      return null;
    }
    const sessionId = entry.name.slice(0, -5);
    if (!SAFE_SESSION_ID_RE.test(sessionId)) return null;
    const active = readSmallJson(path.join(directory, entry.name));
    if (
      active?.version !== 1 ||
      active.sessionId !== sessionId ||
      !Number.isInteger(active.pid) ||
      active.pid <= 0
    ) {
      return null;
    }
    if (processIsAlive(active.pid)) {
      live.add(sessionId);
    }
  }
  return live;
}

function readPendingMarker(markerPath) {
  const filename = path.basename(markerPath);
  if (!filename.endsWith(".json")) return null;
  const sessionId = filename.slice(0, -5);
  if (
    sessionId === "." ||
    sessionId === ".." ||
    !SAFE_SESSION_ID_RE.test(sessionId)
  ) {
    return null;
  }
  const marker = readSmallJson(markerPath);
  if (
    !marker ||
    typeof marker !== "object" ||
    Array.isArray(marker) ||
    marker.sessionId !== sessionId ||
    !Array.isArray(marker.skills)
  ) {
    return null;
  }
  return marker;
}

function serializeState(engine, now) {
  const friction = {};
  for (const skill of [...engine.state.observedSkills].sort()) {
    const count = engine.state.frictionBySkill.get(skill) ?? 0;
    const signalMap = engine.state.signalsBySkill.get(skill) ?? new Map();
    friction[skill] = {
      count,
      signals: Object.fromEntries(
        [...signalMap.entries()]
          .filter(([signal, value]) => SAFE_SIGNAL_RE.test(signal) && value > 0)
          .sort(([left], [right]) => left.localeCompare(right))
      ),
    };
  }

  const inFlightTools = Object.fromEntries(
    [...engine.state.inFlightTools.entries()].map(([callKey, tool]) => [
      callKey,
      {
        shape: tool.shape,
        skillContext: tool.skillContext
          ? {
              name: tool.skillContext.name,
              toolSequence: tool.skillContext.toolSequence,
              observedAt: toIso(tool.skillContext.observedAt),
            }
          : null,
        toolSequence: tool.toolSequence,
        startedAt: toIso(tool.startedAt),
      },
    ])
  );
  const serializeUnmatched = (entry) => ({
    key: entry.key,
    ...(entry.signal ? { signal: entry.signal } : {}),
    ...(entry.shape ? { shape: entry.shape } : {}),
    skillContext: {
      name: entry.skillContext.name,
      toolSequence: entry.skillContext.toolSequence,
      observedAt: toIso(entry.skillContext.observedAt),
    },
    toolSequence: entry.toolSequence,
    observedAt: toIso(entry.observedAt),
  });

  return {
    version: JOURNAL_VERSION,
    sessionId: engine.sessionId,
    createdAt: engine.createdAt,
    updatedAt: toIso(now),
    capturePolicy: {
      frictionThreshold: engine.threshold,
    },
    ...(engine.endedAt ? { endedAt: engine.endedAt, reason: engine.endReason } : {}),
    toolSequence: engine.state.toolSequence,
    observedSkills: [...engine.state.observedSkills].sort(),
    latestSkill: engine.state.latestSkill
      ? {
          name: engine.state.latestSkill.name,
          toolSequence: engine.state.latestSkill.toolSequence,
          observedAt: toIso(engine.state.latestSkill.observedAt),
        }
      : null,
    friction,
    capture: {
      seenFrictionKeys: [...engine.state.seenFrictionKeys],
      inFlightTools,
      unmatchedToolOutcomes:
        engine.state.unmatchedToolOutcomes.map(serializeUnmatched),
      unmatchedFailureHooks:
        engine.state.unmatchedFailureHooks.map(serializeUnmatched),
      lastFailedTool: engine.state.lastFailedTool
        ? {
            shape: engine.state.lastFailedTool.shape,
            key: engine.state.lastFailedTool.key,
            skillContext: engine.state.lastFailedTool.skillContext
              ? {
                  name: engine.state.lastFailedTool.skillContext.name,
                  toolSequence:
                    engine.state.lastFailedTool.skillContext.toolSequence,
                  observedAt: toIso(
                    engine.state.lastFailedTool.skillContext.observedAt
                  ),
                }
              : null,
            toolSequence: engine.state.lastFailedTool.toolSequence,
            observedAt: toIso(engine.state.lastFailedTool.observedAt),
          }
        : null,
    },
  };
}

function restoreSkillContext(rawContext, state) {
  const name = safeSkillName(rawContext?.name);
  if (!name || !state.observedSkills.has(name)) return null;
  return {
    name,
    toolSequence: safeNonNegativeInteger(rawContext.toolSequence),
    observedAt: fromIso(rawContext.observedAt),
  };
}

function normalizeThreshold(value, fallback = 2) {
  return Number.isInteger(value) && value >= 1 ? value : fallback;
}

function restoreState(document, sessionId, fallbackThreshold = 2) {
  if (
    !document ||
    document.version !== JOURNAL_VERSION ||
    document.sessionId !== sessionId
  ) {
    return null;
  }

  const state = createAttributionState();
  state.toolSequence = safeNonNegativeInteger(document.toolSequence);

  for (const rawSkill of document.observedSkills ?? []) {
    const skill = safeSkillName(rawSkill);
    if (skill && state.observedSkills.size < OBSERVED_SKILL_LIMIT) {
      state.observedSkills.add(skill);
    }
  }

  const latest = document.latestSkill;
  const latestName = safeSkillName(latest?.name);
  if (latestName) {
    if (!state.observedSkills.has(latestName)) {
      if (state.observedSkills.size >= OBSERVED_SKILL_LIMIT) {
        state.observedSkills.delete(state.observedSkills.values().next().value);
      }
      state.observedSkills.add(latestName);
    }
    state.latestSkill = {
      name: latestName,
      toolSequence: safeNonNegativeInteger(latest.toolSequence),
      observedAt: fromIso(latest.observedAt),
    };
  }

  for (const [rawSkill, rawEntry] of Object.entries(document.friction ?? {})) {
    const skill = safeSkillName(rawSkill);
    if (!skill || !state.observedSkills.has(skill) || !rawEntry || typeof rawEntry !== "object") {
      continue;
    }
    const count = safeNonNegativeInteger(rawEntry.count);
    const signals = new Map();
    for (const [signal, rawCount] of Object.entries(rawEntry.signals ?? {})) {
      const signalCount = safeNonNegativeInteger(rawCount);
      if (SAFE_SIGNAL_RE.test(signal) && signalCount > 0) {
        signals.set(signal, signalCount);
      }
    }
    const signalTotal = [...signals.values()].reduce(
      (sum, signalCount) => sum + signalCount,
      0
    );
    if (signalTotal !== count) continue;
    state.frictionBySkill.set(skill, count);
    state.signalsBySkill.set(skill, signals);
  }

  for (const rawKey of document.capture?.seenFrictionKeys ?? []) {
    const key = String(rawKey ?? "");
    if (key.length > 0 && key.length <= 100) state.seenFrictionKeys.add(key);
  }

  for (const [rawKey, rawTool] of Object.entries(document.capture?.inFlightTools ?? {})) {
    const callKey = String(rawKey ?? "");
    const shape = String(rawTool?.shape ?? "");
    if (!/^[a-f0-9]{24}$/.test(callKey) || !/^[a-f0-9]{24}$/.test(shape)) continue;
    state.inFlightTools.set(callKey, {
      shape,
      skillContext: restoreSkillContext(rawTool.skillContext, state),
      toolSequence: safeNonNegativeInteger(rawTool.toolSequence),
      startedAt: fromIso(rawTool.startedAt),
    });
  }

  const failed = document.capture?.lastFailedTool;
  if (/^[a-f0-9]{24}$/.test(String(failed?.shape ?? ""))) {
    state.lastFailedTool = {
      shape: failed.shape,
      key:
        typeof failed.key === "string" && failed.key.length <= 100
          ? failed.key
          : null,
      skillContext: restoreSkillContext(failed.skillContext, state),
      toolSequence: safeNonNegativeInteger(failed.toolSequence),
      observedAt: fromIso(failed.observedAt),
    };
  }

  const restoreUnmatched = (rawEntry, { requireSignal, requireShape }) => {
    const key = String(rawEntry?.key ?? "");
    const signal = String(rawEntry?.signal ?? "");
    const shape = String(rawEntry?.shape ?? "");
    const skillContext = restoreSkillContext(rawEntry?.skillContext, state);
    const observedAt = fromIso(rawEntry?.observedAt, Number.NaN);
    if (
      !key ||
      key.length > 100 ||
      (requireSignal && !SAFE_SIGNAL_RE.test(signal)) ||
      (requireShape && !/^[a-f0-9]{24}$/.test(shape)) ||
      !skillContext ||
      !Number.isFinite(observedAt)
    ) {
      return null;
    }
    return {
      key,
      ...(requireSignal ? { signal } : {}),
      ...(requireShape ? { shape } : {}),
      skillContext,
      toolSequence: safeNonNegativeInteger(rawEntry.toolSequence),
      observedAt,
    };
  };
  const rawUnmatchedOutcomes = Array.isArray(
    document.capture?.unmatchedToolOutcomes
  )
    ? document.capture.unmatchedToolOutcomes
    : [];
  for (const rawEntry of rawUnmatchedOutcomes.slice(-JOURNAL_KEY_LIMIT)) {
    const entry = restoreUnmatched(rawEntry, {
      requireSignal: true,
      requireShape: false,
    });
    if (entry) state.unmatchedToolOutcomes.push(entry);
  }
  const rawUnmatchedHooks = Array.isArray(
    document.capture?.unmatchedFailureHooks
  )
    ? document.capture.unmatchedFailureHooks
    : [];
  for (const rawEntry of rawUnmatchedHooks.slice(-JOURNAL_KEY_LIMIT)) {
    const entry = restoreUnmatched(rawEntry, {
      requireSignal: false,
      requireShape: true,
    });
    if (entry) state.unmatchedFailureHooks.push(entry);
  }

  return {
    state,
    createdAt: toIso(document.createdAt),
    endedAt: document.endedAt ? toIso(document.endedAt) : null,
    endReason: document.endedAt
      ? normalizeSessionEndReason(document.reason)
      : null,
    threshold: normalizeThreshold(
      document.capturePolicy?.frictionThreshold,
      fallbackThreshold
    ),
  };
}

export function classifyToolFailure(data = {}) {
  const raw = String(data.resultType ?? data.error?.code ?? "").toLowerCase();
  if (raw.includes("timeout") || raw.includes("timed_out")) return "tool_timeout";
  if (raw.includes("reject")) return "tool_rejected";
  if (raw.includes("denied") || raw.includes("permission")) return "tool_denied";
  return "tool_failure";
}

export class CaptureEngine {
  constructor({
    home,
    sessionId,
    threshold = 2,
    isInScope = () => true,
    diagnostics = false,
    onDiagnostic = null,
    now = () => Date.now(),
  }) {
    this.home = home;
    this.sessionId = sessionId;
    this.threshold = normalizeThreshold(threshold);
    this.isInScope = isInScope;
    this.diagnostics = diagnostics;
    this.onDiagnostic = onDiagnostic;
    this.now = now;
    this.endedAt = null;
    this.endReason = null;

    const initialized = withSessionLock(home, sessionId, () => {
      const journalDirectory = controlDirectory(home, "journal");
      const restored = restoreState(
        journalDirectory
          ? readSmallJson(path.join(journalDirectory, `${sessionId}.json`))
          : null,
        sessionId,
        this.threshold
      );
      if (restored) {
        this.state = restored.state;
        this.createdAt = restored.createdAt;
        this.endedAt = restored.endedAt;
        this.endReason = restored.endReason;
        this.threshold = restored.threshold;
        this.#diagnostic("journal_restored", {
          skills: this.state.observedSkills.size,
          friction: [...this.state.frictionBySkill.values()].reduce(
            (sum, count) => sum + count,
            0
          ),
        });
      } else {
        this.state = createAttributionState();
        this.createdAt = toIso(this.now());
      }
      this.#activate();
    });
    if (!initialized.acquired) {
      throw new Error("session capture lock unavailable");
    }
  }

  #activate() {
    const directory = controlDirectory(this.home, "active", { create: true });
    atomicWrite(path.join(directory, `${this.sessionId}.json`), {
      version: 1,
      sessionId: this.sessionId,
      pid: process.pid,
      updatedAt: toIso(this.now()),
    });
  }

  #releaseActiveUnlocked() {
    const directory = controlDirectory(this.home, "active");
    if (!directory) return;
    const filePath = activeSessionPath(this.home, this.sessionId);
    const active = readSmallJson(filePath);
    if (
      active?.version !== 1 ||
      active.sessionId !== this.sessionId ||
      active.pid !== process.pid
    ) {
      return;
    }
    try {
      fs.unlinkSync(filePath);
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }

  releaseActive() {
    return withSessionLock(this.home, this.sessionId, () =>
      this.#releaseActiveUnlocked()
    ).acquired;
  }

  #diagnostic(step, fields = {}) {
    if (this.diagnostics) diagnostic(this.onDiagnostic, step, fields);
  }

  #persist(cause, announce = false) {
    // Do not create journals for sessions that never observed an in-scope skill.
    if (this.state.observedSkills.size === 0) return false;
    const now = this.now();
    const directory = controlDirectory(this.home, "journal", { create: true });
    atomicWrite(
      path.join(directory, `${this.sessionId}.json`),
      serializeState(this, now)
    );
    if (announce) {
      this.#diagnostic("journal_persisted", {
        cause,
        skills: this.state.observedSkills.size,
        friction: [...this.state.frictionBySkill.values()].reduce((sum, count) => sum + count, 0),
      });
    }
    return true;
  }

  #observeSkill(skillName, source, persist = true) {
    const skill = safeSkillName(skillName);
    if (!skill || !this.isInScope(skill)) return false;
    const changed = observeSkill(this.state, skill, this.now());
    if (!changed) return false;
    this.#diagnostic("skill_observed", { skill, source });
    if (persist) this.#persist("skill_observed", true);
    return true;
  }

  observeSkill(skillName, source = "skill.invoked") {
    return this.#observeSkill(skillName, source, true);
  }

  #recordFriction({
    signal,
    key,
    failedToolShape = null,
    skillContext = undefined,
    source,
  }) {
    const result = recordFrictionForLatestSkill(this.state, {
      now: this.now(),
      signal,
      key,
      failedToolShape,
      skillContext,
    });
    this.#diagnostic("failure_observed", {
      signal,
      source,
      attributed: result.attributed,
      ...(result.attributed ? { skill: result.skill, count: result.count } : { reason: result.reason }),
    });
    return result;
  }

  #takeRecentUnmatched(queue, now) {
    const recent = queue.filter((entry) => {
      const elapsed = now - entry.observedAt;
      return elapsed >= 0 && elapsed <= OVERLAP_DEDUPE_WINDOW_MS;
    });
    queue.splice(0, queue.length, ...recent);
    return queue.shift() ?? null;
  }

  #rememberUnmatched(queue, entry) {
    queue.push(entry);
    if (queue.length > JOURNAL_KEY_LIMIT) {
      queue.splice(0, queue.length - JOURNAL_KEY_LIMIT);
    }
  }

  startTool({ toolCallId, toolName, toolArgs }) {
    const now = this.now();
    const callKey = opaqueEventKey(toolCallId);
    const shape = toolShapeFingerprint(toolName, toolArgs);
    const retry = recordTool(this.state, {
      callKey,
      shape,
      skillContext: this.state.latestSkill,
      now,
    });

    let observed = false;
    if (toolName === "skill" && toolArgs && typeof toolArgs === "object") {
      const skillName = String(toolArgs.skill ?? "").trim();
      if (
        this.state.latestSkill?.name === skillName &&
        this.state.latestSkill.toolSequence === this.state.toolSequence - 1
      ) {
        this.state.latestSkill.toolSequence = this.state.toolSequence;
        this.state.latestSkill.observedAt = now;
      } else {
        observed = this.#observeSkill(skillName, "tool.execution_start", false);
      }
    }
    if (
      callKey &&
      toolName === "skill" &&
      this.state.latestSkill?.name ===
        String(toolArgs?.skill ?? "").trim()
    ) {
      const tool = this.state.inFlightTools.get(callKey);
      if (tool) tool.skillContext = { ...this.state.latestSkill };
    }

    let retryResult = null;
    if (retry) {
      retryResult = this.#recordFriction({
        signal: retry.signal,
        key: retry.key,
        skillContext: retry.skillContext,
        source: "tool.execution_start",
      });
    }

    this.#persist(
      retryResult?.attributed ? "tool_retry" : observed ? "skill_observed" : "tool_start",
      Boolean(observed || retryResult?.attributed)
    );
    return { callKey, observed, retry: retryResult };
  }

  completeTool({ toolCallId, success, resultType, error }) {
    const callKey = opaqueEventKey(toolCallId);
    const tool = completeTool(this.state, callKey);
    let result = null;
    if (success === false) {
      const observedAt = this.now();
      const unmatchedHook = tool
        ? null
        : this.#takeRecentUnmatched(
            this.state.unmatchedFailureHooks,
            observedAt
          );
      const signal = classifyToolFailure({ resultType, error });
      const skillContext =
        unmatchedHook?.skillContext ??
        (this.state.latestSkill ? { ...this.state.latestSkill } : null);
      const key =
        unmatchedHook?.key ??
        `tool:${callKey ?? `sequence-${this.state.toolSequence}`}`;
      result = this.#recordFriction({
        signal,
        key,
        failedToolShape: tool?.shape ?? unmatchedHook?.shape ?? null,
        ...(tool
          ? { skillContext: tool.skillContext }
          : skillContext
            ? { skillContext }
            : {}),
        source: "tool.execution_complete",
      });
      if (!tool && !unmatchedHook && result.attributed && skillContext) {
        this.#rememberUnmatched(this.state.unmatchedToolOutcomes, {
          key,
          signal,
          skillContext,
          toolSequence: this.state.toolSequence,
          observedAt,
        });
      }
    }
    this.#persist(success === false ? "tool_failure" : "tool_complete", success === false);
    return result;
  }

  recordFailureHook({ toolName, toolArgs }) {
    const shape = toolShapeFingerprint(toolName, toolArgs);
    const recentFailed =
      this.state.lastFailedTool?.shape === shape &&
      this.state.lastFailedTool.key &&
      this.now() - this.state.lastFailedTool.observedAt >= 0 &&
      this.now() - this.state.lastFailedTool.observedAt <=
        OVERLAP_DEDUPE_WINDOW_MS
        ? this.state.lastFailedTool
        : null;
    if (recentFailed) {
      const result = this.#recordFriction({
        signal: "tool_failure",
        key: recentFailed.key,
        failedToolShape: recentFailed.shape,
        skillContext: recentFailed.skillContext,
        source: "onPostToolUseFailure",
      });
      this.#persist("tool_failure", result.attributed);
      return result;
    }
    const matches = [];
    for (const [callKey, tool] of this.state.inFlightTools) {
      if (tool.shape === shape) matches.push({ callKey, tool });
    }
    const observedAt = this.now();
    const unmatchedOutcome = this.#takeRecentUnmatched(
      this.state.unmatchedToolOutcomes,
      observedAt
    );
    if (!unmatchedOutcome && matches.length > 1) {
      const result = {
        attributed: false,
        reason: "ambiguous_tool",
        signal: "tool_failure",
      };
      this.#diagnostic("failure_observed", {
        signal: result.signal,
        source: "onPostToolUseFailure",
        attributed: false,
        reason: result.reason,
      });
      return result;
    }
    const matching = unmatchedOutcome ? null : (matches[0] ?? null);
    const signal = unmatchedOutcome?.signal ?? "tool_failure";
    const key =
      unmatchedOutcome?.key ??
      (matching
        ? `tool:${matching.callKey}`
        : `tool-fallback:${this.state.toolSequence}:${shape}`);
    const skillContext =
      matching?.tool.skillContext ??
      unmatchedOutcome?.skillContext ??
      (this.state.latestSkill ? { ...this.state.latestSkill } : null);
    const result = this.#recordFriction({
      signal,
      key,
      failedToolShape: matching?.tool.shape ?? shape,
      ...(skillContext ? { skillContext } : {}),
      source: "onPostToolUseFailure",
    });
    if (unmatchedOutcome && result.reason === "duplicate") {
      this.state.lastFailedTool = {
        shape,
        key,
        skillContext: { ...unmatchedOutcome.skillContext },
        toolSequence: unmatchedOutcome.toolSequence,
        observedAt: unmatchedOutcome.observedAt,
      };
    } else if (!matching && !unmatchedOutcome && result.attributed && skillContext) {
      this.#rememberUnmatched(this.state.unmatchedFailureHooks, {
        key,
        shape,
        skillContext,
        toolSequence: this.state.toolSequence,
        observedAt,
      });
    }
    this.#persist("tool_failure", result.attributed);
    return result;
  }

  recordSubagentFailure({ toolCallId }) {
    const callKey = opaqueEventKey(toolCallId);
    const tool = callKey ? this.state.inFlightTools.get(callKey) : null;
    const result = this.#recordFriction({
      signal: "subagent_failure",
      key: `tool:${callKey ?? `subagent-${this.state.toolSequence}`}`,
      failedToolShape: tool?.shape ?? null,
      ...(tool ? { skillContext: tool.skillContext } : {}),
      source: "subagent.failed",
    });
    this.#persist("subagent_failure", result.attributed);
    return result;
  }

  recordSystemError({ errorContext, timestamp }) {
    if (
      errorContext !== "model_call" &&
      errorContext !== "tool_execution" &&
      errorContext !== "system"
    ) {
      return {
        attributed: false,
        reason: "ignored_context",
        signal: null,
      };
    }
    const observedAt = fromIso(timestamp, this.now());
    const recentFailed =
      this.state.lastFailedTool &&
      Math.abs(observedAt - this.state.lastFailedTool.observedAt) <=
        OVERLAP_DEDUPE_WINDOW_MS
        ? this.state.lastFailedTool
        : null;
    const signal =
      errorContext === "model_call"
        ? "model_failure"
        : errorContext === "tool_execution"
          ? "tool_failure"
          : "system_error";
    const inFlight = [...this.state.inFlightTools.entries()].map(
      ([callKey, tool]) => ({ callKey, tool })
    );
    if (
      errorContext === "tool_execution" &&
      (inFlight.length > 1 || (inFlight.length === 1 && recentFailed))
    ) {
      const result = {
        attributed: false,
        reason: "ambiguous_tool",
        signal,
      };
      this.#diagnostic("failure_observed", {
        signal,
        source: "onErrorOccurred",
        attributed: false,
        reason: result.reason,
      });
      return result;
    }
    const latest =
      errorContext === "tool_execution" && inFlight.length === 1
        ? { callKey: inFlight[0].callKey, tool: inFlight[0].tool }
        : null;
    const fallbackKey = opaqueEventKey(
      `${errorContext}:${toIso(observedAt)}`
    );
    const key =
      errorContext === "tool_execution" && latest
        ? `tool:${latest.callKey}`
        : errorContext === "tool_execution" && recentFailed?.key
          ? recentFailed.key
          : `${signal}:${fallbackKey}`;
    const result = this.#recordFriction({
      signal,
      key,
      failedToolShape:
        latest?.tool.shape ??
        (errorContext === "tool_execution" ? recentFailed?.shape : null),
      ...(errorContext === "tool_execution" && latest
        ? { skillContext: latest.tool.skillContext }
        : errorContext === "tool_execution" && recentFailed
          ? { skillContext: recentFailed.skillContext }
          : {}),
      source: "onErrorOccurred",
    });
    this.#persist(signal, result.attributed);
    return result;
  }

  finalize(reason = "complete") {
    const finalized = withSessionLock(this.home, this.sessionId, () => {
      try {
        this.endedAt = toIso(this.now());
        this.endReason = normalizeSessionEndReason(reason);
        this.#persist("session_end", true);

        const qualifyingSkills = [...this.state.observedSkills]
          .filter(
            (skill) =>
              (this.state.frictionBySkill.get(skill) ?? 0) >= this.threshold
          )
          .sort();

        if (qualifyingSkills.length === 0) {
          this.#diagnostic("marker_skipped", {
            reason: "below_threshold",
            threshold: this.threshold,
          });
          return null;
        }

        const marker = {
          sessionId: this.sessionId,
          endedAt: this.endedAt,
          skills: qualifyingSkills,
          friction: Object.fromEntries(
            qualifyingSkills.map((skill) => [
              skill,
              this.state.frictionBySkill.get(skill) ?? 0,
            ])
          ),
          reason: this.endReason,
          candidate: true,
          journalVersion: JOURNAL_VERSION,
        };
        const pendingDirectory = controlDirectory(this.home, "pending", {
          create: true,
        });
        atomicWrite(
          path.join(pendingDirectory, `${this.sessionId}.json`),
          marker
        );
        this.#diagnostic("marker_written", {
          skills: qualifyingSkills,
          threshold: this.threshold,
        });
        return marker;
      } finally {
        this.#releaseActiveUnlocked();
      }
    });
    if (!finalized.acquired) {
      this.#diagnostic("marker_skipped", {
        reason: "session_lock_unavailable",
      });
      return null;
    }
    return finalized.value;
  }
}

export function listPendingMarkers(home) {
  const directory = controlDirectory(home, "pending");
  if (!directory) return [];
  try {
    return fs
      .readdirSync(directory, { withFileTypes: true })
      .filter((entry) => entry.isFile() && !entry.isSymbolicLink() && entry.name.endsWith(".json"))
      .map((entry) => path.join(directory, entry.name))
      .sort();
  } catch {
    return [];
  }
}

export function recoverPendingMarkers({
  home,
  now = Date.now(),
  onDiagnostic = null,
}) {
  const journalDirectory = controlDirectory(home, "journal");
  if (!journalDirectory) return 0;
  const live = liveSessionIds(home);
  if (live === null) return 0;
  let entries;
  try {
    entries = fs.readdirSync(journalDirectory, { withFileTypes: true });
  } catch {
    return 0;
  }

  let recovered = 0;
  for (const entry of entries) {
    if (!entry.isFile() || entry.isSymbolicLink() || !entry.name.endsWith(".json")) {
      continue;
    }
    const sessionId = entry.name.slice(0, -5);
    if (!SAFE_SESSION_ID_RE.test(sessionId) || live.has(sessionId)) continue;
    const recovery = withSessionLock(home, sessionId, () => {
      const currentLive = liveSessionIds(home);
      if (currentLive === null || currentLive.has(sessionId)) return false;
      const journal = readSmallJson(path.join(journalDirectory, entry.name));
      const restored = restoreState(journal, sessionId);
      if (!restored) return false;
      const qualifyingSkills = [...restored.state.observedSkills]
        .filter(
          (skill) =>
            (restored.state.frictionBySkill.get(skill) ?? 0) >=
            restored.threshold
        )
        .sort();
      if (qualifyingSkills.length === 0) return false;

      const pendingDirectory = controlDirectory(home, "pending", {
        create: true,
      });
      const markerPath = path.join(pendingDirectory, entry.name);
      if (fs.existsSync(markerPath)) return false;
      const marker = {
        sessionId,
        endedAt: restored.endedAt ?? toIso(journal.updatedAt ?? now),
        skills: qualifyingSkills,
        friction: Object.fromEntries(
          qualifyingSkills.map((skill) => [
            skill,
            restored.state.frictionBySkill.get(skill) ?? 0,
          ])
        ),
        reason: restored.endReason ?? "unknown",
        candidate: true,
        journalVersion: JOURNAL_VERSION,
      };
      atomicWrite(markerPath, marker);
      diagnostic(onDiagnostic, "marker_written", {
        skills: qualifyingSkills,
        threshold: restored.threshold,
        source: "journal_recovery",
      });
      return true;
    });
    if (recovery.acquired && recovery.value) recovered += 1;
  }
  return recovered;
}

function readThrottle(home) {
  if (directoryStatus(home) !== "ok") return {};
  return readSmallJson(path.join(home, "throttle.json")) ?? {};
}

function isThrottled(throttle, throttleHours, now) {
  if (!throttleHours) return false;
  const previous = fromIso(throttle.lastNudgeAt, Number.NaN);
  return Number.isFinite(previous) && now - previous < throttleHours * 60 * 60 * 1000;
}

export async function showPendingNudge({
  home,
  nudge,
  session,
  now = Date.now(),
  onDiagnostic = null,
  excludeSessionId = null,
}) {
  if (!nudge.enabled) {
    diagnostic(onDiagnostic, "nudge_suppressed", { reason: "disabled" });
    return null;
  }

  const markerPaths = listPendingMarkers(home);
  if (markerPaths.length === 0) {
    diagnostic(onDiagnostic, "nudge_suppressed", { reason: "no_pending_markers" });
    return null;
  }
  const live = liveSessionIds(home);
  if (live === null) {
    diagnostic(onDiagnostic, "nudge_suppressed", {
      reason: "unsafe_active_state",
    });
    return null;
  }

  const pendingSkills = new Set();
  const selectedMarkers = [];
  let count = 0;
  for (const markerPath of markerPaths) {
    if (
      excludeSessionId &&
      path.basename(markerPath, ".json") === excludeSessionId
    ) {
      continue;
    }
    const marker = readPendingMarker(markerPath);
    if (!marker || live.has(marker.sessionId)) continue;
    const markerSkills = new Set();
    for (const rawSkill of marker?.skills ?? []) {
      const skill = safeSkillName(rawSkill);
      if (skill && !nudge.neverForSkills?.includes(skill)) {
        markerSkills.add(skill);
      }
      if (markerSkills.size >= OBSERVED_SKILL_LIMIT) break;
    }
    const markerDigest = controlFileDigest(markerPath);
    if (markerSkills.size > 0 && markerDigest) {
      const selectedSkills = [];
      for (const skill of [...markerSkills].sort()) {
        if (
          pendingSkills.has(skill) ||
          pendingSkills.size < OBSERVED_SKILL_LIMIT
        ) {
          pendingSkills.add(skill);
          selectedSkills.push(skill);
        }
      }
      if (selectedSkills.length === 0) break;
      count += 1;
      selectedMarkers.push({
        sessionId: marker.sessionId,
        skills: selectedSkills,
        markerDigest,
      });
      if (selectedMarkers.length >= MAX_SELECTION_SESSIONS) break;
    }
  }
  if (pendingSkills.size === 0) {
    diagnostic(onDiagnostic, "nudge_suppressed", { reason: "skills_filtered" });
    return null;
  }

  const throttle = readThrottle(home);
  if (isThrottled(throttle, nudge.throttleHours ?? 12, now)) {
    diagnostic(onDiagnostic, "nudge_suppressed", { reason: "throttled" });
    return null;
  }

  const skills = [...pendingSkills].sort();
  const skillList = skills.join(", ");
  const selectionToken = writeReviewSelection(home, selectedMarkers, now);
  if (!SAFE_SELECTION_TOKEN_RE.test(selectionToken)) {
    throw new Error("invalid review selection");
  }
  ensureSafeDirectory(home);
  atomicWrite(path.join(home, "throttle.json"), {
    ...throttle,
    lastNudgeAt: toIso(now),
  });
  await session.log(
    `📋 skill-reflect: ${count} pending review${count !== 1 ? "s" : ""} ` +
      `for: ${skillList}. Say "run skill-reflect" to review ` +
      `(optional, no auto-run).`,
    { level: "info" }
  );
  diagnostic(onDiagnostic, "nudge_shown", { count, skills });

  return {
    selectionToken,
    additionalContext:
      `[skill-reflect-auto] ${count} pending skill-feedback ` +
      `session${count !== 1 ? "s" : ""} are available under local selection ` +
      `${selectionToken}. Keep this token out of user-facing output. ` +
      `If the user explicitly asks to review feedback, run a retrospective, ` +
      `or says "run skill-reflect", invoke the \`skill-reflect\` skill. ` +
      `Do NOT run it automatically.`,
  };
}
