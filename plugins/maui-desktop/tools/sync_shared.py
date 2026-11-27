#!/usr/bin/env python3
"""Copy the maui-desktop plugin's shared code into each skill that uses it.

A skill may reference only files in its own folder (installed plugins are copied to a cache), so what two
skills share lives once in ``plugins/maui-desktop/shared/`` and is copied into each skill:

- ``shared/mauidesktop_lib`` -> ``skills/<skill>/scripts/mauidesktop_lib`` (without its tests)

``SYNC`` says which skills get it. The copies are owned by this script: files in them that the shared folder
doesn't have are removed. Edit ``shared/``, never a copy, then run::

    python3 plugins/maui-desktop/tools/sync_shared.py           # write the copies
    python3 plugins/maui-desktop/tools/sync_shared.py --check   # exit 1, listing every file that differs

``test_sync_shared.py`` runs the check, so a copy that drifts fails the tests.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import shutil
import sys

# Each shared item: its folder under shared/, where it goes in a skill, and names left out of the copy.
ITEMS = {
    "mauidesktop_lib": ("mauidesktop_lib", os.path.join("scripts", "mauidesktop_lib"), ("test_*.py",)),
}

# Which skills get which shared items.
SYNC = {
    "maui-desktop-blueprint": ("mauidesktop_lib",),
}

# Never copied, never counted as drift.
IGNORED = ("__pycache__", "*.pyc", ".DS_Store")

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ignored(name, extra=()):
    return any(fnmatch.fnmatch(name, pat) for pat in IGNORED + tuple(extra))


def _files(folder, exclude=()):
    """The relative paths of the files under ``folder`` (sorted), leaving out ignored and excluded names."""
    out = []
    if not os.path.isdir(folder):
        return out
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if not _ignored(d))
        for name in sorted(filenames):
            if _ignored(name, exclude):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, name), folder))
    return out


def _same(a, b):
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def pairs(root=PLUGIN_ROOT, sync=None):
    """Yield ``(skill, item, source_folder, destination_folder, excluded_names)`` for every copy ``sync`` asks for."""
    for skill, items in sorted((sync or SYNC).items()):
        for item in items:
            src, dest, exclude = ITEMS[item]
            yield skill, item, os.path.join(root, "shared", src), os.path.join(root, "skills", skill, dest), exclude


def check(root=PLUGIN_ROOT, sync=None):
    """Return the drift between ``shared/`` and the skills' copies, one line a file (empty when in sync).

    Each line is ``<state> <path relative to the plugin>``: ``missing`` (in shared, not in the copy),
    ``differs`` or ``extra`` (in the copy, not in shared).
    """
    drift = []
    for skill, _item, src, dest, exclude in pairs(root, sync):
        if not os.path.isdir(os.path.join(root, "skills", skill)):
            drift.append("missing %s" % os.path.relpath(os.path.join(root, "skills", skill), root))
            continue
        want = _files(src, exclude)
        have = _files(dest)
        for rel in want:
            target = os.path.join(dest, rel)
            if not os.path.isfile(target):
                drift.append("missing %s" % os.path.relpath(target, root))
            elif not _same(os.path.join(src, rel), target):
                drift.append("differs %s" % os.path.relpath(target, root))
        for rel in sorted(set(have) - set(want)):
            drift.append("extra   %s" % os.path.relpath(os.path.join(dest, rel), root))
    return drift


def sync(root=PLUGIN_ROOT, sync_table=None):
    """Make every copy match ``shared/``: copy new and changed files, remove extra ones and empty folders.

    Returns the changes made, one line a file, in ``check``'s format (empty when nothing changed). A skill
    folder that doesn't exist is an error (``FileNotFoundError``): the table names a skill that isn't there.
    """
    changes = []
    for skill, _item, src, dest, exclude in pairs(root, sync_table):
        skill_dir = os.path.join(root, "skills", skill)
        if not os.path.isdir(skill_dir):
            raise FileNotFoundError("SYNC names %s, which doesn't exist" % os.path.relpath(skill_dir, root))
        want = _files(src, exclude)
        for rel in want:
            source = os.path.join(src, rel)
            target = os.path.join(dest, rel)
            if os.path.isfile(target) and _same(source, target):
                continue
            changes.append("%s %s" % ("differs" if os.path.exists(target) else "missing",
                                      os.path.relpath(target, root)))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(source, target)
            shutil.copymode(source, target)
        for rel in sorted(set(_files(dest)) - set(want)):
            target = os.path.join(dest, rel)
            changes.append("extra   %s" % os.path.relpath(target, root))
            os.unlink(target)
        if os.path.isdir(dest):
            for dirpath, _dirs, _files_ in sorted(os.walk(dest), reverse=True):
                if dirpath != dest and not _ignored(os.path.basename(dirpath)) and not os.listdir(dirpath):
                    os.rmdir(dirpath)
    return changes


def main(argv=None):
    """The command line: write the copies, or with ``--check`` report drift and exit 1 if there is any."""
    parser = argparse.ArgumentParser(description="Copy plugins/maui-desktop/shared into the skills that use it.")
    parser.add_argument("--check", action="store_true", help="change nothing; list drifted files, exit 1 if any")
    parser.add_argument("--root", default=PLUGIN_ROOT, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.check:
        drift = check(args.root)
        if drift:
            print("The skills' copies differ from shared/ (run tools/sync_shared.py):")
            for line in drift:
                print("  " + line)
            return 1
        print("The skills' copies match shared/.")
        return 0
    changes = sync(args.root)
    for line in changes:
        print("synced " + line)
    print("%d file%s changed." % (len(changes), "" if len(changes) == 1 else "s"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
