#!/usr/bin/env python3
"""
skill-reflect-maintainer — Claude Code SessionStart update-check hook.

Compares the vendored skill-reflect version pinned in the current plugin with
this maintainer plugin's local VENDORED_SKILL_VERSION file and prints a short,
non-blocking nudge when an update is available.

Hard constraints:
  - Local-only: no AI, no network calls, no auto-update.
  - Stdlib only. Always exits 0.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


# ─── PATHS ────────────────────────────────────────────────────────────────────

def sr_home() -> Path:
    e = os.environ.get("SKILL_REFLECT_HOME", "")
    return Path(e).resolve() if e else Path.home() / ".skill-reflect"


def plugin_root() -> Path:
    e = os.environ.get("CLAUDE_PLUGIN_ROOT", "")
    if e:
        return Path(e).resolve()
    return Path(__file__).resolve().parent.parent


# ─── TOLERANT READS ───────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _read_text(path: Path) -> str | None:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return None


# ─── WALK-UP DISCOVERY ────────────────────────────────────────────────────────

def _resolve_cwd(raw_cwd: str | None) -> Path:
    try:
        d = Path(raw_cwd).expanduser().resolve() if raw_cwd else Path.cwd().resolve()
        return d.parent if d.is_file() else d
    except Exception:
        return Path.cwd()


def _find_up(start: Path, name: str) -> Path | None:
    try:
        d = start.resolve()
        while True:
            candidate = d / name
            if candidate.is_file():
                return candidate
            parent = d.parent
            if parent == d:
                return None
            d = parent
    except Exception:
        return None


# ─── CONFIG / OPT-OUT ─────────────────────────────────────────────────────────

def _nudge_disabled(pin: dict, cwd: Path) -> bool:
    try:
        nudge = pin.get("nudge", {})
        if isinstance(nudge, dict) and nudge.get("enabled") is False:
            return True
    except Exception:
        pass

    cfg_path = _find_up(cwd, "skill-reflect.config.json")
    if not cfg_path:
        return False
    cfg = _read_json(cfg_path)
    try:
        nudge = cfg.get("nudge", {})
        return isinstance(nudge, dict) and nudge.get("enabled") is False
    except Exception:
        return False


# ─── SEMVER ───────────────────────────────────────────────────────────────────

def _parse_semver(value: str | None) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.startswith(("v", "V")):
        s = s[1:]
    parts = s.split(".")
    if len(parts) != 3:
        return None
    parsed: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        parsed.append(int(part))
    return (parsed[0], parsed[1], parsed[2])


# ─── THROTTLE ─────────────────────────────────────────────────────────────────

def _throttle_path() -> Path:
    return sr_home() / "maintainer-throttle.json"


def _read_throttle() -> dict:
    return _read_json(_throttle_path())


def _write_throttle(data: dict) -> None:
    p = _throttle_path()
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


def _is_throttled(throttle: dict, key: str, throttle_hours: float) -> bool:
    if not throttle_hours:
        return False
    try:
        last = (throttle.get("pins") or {}).get(key)
        if not last:
            return False
        elapsed_hours = (
            datetime.now(timezone.utc) - datetime.fromisoformat(last)
        ).total_seconds() / 3600
        return elapsed_hours < throttle_hours
    except Exception:
        return False


def _mark_throttle(throttle: dict, key: str) -> None:
    data = dict(throttle) if isinstance(throttle, dict) else {}
    pins = data.get("pins") if isinstance(data.get("pins"), dict) else {}
    pins = dict(pins)
    pins[key] = datetime.now(timezone.utc).isoformat()
    data["pins"] = pins
    _write_throttle(data)


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main() -> None:
    try:
        raw = sys.stdin.read()
        hook_input: dict = json.loads(raw) if raw.strip() else {}
        if not isinstance(hook_input, dict):
            hook_input = {}
    except Exception:
        hook_input = {}

    cwd = _resolve_cwd(hook_input.get("cwd") or hook_input.get("workingDirectory"))
    pin_path = _find_up(cwd, ".skill-reflect-vendor.json")
    if not pin_path:
        return

    pin = _read_json(pin_path)
    if _nudge_disabled(pin, cwd):
        return

    vendored_raw = pin.get("upstreamVersion")
    available_raw = _read_text(plugin_root() / "VENDORED_SKILL_VERSION")
    vendored = _parse_semver(vendored_raw)
    available = _parse_semver(available_raw)
    if vendored is None or available is None or vendored >= available:
        return

    key = str(pin_path.resolve())
    throttle = _read_throttle()
    if _is_throttled(throttle, key, 24):
        return

    # Update throttle BEFORE printing (prevents double-nudge on restart).
    _mark_throttle(throttle, key)

    print(
        f"\n🔧 skill-reflect-maintainer: your vendored skill-reflect is {vendored_raw}; "
        f"{available_raw} is available.\n"
        f'   Ask the skill-reflect-maintainer skill to "update skill-reflect" to review '
        f"the change (optional — nothing updates without your approval).\n",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
