#!/usr/bin/env python3
"""detect.py: read a .NET MAUI desktop project and report what it already has (CONTRACT.md section 7.1).

    detect.py [--root .] [--json] [--out FILE]

Reads files only: project files, sources, stylesheets, workflows. It never runs ``dotnet``, never follows a
symlink and skips ``bin``, ``obj``, ``node_modules``, ``.git`` and vendored ``wwwroot/lib|vendor``. People get
a short markdown summary; ``--json`` prints the whole detection object (heads, sharing, shell, dialogs,
design, integrations, distribution…, each claim with evidence lines ``"<path>: <matching text>"``);
``--out FILE`` also writes that object to FILE.

Exit codes: 0 done (also when nothing is found); 3 when ``--root`` isn't a folder or FILE can't be written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mauidesktop_lib import detect  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402

EXIT_OK = 0
EXIT_USAGE = 3

NAMES = {"macos": "macOS", "windows": "Windows", "linux": "Linux", "maccatalyst": "Mac Catalyst", "ios": "iOS",
         "android": "Android", "devhost": "browser dev host", "*": "shared code"}
SHARING = {"rcl": "a Razor class library", "links": "compile links into another project", "symlinks": "symlinks",
           "single": "one project", "unknown": "not detected"}


def _plats(items):
    return ", ".join(NAMES.get(p, p) for p in items)


def summary(d):
    """The detection as a short markdown summary for people."""
    lines = []
    app = d.get("app") or {}
    lines.append("# Detected: %s" % (app.get("name") or "no app found"))
    lines.append("")
    if not d.get("projects"):
        lines.append("- No .NET projects found under %s: a new app, nothing to respect yet." % d.get("root"))
        if d.get("agentDocs"):
            lines.append("- Agent docs: %s" % ", ".join(d["agentDocs"]))
        return "\n".join(lines) + "\n"
    sdk = (d.get("dotnet") or {}).get("sdk")
    sol = ", ".join(d.get("solution") or []) or "no solution file"
    lines.append("- Solution: %s%s" % (sol, " (.NET SDK %s from global.json)" % sdk if sdk else ""))
    if app.get("id"):
        lines.append("- App id: `%s`, namespace `%s`" % (app["id"], app.get("namespace")))
    heads = d.get("heads") or {}
    also = {p["path"] for p in d.get("projects") or [] if p.get("alsoUi")}
    by_path = []
    for key in ("macos", "windows", "linux", "maccatalyst", "ios", "android", "devhost"):
        path = heads.get(key)
        if not path:
            continue
        for entry in by_path:
            if entry[0] == path:
                entry[1].append(NAMES[key])
                break
        else:
            by_path.append((path, [NAMES[key]]))
    found = ["%s `%s`%s" % (", ".join(names), path, " (also the shared UI)" if path in also else "")
             for path, names in by_path]
    lines.append("- Heads: %s" % ("; ".join(found) if found else "none"))
    backends = [("%s %s" % (NAMES[p], b)) for p, b in (d.get("backends") or {}).items() if b]
    if backends:
        lines.append("- Backends: %s" % "; ".join(backends))
    sharing = d.get("sharing") or {}
    lines.append("- UI sharing: %s (%d evidence line%s)" % (
        SHARING.get(sharing.get("kind"), sharing.get("kind")), len(sharing.get("evidence") or []),
        "" if len(sharing.get("evidence") or []) == 1 else "s"))
    shell = d.get("shell") or {}
    sidebar = shell.get("sidebar") or {}
    lines.append("- Navigation: %s; toolbar: %s; sidebar: %s" % (
        (shell.get("navigation") or {}).get("kind"), (shell.get("toolbar") or {}).get("kind"),
        ", ".join("%s %s" % (NAMES[p], v) for p, v in sidebar.items() if v and p in NAMES) or "none"))
    menu = shell.get("menuBar") or {}
    lines.append("- Menu bar: %s" % (", ".join("%s %s" % (NAMES[p], v) for p, v in menu.items() if v) or "no heads"))
    dlg = d.get("dialogs") or {}
    lines.append("- Dialogs: %s (%d), %d web overlay%s" % (
        dlg.get("kind"), dlg.get("count") or 0, dlg.get("webOverlays") or 0, "" if dlg.get("webOverlays") == 1 else "s"))
    des = d.get("design") or {}
    sel = des.get("platformSelectors") or {}
    lines.append("- Design: DESIGN.md %s, design/tokens.json %s, design/icons.json %s; %d raw hex colour%s; "
                 "platform selectors macOS %d, Windows %d, Linux %d" % (
                     "yes" if des.get("designMd") else "no", "yes" if des.get("tokensJson") else "no",
                     "yes" if des.get("iconsJson") else "no", des.get("rawHex") or 0,
                     "" if des.get("rawHex") == 1 else "s", sel.get("macos", 0), sel.get("windows", 0), sel.get("linux", 0)))
    integ = d.get("integrations") or {}
    plats = d.get("integrationPlatforms") or {}
    have = ["%s (%s)" % (k, _plats(plats.get(k) or [])) for k, v in integ.items() if v]
    lines.append("- Integrations found: %s" % (", ".join(have) if have else "none"))
    dist = d.get("distribution") or {}
    tags = ["%s %s" % (NAMES[p], ", ".join(dist.get(p) or [])) for p in ("macos", "windows", "linux") if dist.get(p)]
    lines.append("- Distribution: %s%s" % ("; ".join(tags) if tags else "nothing found",
                                           " (workflows: %s)" % ", ".join(dist["workflows"]) if dist.get("workflows") else ""))
    tests = d.get("tests") or {}
    lines.append("- Tests: %d project%s%s" % (len(tests.get("projects") or []), "" if len(tests.get("projects") or []) == 1 else "s",
                                             ", %d driving the UI" % len(tests["ui"]) if tests.get("ui") else ""))
    if d.get("agentDocs"):
        lines.append("- Agent docs: %s" % ", ".join(d["agentDocs"]))
    lines.append("")
    lines.append("Run with `--json` for every claim's evidence.")
    return "\n".join(lines) + "\n"


def parser():
    p = argparse.ArgumentParser(prog="detect.py", description="Report what a MAUI desktop project already has.")
    p.add_argument("--root", default=".", help="the project folder (default: the current folder)")
    p.add_argument("--json", action="store_true", help="print the detection object as JSON")
    p.add_argument("--out", help="also write the detection object (JSON) to this file")
    return p


def main(argv=None):
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if not os.path.isdir(args.root):
        sys.stderr.write("detect.py: --root %s isn't a folder\n" % args.root)
        return EXIT_USAGE
    result = detect.scan(args.root)
    if args.out:
        try:
            jsonio.dump(result, args.out)
        except OSError as e:
            sys.stderr.write("detect.py: can't write %s: %s\n" % (args.out, e))
            return EXIT_USAGE
    if args.json:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    else:
        sys.stdout.write(summary(result))
        if args.out:
            sys.stdout.write("Wrote %s.\n" % args.out.replace(os.sep, "/"))
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
