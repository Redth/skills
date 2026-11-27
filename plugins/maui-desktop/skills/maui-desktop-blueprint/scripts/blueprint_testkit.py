"""Helpers for detect.py's and blueprint.py's tests: the eval fixtures, copies of them in a temp folder, and
running either command in-process. Stdlib only; nothing here reaches a network."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
FILES = os.path.join(SKILL_DIR, "evals", "files")
SCHEMA = os.path.join(SKILL_DIR, "schema", "desktop-blueprint.schema.json")
PROJECTS = ("legacy-hybrid", "declared-shell", "new-app")
DATE = "2026-11-27"


def fixture(*parts):
    """A path inside ``evals/files``."""
    return os.path.join(FILES, *parts)


def copy_project(name, dest_root):
    """Copy a project fixture into ``dest_root/<name>`` (so a command may write into it); return that path."""
    dest = os.path.join(dest_root, name)
    shutil.copytree(fixture(name), dest)
    return dest


def copy_blueprint(name, dest_dir, as_name="desktop-blueprint.json"):
    """Copy ``evals/files/blueprints/<name>.json`` to ``dest_dir/<as_name>``; return that path."""
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, as_name)
    shutil.copyfile(fixture("blueprints", name + ".json"), dest)
    return dest


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, indent=2) + "\n")


def read_text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _run(module, argv, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = module.main(argv)
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


def run_detect(argv, cwd=None):
    """Run ``detect.main(argv)`` in-process; return ``(exit code, stdout, stderr)``."""
    import detect
    return _run(detect, argv, cwd)


def run_blueprint(argv, cwd=None):
    """Run ``blueprint.main(argv)`` in-process; return ``(exit code, stdout, stderr)``."""
    import blueprint
    return _run(blueprint, argv, cwd)


def detect_json(root):
    """``detect.py --root ROOT --json``, parsed."""
    code, out, err = run_detect(["--root", root, "--json"])
    if code != 0:
        raise AssertionError("detect.py failed (%d): %s" % (code, err))
    return json.loads(out)


def check_json(blueprint_path):
    """``blueprint.py check --json``: ``(exit code, parsed report)``."""
    code, out, _err = run_blueprint(["check", "--blueprint", blueprint_path, "--json"])
    return code, json.loads(out)


def finding_ids(report, severity=None):
    return sorted(set(f["id"] for f in report["findings"] if severity is None or f["severity"] == severity))


def all_evidence(value):
    """Every evidence string anywhere in a detection dict (lists under keys named ``evidence`` or ending in
    ``Evidence``, the integrations' lists, and the shell's palette and window lists)."""
    out = []

    def walk(node, key=""):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list) and (key == "evidence" or key.endswith("Evidence") or key in _EVIDENCE_LISTS):
            out.extend(x for x in node if isinstance(x, str))
    walk(value)
    for v in (value.get("integrations") or {}).values():
        out.extend(v)
    return out


_EVIDENCE_LISTS = ("commandPalette", "multiWindow", "devflow", "gallery")
