#!/usr/bin/env python3
"""
validate_marketplace.py — structural + privacy validation for the Redth/skills
Claude Code plugin marketplace.

Checks (hard failures exit 1, warnings exit 0):

  Marketplace / plugin / skill consistency
    - .claude-plugin/marketplace.json exists, is valid JSON, has name + owner.name
      + a non-empty plugins[].
    - Each plugin has name + description + source.
    - Each plugin.skills[] path exists and contains a SKILL.md.
    - Each referenced SKILL.md has YAML frontmatter with `name` and `description`.
    - (warn) skill directory name matches the frontmatter `name`.

  Plugin hooks
    - hooks/hooks.json (if present) is valid JSON.
    - Every command referencing ${CLAUDE_PLUGIN_ROOT}/... points at a file that
      exists in the repo, and every referenced .py compiles.

  Privacy invariants (CONTRACT §0 — non-negotiable)
    - skill-reflect.config.schema.json still declares
        privacy.redactionPreview      const == true
        privacy.allowTranscriptExcerpts const == false
    - No skill-reflect config file anywhere sets
        privacy.allowTranscriptExcerpts truthy   (hard fail)
        privacy.redactionPreview == false         (hard fail)

Stdlib only. No pip installs, no network.
"""
from __future__ import annotations

import json
import py_compile
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        err(f"missing file: {path.relative_to(REPO)}")
    except json.JSONDecodeError as e:
        err(f"invalid JSON in {path.relative_to(REPO)}: {e}")
    return None


# ─── minimal frontmatter parse (no pyyaml dependency) ────────────────────────

def read_frontmatter(md_path: Path) -> dict[str, str] | None:
    """Return top-level scalar keys from a --- fenced YAML frontmatter block.

    Handles simple `key: value` and folded `key: >` / `key: |` blocks well
    enough to confirm presence of `name` and `description`.
    """
    try:
        text = md_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    block = text[3:end]
    keys: dict[str, str] = {}
    cur_key: str | None = None
    folded: list[str] = []
    for line in block.splitlines():
        if not line.strip():
            continue
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            if cur_key is not None and cur_key not in keys:
                keys[cur_key] = " ".join(folded).strip()
            key, val = m.group(1), m.group(2).strip()
            if val in (">", "|", ">-", "|-", ">+", "|+"):
                cur_key = key
                folded = []
            else:
                keys[key] = val
                cur_key = None
                folded = []
        elif cur_key is not None:
            folded.append(line.strip())
    if cur_key is not None and cur_key not in keys:
        keys[cur_key] = " ".join(folded).strip()
    return keys


# ─── marketplace / plugin / skill ────────────────────────────────────────────

def validate_marketplace() -> None:
    mp_path = REPO / ".claude-plugin" / "marketplace.json"
    mp = load_json(mp_path)
    if mp is None:
        return

    if not mp.get("name"):
        err("marketplace.json: missing `name`")
    owner = mp.get("owner")
    if not isinstance(owner, dict) or not owner.get("name"):
        err("marketplace.json: missing `owner.name`")

    plugins = mp.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        err("marketplace.json: `plugins` must be a non-empty array")
        return

    for i, plugin in enumerate(plugins):
        tag = f"marketplace.json plugins[{i}]"
        if not isinstance(plugin, dict):
            err(f"{tag}: not an object")
            continue
        name = plugin.get("name")
        if not name:
            err(f"{tag}: missing `name`")
        if not plugin.get("description"):
            err(f"{tag} ({name}): missing `description`")
        if not plugin.get("source"):
            err(f"{tag} ({name}): missing `source`")

        skills = plugin.get("skills", [])
        if not isinstance(skills, list):
            err(f"{tag} ({name}): `skills` must be an array")
            continue
        for sk in skills:
            sk_dir = (REPO / sk).resolve()
            rel = sk
            if not sk_dir.is_dir():
                err(f"{tag} ({name}): skill path does not exist: {rel}")
                continue
            skill_md = sk_dir / "SKILL.md"
            if not skill_md.is_file():
                err(f"{tag} ({name}): no SKILL.md in {rel}")
                continue
            fm = read_frontmatter(skill_md)
            if fm is None:
                err(f"{rel}/SKILL.md: missing or malformed YAML frontmatter")
                continue
            if not fm.get("name"):
                err(f"{rel}/SKILL.md: frontmatter missing `name`")
            if not fm.get("description"):
                err(f"{rel}/SKILL.md: frontmatter missing `description`")
            if fm.get("name") and fm["name"] != sk_dir.name:
                warn(
                    f"{rel}/SKILL.md: frontmatter name '{fm['name']}' "
                    f"!= directory name '{sk_dir.name}'"
                )


# ─── plugin hooks ─────────────────────────────────────────────────────────────

def validate_hooks() -> None:
    hooks_json = REPO / "hooks" / "hooks.json"
    if not hooks_json.is_file():
        return  # hooks are optional
    data = load_json(hooks_json)
    if data is None:
        return
    text = hooks_json.read_text(encoding="utf-8")
    for ref in re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"'\s\\]+)", text):
        target = REPO / ref
        if not target.exists():
            err(f"hooks.json references missing file: {ref}")
        elif ref.endswith(".py"):
            try:
                py_compile.compile(str(target), doraise=True)
            except py_compile.PyCompileError as e:
                err(f"hooks.json script does not compile: {ref}: {e}")


# ─── privacy invariants ───────────────────────────────────────────────────────

def _walk_json_files():
    for p in REPO.rglob("*.json"):
        parts = set(p.parts)
        if ".git" in parts or "node_modules" in parts or "__pycache__" in parts:
            continue
        yield p


def validate_schema_consts() -> None:
    schema = REPO / "skill-reflect.config.schema.json"
    data = load_json(schema)
    if data is None:
        return
    priv = (
        data.get("properties", {})
        .get("privacy", {})
        .get("properties", {})
    )
    rp = priv.get("redactionPreview", {})
    at = priv.get("allowTranscriptExcerpts", {})
    if rp.get("const") is not True:
        err("config schema: privacy.redactionPreview must declare const: true")
    if at.get("const") is not False:
        err("config schema: privacy.allowTranscriptExcerpts must declare const: false")


def validate_config_privacy() -> None:
    for p in _walk_json_files():
        if p.name.endswith(".schema.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            continue
        priv = data.get("privacy")
        if not isinstance(priv, dict):
            continue
        rel = p.relative_to(REPO)
        if priv.get("allowTranscriptExcerpts"):  # truthy = violation
            err(f"{rel}: privacy.allowTranscriptExcerpts must be false (never true)")
        if priv.get("redactionPreview") is False:
            err(f"{rel}: privacy.redactionPreview must be true (never false)")


# ─── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    validate_marketplace()
    validate_hooks()
    validate_schema_consts()
    validate_config_privacy()

    print("skill-reflect marketplace validator")
    print("=" * 40)
    if warnings:
        print(f"\n⚠️  {len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    if errors:
        print(f"\n❌ {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        print("\nFAILED")
        return 1
    print("\n✅ All marketplace / manifest / privacy checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
