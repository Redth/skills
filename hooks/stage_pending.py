#!/usr/bin/env python3
"""
skill-reflect — Claude Code SessionEnd hook adapter (Tier A).

Claude Code invokes this script on session end, passing hook context as JSON
on stdin with fields: session_id, transcript_path, cwd, hook_event_name.

This script:
  1. Reads the transcript JSONL.
  2. Detects distributed-skill usage (Skill tool calls + SKILL.md loads).
  3. Counts friction signals (tool errors, repeated calls, correction language).
  4. If a distributed skill was used AND friction >= threshold, writes
     $SKILL_REFLECT_HOME/pending/<session_id>.json  (CONTRACT §8 shape).

Hard constraints (CONTRACT §§7,8,9):
  - No AI, no network calls.
  - Never write transcript content, paths, or PII into the marker.
  - Always excludes skill-reflect and skill-reflect-auto.
  - Stdlib only (no pip deps).
  - Wraps everything in try/except; always exits 0.
"""
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── CONTRACT §9: always-excluded skills ─────────────────────────────────────
ALWAYS_EXCLUDE: frozenset[str] = frozenset({"skill-reflect", "skill-reflect-auto"})

# User-correction language heuristic (friction in user messages)
_CORRECTION_RE = re.compile(
    r"\b(that['\u2019]?s wrong|try again|didn['\u2019]?t work|not working|"
    r"failed again|fix this|no[,.]?\s+i meant|that['\u2019]?s not right|"
    r"incorrect|redo that|start over|wrong (file|approach|command|path)|"
    r"please fix|that failed|it['\u2019]?s broken)\b",
    re.IGNORECASE,
)

# ─── PATHS ────────────────────────────────────────────────────────────────────

def sr_home() -> Path:
    """Resolve $SKILL_REFLECT_HOME (default ~/.skill-reflect/)."""
    e = os.environ.get("SKILL_REFLECT_HOME", "")
    return Path(e).resolve() if e else Path.home() / ".skill-reflect"


# ─── CONFIG (CONTRACT §2) ─────────────────────────────────────────────────────

_DEFAULT_CONFIG: dict = {
    "version": 1,
    "scope": {
        "skills": [],
        "excludeSkills": sorted(ALWAYS_EXCLUDE),
    },
    "nudge": {
        "enabled": True,
        "frictionThreshold": 2,
        "throttleHours": 12,
        "neverForSkills": [],
        "neverForRepos": [],
    },
}


def _find_config(start: Path) -> Path | None:
    """Walk up from start looking for skill-reflect.config.json."""
    d = start.resolve()
    while True:
        candidate = d / "skill-reflect.config.json"
        if candidate.is_file():
            return candidate
        parent = d.parent
        if parent == d:
            return None
        d = parent


def load_config(cwd: str | None) -> dict:
    """Load config, merging over defaults. Never throws."""
    cfg: dict = json.loads(json.dumps(_DEFAULT_CONFIG))  # deep-copy defaults
    candidates: list[Path] = []
    if cwd:
        found = _find_config(Path(cwd))
        if found:
            candidates.append(found)
    home_cfg = sr_home() / "skill-reflect.config.json"
    if home_cfg not in candidates:
        candidates.append(home_cfg)
    for p in candidates:
        try:
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k] = {**cfg[k], **v}
                    elif v is not None:
                        cfg[k] = v
                break
        except Exception:
            pass
    return cfg


def is_in_scope(skill_name: str, cfg: dict) -> bool:
    """Return True if skill_name should be tracked (CONTRACT §9)."""
    exclude = set(cfg.get("scope", {}).get("excludeSkills", [])) | ALWAYS_EXCLUDE
    if skill_name in exclude:
        return False
    allow: list[str] = cfg.get("scope", {}).get("skills", [])
    if not allow:
        return True  # empty = all distributed skills
    return any(
        fnmatch.fnmatch(skill_name, p) if "*" in p else skill_name == p
        for p in allow
    )


# ─── TRANSCRIPT PARSING ───────────────────────────────────────────────────────

def _iter_jsonl(path: str):
    """Yield parsed JSON objects from JSONL, skipping bad lines."""
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                pass


def _extract_content(obj: dict) -> list[dict]:
    """
    Flatten all content blocks out of various Claude Code JSONL formats:
      - {"role": "assistant", "content": [...]}
      - {"type": "assistant", "message": {"role": "...", "content": [...]}}
      - {"type": "tool_use", ...}  (bare event)
      - {"type": "tool_result", ...}
      - {"type": "tool", "name": "...", "input": {...}, "result": {...}}
    """
    blocks: list[dict] = []

    # Bare top-level event block
    top_type = obj.get("type", "")
    if top_type in ("tool_use", "tool_result"):
        blocks.append(obj)
    # Claude Code "tool" record with nested result
    elif top_type == "tool":
        inp = obj.get("input") or {}
        blocks.append({"type": "tool_use", "name": obj.get("name", ""), "input": inp})
        result = obj.get("result") or {}
        is_err = bool(result.get("error") or result.get("is_error") or
                      not result.get("success", True) if result else False)
        blocks.append({"type": "tool_result", "is_error": is_err})

    # Nested content array (most common Claude Code format)
    content = obj.get("content")
    if content is None:
        msg = obj.get("message")
        if isinstance(msg, dict):
            content = msg.get("content")
    if isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") in ("tool_use", "tool_result"):
                blocks.append(blk)

    return blocks


def _get_role_and_text(obj: dict) -> tuple[str, str]:
    """Return (role, concatenated-text-content) for a JSONL entry."""
    role = obj.get("role", "")
    content = obj.get("content")
    msg = obj.get("message")
    if isinstance(msg, dict):
        role = msg.get("role", role) or role
        content = content or msg.get("content")
    # Resolve type-based role
    if not role:
        t = obj.get("type", "")
        if t in ("user",):
            role = "user"
        elif t in ("assistant",):
            role = "assistant"

    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for blk in content:
            if isinstance(blk, dict) and blk.get("type") == "text":
                texts.append(blk.get("text") or "")
            elif isinstance(blk, str):
                texts.append(blk)
    return role, " ".join(texts)


def detect_skills_and_friction(
    transcript_path: str, cfg: dict
) -> tuple[set[str], dict[str, int]]:
    """
    Parse the transcript JSONL.

    Returns:
      skill_windows  – set of distributed skill names seen in the session.
      friction_by_skill – per-skill friction count (attributed to all open
                          windows at the time of each friction signal, mirroring
                          the reference extension.mjs logic).

    No raw text, paths, or values are retained — only names and counts.
    """
    # skill_windows grows as the session progresses; once a skill is open it
    # stays open (matching extension.mjs behaviour).
    skill_windows: set[str] = set()
    friction_by_skill: dict[str, int] = {}

    def _add_friction() -> None:
        for s in skill_windows:
            friction_by_skill[s] = friction_by_skill.get(s, 0) + 1

    # For repeated-call detection
    last_call_sig: str | None = None
    repeat_count: int = 0

    for obj in _iter_jsonl(transcript_path):
        blocks = _extract_content(obj)
        role, text = _get_role_and_text(obj)

        for blk in blocks:
            btype = blk.get("type", "")

            # ── skill detection ──────────────────────────────────────────────
            if btype == "tool_use":
                name: str = blk.get("name") or ""
                inp: dict = blk.get("input") or {}

                # Primary: explicit skill tool call  {"name":"skill","input":{"skill":"..."}}
                if name == "skill" and isinstance(inp, dict):
                    skill_name = str(inp.get("skill") or "").strip()
                    if skill_name and is_in_scope(skill_name, cfg):
                        skill_windows.add(skill_name)

                # Secondary: SKILL.md file-load (InstructionsLoaded / read_file)
                for key in ("path", "file_path", "filename", "file"):
                    fpath = str(inp.get(key) or "")
                    if fpath.upper().endswith("SKILL.MD") and fpath:
                        # Derive skill name from parent dir, e.g. ~/.../my-skill/SKILL.md
                        parts = Path(fpath).parts
                        if len(parts) >= 2:
                            skill_dir = parts[-2]
                            if is_in_scope(skill_dir, cfg):
                                skill_windows.add(skill_dir)

                # Repeated identical tool call → friction
                sig = f"{name}:{json.dumps(inp, sort_keys=True)}"
                if sig == last_call_sig:
                    repeat_count += 1
                    if repeat_count >= 2 and skill_windows:
                        _add_friction()
                else:
                    last_call_sig = sig
                    repeat_count = 0

            # ── friction: tool error ─────────────────────────────────────────
            elif btype == "tool_result":
                if (blk.get("is_error") or blk.get("error")) and skill_windows:
                    _add_friction()

        # ── friction: user correction language ──────────────────────────────
        if role == "user" and text and skill_windows:
            if _CORRECTION_RE.search(text):
                _add_friction()

    return skill_windows, {s: c for s, c in friction_by_skill.items() if s in skill_windows}


# ─── ATOMIC WRITE ─────────────────────────────────────────────────────────────

def _atomic_write(dest: Path, data: dict) -> None:
    tmp = dest.with_suffix(f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.rename(dest)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass
        raise


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def _map_reason(raw: str | None) -> str:
    """Map Claude Code stop-reason strings to CONTRACT §8 vocabulary."""
    if not raw:
        return "complete"
    r = raw.lower()
    if "error" in r:
        return "error"
    if "abort" in r or "cancel" in r:
        return "abort"
    if "timeout" in r:
        return "timeout"
    if "user" in r and ("exit" in r or "close" in r):
        return "user_exit"
    return "complete"


def main() -> None:
    # ── Read hook input from stdin ────────────────────────────────────────────
    try:
        raw = sys.stdin.read()
        hook_input: dict = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_input = {}

    session_id: str = (
        hook_input.get("session_id")
        or hook_input.get("sessionId")
        or "unknown"
    )
    transcript_path: str | None = (
        hook_input.get("transcript_path")
        or hook_input.get("transcriptPath")
    )
    cwd: str | None = hook_input.get("cwd") or hook_input.get("workingDirectory")
    stop_reason: str | None = (
        hook_input.get("stop_reason")
        or hook_input.get("reason")
        or hook_input.get("hook_event_name")
    )

    cfg = load_config(cwd)

    if not cfg.get("nudge", {}).get("enabled", True):
        return
    if not transcript_path:
        return
    try:
        if not Path(transcript_path).is_file():
            return
    except Exception:
        return

    skill_windows, friction_by_skill = detect_skills_and_friction(transcript_path, cfg)

    threshold: int = int(cfg.get("nudge", {}).get("frictionThreshold", 2))

    # Qualifying: in-scope AND per-skill friction >= threshold  (mirrors extension.mjs)
    qualifying: list[str] = [
        s for s in skill_windows if friction_by_skill.get(s, 0) >= threshold
    ]
    if not qualifying:
        return

    friction_snapshot: dict[str, int] = {s: friction_by_skill[s] for s in qualifying}

    # ── CONTRACT §8 marker shape ──────────────────────────────────────────────
    marker: dict = {
        "sessionId": session_id,
        "endedAt": datetime.now(timezone.utc).isoformat(),
        "skills": qualifying,
        "friction": friction_snapshot,
        "reason": _map_reason(stop_reason),
    }

    pending_dir = sr_home() / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(pending_dir / f"{session_id}.json", marker)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # never raise into the host
    sys.exit(0)
