#!/usr/bin/env python3
"""
skill-reflect — Gemini CLI SessionStart nudge hook (Tier A).

Gemini CLI invokes this script at session start, passing hook context as
JSON on stdin.

If pending skill-reflect markers exist and the nudge is not throttled, this
script prints a short, non-blocking message offering the opt-in review.

# ASSUMPTION: Gemini CLI passes hook input as JSON on stdin with at minimum
# session_id (or sessionId) and cwd (or workingDirectory). Verify against
# Gemini CLI hooks documentation.

Hard constraints:
  - No AI, no network calls.
  - Prints a nudge only; NEVER auto-runs skill-reflect.
  - Stdlib only. Always exits 0.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


def sr_home() -> Path:
    e = os.environ.get("SKILL_REFLECT_HOME", "")
    return Path(e).resolve() if e else Path.home() / ".skill-reflect"


_DEFAULT_NUDGE = {
    "enabled": True,
    "frictionThreshold": 2,
    "throttleHours": 12,
    "neverForSkills": [],
    "neverForRepos": [],
}


def _load_nudge_config(cwd: str | None) -> dict:
    cfg = dict(_DEFAULT_NUDGE)
    candidates: list[Path] = []
    if cwd:
        d = Path(cwd).resolve()
        while True:
            c = d / "skill-reflect.config.json"
            if c.is_file():
                candidates.append(c)
                break
            parent = d.parent
            if parent == d:
                break
            d = parent
    candidates.append(sr_home() / "skill-reflect.config.json")
    for p in candidates:
        try:
            if p.is_file():
                raw = json.loads(p.read_text(encoding="utf-8"))
                nudge = raw.get("nudge", {})
                if isinstance(nudge, dict):
                    cfg.update({k: v for k, v in nudge.items() if v is not None})
                break
        except Exception:
            pass
    return cfg


def _read_throttle() -> dict:
    p = sr_home() / "throttle.json"
    try:
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_throttle(data: dict) -> None:
    p = sr_home() / "throttle.json"
    tmp = p.with_suffix(f".tmp.{os.getpid()}")
    try:
        sr_home().mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.rename(p)
    except Exception:
        try:
            tmp.unlink()
        except Exception:
            pass


def _is_throttled(throttle: dict, throttle_hours: float) -> bool:
    if not throttle_hours:
        return False
    last = throttle.get("lastNudgeAt")
    if not last:
        return False
    try:
        elapsed = (
            datetime.now(timezone.utc) - datetime.fromisoformat(last)
        ).total_seconds() / 3600
        return elapsed < throttle_hours
    except Exception:
        return False


def _list_pending_markers() -> list[Path]:
    d = sr_home() / "pending"
    if not d.is_dir():
        return []
    try:
        return sorted(d.glob("*.json"))
    except Exception:
        return []


def _collect_pending_skills(markers: list[Path], never_for: list[str]) -> list[str]:
    seen: set[str] = set()
    for mp in markers:
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
            for s in data.get("skills") or []:
                if s not in never_for:
                    seen.add(s)
        except Exception:
            pass
    return sorted(seen)


def _get_repo_name(cwd: str | None) -> str | None:
    if not cwd:
        return None
    try:
        d = Path(cwd).resolve()
        while True:
            gc = d / ".git" / "config"
            if gc.is_file():
                txt = gc.read_text(encoding="utf-8", errors="replace")
                m = re.search(r"url\s*=\s*.*[:/]([^/:@\s]+/[^/\s]+?)(?:\.git)?\s*$", txt, re.M)
                return m.group(1) if m else None
            parent = d.parent
            if parent == d:
                return None
            d = parent
    except Exception:
        return None


def main() -> None:
    try:
        raw = sys.stdin.read()
        hook_input: dict = json.loads(raw) if raw.strip() else {}
    except Exception:
        hook_input = {}

    cwd: str | None = (
        hook_input.get("cwd")
        or hook_input.get("workingDirectory")
        or hook_input.get("working_directory")
    )

    nudge = _load_nudge_config(cwd)
    if not nudge.get("enabled", True):
        return

    repo = _get_repo_name(cwd)
    if repo and repo in (nudge.get("neverForRepos") or []):
        return

    markers = _list_pending_markers()
    if not markers:
        return

    skills = _collect_pending_skills(markers, nudge.get("neverForSkills") or [])
    if not skills:
        return

    throttle = _read_throttle()
    if _is_throttled(throttle, float(nudge.get("throttleHours", 12))):
        return

    _write_throttle({**throttle, "lastNudgeAt": datetime.now(timezone.utc).isoformat()})

    count = len(markers)
    skill_list = ", ".join(skills)
    plural = "s" if count != 1 else ""

    print(
        f"\n📋 skill-reflect: {count} pending review{plural} for: {skill_list}.\n"
        f'   Say "run skill-reflect" to review (optional — never auto-runs).\n'
        f"   Nothing is sent anywhere without your explicit approval.\n",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
