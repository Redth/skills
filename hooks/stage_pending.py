#!/usr/bin/env python3
"""
skill-reflect — Claude Code SessionEnd hook adapter (Tier A).

Claude Code invokes this script on session end, passing hook context as JSON
on stdin with fields: session_id, transcript_path, cwd, hook_event_name.

This script:
  1. Reads the transcript JSONL.
  2. Detects skill candidates (Skill tool calls + SKILL.md loads).
  3. Counts nearby friction signals (tool errors and repeated call shapes).
  4. If a candidate crossed the threshold, writes
     $SKILL_REFLECT_HOME/pending/<session_id>.json  (CONTRACT §8 shape).

Hard constraints (CONTRACT §§7,8,9):
  - No AI, no network calls.
  - Never write transcript content, paths, or PII into the marker.
  - Always excludes skill-reflect and skill-reflect-auto.
  - Stdlib only (no pip deps).
  - Wraps everything in try/except; always exits 0.
"""
import fnmatch
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ─── CONTRACT §9: always-excluded skills ─────────────────────────────────────
ALWAYS_EXCLUDE: frozenset[str] = frozenset({"skill-reflect", "skill-reflect-auto"})

# ─── PATHS ────────────────────────────────────────────────────────────────────

ATTRIBUTION_TOOL_WINDOW = 6
_SAFE_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")


def _opaque_session_id(value) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if candidate not in {".", ".."} and _SAFE_SESSION_ID_RE.fullmatch(candidate):
        return candidate
    digest = hashlib.sha256(candidate.encode("utf-8")).hexdigest()[:24]
    return f"session-{digest}"

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
    """Return True if a skill candidate should be tracked (CONTRACT §9)."""
    exclude = set(cfg.get("scope", {}).get("excludeSkills", [])) | ALWAYS_EXCLUDE
    if skill_name in exclude:
        return False
    allow: list[str] = cfg.get("scope", {}).get("skills", [])
    if not allow:
        return True  # empty = all observed candidates; core later resolves provenance
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


def _argument_shape(value, depth: int = 0):
    """Return argument keys/types only; never retain tool argument values."""
    if depth >= 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {
            str(key): _argument_shape(child, depth + 1)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        item_shapes = {
            json.dumps(_argument_shape(item, depth + 1), sort_keys=True)
            for item in value
        }
        return {"list": sorted(item_shapes)}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _tool_signature(name: str, inp: dict) -> str:
    return f"{name}:{json.dumps(_argument_shape(inp), sort_keys=True)}"


def detect_skills_and_friction(
    transcript_path: str, cfg: dict
) -> tuple[set[str], dict[str, int]]:
    """
    Parse the transcript JSONL.

    Returns:
      skill_windows  – set of unverified skill candidates seen in the session.
      friction_by_skill – per-skill friction count, attributed only to the most
                          recently observed skill within a bounded tool window.

    No raw text, paths, or values are retained — only names and counts.
    """
    skill_windows: set[str] = set()
    friction_by_skill: dict[str, int] = {}
    latest_skill: str | None = None
    latest_skill_tool_index: int = -1
    tool_index: int = 0

    def _add_friction() -> None:
        if (
            latest_skill
            and tool_index - latest_skill_tool_index <= ATTRIBUTION_TOOL_WINDOW
        ):
            friction_by_skill[latest_skill] = friction_by_skill.get(latest_skill, 0) + 1

    # For repeated-call detection
    last_call_sig: str | None = None
    repeat_count: int = 0

    for obj in _iter_jsonl(transcript_path):
        blocks = _extract_content(obj)

        for blk in blocks:
            btype = blk.get("type", "")

            # ── skill detection ──────────────────────────────────────────────
            if btype == "tool_use":
                tool_index += 1
                name: str = blk.get("name") or ""
                inp: dict = blk.get("input") or {}
                observed_skill: str | None = None

                # Primary: explicit skill tool call  {"name":"skill","input":{"skill":"..."}}
                if name == "skill" and isinstance(inp, dict):
                    skill_name = str(inp.get("skill") or "").strip()
                    if skill_name and is_in_scope(skill_name, cfg):
                        skill_windows.add(skill_name)
                        observed_skill = skill_name

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
                                observed_skill = skill_dir

                if observed_skill:
                    latest_skill = observed_skill
                    latest_skill_tool_index = tool_index

                # Repeated call shape → friction. Signatures contain keys/types only.
                sig = _tool_signature(name, inp)
                if sig == last_call_sig:
                    repeat_count += 1
                    if repeat_count >= 2:
                        _add_friction()
                else:
                    last_call_sig = sig
                    repeat_count = 0

            # ── friction: tool error ─────────────────────────────────────────
            elif btype == "tool_result":
                if blk.get("is_error") or blk.get("error"):
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

    session_id = _opaque_session_id(
        hook_input.get("session_id")
        or hook_input.get("sessionId")
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
    if not session_id:
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
    qualifying: list[str] = sorted(
        s for s in skill_windows if friction_by_skill.get(s, 0) >= threshold
    )
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
        "candidate": True,
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
