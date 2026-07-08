#!/usr/bin/env python3
"""Deterministic skill-reflect vendoring engine (CONTRACT §11.3)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

PIN_NAME = ".skill-reflect-vendor.json"
CONFIG_NAME = "skill-reflect.config.json"
SCHEMA_NAME = "skill-reflect.config.schema.json"
DEFAULT_SKILL_TARGET = "skills/skill-reflect"
DEFAULT_HOOKS_TARGET = "hooks"
DEFAULT_AUTO_TARGET = "extensions/skill-reflect-auto"
DEFAULT_SOURCE_REPO = "Redth/skills"
DEFAULT_SOURCE_REF = "main"
HOOK_SCRIPTS = ("stage_pending.py", "nudge_start.py")
HOOK_EVENTS = {
    "SessionEnd": "stage_pending.py",
    "SessionStart": "nudge_start.py",
}


class AdoptError(Exception):
    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


class DryRun:
    def __init__(self, enabled: bool):
        self.enabled = enabled
        self.actions: list[str] = []

    def record(self, text: str) -> None:
        if self.enabled:
            self.actions.append(text)

    def print(self) -> None:
        if self.enabled:
            for action in self.actions:
                print(f"DRY-RUN: {action}")


def _json_dump(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise AdoptError(f"Invalid JSON in {path}: {exc}") from exc


def _plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _normalize_rel(rel: str) -> PurePosixPath:
    rel = rel.replace("\\", "/").strip("/")
    if not rel or rel.startswith("../") or "/../" in f"/{rel}/" or rel == "..":
        raise AdoptError(f"Unsafe relative path: {rel!r}")
    p = PurePosixPath(rel)
    if p.is_absolute():
        raise AdoptError(f"Path must be relative: {rel!r}")
    return p


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_join(root: Path, rel: str | PurePosixPath) -> Path:
    rel_posix = _normalize_rel(str(rel))
    dest = root.joinpath(*rel_posix.parts)
    if not _inside(root, dest):
        raise AdoptError(f"Refusing to write outside --to: {dest}")
    return dest


def _copy_file(src: Path, dst: Path, dry: DryRun) -> None:
    if dry.enabled:
        dry.record(f"copy file {src} -> {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_tree(src: Path, dst: Path, root: Path, dry: DryRun) -> None:
    if not src.is_dir():
        raise AdoptError(f"Required source directory missing: {src}")
    if not _inside(root, dst):
        raise AdoptError(f"Refusing to write outside --to: {dst}")
    if dry.enabled:
        dry.record(f"replace directory {dst} from {src}")
        return
    if dst.exists():
        if not dst.is_dir():
            raise AdoptError(f"Destination exists and is not a directory: {dst}")
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _parse_github_spec(spec: str) -> tuple[str, str]:
    if "@" in spec:
        repo, ref = spec.rsplit("@", 1)
    else:
        repo, ref = spec, DEFAULT_SOURCE_REF
    if repo.count("/") != 1 or not repo.replace("/", "").strip() or not ref.strip():
        raise AdoptError(f"Invalid --from-github value: {spec!r}")
    return repo, ref


def _auto_detect_source() -> Path | None:
    d = Path(__file__).resolve()
    for parent in (d, *d.parents):
        if (parent / "skills" / "skill-reflect" / "VERSION").is_file():
            return parent
    return None


def _resolve_source(args: argparse.Namespace, to_root: Path | None) -> tuple[Path, str, str, tempfile.TemporaryDirectory[str] | None]:
    if getattr(args, "from_path", None):
        src = Path(args.from_path).expanduser().resolve()
        if not (src / "skills" / "skill-reflect" / "VERSION").is_file():
            raise AdoptError(f"--from is not a Redth/skills checkout: {src}")
        return src, DEFAULT_SOURCE_REPO, DEFAULT_SOURCE_REF, None

    if getattr(args, "from_github", None):
        repo, ref = _parse_github_spec(args.from_github)
        print(f"Fetching skill-reflect source from GitHub {repo}@{ref} (network requested by --from-github)")
        if shutil.which("git") is None:
            raise AdoptError("Cannot fetch --from-github: git is not available")
        temp_parent = to_root if to_root is not None else Path.cwd()
        temp_parent.mkdir(parents=True, exist_ok=True)
        tmp = tempfile.TemporaryDirectory(prefix=".skill-reflect-source-", dir=str(temp_parent))
        clone_dir = Path(tmp.name) / "repo"
        url = f"https://github.com/{repo}.git"
        cmd = ["git", "clone", "--depth", "1", url, str(clone_dir)]
        proc = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            tmp.cleanup()
            raise AdoptError(f"git clone failed: {proc.stderr.strip() or proc.stdout.strip()}")
        proc = subprocess.run(["git", "-C", str(clone_dir), "checkout", ref], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            tmp.cleanup()
            raise AdoptError(f"git checkout {ref} failed: {proc.stderr.strip() or proc.stdout.strip()}")
        return clone_dir, repo, ref, tmp

    src = _auto_detect_source()
    if src is None:
        raise AdoptError("Could not auto-detect Redth/skills; pass --from <path> or explicit --from-github Redth/skills[@ref]")
    return src, DEFAULT_SOURCE_REPO, DEFAULT_SOURCE_REF, None


def _read_version(source: Path) -> str:
    version = (source / "skills" / "skill-reflect" / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise AdoptError(f"Empty VERSION in {source}")
    return version


def _scope(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _compute_skill_hash(skill_root: Path) -> str:
    if not skill_root.is_dir():
        raise AdoptError(f"Vendored skill tree missing: {skill_root}")
    h = hashlib.sha256()
    files = sorted(p for p in skill_root.rglob("*") if p.is_file())
    for path in files:
        rel = path.relative_to(skill_root).as_posix()
        if rel in {PIN_NAME, CONFIG_NAME}:
            continue
        h.update(rel.encode("utf-8"))
        h.update(b"\0")
        h.update(path.read_bytes())
    return "sha256:" + h.hexdigest()


def _hook_command(hooks_target: str, script: str) -> str:
    rel = PurePosixPath(str(_normalize_rel(hooks_target))) / script
    return f'python3 "${{CLAUDE_PLUGIN_ROOT}}/{rel.as_posix()}"'


def _commands_equivalent(existing: str, desired: str, script: str) -> bool:
    return existing == desired or f"/{script}" in existing or existing.endswith(script) or script in existing


def _merge_hooks(to_root: Path, hooks_target: str, dry: DryRun) -> None:
    hooks_file = _safe_join(to_root, PurePosixPath(hooks_target) / "hooks.json")
    manifest = _read_json(hooks_file, {}) if hooks_file.exists() else {}
    if not isinstance(manifest, dict):
        raise AdoptError(f"hooks.json must be an object: {hooks_file}")
    hooks = manifest.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        raise AdoptError(f"hooks.json hooks must be an object: {hooks_file}")

    changed = False
    for event, script in HOOK_EVENTS.items():
        event_entries = hooks.setdefault(event, [])
        if not isinstance(event_entries, list):
            raise AdoptError(f"hooks.{event} must be a list in {hooks_file}")
        desired = _hook_command(hooks_target, script)
        found = False
        for entry in event_entries:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) if isinstance(entry.get("hooks", []), list) else []:
                if isinstance(hook, dict) and hook.get("type") == "command" and _commands_equivalent(str(hook.get("command", "")), desired, script):
                    found = True
                    break
            if found:
                break
        if not found:
            event_entries.append({"hooks": [{"type": "command", "command": desired}]})
            changed = True
    if changed:
        if dry.enabled:
            dry.record(f"merge skill-reflect hook commands into {hooks_file}")
        else:
            hooks_file.parent.mkdir(parents=True, exist_ok=True)
            _json_dump(hooks_file, manifest)


def _scaffold_config(to_root: Path, scope: list[str], destination: str | None, dry: DryRun) -> None:
    config_path = to_root / CONFIG_NAME
    if config_path.exists():
        return
    config = {
        "version": 1,
        "mode": "vendored",
        "scope": {"skills": scope, "excludeSkills": ["skill-reflect", "skill-reflect-auto"]},
        "destination": {"mode": "ask", "repo": destination, "registryMapPath": None},
        "nudge": {"enabled": True, "frictionThreshold": 2, "throttleHours": 12, "neverForSkills": [], "neverForRepos": []},
        "privacy": {"extraScrubPatterns": [], "redactionPreview": True, "allowTranscriptExcerpts": False},
        "eval": {"emitFormats": ["skill-creator", "portable"], "evalsOutPath": ".skill-feedback/evals"},
        "artifactDir": ".skill-feedback",
    }
    if dry.enabled:
        dry.record(f"create scaffold config {config_path}")
    else:
        _json_dump(config_path, config)


def _write_pin(
    to_root: Path,
    upstream_version: str,
    source_repo: str,
    source_ref: str,
    skill_target: str,
    hooks_target: str,
    auto_target: str | None,
    scope: list[str],
    destination: str | None,
    content_hash: str,
    dry: DryRun,
) -> None:
    pin = {
        "schema": 1,
        "upstreamVersion": upstream_version,
        "sourceRepo": source_repo,
        "sourceRef": source_ref,
        "vendoredAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "targets": {"skill": skill_target, "hooks": hooks_target, "autoExtension": auto_target},
        "contentHash": content_hash,
        "scope": scope,
        "destinationRepo": destination,
    }
    pin_path = to_root / PIN_NAME
    if dry.enabled:
        dry.record(f"write vendor pin {pin_path}")
    else:
        _json_dump(pin_path, pin)


def _read_pin(to_root: Path) -> dict[str, Any]:
    pin_path = to_root / PIN_NAME
    pin = _read_json(pin_path, None)
    if not isinstance(pin, dict):
        raise AdoptError(f"Missing or invalid vendor pin: {pin_path}")
    return pin


def _sync_payload(source: Path, to_root: Path, skill_target: str, hooks_target: str, with_auto: bool, dry: DryRun) -> None:
    _copy_tree(source / "skills" / "skill-reflect", _safe_join(to_root, skill_target), to_root, dry)
    hooks_dir = _safe_join(to_root, hooks_target)
    for script in HOOK_SCRIPTS:
        _copy_file(source / "hooks" / script, hooks_dir / script, dry)
    _merge_hooks(to_root, hooks_target, dry)
    _copy_file(source / SCHEMA_NAME, to_root / SCHEMA_NAME, dry)
    if with_auto:
        _copy_tree(source / "integrations" / "copilot-cli" / "skill-reflect-auto", _safe_join(to_root, DEFAULT_AUTO_TARGET), to_root, dry)


def _detect_drift(to_root: Path, pin: dict[str, Any]) -> tuple[bool, list[str]]:
    targets = pin.get("targets", {}) if isinstance(pin.get("targets"), dict) else {}
    skill_target = targets.get("skill", DEFAULT_SKILL_TARGET)
    skill_root = _safe_join(to_root, str(skill_target))
    expected = pin.get("contentHash")
    actual = _compute_skill_hash(skill_root)
    if actual == expected:
        return False, []
    return True, [f"{skill_target}: expected {expected}, actual {actual}"]


def _adopt(args: argparse.Namespace) -> int:
    to_root = Path(args.to).expanduser().resolve()
    dry = DryRun(args.dry_run)
    if not dry.enabled:
        to_root.mkdir(parents=True, exist_ok=True)
    skill_target = str(_normalize_rel(args.skill_target or DEFAULT_SKILL_TARGET))
    hooks_target = str(_normalize_rel(args.hooks_target or DEFAULT_HOOKS_TARGET))
    scope = _scope(args.scope)
    source_tmp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source, source_repo, source_ref, source_tmp = _resolve_source(args, to_root)
        version = _read_version(source)
        _sync_payload(source, to_root, skill_target, hooks_target, bool(args.with_auto), dry)
        auto_target = DEFAULT_AUTO_TARGET if args.with_auto else None
        if dry.enabled:
            content_hash = "sha256:" + "0" * 64
        else:
            content_hash = _compute_skill_hash(_safe_join(to_root, skill_target))
        _write_pin(to_root, version, source_repo, source_ref, skill_target, hooks_target, auto_target, scope, args.destination, content_hash, dry)
        _scaffold_config(to_root, scope, args.destination, dry)
        dry.print()
        print(f"Adopted skill-reflect {version} into {to_root}")
        return 0
    finally:
        if source_tmp is not None:
            source_tmp.cleanup()


def _update(args: argparse.Namespace) -> int:
    to_root = Path(args.to).expanduser().resolve()
    dry = DryRun(args.dry_run)
    pin = _read_pin(to_root)
    drift, details = _detect_drift(to_root, pin)
    if drift and not args.force:
        print("Local drift detected; refusing update without --force:")
        for detail in details:
            print(f"- {detail}")
        return 3
    targets = pin.get("targets", {}) if isinstance(pin.get("targets"), dict) else {}
    skill_target = str(targets.get("skill") or DEFAULT_SKILL_TARGET)
    hooks_target = str(targets.get("hooks") or DEFAULT_HOOKS_TARGET)
    with_auto = bool(targets.get("autoExtension"))
    source_tmp: tempfile.TemporaryDirectory[str] | None = None
    try:
        source, source_repo, source_ref, source_tmp = _resolve_source(args, to_root)
        version = args.to_version or _read_version(source)
        if args.to_version and not args.from_github:
            source_ref = args.to_version
        _sync_payload(source, to_root, skill_target, hooks_target, with_auto, dry)
        if dry.enabled:
            content_hash = pin.get("contentHash", "sha256:" + "0" * 64)
        else:
            content_hash = _compute_skill_hash(_safe_join(to_root, skill_target))
        _write_pin(
            to_root,
            version,
            source_repo,
            source_ref,
            skill_target,
            hooks_target,
            targets.get("autoExtension") if with_auto else None,
            list(pin.get("scope", [])) if isinstance(pin.get("scope"), list) else [],
            pin.get("destinationRepo"),
            content_hash,
            dry,
        )
        dry.print()
        print(f"Updated skill-reflect to {version} in {to_root}")
        return 0
    finally:
        if source_tmp is not None:
            source_tmp.cleanup()


def _reference_version(args: argparse.Namespace) -> str:
    if args.reference_version:
        return args.reference_version
    version_file = _plugin_root() / "VENDORED_SKILL_VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    raise AdoptError("Missing VENDORED_SKILL_VERSION; pass --reference-version")


def _validate_config(to_root: Path) -> list[str]:
    path = to_root / CONFIG_NAME
    if not path.is_file():
        return [f"missing {CONFIG_NAME}"]
    data = _read_json(path, None)
    if not isinstance(data, dict):
        return [f"{CONFIG_NAME} must be an object"]
    errors: list[str] = []
    allowed_top = {"version", "mode", "scope", "destination", "nudge", "privacy", "eval", "artifactDir"}
    extra = set(data) - allowed_top
    if extra:
        errors.append(f"unexpected config keys: {', '.join(sorted(extra))}")
    if data.get("version") != 1:
        errors.append("version must be 1")
    if data.get("mode") not in {"standalone", "vendored"}:
        errors.append("mode must be standalone or vendored")
    scope = data.get("scope", {})
    if not isinstance(scope, dict):
        errors.append("scope must be an object")
    else:
        if not isinstance(scope.get("skills", []), list) or not all(isinstance(x, str) for x in scope.get("skills", [])):
            errors.append("scope.skills must be an array of strings")
        if not isinstance(scope.get("excludeSkills", []), list) or not all(isinstance(x, str) for x in scope.get("excludeSkills", [])):
            errors.append("scope.excludeSkills must be an array of strings")
    dest = data.get("destination", {})
    if not isinstance(dest, dict):
        errors.append("destination must be an object")
    else:
        if dest.get("mode") not in {"local", "issue", "ask", None}:
            errors.append("destination.mode must be local, issue, or ask")
        if dest.get("repo") is not None and not isinstance(dest.get("repo"), str):
            errors.append("destination.repo must be a string or null")
        if dest.get("registryMapPath") is not None and not isinstance(dest.get("registryMapPath"), str):
            errors.append("destination.registryMapPath must be a string or null")
    privacy = data.get("privacy", {})
    if isinstance(privacy, dict):
        if privacy.get("redactionPreview", True) is not True:
            errors.append("privacy.redactionPreview must be true")
        if privacy.get("allowTranscriptExcerpts", False) is not False:
            errors.append("privacy.allowTranscriptExcerpts must be false")
    return errors


def _check_hooks(to_root: Path, hooks_target: str) -> list[str]:
    hooks_file = _safe_join(to_root, PurePosixPath(hooks_target) / "hooks.json")
    if not hooks_file.is_file():
        return [f"missing {hooks_file.relative_to(to_root).as_posix()}"]
    manifest = _read_json(hooks_file, {})
    errors: list[str] = []
    hooks = manifest.get("hooks", {}) if isinstance(manifest, dict) else {}
    for event, script in HOOK_EVENTS.items():
        desired = _hook_command(hooks_target, script)
        found = False
        for entry in hooks.get(event, []) if isinstance(hooks, dict) else []:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []) if isinstance(entry.get("hooks", []), list) else []:
                if isinstance(hook, dict) and hook.get("type") == "command" and _commands_equivalent(str(hook.get("command", "")), desired, script):
                    found = True
        if not found:
            errors.append(f"missing {event} command for {script}")
    return errors


def _check_nudge_blocks(to_root: Path, scope: list[str]) -> list[str]:
    errors: list[str] = []
    begin = "<!-- BEGIN skill-reflect nudge -->"
    end = "<!-- END skill-reflect nudge -->"
    for skill in scope:
        candidates = [to_root / "skills" / skill / "SKILL.md"]
        found_existing = [p for p in candidates if p.is_file()]
        if not found_existing:
            continue
        text = found_existing[0].read_text(encoding="utf-8", errors="replace")
        if begin not in text or end not in text:
            errors.append(f"missing Improve This Skill nudge block in {found_existing[0].relative_to(to_root).as_posix()}")
    return errors


def _doctor(args: argparse.Namespace) -> int:
    to_root = Path(args.to).expanduser().resolve()
    problems_12: list[str] = []
    drift_details: list[str] = []
    update_available = False
    try:
        pin = _read_pin(to_root)
    except AdoptError as exc:
        print(f"skill-reflect doctor: unhealthy\n- {exc}")
        return 12
    targets = pin.get("targets", {}) if isinstance(pin.get("targets"), dict) else {}
    hooks_target = str(targets.get("hooks") or DEFAULT_HOOKS_TARGET)
    scope = [x for x in pin.get("scope", []) if isinstance(x, str)] if isinstance(pin.get("scope"), list) else []

    reference = _reference_version(args)
    if pin.get("upstreamVersion") != reference:
        update_available = True
    try:
        drift, drift_details = _detect_drift(to_root, pin)
    except AdoptError as exc:
        drift = True
        drift_details = [str(exc)]
    problems_12.extend(_validate_config(to_root))
    problems_12.extend(_check_hooks(to_root, hooks_target))
    problems_12.extend(_check_nudge_blocks(to_root, scope))

    print("skill-reflect doctor")
    print(f"- vendored version: {pin.get('upstreamVersion')} (reference: {reference})")
    print(f"- update available: {'yes' if update_available else 'no'}")
    print(f"- local drift: {'yes' if drift else 'no'}")
    if drift:
        for detail in drift_details:
            print(f"  - {detail}")
    print(f"- config/hooks/nudge: {'problem' if problems_12 else 'ok'}")
    for problem in problems_12:
        print(f"  - {problem}")

    if problems_12:
        return 12
    if drift:
        return 11
    if update_available:
        return 10
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adopt, update, and doctor vendored skill-reflect copies.")
    sub = parser.add_subparsers(dest="command", required=True)

    adopt = sub.add_parser("adopt")
    adopt.add_argument("--to", required=True)
    adopt.add_argument("--from", dest="from_path")
    adopt.add_argument("--from-github", dest="from_github")
    adopt.add_argument("--skill-target", default=DEFAULT_SKILL_TARGET)
    adopt.add_argument("--hooks-target", default=DEFAULT_HOOKS_TARGET)
    adopt.add_argument("--with-auto", action="store_true")
    adopt.add_argument("--scope")
    adopt.add_argument("--destination")
    adopt.add_argument("--dry-run", action="store_true")
    adopt.set_defaults(func=_adopt)

    update = sub.add_parser("update")
    update.add_argument("--to", required=True)
    update.add_argument("--from", dest="from_path")
    update.add_argument("--from-github", dest="from_github")
    update.add_argument("--to-version")
    update.add_argument("--force", action="store_true")
    update.add_argument("--dry-run", action="store_true")
    update.set_defaults(func=_update)

    doctor = sub.add_parser("doctor")
    doctor.add_argument("--to", required=True)
    doctor.add_argument("--reference-version")
    doctor.set_defaults(func=_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if getattr(args, "from_path", None) and getattr(args, "from_github", None):
            raise AdoptError("Use only one of --from or --from-github")
        return int(args.func(args))
    except AdoptError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return exc.code
    except KeyboardInterrupt:
        print("ERROR: interrupted", file=sys.stderr)
        return 130
    except Exception as exc:  # defensive: CONTRACT requires clear nonzero, no uncaught tracebacks.
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
