#!/usr/bin/env python3
"""install.py: copy the design scripts into the app's repository, so its CI can run them without the skill.

    install.py [--root .] [--into build/design] [--force]

Copies ``tokens.py``, ``icons.py``, ``lint.py`` and ``design_color.py``, the two schemas (into
``<into>/schema/``) and the ``mauidesktop_lib`` package (without its tests) into ``<root>/<into>``, with a
``VERSION`` file naming this skill's version. The app's CI then runs, for example:

    python3 build/design/tokens.py build --check
    python3 build/design/tokens.py contrast --quiet
    python3 build/design/icons.py build --check
    python3 build/design/lint.py

Running it again with the same version refreshes the copy. A folder holding files from a different version
(or files without a ``VERSION``) is refused unless ``--force``, which replaces what an install wrote and leaves
anything else there alone. Text files are written UTF-8 with ``\\n`` endings.

Exit codes: 0 installed; 2 refused (another version is there); 3 usage (``--root`` isn't a folder).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_USAGE = 3

SCRIPTS = ("tokens.py", "icons.py", "lint.py", "design_color.py")
SCHEMAS = ("tokens.schema.json", "icons.schema.json")
PACKAGE = "mauidesktop_lib"
DEFAULT_INTO = "build/design"


def _find(*parts):
    """A file of this skill: beside the scripts (an installed copy) or in the skill's folder."""
    for base in (SCRIPTS_DIR, SKILL_DIR):
        path = os.path.join(base, *parts)
        if os.path.exists(path):
            return path
    return os.path.join(SKILL_DIR, *parts)


def skill_version():
    """This skill's version: the first line of its ``VERSION`` file."""
    with open(_find("VERSION"), "r", encoding="utf-8") as f:
        return f.read().strip().splitlines()[0].strip()


def plan():
    """``[(source, relative destination)]``: every file an install writes."""
    files = [(os.path.join(SCRIPTS_DIR, name), name) for name in SCRIPTS]
    files += [(_find("schema", name), "schema/" + name) for name in SCHEMAS]
    package = os.path.join(SCRIPTS_DIR, PACKAGE)
    for name in sorted(os.listdir(package)):
        if name.endswith(".py") and not name.startswith("test_"):
            files.append((os.path.join(package, name), PACKAGE + "/" + name))
    return files


def copy_text(source, dest):
    """Copy a text file as UTF-8 with ``\\n`` line endings, whatever the source's were."""
    with open(source, "r", encoding="utf-8") as f:
        text = f.read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def installed_version(folder):
    path = os.path.join(folder, "VERSION")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    return lines[0].strip() if lines else ""


def remove_previous(folder):
    """Delete what an earlier install wrote (the scripts, schemas, package and VERSION), nothing else."""
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.endswith(".py") and os.path.isfile(path):
            os.unlink(path)
    for name in ("VERSION",):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            os.unlink(path)
    schema_dir = os.path.join(folder, "schema")
    if os.path.isdir(schema_dir):
        for name in os.listdir(schema_dir):
            if name.endswith(".schema.json"):
                os.unlink(os.path.join(schema_dir, name))
    shutil.rmtree(os.path.join(folder, PACKAGE), ignore_errors=True)


def install(root, into=DEFAULT_INTO, force=False, stream=None):
    stream = stream or sys.stdout
    folder = os.path.normpath(os.path.join(root, *into.replace("\\", "/").split("/")))
    version = skill_version()
    if os.path.isdir(folder) and os.listdir(folder):
        there = installed_version(folder)
        if there != version and not force:
            what = "version %s" % there if there else "files without a VERSION"
            stream.write("%s holds %s, not %s: pass --force to replace what an install wrote there.\n"
                         % (into, what, version))
            return EXIT_REFUSED
        remove_previous(folder)
    files = plan()
    for source, dest in files:
        copy_text(source, os.path.join(folder, *dest.split("/")))
    with open(os.path.join(folder, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
        f.write(version + "\n")
    stream.write("installed maui-desktop-design %s into %s (%d files)\n" % (version, into, len(files) + 1))
    stream.write("  CI: python3 %s/tokens.py build --check && python3 %s/icons.py build --check && "
                 "python3 %s/lint.py\n" % (into, into, into))
    return EXIT_OK


def parse_args(argv):
    p = argparse.ArgumentParser(prog="install.py", description="Copy the design scripts into the app's repository.")
    p.add_argument("--root", default=".")
    p.add_argument("--into", default=DEFAULT_INTO, help="the folder under --root (default: build/design)")
    p.add_argument("--force", action="store_true", help="replace an install of another version")
    return p.parse_args(argv)


def main(argv=None, stream=None):
    stream = stream or sys.stdout
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.stderr.write("--root %s isn't a folder\n" % args.root)
        return EXIT_USAGE
    return install(root, args.into, args.force, stream)


if __name__ == "__main__":
    sys.exit(main())
