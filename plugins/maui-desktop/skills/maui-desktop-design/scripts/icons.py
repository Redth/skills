#!/usr/bin/env python3
"""icons.py: one icon file (``design/icons.json``) to every platform's way of naming an icon.

Subcommands (run from the app's project root, or pass ``--root``; offline):

    icons.py init  [--root .] [--out design/icons.json] [--blueprint desktop-blueprint.json]
    icons.py build [--root .] [--icons design/icons.json] [--check] [--json]

Shared code names an ``IconRef``; each platform resolves it: an SF Symbol on macOS, an Adwaita ``*-symbolic``
name on GTK, the sprite's stroke geometry (or a Segoe Fluent Icons glyph) on Windows, and a sprite symbol in
the web content. A mapping a listed platform needs but an icon lacks is an error, never a blank button on one
platform (CONTRACT.md section 5).

``build`` writes the outputs ``outputs`` names: ``Icons.g.cs`` (the enum and the resolution tables), the SVG
sprite, an ``IconSprite.razor`` with the same symbols inline (WebKit doesn't resolve
``<use href="file.svg#id">`` across documents, so every icon in a macOS web view would silently vanish), and a
template image set per mark for a macOS status item. ``build --check`` writes nothing and fails naming each
stale output. ``init`` copies the skill's ``templates/icons.json`` (refusing to overwrite a file) with the
platforms the blueprint enables and outputs guessed from the project's layout.

Exit codes: 0 done; 1 stale or incomplete; 2 refused; 3 usage or invalid input.
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import sys
import xml.etree.ElementTree as ET

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import design_color as dc  # noqa: E402
import tokens as T  # noqa: E402
from mauidesktop_lib import findings as fnd  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402
from mauidesktop_lib.findings import Finding  # noqa: E402

DEFAULT_ICONS = os.path.join("design", "icons.json")
PLATFORM_KEY = {"macos": "sf", "linux": "gtk", "web": "svg"}
KEBAB = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
DEFAULT_GEOMETRY = collections.OrderedDict(
    [("viewBox", "0 0 24 24"), ("strokeWidth", 1.75), ("linecap", "round"), ("linejoin", "round")])
SVG_NS = "http://www.w3.org/2000/svg"


class Icons(object):
    """``icons.json`` read: the icons and marks (without ``$`` keys), the platforms and the geometry."""

    def __init__(self, data, source="design/icons.json"):
        self.data = data
        self.source = source
        self.meta = data.get("meta", {})
        self.windows = self.meta.get("windows", "svg")
        self.platforms = data.get("platforms") or ["macos", "windows", "linux", "web"]
        self.outputs = data.get("outputs", {})
        geometry = collections.OrderedDict(DEFAULT_GEOMETRY)
        geometry.update(T.visible(data.get("geometry", {})))
        self.geometry = geometry
        self.icons = collections.OrderedDict(T.visible(data.get("icons", {})))
        self.marks = collections.OrderedDict(T.visible(data.get("marks", {})))

    def keys(self):
        """The mappings every icon needs, from ``platforms`` (and the sprite, which draws ``svg``)."""
        need = []
        for p in self.platforms:
            key = self.windows if p == "windows" else PLATFORM_KEY[p]
            if key not in need:
                need.append(key)
        if (self.outputs.get("sprite") or self.outputs.get("razor")) and "svg" not in need:
            need.append("svg")
        return need

    @property
    def has_svg(self):
        return "svg" in self.keys()


def load_icons(path, root):
    label = T.rel(path, root)
    data = T.validate_against(T.load_json(path, label), "icons.schema.json", label)
    problems = []
    for group in ("icons", "marks"):
        for name, _ in T.visible(data.get(group, {})):
            if not KEBAB.match(name):
                problems.append(Finding("icon-name", "error", "/%s/%s" % (group, name),
                                        "names are kebab-case (\"%s\"), so each maps to one PascalCase member"
                                        % "-".join(p.lower() for p in re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])",
                                                                                  name))))
    if problems:
        raise T.UsageError("%s has %d problem(s)" % (label, len(problems)), problems)
    return Icons(data, label)


def _svg_ok(body):
    try:
        ET.fromstring('<svg xmlns="%s">%s</svg>' % (SVG_NS, body))
        return True
    except ET.ParseError:
        return False


def completeness(icons):
    """Findings for every mapping a listed platform needs but an icon lacks, and for broken SVG markup."""
    out = []
    need = icons.keys()
    for name, icon in icons.icons.items():
        for key in need:
            if not str(icon.get(key, "")).strip():
                platforms = [p for p in icons.platforms
                             if (icons.windows if p == "windows" else PLATFORM_KEY[p]) == key] or ["the sprite"]
                out.append(Finding("icon-incomplete", "error", "/icons/%s" % name,
                                   "no \"%s\", which %s needs: every icon maps on every listed platform"
                                   % (key, " and ".join(platforms))))
        if icon.get("svg") and not _svg_ok(icon["svg"]):
            out.append(Finding("svg-markup", "error", "/icons/%s/svg" % name, "the SVG isn't well-formed markup"))
    for name, mark in icons.marks.items():
        if not _svg_ok(mark["svg"]):
            out.append(Finding("svg-markup", "error", "/marks/%s/svg" % name, "the SVG isn't well-formed markup"))
    if not icons.icons:
        out.append(Finding("no-icons", "warning", "/icons", "there are no icons"))
    return out


# ------------------------------------------------------------------ outputs


def cs_string(text):
    """A C# regular string literal for ``text``."""
    out = []
    for ch in text:
        code = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20 or code in (0x85, 0x2028, 0x2029):
            out.append("\\u%04x" % code)
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def glyph_literal(codepoint):
    """A Segoe Fluent codepoint (hex) as a C# string literal holding that one character."""
    value = int(codepoint, 16)
    return '"\\u%04X"' % value if value <= 0xFFFF else '"\\U%08X"' % value


def _stroke_attrs(geometry, quote):
    q = quote
    return ("stroke-width=%s%s%s stroke-linecap=%s%s%s stroke-linejoin=%s%s%s" % (
        q, dc.js_number(geometry["strokeWidth"]), q, q, geometry["linecap"], q, q, geometry["linejoin"], q))


def sprite_body(icons):
    g = icons.geometry
    symbols = ['  <symbol id="i-%s" viewBox="%s">%s</symbol>' % (n, g["viewBox"], i["svg"])
               for n, i in icons.icons.items()]
    symbols += ['  <symbol id="mark-%s" viewBox="%s">%s</symbol>' % (n, g["viewBox"], m["svg"])
                for n, m in icons.marks.items()]
    return "\n".join([
        '<svg xmlns="http://www.w3.org/2000/svg" style="display:none" aria-hidden="true"',
        '     fill="none" stroke="currentColor" stroke-width="%s"' % dc.js_number(g["strokeWidth"]),
        '     stroke-linecap="%s" stroke-linejoin="%s">' % (g["linecap"], g["linejoin"]),
    ] + symbols + ["</svg>"])


def sprite_text(icons):
    return "<!-- %s -->\n%s\n" % (T.banner("icons.py", icons.source), sprite_body(icons))


def razor_text(icons):
    return ("@* %s *@\n\n"
            "@* Mounted once per document. WebKit doesn't resolve <use href=\"file.svg#id\"> across documents (an\n"
            "   external reference draws a 0x0 box and no error), so the symbols are inline and every <use> is a\n"
            "   same-document reference. *@\n\n%s\n") % (T.banner("icons.py", icons.source), sprite_body(icons))


def _table(name, pairs, value, visibility="public "):
    head = "    %sstatic readonly IReadOnlyDictionary<IconRef, string> %s = new Dictionary<IconRef, string>" % (
        visibility, name)
    return [head, "    {"] + ["        [IconRef.%s] = %s," % (T.pascal(n), value(n, i)) for n, i in pairs] + ["    };"]


def csharp_text(icons):
    spec = icons.outputs["csharp"]
    g = icons.geometry
    need = icons.keys()
    items = list(icons.icons.items())
    svg_open = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='%s' fill='none' " % g["viewBox"], "' %s>"
                % _stroke_attrs(g, "'"))
    L = ["// %s" % T.banner("icons.py", icons.source), "#nullable enable", "",
         "using System.Collections.Generic;", "", "namespace %s;" % spec["namespace"], "",
         "/// <summary>",
         "/// Every icon the app renders. Shared code names one of these; each platform head resolves it to its own",
         "/// vocabulary. Never put an SF Symbol name or a glyph in shared code.",
         "/// </summary>",
         "public enum IconRef", "{"] + ["    %s," % T.pascal(n) for n, _ in items] + ["}", "",
         "/// <summary>Resolves an <see cref=\"IconRef\"/> for one platform's chrome.</summary>",
         "public static class Icons", "{"]
    methods = []
    if "macos" in icons.platforms:
        methods.append(["    /// <summary>The SF Symbol name, for AppKit chrome.</summary>",
                        "    public static string SfSymbol(IconRef icon) => SfSymbols[icon];"])
    if "linux" in icons.platforms:
        methods.append(["    /// <summary>The Adwaita icon name, for GTK chrome.</summary>",
                        "    public static string GtkName(IconRef icon) => GtkNames[icon];"])
    if "windows" in icons.platforms and icons.windows == "fluent":
        methods.append(["    /// <summary>The Segoe Fluent Icons glyph (one character), for WinUI chrome.</summary>",
                        "    public static string FluentGlyph(IconRef icon) => FluentGlyphs[icon];"])
    if "svg" in need:
        methods.append(["    /// <summary>The sprite symbol's id, for the web content.</summary>",
                        "    public static string SpriteId(IconRef icon) => \"i-\" + SpriteSlugs[icon];"])
        methods.append([
            "    /// <summary>",
            "    /// The sprite geometry as a standalone SVG document, stroked in <paramref name=\"stroke\"/>: for a",
            "    /// native image, which has no <c>currentColor</c> to inherit, so the head passes the colour it",
            "    /// resolved from the generated palette for the theme it's drawing.",
            "    /// </summary>",
            "    public static string Svg(IconRef icon, string stroke) =>",
            "        %s +" % cs_string(svg_open[0]),
            "        \"stroke='\" + stroke + %s +" % cs_string(svg_open[1]),
            "        SvgBodies[icon] + \"</svg>\";"])
        if icons.marks:
            methods.append([
                "    /// <summary>One of the app's own marks (no platform names it) as a standalone SVG document,",
                "    /// with the same contract as <see cref=\"Svg\"/>.</summary>",
                "    public static string MarkSvg(string name, string stroke) =>",
                "        %s +" % cs_string(svg_open[0]),
                "        \"stroke='\" + stroke + %s +" % cs_string(svg_open[1]),
                "        MarkBodies[name] + \"</svg>\";"])
    for m in methods:
        L += m + [""]
    tables = []
    if "macos" in icons.platforms:
        tables.append(_table("SfSymbols", items, lambda n, i: cs_string(i["sf"])))
    if "linux" in icons.platforms:
        tables.append(_table("GtkNames", items, lambda n, i: cs_string(i["gtk"])))
    if "windows" in icons.platforms and icons.windows == "fluent":
        tables.append(_table("FluentGlyphs", items, lambda n, i: glyph_literal(i["fluent"])))
    if "svg" in need:
        tables.append(_table("SvgBodies", items, lambda n, i: cs_string(i["svg"]), ""))
        tables.append(_table("SpriteSlugs", items, lambda n, i: cs_string(n), "internal "))
        if icons.marks:
            tables.append(["    static readonly IReadOnlyDictionary<string, string> MarkBodies = "
                           "new Dictionary<string, string>", "    {"]
                          + ["        [%s] = %s," % (cs_string(n), cs_string(m["svg"])) for n, m in icons.marks.items()]
                          + ["    };"])
    for i, t in enumerate(tables):
        L += ([""] if i else []) + t
    if L[-1] == "":
        L.pop()
    L.append("}")
    return "\n".join(L) + "\n"


def mark_files(icons):
    """``[(relative path, text)]``: a template image set per mark, for a status item or a dock menu."""
    g = icons.geometry
    out = []
    for name, mark in icons.marks.items():
        stem = T.pascal(name) + "Mark"
        folder = "%s/%s.imageset" % (icons.outputs["macosMarks"].rstrip("/"), stem)
        svg = "\n".join([
            '<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="%s"' % g["viewBox"],
            '     fill="none" stroke="black" stroke-width="%s"' % dc.js_number(g["strokeWidth"]),
            '     stroke-linecap="%s" stroke-linejoin="%s">' % (g["linecap"], g["linejoin"]),
            "  " + mark["svg"], "</svg>", ""])
        contents = collections.OrderedDict([
            ("images", [collections.OrderedDict([("filename", stem + ".svg"), ("idiom", "universal")])]),
            ("info", collections.OrderedDict([("author", "xcode"), ("version", 1)])),
            ("properties", collections.OrderedDict([("preserves-vector-representation", True),
                                                    ("template-rendering-intent", "template")]))])
        out.append(("%s/%s.svg" % (folder, stem), svg))
        out.append(("%s/Contents.json" % folder, jsonio.dumps(contents)))
    return out


def render(icons):
    outputs = []
    spec = icons.outputs
    if spec.get("csharp"):
        outputs.append(("csharp", spec["csharp"]["path"], csharp_text(icons)))
    if spec.get("sprite"):
        outputs.append(("sprite", spec["sprite"], sprite_text(icons)))
    if spec.get("razor"):
        outputs.append(("razor", spec["razor"], razor_text(icons)))
    if spec.get("macosMarks"):
        outputs += [("macosMarks", path, text) for path, text in mark_files(icons)]
    return outputs


def build(root, icons_file, check=False, json_output=False, stream=None):
    stream = stream or sys.stdout
    icons = load_icons(icons_file, root)
    found = completeness(icons)
    if fnd.errors(found):
        fnd.print_findings(found, json_output, stream)
        return fnd.exit_code(found)
    outputs = render(icons)
    if not outputs:
        found.append(Finding("no-outputs", "info", icons.source,
                             "outputs names nothing to generate: add csharp, sprite, razor or macosMarks"))
    written, statuses = T.write_outputs(root, outputs, icons.outputs.get("ignored", []), check)
    found += written
    if json_output:
        fnd.print_findings(found, True, stream, outputs=statuses, icons=len(icons.icons))
    else:
        for s in statuses:
            mark = {"current": "=", "written": "wrote", "stale": "STALE", "absent (ignored)": "-"}[s["status"]]
            stream.write("  %-5s %s\n" % (mark, s["path"]))
        fnd.print_findings(found, False, stream, summary="%d icons, %d marks." % (len(icons.icons),
                                                                               len(icons.marks)))
    return fnd.exit_code(found)


# ------------------------------------------------------------------ init


def init(root, out, blueprint=None, stream=None):
    stream = stream or sys.stdout
    target = out if os.path.isabs(out) else os.path.join(root, out)
    if os.path.exists(target):
        stream.write("%s already exists; not overwriting it. Edit it, or move it aside first.\n"
                     % T.rel(target, root))
        return T.EXIT_REFUSED
    template = T.find_resource("templates", "icons.json")
    if not os.path.isfile(template):
        raise T.UsageError("the skill's templates/icons.json isn't here: run init from the skill, not an "
                           "installed copy")
    data = jsonio.load(template)
    bp = T.blueprint_for(root, blueprint)
    name = (bp or {}).get("name") or T.project_name(root)
    meta = collections.OrderedDict(data.get("meta", {}))
    meta["name"] = name
    meta["csharpPrefix"] = T.csharp_prefix({"csharpPrefix": (bp or {}).get("namespace"), "name": name})
    data["meta"] = meta
    notes = []
    if bp is not None:
        data["platforms"] = list(bp["platforms"]) or data.get("platforms")
        notes.append("platforms from the blueprint: %s" % ", ".join(data["platforms"]))
    layout = T.guess_layout(root)
    outputs = collections.OrderedDict((k, v) for k, v in data.get("outputs", {}).items() if k.startswith("$"))
    if layout["core"]:
        outputs["csharp"] = collections.OrderedDict([
            ("path", T._join(layout["core"]["dir"], "Shell/Icons.g.cs")),
            ("namespace", layout["core"]["namespace"] + ".Shell")])
    else:
        notes.append("no library for Icons.g.cs: set outputs.csharp by hand")
    if layout["ui"]:
        outputs["sprite"] = T._join(layout["ui"]["dir"], "wwwroot/icons/sprite.svg")
        outputs["razor"] = T._join(layout["ui"]["dir"], "Components/IconSprite.razor")
    else:
        notes.append("no project with a wwwroot folder: set outputs.sprite and outputs.razor by hand")
    if layout["macos"] and T.visible(data.get("marks", {})):
        outputs["macosMarks"] = T._join(layout["macos"]["dir"], "Assets.xcassets")
    outputs["ignored"] = []
    data["outputs"] = outputs
    T.write_text(target, T.pretty_json(data) + "\n")
    stream.write("wrote %s (%d icons)\n" % (T.rel(target, root), len(T.visible(data.get("icons", {})))))
    for key in ("csharp", "sprite", "razor", "macosMarks"):
        if key in outputs:
            value = outputs[key]
            stream.write("  outputs.%s: %s\n" % (key, value["path"] if isinstance(value, dict) else value))
    for n in notes:
        stream.write("  note: %s\n" % n)
    return T.EXIT_OK


# ------------------------------------------------------------------ command line


def parse_args(argv):
    p = argparse.ArgumentParser(prog="icons.py", description="Generate and check an app's per-platform icon layer.")
    sub = p.add_subparsers(dest="command")
    sub.required = True
    i = sub.add_parser("init", help="start design/icons.json from the skill's template")
    i.add_argument("--root", default=".")
    i.add_argument("--out", default=DEFAULT_ICONS)
    i.add_argument("--blueprint", help="desktop-blueprint.json (default: the root's, when there is one)")
    b = sub.add_parser("build", help="write every output (or check them with --check)")
    b.add_argument("--root", default=".")
    b.add_argument("--icons", default=DEFAULT_ICONS)
    b.add_argument("--check", action="store_true", help="write nothing; exit 1 naming each stale output")
    b.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def main(argv=None, stream=None):
    stream = stream or sys.stdout
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    json_output = getattr(args, "json", False)
    try:
        if not os.path.isdir(root):
            raise T.UsageError("--root %s isn't a folder" % args.root)
        if args.command == "init":
            return init(root, args.out, args.blueprint, stream)
        path = args.icons if os.path.isabs(args.icons) else os.path.join(root, args.icons)
        return build(root, path, args.check, json_output, stream)
    except T.UsageError as e:
        fnd.print_findings(e.findings, json_output, stream if json_output else sys.stderr)
        return T.EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
