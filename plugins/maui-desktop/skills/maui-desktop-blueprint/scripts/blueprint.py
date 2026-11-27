#!/usr/bin/env python3
"""blueprint.py: draft, check and record an app's desktop blueprint, ``desktop-blueprint.json`` (CONTRACT.md 2, 7.2).

    blueprint.py init      [--root .] [--out desktop-blueprint.json] [--kind K] [--name N] [--id ID]
                           [--platforms macos,windows,linux]
    blueprint.py check     [--blueprint F] [--json]
    blueprint.py questions [--blueprint F] [--root .]
    blueprint.py set PATH=VALUE ... --reason TEXT [--by user|proposal] [--blueprint F]
    blueprint.py confirm   --note TEXT [--blueprint F]
    blueprint.py gaps      [--blueprint F] [--root .] [--out docs/desktop/gap-report.md] [--print]
    blueprint.py show      [--blueprint F] [--json]

``init`` detects the project and writes a draft: the defaults for the kind (``monitor`` when a tray icon is
found, else ``tool``), overridden by what's there. ``questions`` prints the interview for every undecided field,
each with the proposed answer and why, as markdown the agent turns into one message. ``set`` records answers
(``VALUE`` is JSON such as ``true``, ``"x"``, ``["a"]`` or ``{"scheme": "x"}``; anything else, a bare number
such as ``14.0`` included, is a string; ``null`` removes the field so its default applies) and appends one
decisions-log entry per field. ``confirm`` marks the blueprint as approved, on the user's own word only.
``gaps`` writes the gap report: each seam, where the project is now, the blueprint's target, the size of the
move and the skill that makes it.

The move sizes (a measure of how much code changes, not of time):

- ``none``: the project already does what the blueprint asks.
- ``S``: one new file or setting, or a change in one place.
- ``M``: a handful of files, or the same change once per platform.
- ``L``: restructuring projects, or touching most pages or files.

Per seam: UI sharing into a class library from links or symlinks is L, from one project (or nothing visible) M.
Navigation or page chrome moving to a declared contract is M. Icons scale with the files naming them (up to 3 S,
up to 30 M, more L); design tokens with the raw colours (up to 20 S, 150 M, more L; with a tokens file already
there, up to 50 S). Platform styling: no selectors yet S; hand-written platform selectors becoming token blocks M
up to 50, else L. Dialogs moving shape: M up to 15, else L (a session with a few web overlays left, S). Menus:
S for one platform out of step or a missing command palette, M for more. Windows: one window to several M, the
other way S. An integration missing everywhere is its base size (tray, deep links, file types, global hotkey,
context menus and auto-update M; the rest S), one size smaller when it already works somewhere. Distribution: S
for one missing channel or signing identity, M for 2-3, L beyond.

Exit codes: 0 done; 1 check errors (check, confirm); 2 refused (init onto an existing file); 3 usage or
environment (no blueprint, invalid JSON, a schema violation in the input or in what ``set`` would write).
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mauidesktop_lib import blueprint as bpl  # noqa: E402
from mauidesktop_lib import detect  # noqa: E402
from mauidesktop_lib import findings as fnd  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "desktop-blueprint.schema.json")

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

DEFAULT_BLUEPRINT = "desktop-blueprint.json"
DEFAULT_GAPS = "docs/desktop/gap-report.md"
NAMES = bpl.PLATFORM_NAMES
SKILLS = {
    "UI sharing": "maui-desktop-shell", "Navigation": "maui-desktop-shell", "Page chrome": "maui-desktop-shell",
    "Menus and shortcuts": "maui-desktop-shell", "Windows": "maui-desktop-shell",
    "Icons": "maui-desktop-design", "Design tokens": "maui-desktop-design", "Platform styling": "maui-desktop-design",
    "Dialogs": "maui-desktop-dialogs", "Distribution": "maui-desktop-ship",
}
INTEGRATION_SKILL = "maui-desktop-integrations"
INTEGRATION_LABELS = {
    "tray": "Tray icon", "closeToTray": "Keep running when closed", "launchAtLogin": "Start at login",
    "notifications": "Notifications", "badge": "Dock or taskbar badge", "progress": "Taskbar progress",
    "singleInstance": "Single instance", "deepLinks": "Deep links", "fileTypes": "File types",
    "globalHotkey": "Global hotkey", "contextMenus": "Native context menus", "fileDrop": "File drop",
    "windowState": "Window size and position", "autoUpdate": "Auto-update",
}
INTEGRATION_SIZE = {"tray": "M", "deepLinks": "M", "fileTypes": "M", "globalHotkey": "M", "contextMenus": "M",
                    "autoUpdate": "M"}
UNDETECTED = ("closeToTray",)
SIZES = ("none", "S", "M", "L")


class UsageError(Exception):
    """Exit 3 with this message."""


# --- loading --------------------------------------------------------------------------------------------

def load_schema():
    try:
        return jsonio.load(SCHEMA_PATH)
    except (OSError, jsonio.JsonError) as e:
        raise UsageError("the skill's schema can't be read: %s" % e)


def load_blueprint(path, require_valid=True):
    """``(blueprint, schema findings)``. Raises ``UsageError`` when it's missing, not JSON, or (with
    ``require_valid``) breaks the schema."""
    if not os.path.isfile(path):
        raise UsageError("no blueprint at %s (run blueprint.py init first, or pass --blueprint)" % path)
    try:
        bp = bpl.load(path)
    except jsonio.JsonError as e:
        raise UsageError(str(e))
    except OSError as e:
        raise UsageError("can't read %s: %s" % (path, e))
    if not isinstance(bp, dict):
        raise UsageError("%s isn't a JSON object" % path)
    problems = bpl.validate(bp, load_schema())
    if problems and require_valid:
        raise UsageError("%s doesn't match the schema (run blueprint.py check):\n%s" % (
            path, "\n".join("  %s: %s" % (f.where, f.message) for f in problems)))
    return bp, problems


def scan_root(root):
    if not os.path.isdir(root):
        raise UsageError("--root %s isn't a folder" % root)
    return detect.scan(root)


def write_blueprint(bp, path):
    jsonio.dump(bpl.ordered(bp), path)


def today(args):
    return getattr(args, "date", None) or datetime.date.today().strftime("%Y-%m-%d")


def rel(path):
    """A path for messages: relative to the current folder when it's inside it, else absolute; ``/`` always."""
    try:
        out = os.path.relpath(path)
    except ValueError:
        out = os.path.abspath(path)
    if out.startswith(".."):
        out = os.path.abspath(path)
    return out.replace(os.sep, "/")


# --- formatting values ----------------------------------------------------------------------------------

def yes_no(v):
    return "yes" if v else "no"


def fmt(val):
    """A field's value in words: yes/no, comma lists, ``platform: value`` pairs."""
    if val is None:
        return "(not set)"
    if isinstance(val, bool):
        return yes_no(val)
    if isinstance(val, list):
        if not val:
            return "none"
        if all(isinstance(x, dict) and "extension" in x for x in val):
            return ", ".join(x["extension"] + (" (%s)" % x["role"] if x.get("role") else "") for x in val)
        return ", ".join(str(x) for x in val)
    if isinstance(val, dict):
        if "scheme" in val and "platforms" not in val:
            return "yes, scheme `%s`" % val.get("scheme")
        if "platforms" in val:
            extra = ", scheme `%s`" % val["scheme"] if "scheme" in val else ""
            return "yes on %s%s" % (", ".join(NAMES.get(p, p) for p in val["platforms"]), extra)
        return "; ".join("%s: %s" % (NAMES.get(k, k), fmt(v)) for k, v in val.items() if not k.startswith("$"))
    return str(val)


def cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


# --- init -----------------------------------------------------------------------------------------------

def cmd_init(args):
    det = scan_root(args.root)
    out = args.out or os.path.join(args.root, DEFAULT_BLUEPRINT)
    if os.path.exists(out):
        sys.stderr.write("blueprint.py init: %s exists; it's the user's, so nothing was written "
                         "(edit it with blueprint.py set, or pass --out)\n" % rel(out))
        return EXIT_REFUSED
    overrides = {}
    if args.name:
        overrides["app.name"] = args.name
    if args.id:
        overrides["app.id"] = args.id
    if args.platforms:
        plats = [p.strip().lower() for p in args.platforms.split(",") if p.strip()]
        bad = [p for p in plats if p not in bpl.DESKTOP]
        if bad or not plats:
            raise UsageError("--platforms takes macos, windows and linux, comma-separated (not %s)" % ", ".join(bad or ["nothing"]))
        overrides["platforms"] = plats
    bp = bpl.draft(det, kind=args.kind, overrides=overrides)
    problems = bpl.validate(bp, load_schema())
    if problems:
        raise UsageError("the draft doesn't match the schema, so nothing was written:\n%s" % "\n".join(
            "  %s: %s" % (f.where, f.message) for f in problems))
    write_blueprint(bp, out)
    on = [NAMES[p] for p in bpl.enabled(bp, desktop_only=True)]
    tray = bool((det.get("integrations") or {}).get("tray"))
    why = "given" if args.kind else ("a tray icon was found" if tray else "no tray icon found")
    print("Wrote %s: a draft for %s, a %s app (%s) on %s%s." % (
        rel(out), bp["app"]["name"], bp["app"]["kind"], why, ", ".join(on),
        ", detected from %d project%s" % (len(det["projects"]), "" if len(det["projects"]) == 1 else "s")
        if det.get("projects") else " (a new app: no projects found)"))
    notes = bpl.consistency(bp)
    for f in notes:
        print("  %s [%s] %s" % (f.severity, f.id, f.message))
    print("Nothing is decided yet. Next: blueprint.py questions, then ask the user in one message.")
    return EXIT_OK


# --- check ----------------------------------------------------------------------------------------------

def check_findings(bp, schema_findings):
    if schema_findings:
        return list(schema_findings)
    return bpl.consistency(bp)


def cmd_check(args):
    bp, schema_findings = load_blueprint(args.blueprint, require_valid=False)
    found = check_findings(bp, schema_findings)
    fnd.print_findings(found, json_output=args.json, blueprint=args.blueprint.replace(os.sep, "/"),
                       summary=None if args.json else "Checked %s." % rel(args.blueprint))
    return fnd.exit_code(found)


# --- questions ------------------------------------------------------------------------------------------

def _evidence_for(path, det):
    """Detection's evidence for a field, most telling first."""
    if not det:
        return []
    shell = det.get("shell") or {}
    top = path.split(".")
    if path.startswith("integrations."):
        return (det.get("integrations") or {}).get(top[1]) or []
    table = {
        "app.kind": (det.get("integrations") or {}).get("tray") or [],
        "chrome.sidebar": shell.get("sidebarEvidence") or [],
        "chrome.toolbar": (shell.get("toolbar") or {}).get("evidence") or [],
        "chrome.menuBar": shell.get("menuBarEvidence") or [],
        "chrome.dialogs": (det.get("dialogs") or {}).get("evidence") or [],
        "chrome.commandPalette": shell.get("commandPalette") or [],
        "chrome.multiWindow": shell.get("multiWindow") or [],
        "stack.sharing": (det.get("sharing") or {}).get("evidence") or [],
        "look.fidelity": (det.get("design") or {}).get("evidence") or [],
        "engineering.devflow": (det.get("engineering") or {}).get("devflow") or [],
        "engineering.gallery": (det.get("engineering") or {}).get("gallery") or [],
        "distribution.channels": (det.get("distribution") or {}).get("evidence") or [],
        "distribution.signing": (det.get("distribution") or {}).get("evidence") or [],
    }
    if path == "look.fidelity":
        selectors = (det.get("design") or {}).get("platformSelectors") or {}
        counted = ["%d .platform-%s selectors" % (n, p) for p, n in sorted(selectors.items(), key=lambda kv: -kv[1]) if n]
        return ["the stylesheets have " + ", ".join(counted)] if counted else []
    if path in table:
        return table[path]
    if path == "engineering.devHost":
        dh = (det.get("heads") or {}).get("devhost")
        return [dh] if dh else []
    return []


def _detected_value(path, det, kind, cache):
    if not det or not det.get("projects"):
        return None
    if "draft" not in cache:
        cache["draft"] = bpl.draft(det, kind=kind)
    return bpl.get(cache["draft"], path, None)


def _why(path, kind, cur, dflt, found, ev, has_project):
    """The reason text for a value against its default and what detection proposes."""
    default_text = None
    if dflt is not None and cur == dflt:
        default_text = "the default for a %s app" % kind if path in bpl.KIND_FIELDS else "the default for every kind of app"
    if found is not None and cur == found and ev:
        if default_text:
            return "%s, and the project has it (%s)" % (default_text, ev[0])
        return "found in the project: %s" % ev[0]
    if default_text:
        if path.startswith("integrations.") and has_project and cur not in (False, None, [], "web"):
            return "%s; not found in the project yet" % default_text
        return default_text
    if found is not None and cur == found:
        return "what the project has"
    return "proposed earlier (see the decisions log)"


def _reason(bp, path, det, cache):
    """Why a field holds what it does, in one line: the user's word, what the project has, or the default."""
    if bpl.is_decided(bp, path):
        return "you said so"
    kind = bpl.kind_of(bp)
    cur = bpl.get(bp, path, None)
    if cur is None:
        cur = bpl.value(bp, path)
    has_project = bool(det and det.get("projects"))
    ev = _evidence_for(path, det)
    if path == "app.kind":
        if ev and cur == "monitor":
            return "a tray icon was found (%s)" % ev[0]
        return "no tray icon was found" if has_project else "the default"
    if path == "app.existing":
        n = len((det or {}).get("projects") or [])
        return "found %d project%s" % (n, "" if n == 1 else "s") if n else "no projects found"
    if path.startswith("platforms.") and path.endswith(".enabled"):
        plat = path.split(".")[1]
        head = ((det or {}).get("heads") or {}).get(plat)
        if head:
            return "found the %s head (%s)" % (NAMES[plat], head)
        return "no %s head found" % NAMES[plat] if has_project else "every desktop platform, to start"
    if path.startswith("platforms.") and path.endswith(".minimum"):
        plat = path.split(".")[1]
        mins = ((det or {}).get("app") or {}).get("minimums") or {}
        if mins.get(plat) and mins.get(plat) == cur:
            return "the %s head's SupportedOSPlatformVersion" % NAMES[plat]
        return "the skills' default"
    if path == "stack.sharing" and cur in ("links", "symlinks", "single", "unknown") and has_project:
        return "what the project does today%s; a Razor class library is recommended (see the gap report)" % (
            " (%s)" % ev[0] if ev else "")
    if path == "stack.sharing" and cur == "rcl" and not has_project:
        return "recommended for a new app"
    found = _detected_value(path, det, kind, cache)
    return _why(path, kind, cur, bpl.default_value(kind, path), found, ev, has_project)


def _platform_reasons(bp, path, plats, det, cache):
    """A per-platform field's reasons, grouped: ``Linux: you said so; macOS, Windows: the default…``."""
    kind = bpl.kind_of(bp)
    has_project = bool(det and det.get("projects"))
    ev = _evidence_for(path, det)
    if not any(bpl.is_decided(bp, "%s.%s" % (path, p)) for p in plats):
        return _reason(bp, path, det, cache)
    found_all = _detected_value(path, det, kind, cache)
    groups = []
    for p in plats:
        if bpl.is_decided(bp, "%s.%s" % (path, p)):
            text = "you said so"
        else:
            cur = bpl.value(bp, path, p)
            found = found_all.get(p) if isinstance(found_all, dict) else found_all
            dflt = bpl.default_value(kind, path, p)
            if p == "web":
                cur, found, dflt = bpl.for_web(path, cur), bpl.for_web(path, found), bpl.for_web(path, dflt)
            text = _why(path, kind, cur, dflt, found, ev, has_project)
        for g in groups:
            if g[1] == text:
                g[0].append(NAMES[p])
                break
        else:
            groups.append(([NAMES[p]], text))
    return "; ".join("%s: %s" % (", ".join(names), text) for names, text in groups)


def _shown(bp, path, p):
    v = bpl.value(bp, path, p)
    return bpl.for_web(path, v) if p == "web" else v


def _platform_summary(bp, todo, what):
    on = bpl.enabled(bp, desktop_only=True)
    if what == "enabled":
        home = [p for p in bpl.DESKTOP if bpl.get(bp, "platforms.%s.home" % p, False) is True]
        off = [NAMES[p] for p in bpl.DESKTOP if p not in on]
        return "%s%s%s" % (", ".join(NAMES[p] for p in on) or "none",
                           "; home: %s" % NAMES[home[0]] if home else "; no home platform",
                           "; off: %s" % ", ".join(off) if off else "")
    if what == "minimum":
        return ", ".join("%s %s" % (NAMES[p], bpl.get(bp, "platforms.%s.minimum" % p, "?"))
                         for p in on if p in bpl.DEFAULT_MINIMUM) or "none needed"
    return ""


def render_questions(bp, det, blueprint_path):
    cache = {}
    todo = bpl.open_questions(bp)
    lines = []
    name = (bp.get("app") or {}).get("name") or "the app"
    total = sum(len(q["questions"]) for q in bpl.QUESTIONS)
    lines.append("# Desktop blueprint: open questions for %s" % name)
    lines.append("")
    if not todo:
        lines.append("Every question in `%s` has been answered (%d decided field%s). If the user approves the "
                     "whole blueprint, run `blueprint.py confirm --note \"<their words>\"`." % (
                         rel(blueprint_path), len(bp.get("decided") or []), "" if len(bp.get("decided") or []) == 1 else "s"))
        return "\n".join(lines) + "\n"
    lines.append("%d of %d questions are open in `%s` (a %s app, %s). Ask them in ONE message, each with its "
                 "proposed answer and reason; the user corrects what's wrong. Record each answer in the user's words: "
                 "`blueprint.py set PATH=VALUE --reason \"<their words>\"`." % (
                     len(todo), total, rel(blueprint_path), bpl.kind_of(bp),
                     "existing" if (bp.get("app") or {}).get("existing") else "new"))
    group = None
    n = 0
    for gname, q, paths in todo:
        if gname != group:
            group = gname
            lines.append("")
            lines.append("## %s" % gname)
            lines.append("")
        n += 1
        options = " / ".join(q["options"])
        head = "%d. **%s**" % (n, q["ask"])
        fields = ", ".join("`%s`" % p for p in q["paths"])
        lines.append("%s (%s%s)" % (head, fields, ": " + options if options else ""))
        if q["id"] == "platforms":
            lines.append("   - Proposed: %s. Why: %s." % (
                _platform_summary(bp, paths, "enabled"),
                "; ".join(_reason(bp, "platforms.%s.enabled" % p, det, cache) for p in bpl.DESKTOP)))
            continue
        if q["id"] == "minimums":
            reasons = sorted(set(_reason(bp, p, det, cache) for p in paths))
            lines.append("   - Proposed: %s. Why: %s." % (_platform_summary(bp, paths, "minimum"), "; ".join(reasons)))
            continue
        for path in paths:
            if q["perPlatform"]:
                on = bpl.enabled(bp, desktop_only=True)
                raw = bpl.get(bp, path, None)
                if isinstance(raw, dict) and "web" in raw and "web" in bpl.enabled(bp):
                    on = on + ["web"]
                per = ", ".join("%s %s" % (NAMES[p], fmt(_shown(bp, path, p))) for p in on)
                lines.append("   - `%s` proposed: %s. Why: %s." % (path, per, _platform_reasons(bp, path, on, det, cache)))
            else:
                lines.append("   - `%s` proposed: %s. Why: %s." % (
                    path, fmt(bpl.value(bp, path)), _reason(bp, path, det, cache)))
    lines.append("")
    return "\n".join(lines) + "\n"


def cmd_questions(args):
    bp, _ = load_blueprint(args.blueprint)
    det = scan_root(args.root) if os.path.isdir(args.root) else None
    sys.stdout.write(render_questions(bp, det, args.blueprint))
    return EXIT_OK


# --- set and confirm ------------------------------------------------------------------------------------

_RESERVED = ("version", "confirmedByUser", "decided")


def parse_assignment(text):
    """``PATH=VALUE`` -> ``(path, value)``: VALUE as JSON when it parses (a number stays a string), else the
    bare text. Raises ``UsageError``."""
    if "=" not in text:
        raise UsageError("expected PATH=VALUE, not %r" % text)
    path, raw = text.split("=", 1)
    path = path.strip()
    try:
        bpl.split(path)
    except ValueError as e:
        raise UsageError(str(e))
    if path.split(".")[0] in _RESERVED:
        raise UsageError("%s can't be set this way%s" % (
            path, " (only blueprint.py confirm sets it, on the user's word)" if path == "confirmedByUser" else
            " (set --by user records decisions)" if path.startswith("decided") else ""))
    raw = raw.strip()
    try:
        val = json.loads(raw)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            val = raw
    except ValueError:
        val = raw
    return path, val


def _unset(bp, path):
    parts = path.split(".")
    node = bp
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def cmd_set(args):
    if not args.assignments:
        raise UsageError("give at least one PATH=VALUE")
    if not (args.reason or "").strip():
        raise UsageError("--reason is required: quote the user where they gave one")
    bp, _ = load_blueprint(args.blueprint)
    changes = []
    for text in args.assignments:
        path, val = parse_assignment(text)
        try:
            if val is None:
                was = bpl.effective(bp, path)
                _unset(bp, path)
            else:
                was = bpl.set_path(bp, path, val)
        except ValueError as e:
            raise UsageError(str(e))
        changes.append((path, val, was))
    problems = bpl.validate(bp, load_schema())
    if problems:
        raise UsageError("that would break the schema, so nothing was written:\n%s" % "\n".join(
            "  %s: %s" % (f.where, f.message) for f in problems))
    reset = False
    if args.by == "user":
        for path, _v, _w in changes:
            bpl.mark_decided(bp, path)
    elif bp.get("confirmedByUser"):
        bp["confirmedByUser"] = False
        reset = True
    write_blueprint(bp, args.blueprint)
    log = bpl.log_path(bp, args.blueprint)
    for path, val, was in changes:
        bpl.append_decision(log, path, val, was, args.by, args.reason, today(args))
        print("Set %s = %s (was %s), by %s." % (path, bpl.format_value(val), bpl.format_value(was), args.by))
    print("Logged %d decision%s in %s." % (len(changes), "" if len(changes) == 1 else "s", rel(log)))
    if reset:
        print("confirmedByUser is now false: the user hasn't approved this proposal yet.")
    after = bpl.consistency(bp)
    for f in after:
        if f.severity != "info":
            print("  %s [%s] %s" % (f.severity, f.id, f.message))
    return EXIT_OK


def cmd_confirm(args):
    if not (args.note or "").strip():
        raise UsageError("--note is required: the user's own words approving the blueprint")
    bp, schema_findings = load_blueprint(args.blueprint, require_valid=False)
    found = check_findings(bp, schema_findings)
    if fnd.errors(found):
        fnd.print_findings(found, summary="Not confirmed: fix the errors first (nothing was written).")
        return EXIT_ERRORS
    was = bool(bp.get("confirmedByUser"))
    bp["confirmedByUser"] = True
    write_blueprint(bp, args.blueprint)
    log = bpl.log_path(bp, args.blueprint)
    bpl.append_decision(log, "confirmedByUser", True, was, "user", args.note, today(args))
    print("Confirmed %s; logged in %s." % (rel(args.blueprint), rel(log)))
    return EXIT_OK


# --- gaps -----------------------------------------------------------------------------------------------

def _size_by(count, s_max, m_max):
    if count <= s_max:
        return "S"
    return "M" if count <= m_max else "L"


def _smaller(size):
    return {"L": "M", "M": "S"}.get(size, "S")


def _plat_list(plats):
    return ", ".join(NAMES.get(p, p) for p in plats)


def _row(seam, now, target, move, why, skill=None):
    return {"seam": seam, "now": now, "target": target, "move": move, "skill": skill or SKILLS[seam], "why": why}


def gap_sharing(bp, det):
    kind = (det.get("sharing") or {}).get("kind") or "unknown"
    ev = (det.get("sharing") or {}).get("evidence") or []
    links = any("<ProjectReference" not in e and re.search(r"\b(?:Include|Update)=", e) for e in ev)
    words = {"rcl": "Razor class library", "links": "compile links", "symlinks": "symlinks", "single": "one project",
             "unknown": "not detected"}
    now = words.get(kind, kind)
    if kind == "symlinks" and links:
        now = "symlinks + compile links"
    target_kind = bpl.value(bp, "stack.sharing") or "rcl"
    target = words.get(target_kind, target_kind)
    if target_kind == kind:
        return _row("UI sharing", now, target, "none",
                    "The heads already share the UI the way the blueprint says (%s)." % target)
    if target_kind == "rcl":
        move = "L" if kind in ("links", "symlinks") else "M"
        how = {"links": "compile items that reach into another project", "symlinks": "symlinked folders",
               "single": "one project", "unknown": "no mechanism the detector could see"}.get(kind, kind)
        why = ("Today the heads share the UI through %s. Move the shared pages, components and static files into "
               "one Razor class library that every head references, then delete the links%s." % (
                   how, " and symlinks" if kind == "symlinks" else ""))
        if kind == "single":
            why = ("Today one project holds both a head and the UI. Move the pages, components and static files into "
                   "a Razor class library so each new head (and the browser dev host) can reference it.")
        return _row("UI sharing", now, target, move, why)
    return _row("UI sharing", now, target, "M",
                "The blueprint keeps %s rather than a Razor class library; make every head use that one way." % target)


def _native_anywhere(bp, path):
    return any(bpl.value(bp, path, p) == "native" for p in bpl.enabled(bp, desktop_only=True))


def gap_navigation(bp, det):
    nav = (det.get("shell") or {}).get("navigation") or {}
    kind = nav.get("kind") or "unknown"
    heads = [p for p in bpl.DESKTOP if (det.get("heads") or {}).get(p)]
    now = {"manifest": "a navigation manifest", "per-head": "sidebar items built in each head (%d)" % len(heads),
           "web": "NavLink markup only", "unknown": "not detected"}.get(kind, kind)
    if _native_anywhere(bp, "chrome.sidebar"):
        target = "one navigation manifest in shared code"
        if kind == "manifest":
            return _row("Navigation", now, target, "none", "The pages are declared once; every sidebar reads the list.")
        why = {"per-head": "Each head builds its own sidebar list, so adding a page means an edit per head. Declare the "
                           "pages once (a navigation manifest in shared code) and let every native sidebar and the web "
                           "NavLinks read it.",
               "web": "Navigation lives only in web markup, but the blueprint wants a native sidebar. Declare the pages "
                      "once in shared code so each head's native sidebar and the web markup are built from one list."}
        return _row("Navigation", now, target, "M", why.get(kind, "Declare the pages once in shared code (a navigation "
                                                                "manifest) for the native sidebars to read."))
    target = "web navigation" if any(bpl.value(bp, "chrome.sidebar", p) == "web" for p in bpl.enabled(bp)) else "no sidebar"
    if kind in ("web", "manifest") or target == "no sidebar":
        return _row("Navigation", now, target, "none", "Nothing to move: the blueprint has no native sidebar.")
    return _row("Navigation", now, target, "S", "The blueprint keeps the sidebar in web content; the per-head native "
                                                "lists can go once the web sidebar covers every page.")


def gap_page_chrome(bp, det):
    tb = (det.get("shell") or {}).get("toolbar") or {}
    kind = tb.get("kind") or "none"
    sf = any("SfSymbol" in e for e in tb.get("evidence") or [])
    now = {"declared": "declared page chrome", "imperative": "an imperative toolbar service%s" % (
        " (SF Symbol names in the action)" if sf else ""), "web": "web toolbar markup", "none": "no toolbar"}.get(kind, kind)
    if _native_anywhere(bp, "chrome.toolbar"):
        target = "declared page chrome (each page states its toolbar)"
        if kind == "declared":
            return _row("Page chrome", now, target, "none", "Pages already state their toolbar; each head draws it.")
        why = {"imperative": "Pages call a toolbar service to set native items, and the action names a platform icon. "
                             "Let each page declare its chrome (title, actions, search) as data in shared code, with "
                             "icon names from design/icons.json, and let each head draw it natively."}
        return _row("Page chrome", now, target, "M", why.get(kind, "Give each page a declared chrome record (title, "
                                                                   "actions, search) that every head draws natively."))
    target = "a web toolbar in the page" if any(bpl.value(bp, "chrome.toolbar", p) == "web" for p in bpl.enabled(bp)) else "no toolbar"
    if kind in ("web", "none") or target == "no toolbar":
        return _row("Page chrome", now, target, "none", "Nothing to move: the blueprint has no native toolbar.")
    return _row("Page chrome", now, target, "S", "The blueprint keeps the toolbar in web content: drop the native items.")


def gap_icons(bp, det):
    des = det.get("design") or {}
    target = "design/icons.json: one name per icon, mapped for every platform"
    if des.get("iconsJson"):
        return _row("Icons", "design/icons.json", target, "none", "Every icon is already named once and mapped per platform.")
    srcs = des.get("iconSources") or {}
    words = {"sf-symbols": "SF Symbol names", "font-awesome": "Font Awesome classes", "fluent-glyphs": "Fluent glyphs",
             "gtk-icon-names": "GTK icon names"}
    files = sum(srcs.values())
    if not files:
        return _row("Icons", "none found", target, "S", "Start design/icons.json before the first icon goes in; "
                                                         "nothing exists to migrate.")
    now = "%s in code (%d file%s)" % (", ".join(words.get(k, k) for k in srcs), files, "" if files == 1 else "s")
    move = _size_by(files, 3, 30)
    return _row("Icons", now, target, move,
                "Icons are named per platform where they're used. List each icon once in design/icons.json with its SF "
                "Symbol, Windows and GTK names and an SVG, then replace the names in code with the generated ones.")


def gap_tokens(bp, det):
    des = det.get("design") or {}
    raw = des.get("rawHex") or 0
    target = "design/tokens.json generating the CSS (and C#)"
    if des.get("tokensJson"):
        if not raw:
            return _row("Design tokens", "design/tokens.json", target, "none", "Colours and sizes come from the tokens file.")
        return _row("Design tokens", "design/tokens.json, %d raw hex colour%s left" % (raw, "" if raw == 1 else "s"),
                    target, _size_by(raw, 50, 150),
                    "The tokens file exists but some stylesheets still hard-code colours; move them to roles in the "
                    "tokens file and let the lint gate keep them out.")
    now = "hand-kept CSS, %d raw hex colour%s" % (raw, "" if raw == 1 else "s") if raw else "no colours found"
    return _row("Design tokens", now, target, _size_by(raw, 20, 150) if raw else "S",
                "Colours and sizes are written by hand where they're used. Write them once in design/tokens.json (light "
                "and dark roles, the scale), generate the CSS from it, and replace the raw values with the variables."
                if raw else "Start design/tokens.json before the first colour goes in.")


def gap_styling(bp, det):
    des = det.get("design") or {}
    sel = des.get("platformSelectors") or {}
    on = bpl.enabled(bp, desktop_only=True)
    fid = {p: bpl.value(bp, "look.fidelity", p) or "adaptive" for p in on}
    groups = {}
    for p in on:
        groups.setdefault(fid[p], []).append(NAMES[p])
    words = {"unified": "one look (fonts and shortcut labels adapt)", "adaptive": "a token block per platform",
             "native-faithful": "token blocks + a component layer per platform"}
    if len(groups) == 1:
        target = words[list(groups)[0]]
    else:
        target = "; ".join("%s %s" % (", ".join(v), k) for k, v in groups.items())
    total = sum(sel.get(p, 0) for p in on)
    tplats = des.get("tokenPlatforms") or []
    if tplats:
        now = "token blocks for %s" % _plat_list(tplats)
    elif total:
        now = "%d hand-written platform selectors (%s)" % (total, ", ".join("%s %d" % (NAMES[p], sel.get(p, 0)) for p in on))
    else:
        now = "none"
    if all(v == "unified" for v in fid.values()):
        if total:
            return _row("Platform styling", now, target, "S", "The blueprint wants one look: drop the per-platform "
                                                              "selectors, keeping only fonts and shortcut labels.")
        return _row("Platform styling", now, target, "none", "One look everywhere, as the blueprint asks.")
    if tplats and set(on) <= set(tplats):
        faithful = [p for p in on if fid[p] == "native-faithful" and not sel.get(p)]
        if faithful:
            return _row("Platform styling", now, target, "M", "The tokens adapt per platform; %s also needs its own "
                                                              "component layer (control shapes)." % _plat_list(faithful))
        return _row("Platform styling", now, target, "none", "The tokens already carry a block per platform.")
    if not total:
        return _row("Platform styling", now, target, "S", "Add a platform block to the tokens file for each platform "
                                                          "(font, base size, radii, control heights).")
    return _row("Platform styling", now, target, _size_by(total, 0, 50),
                "Platform differences are hand-written selectors in the stylesheet. Move what are really values (fonts, "
                "radii, heights, accents) into per-platform token blocks; keep selectors only for real shape changes%s." % (
                    " on %s" % _plat_list([p for p in on if fid[p] == "native-faithful"])
                    if any(fid[p] == "native-faithful" for p in on) else ""))


def gap_dialogs(bp, det):
    dlg = det.get("dialogs") or {}
    kind = dlg.get("kind") or "none"
    count = dlg.get("count") or 0
    overlays = dlg.get("webOverlays") or 0
    now = {"session": "a dialog session (%d)" % count, "page-subclass": "a native page class per dialog (%d)" % count,
           "web": "web overlays in pages (%d)" % count, "alerts-only": "alerts only", "none": "none"}.get(kind, kind)
    if overlays and kind != "web":
        now += ", %d web overlay%s" % (overlays, "" if overlays == 1 else "s")
    want = bpl.value(bp, "chrome.dialogs") or "native-frame"
    target = {"native-frame": "a dialog session: native frame, web body", "web": "web overlays",
              "mixed": "native frames for forms, web overlays for the rest"}[want]
    if want == "native-frame":
        if kind == "session":
            if overlays:
                return _row("Dialogs", now, target, "S", "Dialogs run through the session; move the remaining web "
                                                         "overlay%s onto it." % ("" if overlays == 1 else "s"))
            return _row("Dialogs", now, target, "none", "Dialogs already run through one session with a native frame.")
        if kind == "page-subclass":
            return _row("Dialogs", now, target, _size_by(count, 0, 15),
                        "Each dialog is its own native page class around a web view. Replace them with one dialog "
                        "request the body drives (title, buttons, size), so a dialog is just a component and the frame "
                        "is drawn once per platform.")
        if kind == "web":
            return _row("Dialogs", now, target, _size_by(count, 0, 15),
                        "Dialogs are overlays inside the page. Present them through one dialog session so each opens in "
                        "a native frame (title and buttons) with the web body inside.")
        return _row("Dialogs", now, target, "S", "Build the dialog session before the first dialog.")
    if want == "web":
        if kind == "web":
            return _row("Dialogs", now, target, "none", "Dialogs are web overlays, as the blueprint asks.")
        return _row("Dialogs", now, target, "M" if kind in ("session", "page-subclass") else "S",
                    "The blueprint keeps dialogs in web content: one overlay component replaces the native frames.")
    if kind in ("session", "page-subclass"):
        return _row("Dialogs", now, target, "none", "Forms have native frames and the rest can stay web overlays.")
    return _row("Dialogs", now, target, "M" if kind == "web" else "S",
                "Give forms a native frame through a dialog session; small notices can stay web overlays.")


def gap_menus(bp, det):
    shell = det.get("shell") or {}
    have = shell.get("menuBar") or {}
    on = bpl.enabled(bp, desktop_only=True)
    want = {p: bpl.value(bp, "chrome.menuBar", p) or "none" for p in on}
    hw = {"custom-items": "custom items", "default": "the default menu", "none": "none", None: "no head"}
    now = "; ".join("%s %s" % (NAMES[p], hw.get(have.get(p), have.get(p))) for p in on)
    target = "; ".join("%s %s" % (NAMES[p], want[p]) for p in on)
    out_of_step = []
    for p in on:
        h = have.get(p)
        if want[p] in ("standard", "full") and h != "custom-items":
            out_of_step.append(NAMES[p])
        elif want[p] == "none" and h == "custom-items":
            out_of_step.append(NAMES[p])
    palette_wanted = bool(bpl.value(bp, "chrome.commandPalette"))
    palette_found = bool(shell.get("commandPalette"))
    now += "; command palette %s" % ("found" if palette_found else "not found")
    target += "; command palette %s" % yes_no(palette_wanted)
    misses = len(out_of_step) + (1 if palette_wanted and not palette_found else 0)
    if not misses:
        return _row("Menus and shortcuts", now, target, "none", "The menus already match the blueprint.")
    parts = []
    if out_of_step:
        parts.append("The menu bar on %s doesn't match the blueprint yet: declare the commands once (name, shortcut, "
                     "icon) and build each platform's menu from them." % ", ".join(out_of_step))
    if palette_wanted and not palette_found:
        parts.append("No command palette was found and the blueprint wants one: build it on %s declared command "
                     "list the menus read." % ("the same" if out_of_step else "a"))
    return _row("Menus and shortcuts", now, target, "S" if misses == 1 else "M", " ".join(parts))


def gap_windows(bp, det):
    multi_now = bool((det.get("shell") or {}).get("multiWindow"))
    multi = bool(bpl.value(bp, "chrome.multiWindow"))
    settings = bpl.value(bp, "chrome.settings") or "dialog"
    now = "several windows" if multi_now else "one window"
    target = "%s; settings as a %s" % ("several windows" if multi else "one window", settings)
    if multi and not multi_now:
        return _row("Windows", now, target, "M", "The app opens one window today. Give each window its own state and "
                                                 "chrome, and route commands to the focused one.")
    if not multi and multi_now:
        return _row("Windows", now, target, "S", "The project opens extra windows the blueprint doesn't plan for: "
                                                 "keep them, or fold them into the main window.")
    return _row("Windows", now, target, "none", "The window model matches the blueprint.")


def gap_integrations(bp, det):
    rows = []
    found = det.get("integrations") or {}
    plats = det.get("integrationPlatforms") or {}
    for name in bpl.INTEGRATIONS:
        want = bpl.integration_platforms(bp, name)
        if not want:
            continue
        label = INTEGRATION_LABELS[name]
        target = "on: %s" % _plat_list(want)
        links = bpl.value(bp, "integrations.deepLinks")
        if name == "deepLinks" and isinstance(links, dict) and links.get("scheme"):
            target += " (scheme `%s`)" % links["scheme"]
        base = INTEGRATION_SIZE.get(name, "S")
        if name in UNDETECTED:
            rows.append(_row(label, "not detectable from files", target, base,
                             "Check by hand: closing the window should hide it while the tray icon keeps the app "
                             "running.", INTEGRATION_SKILL))
            continue
        where = plats.get(name) or []
        covered = list(want) if "*" in where else [p for p in want if p in where]
        missing_on = [p for p in want if p not in covered]
        named = [p for p in where if p != "*"]
        if not found.get(name):
            now = "not found"
        elif not named:
            now = "found in shared code"
        else:
            now = "found on %s%s" % (_plat_list(named), " and in shared code" if "*" in where else "")
        if not missing_on:
            rows.append(_row(label, now, target, "none", "Already in place on every platform the blueprint asks for.",
                             INTEGRATION_SKILL))
            continue
        move = _smaller(base) if covered else base
        if covered:
            why = "It works on %s but not yet on %s." % (_plat_list(covered), _plat_list(missing_on))
        else:
            why = "Nothing in the project does this yet on %s." % _plat_list(missing_on)
        why += " Put it behind one service in shared code, with each platform's own API in its head."
        rows.append(_row(label, now, target, move, why, INTEGRATION_SKILL))
    return rows


def gap_distribution(bp, det):
    dist = det.get("distribution") or {}
    on = bpl.enabled(bp, desktop_only=True)
    now_parts, target_parts, missing_items = [], [], []
    for p in on:
        tags = dist.get(p) or []
        have = bpl.channels_for(tags, p)
        want = bpl.value(bp, "distribution.channels", p) or []
        sign = bpl.value(bp, "distribution.signing", p)
        now_parts.append("%s %s" % (NAMES[p], ", ".join(tags) if tags else "nothing"))
        target_parts.append("%s %s%s" % (NAMES[p], ", ".join(want) or "none", ", signed" if sign == "available" else ""))
        for c in want:
            if c not in have:
                missing_items.append("%s %s" % (NAMES[p], c))
        if sign == "available":
            signed = ("codesign" in tags) if p == "macos" else ("signing" in tags) if p == "windows" else True
            if not signed:
                missing_items.append("%s signing" % NAMES[p])
    now = "; ".join(now_parts)
    target = "; ".join(target_parts)
    n = len(missing_items)
    if not n:
        return _row("Distribution", now, target, "none", "Every channel the blueprint names is already built.")
    move = "S" if n == 1 else "M" if n <= 3 else "L"
    return _row("Distribution", now, target, move,
                "Not built yet: %s. Each channel is a packaging step in the release workflow, with signing where the "
                "channel needs it." % ", ".join(missing_items))


def gap_rows(bp, det):
    rows = [gap_sharing(bp, det), gap_navigation(bp, det), gap_page_chrome(bp, det), gap_icons(bp, det),
            gap_tokens(bp, det), gap_styling(bp, det), gap_dialogs(bp, det), gap_menus(bp, det), gap_windows(bp, det)]
    rows += gap_integrations(bp, det)
    rows.append(gap_distribution(bp, det))
    return rows


def render_gaps(bp, det, blueprint_path, date):
    rows = gap_rows(bp, det)
    name = (bp.get("app") or {}).get("name") or "the app"
    lines = ["# Desktop gap report: %s" % name, "",
             "Where the project is now against `%s`, seam by seam. Written by `blueprint.py gaps` on %s; run it "
             "again after each move. Move: none, S (a file or a setting), M (a handful of files, or once per "
             "platform), L (restructuring projects, or most pages)." % (os.path.basename(blueprint_path), date), "",
             "| Seam | Now | Target | Move | Skill |", "|---|---|---|---|---|"]
    for r in rows:
        lines.append("| %s | %s | %s | %s | %s |" % (cell(r["seam"]), cell(r["now"]), cell(r["target"]), r["move"],
                                                     r["skill"]))
    for r in rows:
        lines += ["", "## %s" % r["seam"], "", r["why"]]
    return "\n".join(lines) + "\n", rows


def cmd_gaps(args):
    bp, _ = load_blueprint(args.blueprint)
    det = scan_root(args.root)
    if not det.get("projects"):
        print("No .NET projects found under %s: a new app has no gaps to report. Build each seam with its skill "
              "(maui-desktop-shell first)." % args.root.replace(os.sep, "/"))
        return EXIT_OK
    text, rows = render_gaps(bp, det, args.blueprint, today(args))
    if args.print:
        sys.stdout.write(text)
        return EXIT_OK
    out = args.out or os.path.join(args.root, *DEFAULT_GAPS.split("/"))
    folder = os.path.dirname(os.path.abspath(out))
    os.makedirs(folder, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    moves = [r for r in rows if r["move"] != "none"]
    print("Wrote %s: %d seam%s, %d to move (%s)." % (
        rel(out), len(rows), "" if len(rows) == 1 else "s", len(moves),
        ", ".join("%s %s" % (r["seam"], r["move"]) for r in moves) or "nothing"))
    return EXIT_OK


# --- show -----------------------------------------------------------------------------------------------

SHOW_PER_PLATFORM = ("chrome.sidebar", "chrome.toolbar", "chrome.menuBar", "look.fidelity")
SHOW_EVERYWHERE = ("app.name", "app.id", "app.namespace", "app.kind", "app.existing", "stack.dotnet", "stack.content",
                   "stack.componentLibrary", "stack.sharing", "chrome.search", "chrome.dialogs", "chrome.settings",
                   "chrome.commandPalette", "chrome.multiWindow", "look.accent", "look.theme", "look.density",
                   "engineering.devHost", "engineering.gallery", "engineering.devflow", "engineering.crashReporting",
                   "engineering.accessibility", "engineering.locales", "decisionsLog")


def resolved(bp):
    """``{path: {platform: value}}`` for the per-platform rows of ``show``."""
    on = bpl.enabled(bp)
    out = {}
    for p in on:
        entry = bpl.get(bp, "platforms." + p, {}) or {}
        out.setdefault("platforms.enabled", {})[p] = True
        out.setdefault("platforms.home", {})[p] = bool(entry.get("home"))
        if p in bpl.DEFAULT_MINIMUM:
            out.setdefault("platforms.minimum", {})[p] = entry.get("minimum")
        out.setdefault("stack.backends", {})[p] = bpl.get(bp, "stack.backends." + p, None)
    for path in SHOW_PER_PLATFORM:
        out[path] = {p: _shown(bp, path, p) for p in on}
    for name in bpl.INTEGRATIONS:
        if name in ("contextMenus", "fileTypes"):
            continue
        plats = bpl.integration_platforms(bp, name)
        out["integrations." + name] = {p: (p in plats) for p in on if p != "web"}
    for path in ("distribution.channels", "distribution.signing"):
        out[path] = {p: bpl.value(bp, path, p) for p in on if p != "web"}
    return out


def cmd_show(args):
    bp, _ = load_blueprint(args.blueprint)
    table = resolved(bp)
    if args.json:
        fnd.print_findings([], json_output=True, blueprint=bp, resolved=table)
        return EXIT_OK
    on = bpl.enabled(bp)
    app = bp.get("app") or {}
    decided = bp.get("decided") or []
    lines = ["# %s%s" % (app.get("name") or "Blueprint", " (`%s`)" % app["id"] if app.get("id") else ""), "",
             "A %s app, %s. Confirmed by the user: %s. %d field%s decided." % (
                 app.get("kind"), "existing" if app.get("existing") else "new", yes_no(bp.get("confirmedByUser")),
                 len(decided), "" if len(decided) == 1 else "s"), "",
             "| Field | %s |" % " | ".join(NAMES[p] for p in on), "|---|%s" % ("---|" * len(on))]
    for path, per in table.items():
        vals = []
        for p in on:
            if p not in per:
                vals.append("-")
            elif path in ("platforms.enabled", "platforms.home") or path.startswith("integrations."):
                vals.append(yes_no(per[p]))
            else:
                vals.append(fmt(per[p]) if per[p] is not None else "-")
        lines.append("| %s | %s |" % (path, " | ".join(cell(v) for v in vals)))
    disabled = [NAMES[p] for p in bpl.PLATFORMS if p not in on]
    if disabled:
        lines += ["", "Not enabled: %s." % ", ".join(disabled)]
    lines += ["", "| Everywhere | Value |", "|---|---|"]
    for path in SHOW_EVERYWHERE:
        v = bpl.get(bp, path, None)
        if v is None:
            v = bpl.value(bp, path)
        if v is None:
            continue
        lines.append("| %s | %s |" % (path, cell(fmt(v))))
    links = bpl.value(bp, "integrations.deepLinks")
    if isinstance(links, dict) and links.get("scheme"):
        lines.append("| integrations.deepLinks.scheme | %s |" % cell(links["scheme"]))
    files = bpl.value(bp, "integrations.fileTypes") or []
    if files:
        lines.append("| integrations.fileTypes | %s |" % cell(fmt(files)))
    lines.append("| integrations.contextMenus | %s |" % cell(bpl.value(bp, "integrations.contextMenus")))
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_OK


# --- the command line -----------------------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(prog="blueprint.py", description="Draft, check and record desktop-blueprint.json.")
    sub = p.add_subparsers(dest="command")

    ini = sub.add_parser("init", help="detect the project and write a draft blueprint")
    ini.add_argument("--root", default=".")
    ini.add_argument("--out", help="default: <root>/desktop-blueprint.json")
    ini.add_argument("--kind", choices=bpl.KINDS)
    ini.add_argument("--name")
    ini.add_argument("--id")
    ini.add_argument("--platforms", help="comma-separated: macos,windows,linux (default: the heads found, else all)")

    chk = sub.add_parser("check", help="the schema, then the consistency rules")
    chk.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    chk.add_argument("--json", action="store_true")

    qst = sub.add_parser("questions", help="the interview for every undecided field, as markdown")
    qst.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    qst.add_argument("--root", default=".")

    st = sub.add_parser("set", help="set fields and log each decision")
    st.add_argument("assignments", nargs="*", metavar="PATH=VALUE")
    st.add_argument("--reason", required=True, help="why, in the user's words where they gave them")
    st.add_argument("--by", choices=("user", "proposal"), default="user")
    st.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    st.add_argument("--date", help=argparse.SUPPRESS)

    cnf = sub.add_parser("confirm", help="mark the blueprint approved, on the user's own word")
    cnf.add_argument("--note", required=True, help="the user's words approving it")
    cnf.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    cnf.add_argument("--date", help=argparse.SUPPRESS)

    gp = sub.add_parser("gaps", help="write the gap report: detection against the blueprint")
    gp.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    gp.add_argument("--root", default=".")
    gp.add_argument("--out", help="default: <root>/docs/desktop/gap-report.md")
    gp.add_argument("--print", action="store_true", help="print the report instead of writing it")
    gp.add_argument("--date", help=argparse.SUPPRESS)

    sh = sub.add_parser("show", help="the blueprint as a table, one column a platform")
    sh.add_argument("--blueprint", default=DEFAULT_BLUEPRINT)
    sh.add_argument("--json", action="store_true")
    return p


HANDLERS = {"init": cmd_init, "check": cmd_check, "questions": cmd_questions, "set": cmd_set,
            "confirm": cmd_confirm, "gaps": cmd_gaps, "show": cmd_show}


def main(argv=None):
    p = parser()
    try:
        args = p.parse_args(argv)
    except SystemExit as e:
        return EXIT_OK if e.code in (0, None) else EXIT_USAGE
    if not args.command:
        p.print_help()
        return EXIT_USAGE
    try:
        return HANDLERS[args.command](args)
    except UsageError as e:
        sys.stderr.write("blueprint.py %s: %s\n" % (args.command, e))
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
