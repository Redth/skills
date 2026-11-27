#!/usr/bin/env python3
"""tokens.py: one design-token file (``design/tokens.json``) to every place the app reads colour and size.

Subcommands (run from the app's project root, or pass ``--root``; every one is offline):

    tokens.py init     [--root .] [--out design/tokens.json] [--blueprint desktop-blueprint.json]
    tokens.py build    [--root .] [--tokens design/tokens.json] [--check] [--json]
    tokens.py contrast [--root .] [--tokens design/tokens.json] [--json] [--quiet]
    tokens.py show     [--root .] [--tokens design/tokens.json] [--theme light|dark] [--platform P] [--json]

``init`` copies the skill's ``templates/tokens.json``, filling ``meta`` and the platforms the blueprint enables,
and guesses ``outputs`` from the project's layout; it refuses to overwrite a file. ``build`` writes every
output the file names (CONTRACT.md section 4): ``tokens.css`` for the web content, a C# palette and scale for
native chrome, the macOS accent colour set, and the generated tables in ``DESIGN.md`` (only between their
markers). ``build --check`` writes nothing and fails naming each stale output: the CI gate. ``contrast``
recomputes every WCAG pair and separation rule for each theme, and again for each platform that overrides
colours, and fails on a regression, an out-of-gamut colour or an exception that's no longer needed. ``show``
prints the resolved palette and scale.

Paths in ``outputs`` and ``lint`` are relative to ``--root``. Without ``--tokens``, the file is
``<root>/design/tokens.json`` (or ``<root>/tokens.json`` when only that exists).

Exit codes: 0 done; 1 findings (stale output, failed contrast, a broken mix); 2 refused (``init`` over an
existing file); 3 usage or invalid input (missing file, invalid JSON, a schema violation, an unknown name).
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS_DIR)

import design_color as dc  # noqa: E402
from mauidesktop_lib import findings as fnd  # noqa: E402
from mauidesktop_lib import jsonio  # noqa: E402
from mauidesktop_lib import schema  # noqa: E402
from mauidesktop_lib.findings import Finding  # noqa: E402

SKILL_DIR = os.path.dirname(SCRIPTS_DIR)

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_REFUSED = 2
EXIT_USAGE = 3

THEMES = ("light", "dark")
PLATFORMS = ("macos", "windows", "linux", "web")
PLATFORM_PASCAL = {"macos": "MacOS", "windows": "Windows", "linux": "Linux", "web": "Web"}
PLATFORM_TITLE = {"macos": "macOS", "windows": "Windows", "linux": "Linux", "web": "Web"}
OUTPUT_KEYS = ("css", "csharp", "macosAccent", "design")
DEFAULT_TOKENS = os.path.join("design", "tokens.json")
DEFAULT_BLUEPRINT = "desktop-blueprint.json"
DURATION = re.compile(r"^-?(?:\d+\.?\d*|\.\d+)(?:ms|s)$")
PX = re.compile(r"^(-?(?:\d+\.?\d*|\.\d+))px$")
SKIP_DIRS = frozenset(["bin", "obj", "node_modules", ".git", ".vs", ".idea", "artifacts", "packages"])
# C# names the generated types and members already use; a scale group can't take one.
RESERVED_TYPES = frozenset(["Color", "Rgb", "Theme", "Platform", "Tokens"])
RESERVED_MEMBERS = frozenset(["Get", "Light", "Dark", "Overrides"])
DASH = "\u2014"  # an em dash: "the same as the base" in a table


class UsageError(Exception):
    """Exit 3: a missing file, invalid JSON, a schema violation or a name that doesn't resolve."""

    def __init__(self, message, found=None):
        super().__init__(message)
        self.findings = found or [Finding("usage", "error", "", message)]


# ------------------------------------------------------------------ small helpers


def find_resource(*parts):
    """A file shipped with the scripts: ``<scripts>/<parts>`` in an installed copy, else ``<skill>/<parts>``."""
    for base in (SCRIPTS_DIR, SKILL_DIR):
        path = os.path.join(base, *parts)
        if os.path.exists(path):
            return path
    return os.path.join(SKILL_DIR, *parts)


def visible(obj):
    """An object's items without the ``$`` keys (comments and settings)."""
    return [(k, v) for k, v in obj.items() if not k.startswith("$")]


def pascal(name):
    """``on-accent`` -> ``OnAccent``; ``Sample Notes`` -> ``SampleNotes``. The rest of each word is kept."""
    return "".join(p[:1].upper() + p[1:] for p in re.split(r"[^A-Za-z0-9]+", name) if p)


def csharp_prefix(meta):
    """``meta.csharpPrefix``, or ``meta.name`` in PascalCase (letters and digits only)."""
    prefix = meta.get("csharpPrefix") or pascal(meta.get("name", "")) or "App"
    return "_" + prefix if prefix[0].isdigit() else prefix


def rel(path, root):
    """``path`` relative to ``root`` with forward slashes (for messages and baselines)."""
    try:
        r = os.path.relpath(path, root)
    except ValueError:  # another drive on Windows
        return path.replace(os.sep, "/")
    return r.replace(os.sep, "/")


def under(root, path):
    """``path`` (relative, with ``/``) under ``root``, as a native path."""
    return os.path.normpath(os.path.join(root, *path.split("/")))


def read_text(path):
    """A UTF-8 text file with its line endings read as ``\\n`` (a byte-order mark is dropped)."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    return text[1:] if text.startswith("﻿") else text


def write_text(path, text):
    """Write UTF-8 text with ``\\n`` endings, atomically (a temp file in the same folder, then replace)."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        if os.path.exists(path):
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        else:
            mask = os.umask(0)
            os.umask(mask)
            os.chmod(tmp, 0o666 & ~mask)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def pretty_json(value, indent=0, width=100):
    """JSON as the templates are written: 2-space indent, short scalar-only arrays and objects on one line."""
    pad = "  " * indent
    flat = json.dumps(value, ensure_ascii=False, separators=(", ", ": "))
    if not isinstance(value, (dict, list)):
        return flat
    nested = any(isinstance(v, dict) or (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v))
                 for v in (value.values() if isinstance(value, dict) else value))
    if not value or (not nested and len(pad) + len(flat) <= width):
        return flat
    inner = "  " * (indent + 1)
    if isinstance(value, list):
        body = [inner + pretty_json(v, indent + 1, width) for v in value]
        return "[\n" + ",\n".join(body) + "\n" + pad + "]"
    body = [inner + json.dumps(k, ensure_ascii=False) + ": " + pretty_json(v, indent + 1, width)
            for k, v in value.items()]
    return "{\n" + ",\n".join(body) + "\n" + pad + "}"


def scalar_text(value):
    """A scale value as CSS: strings verbatim, numbers bare."""
    return value if isinstance(value, str) else dc.js_number(value)


def banner(tool, source):
    return "Generated by %s from %s. Do not edit." % (tool, source)


# ------------------------------------------------------------------ loading


def load_json(path, label=None):
    """A JSON file, or ``UsageError`` naming the file (and line) when it's missing or invalid."""
    label = label or path
    if not os.path.isfile(path):
        raise UsageError("%s: no such file" % label, [Finding("missing-file", "error", label, "no such file")])
    try:
        return jsonio.load(path)
    except jsonio.JsonError as e:
        raise UsageError(str(e), [Finding("invalid-json", "error", label, str(e))])


def validate_against(data, schema_name, label):
    """Schema-check ``data``; ``UsageError`` with one finding a violation when it fails."""
    sch = jsonio.load(find_resource("schema", schema_name))
    errors = schema.validate(data, sch)
    if errors:
        raise UsageError("%s doesn't match %s" % (label, schema_name),
                         [Finding("schema", "error", label, e) for e in errors])
    return data


def tokens_path(root, given):
    """The tokens file: ``--tokens`` (relative to ``root``), else design/tokens.json, else tokens.json."""
    if given:
        return given if os.path.isabs(given) else os.path.join(root, given)
    default = os.path.join(root, DEFAULT_TOKENS)
    if not os.path.exists(default) and os.path.isfile(os.path.join(root, "tokens.json")):
        return os.path.join(root, "tokens.json")
    return default


def load_tokens(path, root):
    """Read, schema-check and resolve a tokens file. Raises ``UsageError`` for invalid input."""
    label = rel(path, root)
    data = validate_against(load_json(path, label), "tokens.schema.json", label)
    tok = Tokens(data, label)
    if tok.problems:
        raise UsageError("%s has %d problem(s)" % (label, len(tok.problems)), tok.problems)
    return tok


# ------------------------------------------------------------------ the resolved model


Group = collections.namedtuple("Group", "name prefix base entries")  # entries: [(var, value, entry, key)]
Mode = collections.namedtuple("Mode", "name default selector values")  # values: {mode: [(var, value)]}


class Tokens(object):
    """``tokens.json`` resolved: a palette per theme (and per platform), effects, scale and modes.

    Problems that make the input unusable (an unknown primitive, a role one theme lacks, a platform override
    with no base) are collected in ``problems`` rather than raised, so every one is reported at once.
    """

    def __init__(self, data, source="design/tokens.json"):
        self.data = data
        self.source = source
        self.problems = []
        meta = data.get("meta", {})
        self.name = meta.get("name", "App")
        self.prefix = csharp_prefix(meta)
        self.color_space = meta.get("colorSpace", "oklch")
        self.root = data.get("root", ":root")
        self.outputs = data.get("outputs", {})
        self.primitives = collections.OrderedDict(
            (k, dc.from_value(v)) for k, v in visible(data.get("primitives", {})))
        self._palettes()
        self._effects()
        self._scale()
        self._modes()
        self._platforms()
        self._duplicates()
        self._csharp_scale()

    def problem(self, id, where, message):
        self.problems.append(Finding(id, "error", where, message))

    # -- colour

    def resolve(self, ref, where):
        """A role's value (a primitive's name, or a mix of two) as a colour; None (and a problem) if unknown."""
        if isinstance(ref, str):
            if ref not in self.primitives:
                self.problem("unknown-primitive", where, "\"%s\" isn't a primitive" % ref)
                return None
            return self.primitives[ref]
        ends = []
        for key in ("mix", "into"):
            if ref[key] not in self.primitives:
                self.problem("unknown-primitive", where, "%s: \"%s\" isn't a primitive" % (key, ref[key]))
                return None
            ends.append(self.primitives[ref[key]])
        return dc.mix(ends[0], ends[1], ref["amount"])

    def _palettes(self):
        semantic = self.data.get("semantic", {})
        self.refs = {t: collections.OrderedDict(visible(semantic.get(t, {}))) for t in THEMES}
        self.role_names = list(self.refs["light"])
        for theme, other in (("light", "dark"), ("dark", "light")):
            for role in self.refs[theme]:
                if role not in self.refs[other]:
                    self.problem("role-missing", "/semantic/%s" % other,
                                 "%s defines \"%s\" but %s doesn't: both themes define the same roles"
                                 % (theme, role, other))
        if not self.role_names:
            self.problem("no-roles", "/semantic/light", "there are no colour roles")
        self.palette = {}
        for theme in THEMES:
            pal = collections.OrderedDict()
            for role in self.role_names:
                if role in self.refs[theme]:
                    color = self.resolve(self.refs[theme][role], "/semantic/%s/%s" % (theme, role))
                    if color is not None:
                        pal[role] = color
            self.palette[theme] = pal

    def _effects(self):
        effects = self.data.get("effects", {})
        self.effects = {t: collections.OrderedDict(visible(effects.get(t, {}))) for t in THEMES}
        for theme, other in (("light", "dark"), ("dark", "light")):
            for name in self.effects[theme]:
                if name not in self.effects[other]:
                    self.problem("effect-missing", "/effects/%s" % other,
                                 "%s defines effect \"%s\" but %s doesn't" % (theme, name, other))

    # -- scale and modes

    def _scale(self):
        self.scale = []
        for group, spec in visible(self.data.get("scale", {})):
            prefix = spec.get("$prefix", group + "-")
            base = spec.get("$base", "value")
            entries = []
            for name, value in visible(spec):
                if isinstance(value, dict):
                    for key, v in visible(value):
                        entries.append((self.var_name(prefix, base, name, key), v, name, key))
                else:
                    entries.append((prefix + name, value, name, None))
            self.scale.append(Group(group, prefix, base, entries))
        self.groups = {g.name: g for g in self.scale}

    @staticmethod
    def var_name(prefix, base, entry, key):
        return prefix + entry if key is None or key == base else "%s%s-%s" % (prefix, entry, key)

    def _modes(self):
        self.modes = []
        for name, spec in visible(self.data.get("modes", {})):
            values = collections.OrderedDict(
                (mode, [(k, v) for k, v in visible(decls)]) for mode, decls in visible(spec["values"]))
            default = spec["default"]
            if default not in values:
                self.problem("mode-default", "/modes/%s/default" % name,
                             "\"%s\" isn't one of the mode's values (%s)" % (default, ", ".join(values)))
                continue
            keys = set(k for k, _ in values[default])
            for mode, decls in values.items():
                for k, _ in decls:
                    if k not in keys:
                        self.problem("mode-key", "/modes/%s/values/%s/%s" % (name, mode, k),
                                     "the default mode (%s) doesn't set \"%s\": every mode sets the same names"
                                     % (default, k))
            self.modes.append(Mode(name, default, spec["selector"], values))

    # -- platforms

    def _platforms(self):
        block = self.data.get("platforms", {})
        self.platforms = [p for p, _ in visible(block)]
        self.attribute = {}
        self.platform_refs = {}
        self.platform_palette = {}
        self.platform_effects = {}
        self.platform_scale = {}
        for p in self.platforms:
            spec = block[p]
            self.attribute[p] = spec.get("attribute", p)
            self.platform_refs[p] = {}
            self.platform_palette[p] = {}
            self.platform_effects[p] = {}
            semantic = spec.get("semantic", {})
            effects = spec.get("effects", {})
            for theme in THEMES:
                refs = collections.OrderedDict(visible(semantic.get(theme, {})))
                pal = collections.OrderedDict()
                for role in self.role_names:  # base order, whatever order the platform wrote them in
                    if role in refs:
                        color = self.resolve(refs[role], "/platforms/%s/semantic/%s/%s" % (p, theme, role))
                        if color is not None:
                            pal[role] = color
                for role in refs:
                    if role not in self.refs[theme]:
                        self.problem("platform-unknown-role", "/platforms/%s/semantic/%s/%s" % (p, theme, role),
                                     "the base palette has no \"%s\" role: a platform overrides only roles that "
                                     "exist" % role)
                self.platform_refs[p][theme] = refs
                self.platform_palette[p][theme] = pal
                fx = collections.OrderedDict()
                for name, value in visible(effects.get(theme, {})):
                    if name not in self.effects[theme]:
                        self.problem("platform-unknown-effect", "/platforms/%s/effects/%s/%s" % (p, theme, name),
                                     "the base has no \"%s\" effect for %s" % (name, theme))
                    else:
                        fx[name] = value
                self.platform_effects[p][theme] = fx
            self.platform_scale[p] = self._platform_scale(p, spec.get("scale", {}))

    def _platform_scale(self, p, scale):
        """A platform's scale overrides as ``[(var, value, group, entry, key)]``, in the base's order."""
        found = {}
        for group, spec in visible(scale):
            where = "/platforms/%s/scale/%s" % (p, group)
            base_group = self.groups.get(group)
            if base_group is None:
                self.problem("platform-unknown-scale", where, "the base scale has no \"%s\" group" % group)
                continue
            base_entries = dict(visible(self.data["scale"][group]))
            for name, value in visible(spec):
                if name not in base_entries:
                    self.problem("platform-unknown-scale", "%s/%s" % (where, name),
                                 "the base \"%s\" group has no \"%s\"" % (group, name))
                    continue
                base_value = base_entries[name]
                if isinstance(base_value, dict) != isinstance(value, dict):
                    self.problem("platform-scale-shape", "%s/%s" % (where, name),
                                 "the base entry is %s, so the override must be too"
                                 % ("an object" if isinstance(base_value, dict) else "a single value"))
                    continue
                if isinstance(value, dict):
                    for key, v in visible(value):
                        if key not in base_value:
                            self.problem("platform-unknown-scale", "%s/%s/%s" % (where, name, key),
                                         "the base \"%s.%s\" has no \"%s\"" % (group, name, key))
                            continue
                        found[(group, name, key)] = v
                else:
                    found[(group, name, None)] = value
        out = []
        for g in self.scale:
            for var, _, entry, key in g.entries:
                if (g.name, entry, key) in found:
                    out.append((var, found[(g.name, entry, key)], g.name, entry, key))
        return out

    def _duplicates(self):
        seen = {}
        names = [(r, "/semantic/light/" + r) for r in self.role_names]
        names += [(e, "/effects/light/" + e) for e in self.effects["light"]]
        names += [(var, "/scale/%s/%s" % (g.name, entry)) for g in self.scale for var, _, entry, _ in g.entries]
        for m in self.modes:
            names += [(k, "/modes/%s" % m.name) for k, _ in m.values[m.default]]
        for name, where in names:
            if name in seen:
                self.problem("duplicate-property", where,
                             "--%s is also written by %s: every custom property has one source" % (name, seen[name]))
            else:
                seen[name] = where

    def _csharp_scale(self):
        csharp = self.outputs.get("csharp")
        if not csharp:
            return
        types = set()
        for group in csharp.get("scale", []):
            where = "/outputs/csharp/scale"
            if group not in self.groups:
                self.problem("csharp-scale", where, "there's no \"%s\" scale group" % group)
                continue
            gp = pascal(group)
            if gp in RESERVED_TYPES or gp in RESERVED_MEMBERS or gp in types:
                self.problem("csharp-scale", where, "a scale group named \"%s\" would clash with a generated C# "
                             "name; rename the group" % group)
            types.add(gp)
            values = [(var, v) for var, v, _, _ in self.groups[group].entries]
            for p in self.platforms:
                values += [(var, v) for var, v, g, _, _ in self.platform_scale[p] if g == group]
            for var, v in values:
                if px_number(v) is None:
                    self.problem("csharp-scale", "/scale/%s" % group,
                                 "--%s is %s: only px values and bare numbers can go to C#" % (var, json.dumps(v)))

    # -- lookups

    def overrides_colors(self, p, theme=None):
        themes = [theme] if theme else THEMES
        return any(self.platform_palette[p][t] or self.platform_effects[p][t] for t in themes)

    def merged(self, p, theme):
        """The full palette a platform sees in a theme: the base with its overrides."""
        pal = collections.OrderedDict(self.palette[theme])
        if p:
            pal.update(self.platform_palette[p][theme])
        return pal

    def ground(self, palette):
        """The role DESIGN.md measures every colour against: ``bg`` when there is one, else the first role."""
        return "bg" if "bg" in palette else next(iter(palette), None)

    def scale_member(self, group, entry, key):
        g = self.groups[group]
        name = entry if key is None or key == g.base else "%s-%s" % (entry, key)
        member = pascal(name)
        return pascal(group) + member if member[:1].isdigit() else member


def px_number(value):
    """``10px`` -> 10, ``13.5px`` -> 13.5, a bare number -> itself; anything else -> None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    m = PX.match(value.strip()) if isinstance(value, str) else None
    if not m:
        return None
    number = float(m.group(1))
    return int(number) if number == int(number) else number


# ------------------------------------------------------------------ checks


def mix_findings(tok):
    """A mix into a grey must keep the coloured end's hue (CONTRACT.md section 4).

    This went wrong once in the pipeline this was ported from: the hue was interpolated towards the grey's
    placeholder H of 0, and the dark success tint came out at hue 27, so every success banner in dark mode
    looked like a failure. Cheap to assert, invisible to review.
    """
    out = []
    sets = [(None, t, tok.refs[t], tok.palette[t]) for t in THEMES]
    sets += [(p, t, tok.platform_refs[p][t], tok.platform_palette[p][t]) for p in tok.platforms for t in THEMES]
    for p, theme, refs, palette in sets:
        for role, ref in refs.items():
            if not isinstance(ref, dict) or role not in palette:
                continue
            source, into = tok.primitives[ref["mix"]], tok.primitives[ref["into"]]
            if dc.is_grey(source) or not dc.is_grey(into):
                continue
            hue = palette[role][2]
            if dc.hue_distance(hue, source[2]) > 0.5:
                where = ("/platforms/%s" % p if p else "") + "/semantic/%s/%s" % (theme, role)
                out.append(Finding("mix-grey-hue", "error", where,
                                   "hue %.2f but %s is %s: a mix into a grey must keep the coloured end's hue"
                                   % (hue, ref["mix"], dc.short_number(source[2]))))
    return out


def gamut_findings(tok):
    out = []
    for name, color in tok.primitives.items():
        if dc.out_of_gamut(color):
            out.append(Finding("gamut", "error", "/primitives/%s" % name,
                               "%s is outside sRGB and would clip to %s" % (dc.to_css(color), dc.to_hex(color))))
    sets = [(None, t, tok.refs[t], tok.palette[t]) for t in THEMES]
    sets += [(p, t, tok.platform_refs[p][t], tok.platform_palette[p][t]) for p in tok.platforms for t in THEMES]
    for p, theme, refs, palette in sets:
        for role, ref in refs.items():
            if isinstance(ref, dict) and role in palette and dc.out_of_gamut(palette[role]):
                where = ("/platforms/%s" % p if p else "") + "/semantic/%s/%s" % (theme, role)
                out.append(Finding("gamut", "error", where, "the mix %s is outside sRGB and would clip to %s"
                                   % (dc.to_css(palette[role]), dc.to_hex(palette[role]))))
    return out


def _exceptions(tok):
    found = collections.OrderedDict()
    for name, e in visible(tok.data.get("contrast", {}).get("exceptions", {})):
        themes = ("light", "dark") if e["applies"] == "light+dark" else (e["applies"],)
        found[name] = {"rule": e["rule"], "themes": themes, "platforms": e.get("platforms"), "results": {}}
    return found


def _applies(exc, platform, theme):
    if theme not in exc["themes"]:
        return False
    return exc["platforms"] is None or (platform is not None and platform in exc["platforms"])


def contrast_report(tok):
    """Every contrast and separation pair, per theme and per colour-overriding platform.

    Returns ``(findings, pairs)``: a pair is a dict (context, kind, pair, ratio, min, status, label) for the
    report. A platform re-checks only the pairs whose roles it overrides (the rest are the base's).
    """
    out = gamut_findings(tok) + mix_findings(tok)
    pairs = []
    contrast = tok.data.get("contrast", {})
    rules = contrast.get("rules", [])
    separation = contrast.get("separation", {})
    sep_rules = separation.get("rules", [])
    min_hue = separation.get("minHueDelta", 60)
    exceptions = _exceptions(tok)
    contexts = [(None, t, tok.palette[t], None) for t in THEMES]
    for p in tok.platforms:
        for t in THEMES:
            if tok.platform_palette[p][t]:
                contexts.append((p, t, tok.merged(p, t), set(tok.platform_palette[p][t])))

    def excepted(platform, theme, key, passed):
        hit = False
        for exc in exceptions.values():
            if exc["rule"] == key and _applies(exc, platform, theme):
                exc["results"].setdefault(theme, []).append(passed)
                hit = True
        return hit

    for platform, theme, palette, changed in contexts:
        label = "%s/%s" % (platform, theme) if platform else theme
        for i, rule in enumerate(rules):
            if changed is not None and rule["fg"] not in changed and rule["bg"] not in changed:
                continue
            key = "%s on %s" % (rule["fg"], rule["bg"])
            where = "%s: %s" % (label, key)
            missing = [r for r in (rule["fg"], rule["bg"]) if r not in palette]
            if missing:
                if platform is None and theme == THEMES[0]:  # once, not once a theme
                    out.append(Finding("unknown-role", "error", "/contrast/rules/%d" % i,
                                       "%s: no role named %s" % (key, ", ".join("\"%s\"" % m for m in missing))))
                continue
            fg, bg = palette[rule["fg"]], palette[rule["bg"]]
            if dc.alpha(bg) < 1:
                out.append(Finding("alpha-background", "error", where,
                                   "the background \"%s\" has alpha, so the ratio depends on what's under it: "
                                   "check it against an opaque role" % rule["bg"]))
                continue
            r = dc.contrast_over(fg, bg)
            passed = r >= rule["min"]
            status = "pass" if passed else "fail"
            if excepted(platform, theme, key, passed):
                status = "pass" if passed else "excepted"
            elif not passed:
                out.append(Finding("contrast", "error", where, "%s:1, needs %s:1 (%s)" % (
                    dc.to_fixed(r, 2), dc.js_number(rule["min"]), rule.get("label", key))))
            pairs.append({"context": label, "kind": "contrast", "pair": key, "ratio": float(dc.to_fixed(r, 2)),
                          "min": rule["min"], "status": status, "label": rule.get("label", "")})
        for i, rule in enumerate(sep_rules):
            if changed is not None and rule["a"] not in changed and rule["b"] not in changed:
                continue
            key = "separation %s vs %s" % (rule["a"], rule["b"])
            where = "%s: %s" % (label, key)
            missing = [r for r in (rule["a"], rule["b"]) if r not in palette]
            if missing:
                if platform is None and theme == THEMES[0]:  # once, not once a theme
                    out.append(Finding("unknown-role", "error", "/contrast/separation/rules/%d" % i,
                                       "%s: no role named %s" % (key, ", ".join("\"%s\"" % m for m in missing))))
                continue
            a, b = palette[rule["a"]], palette[rule["b"]]
            if dc.alpha(a) < 1 or dc.alpha(b) < 1:
                out.append(Finding("alpha-background", "error", where,
                                   "separation compares two opaque fills; one of these has alpha"))
                continue
            r = dc.contrast_ratio(a, b)
            hue = 0.0 if dc.is_grey(a) or dc.is_grey(b) else dc.hue_distance(a[2], b[2])
            by_hue = hue >= min_hue
            passed = r >= rule["min"] or by_hue
            status = "pass" if passed else "fail"
            if excepted(platform, theme, key, passed):
                status = "pass" if passed else "excepted"
            elif not passed:
                out.append(Finding("separation", "error", where,
                                   "luminance %s (needs %s) and hue %d degrees (needs %s): %s" % (
                                       dc.to_fixed(r, 2), dc.js_number(rule["min"]), dc.js_round(hue),
                                       dc.js_number(min_hue), rule.get("label", key))))
            pairs.append({"context": label, "kind": "separation", "pair": key, "ratio": float(dc.to_fixed(r, 2)),
                          "min": rule["min"], "hue": dc.js_round(hue), "byHue": by_hue, "status": status,
                          "label": rule.get("label", "")})

    for name, exc in exceptions.items():
        where = "/contrast/exceptions/%s" % name
        if not exc["results"]:
            out.append(Finding("exception-unused", "warning", where,
                               "no checked pair is \"%s\": name it as \"<fg> on <bg>\" or \"separation <a> vs <b>\", "
                               "or delete the exception" % exc["rule"]))
            continue
        for theme in exc["themes"]:
            results = exc["results"].get(theme)
            if results and all(results):
                out.append(Finding("stale-exception", "error", where,
                                   "\"%s\" now passes in %s: delete the exception (or narrow \"applies\")"
                                   % (exc["rule"], theme)))
    return out, pairs


# ------------------------------------------------------------------ CSS


def _color_value(color, space):
    return dc.to_hex(color) if space == "srgb" else dc.to_css(color)


def palette_lines(colors, effects, indent, space):
    """Declarations for a palette, a hex comment aligned after each (as OKLCH), then effects verbatim."""
    decls = [("--%s: %s;" % (role, _color_value(c, space)), dc.to_hex(c)) for role, c in colors]
    lines = []
    if decls:
        width = max(len(d) for d, _ in decls) + 2
        for d, hx in decls:
            lines.append(indent + (d.ljust(width) + "/* %s */" % hx if space != "srgb" else d))
    fx = ["%s--%s: %s;" % (indent, k, v) for k, v in effects]
    if lines and fx:
        lines.append("")
    return lines + fx


def _block(selector, body, indent=""):
    return [indent + selector + " {"] + body + [indent + "}"]


def css_text(tok):
    space = tok.color_space
    root = tok.root
    L = ["/* %s */" % banner("tokens.py", tok.source), ""]
    body = ["  color-scheme: light;", ""] + palette_lines(tok.palette["light"].items(),
                                                         tok.effects["light"].items(), "  ", space)
    for g in tok.scale:
        if g.entries:
            body += ["", "  /* %s */" % g.name] + ["  --%s: %s;" % (v, scalar_text(x)) for v, x, _, _ in g.entries]
    for m in tok.modes:
        others = [k for k in m.values if k != m.default]
        note = "; %s for the others" % m.selector if others else ""
        body += ["", "  /* %s: %s (default)%s */" % (m.name, m.default, note)]
        body += ["  --%s: %s;" % (k, scalar_text(v)) for k, v in m.values[m.default]]
    L += _block(root, body)
    for m in tok.modes:
        for mode, decls in m.values.items():
            if mode != m.default:
                L += [""] + _block(m.selector.replace("{mode}", mode),
                                   ["  --%s: %s;" % (k, scalar_text(v)) for k, v in decls])
    dark = (tok.palette["dark"].items(), tok.effects["dark"].items())
    light = (tok.palette["light"].items(), tok.effects["light"].items())
    L += ["", "/* The system appearance stamps nothing on the root, so prefers-color-scheme is the signal;",
          "   an explicit data-theme wins in both directions. */",
          "@media (prefers-color-scheme: dark) {"]
    L += _block('%s:not([data-theme="light"])' % root,
                ["    color-scheme: dark;", ""] + palette_lines(dark[0], dark[1], "    ", space), "  ")
    L += ["}", ""]
    L += _block('%s[data-theme="dark"]' % root, ["  color-scheme: dark;", ""] + palette_lines(*dark, "  ", space))
    L += [""]
    L += _block('%s[data-theme="light"]' % root,
                ["  color-scheme: light;", ""] + palette_lines(*light, "  ", space))
    for p in tok.platforms:
        L += _platform_css(tok, p)
    L += _reduced_motion(tok)
    return "\n".join(L) + "\n"


def _platform_css(tok, p):
    root = tok.root
    space = tok.color_space
    sel = '%s[data-platform="%s"]' % (root, tok.attribute[p])
    out = []
    if tok.platform_scale[p]:
        out += [""] + _block(sel, ["  --%s: %s;" % (v, scalar_text(x)) for v, x, _, _, _ in tok.platform_scale[p]])
    for theme, other in (("light", "dark"), ("dark", "light")):
        colors = tok.platform_palette[p][theme].items()
        effects = tok.platform_effects[p][theme].items()
        if not colors and not effects:
            continue
        out += ["", "@media (prefers-color-scheme: %s) {" % theme]
        out += _block('%s:not([data-theme="%s"])' % (sel, other), palette_lines(colors, effects, "    ", space), "  ")
        out += ["}", ""]
        out += _block('%s[data-theme="%s"]' % (sel, theme), palette_lines(colors, effects, "  ", space))
    if out:
        out = ["", "/* %s: the head stamps data-platform=\"%s\" on the root. */" % (PLATFORM_TITLE[p],
                                                                                  tok.attribute[p])] + out[1:]
    return out


def _reduced_motion(tok):
    motion = tok.groups.get("motion")
    if not motion:
        return []
    names = [v for v, x, _, _ in motion.entries if isinstance(x, str) and DURATION.match(x.strip())]
    if not names:
        return []
    platform_motion = any(g == "motion" for p in tok.platforms for _, _, g, _, _ in tok.platform_scale[p])
    selector = tok.root + (",\n  %s[data-platform]" % tok.root if platform_motion else "")
    return ["", "@media (prefers-reduced-motion: reduce) {"] + _block(
        selector, ["    --%s: 1ms;" % n for n in names], "  ") + ["}"]


# ------------------------------------------------------------------ C#


def _rgb(color):
    r, g, b, a = dc.srgb_bytes(color)
    return "new(%d, %d, %d)" % (r, g, b) if dc.alpha(color) >= 1 else "new(%d, %d, %d, %d)" % (r, g, b, a)


def _color_table(tok, name, colors, public=True):
    P = tok.prefix
    head = "    %sstatic readonly IReadOnlyDictionary<%sColor, %sRgb> %s = new Dictionary<%sColor, %sRgb>" % (
        "public " if public else "", P, P, name, P, P)
    rows = ["        [%sColor.%s] = %s," % (P, pascal(role), _rgb(c)) for role, c in colors.items()]
    return [head, "    {"] + rows + ["    };"]


def csharp_text(tok):
    spec = tok.outputs["csharp"]
    P = tok.prefix
    groups = spec.get("scale", [])
    L = ["// %s" % banner("tokens.py", tok.source), "#nullable enable", "",
         "using System.Collections.Generic;", "", "namespace %s;" % spec["namespace"], ""]
    L += ["/// <summary>Every semantic colour role. Native chrome and CSS resolve the same values.</summary>",
          "public enum %sColor" % P, "{"] + ["    %s," % pascal(r) for r in tok.role_names] + ["}", ""]
    L += ["/// <summary>An sRGB colour, 0-255 per channel.</summary>",
          "public readonly record struct %sRgb(byte R, byte G, byte B, byte A = 255)" % P, "{",
          '    public string ToHex() => A == 255 ? $"#{R:x2}{G:x2}{B:x2}" : $"#{R:x2}{G:x2}{B:x2}{A:x2}";', "}", "",
          "public enum %sTheme { Light, Dark }" % P]
    if tok.platforms:
        L += ["", "public enum %sPlatform { %s }" % (P, ", ".join(PLATFORM_PASCAL[p] for p in tok.platforms))]
    for group in groups:
        members = [tok.scale_member(group, entry, key) for _, _, entry, key in tok.groups[group].entries]
        L += ["", "public enum %s%s" % (P, pascal(group)), "{"] + ["    %s," % m for m in members] + ["}"]
    L += ["", "/// <summary>",
          "/// The generated palette and scale. Platform heads build their native colour type from these (NSColor on",
          "/// macOS, Windows.UI.Color on WinUI, Gdk.RGBA on GTK), so native chrome and the web content can't drift.",
          "/// </summary>",
          "public static class %sTokens" % P, "{",
          "    public static %sRgb Get(%sTheme theme, %sColor color) =>" % (P, P, P),
          "        theme == %sTheme.Dark ? Dark[color] : Light[color];" % P]
    colored = [p for p in tok.platforms if any(tok.platform_palette[p][t] for t in THEMES)]
    if tok.platforms:
        L += ["", "    /// <summary>A platform's colour: its override when it has one, else the base palette.</summary>",
              "    public static %sRgb Get(%sPlatform platform, %sTheme theme, %sColor color) =>" % (P, P, P, P)]
        if colored:
            L += ["        Overrides(platform, theme) is { } overrides && overrides.TryGetValue(color, out var rgb)",
                  "            ? rgb",
                  "            : Get(theme, color);", "",
                  "    static IReadOnlyDictionary<%sColor, %sRgb>? Overrides(%sPlatform platform, %sTheme theme) =>"
                  % (P, P, P, P), "        (platform, theme) switch", "        {"]
            for p in colored:
                for t in THEMES:
                    if tok.platform_palette[p][t]:
                        L.append("            (%sPlatform.%s, %sTheme.%s) => %s%s," % (
                            P, PLATFORM_PASCAL[p], P, t.capitalize(), PLATFORM_PASCAL[p], t.capitalize()))
            L += ["            _ => null,", "        };"]
        else:
            L += ["        Get(theme, color);"]
    for group in groups:
        L += [""] + _scale_method(tok, group)
    L += [""] + _color_table(tok, "Light", tok.palette["light"])
    L += [""] + _color_table(tok, "Dark", tok.palette["dark"])
    for p in colored:
        for t in THEMES:
            if tok.platform_palette[p][t]:
                L += [""] + _color_table(tok, PLATFORM_PASCAL[p] + t.capitalize(), tok.platform_palette[p][t], False)
    L.append("}")
    return "\n".join(L) + "\n"


def _scale_method(tok, group):
    P = tok.prefix
    G = pascal(group)
    enum = P + G
    entries = tok.groups[group].entries
    doc = "    /// <summary>The %s scale, in device-independent pixels (a bare number as written).</summary>" % group
    if not tok.platforms:
        out = [doc, "    public static double %s(%s token) => token switch" % (G, enum), "    {"]
        for _, value, entry, key in entries:
            out.append("        %s.%s => %s," % (enum, tok.scale_member(group, entry, key), dc.js_number(px_number(value))))
        return out + ["        _ => throw new System.ArgumentOutOfRangeException(nameof(token)),", "    };"]
    out = [doc, "    public static double %s(%sPlatform platform, %s token) => (platform, token) switch" % (G, P, enum),
           "    {"]
    for p in tok.platforms:
        for _, value, g, entry, key in tok.platform_scale[p]:
            if g == group:
                out.append("        (%sPlatform.%s, %s.%s) => %s," % (P, PLATFORM_PASCAL[p], enum,
                                                                   tok.scale_member(group, entry, key),
                                                                   dc.js_number(px_number(value))))
    for _, value, entry, key in entries:
        out.append("        (_, %s.%s) => %s," % (enum, tok.scale_member(group, entry, key),
                                                 dc.js_number(px_number(value))))
    return out + ["        _ => throw new System.ArgumentOutOfRangeException(nameof(token)),", "    };"]


# ------------------------------------------------------------------ macOS accent colour


def accent_text(tok):
    """The asset-catalog colour set AppKit reads the app's accent from at launch (light, then dark)."""
    role = tok.outputs["macosAccent"]["role"]
    platform = "macos" if "macos" in tok.platforms else None

    def entry(theme, appearances=None):
        color = tok.merged(platform, theme)[role]
        r, g, b = (dc.to_fixed(dc.clamp01(c), 3) for c in dc.oklch_to_srgb(color))
        item = collections.OrderedDict([("idiom", "universal")])
        if appearances:
            item["appearances"] = appearances
        item["color"] = {"color-space": "srgb", "components": collections.OrderedDict(
            [("red", r), ("green", g), ("blue", b), ("alpha", dc.to_fixed(dc.clamp01(dc.alpha(color)), 3))])}
        return item

    doc = {"colors": [entry("light"), entry("dark", [{"appearance": "luminosity", "value": "dark"}])],
           "info": {"author": "xcode", "version": 1}}
    return jsonio.dumps(doc)


# ------------------------------------------------------------------ DESIGN.md


def palette_table(tok, palette):
    ground = tok.ground(palette)
    rows = ["| Token | OKLCH | Hex | Contrast |", "|---|---|---|---|"]
    for role, color in palette.items():
        if role == ground:
            ratio = DASH
        else:
            ratio = "%s:1 vs %s" % (dc.to_fixed(dc.contrast_over(color, palette[ground]), 2), ground)
        rows.append("| `--%s` | `%s` | `%s` | %s |" % (role, dc.to_css(color), dc.to_hex(color), ratio))
    return "\n".join(rows)


def _cell(text):
    """A table cell holding a value: in backticks, with any ``|`` escaped so the row stays one row."""
    return "`%s`" % text.replace("|", "\\|")


def platform_matrix(tok):
    """Every token that differs by platform: one row a token, one column a platform (``DASH``: the base's)."""
    if not tok.platforms:
        return "No token differs by platform."
    head = "| Token | Base | %s |" % " | ".join(PLATFORM_TITLE[p] for p in tok.platforms)
    rows = [head, "|---|---|%s" % ("---|" * len(tok.platforms))]
    for g in tok.scale:
        for var, value, entry, key in g.entries:
            cells = []
            for p in tok.platforms:
                hit = [x for v, x, _, _, _ in tok.platform_scale[p] if v == var]
                cells.append(_cell(scalar_text(hit[0])) if hit else DASH)
            if any(c != DASH for c in cells):
                rows.append("| `--%s` | %s | %s |" % (var, _cell(scalar_text(value)), " | ".join(cells)))
    for theme in THEMES:
        for role in tok.role_names:
            cells = [(_cell(dc.to_hex(tok.platform_palette[p][theme][role]))
                      if role in tok.platform_palette[p][theme] else DASH) for p in tok.platforms]
            if any(c != DASH for c in cells) and role in tok.palette[theme]:
                rows.append("| `--%s` (%s) | %s | %s |" % (role, theme, _cell(dc.to_hex(tok.palette[theme][role])),
                                                           " | ".join(cells)))
        for name, value in tok.effects[theme].items():
            cells = [(_cell(tok.platform_effects[p][theme][name]) if name in tok.platform_effects[p][theme]
                      else DASH) for p in tok.platforms]
            if any(c != DASH for c in cells):
                rows.append("| `--%s` (%s) | %s | %s |" % (name, theme, _cell(value), " | ".join(cells)))
    if len(rows) == 2:
        return "No token differs by platform."
    return "\n".join(rows)


def marker_span(text, name):
    """``(i, j)``: the end of the start marker and the start of the end marker, or None when absent.
    Raises ``ValueError`` when only one is there or they're out of order."""
    start = "<!-- generated:%s:start -->" % name
    end = "<!-- generated:%s:end -->" % name
    i, j = text.find(start), text.find(end)
    if i == -1 and j == -1:
        return None
    if i == -1 or j == -1 or j < i:
        raise ValueError("the %s and %s markers must both be there, in that order" % (start, end))
    return i + len(start), j


def splice(text, name, body):
    """Replace what's between a marker pair with ``body`` (and nothing else in the file)."""
    span = marker_span(text, name)
    if span is None:
        return text
    return text[:span[0]] + "\n" + body + "\n" + text[span[1]:]


def design_text(tok, current, where):
    """DESIGN.md with every present marker pair refilled. ``(text, findings)``."""
    out = []
    tables = [("palette-light", palette_table(tok, tok.palette["light"])),
              ("palette-dark", palette_table(tok, tok.palette["dark"]))]
    for p in tok.platforms:
        for t in THEMES:
            tables.append(("palette-%s-%s" % (p, t), palette_table(tok, tok.merged(p, t))))
    tables.append(("platform-matrix", platform_matrix(tok)))
    text = current
    for name, body in tables:
        try:
            span = marker_span(text, name)
        except ValueError as e:
            out.append(Finding("design-markers", "error", where, str(e)))
            continue
        if span is None:
            if name in ("palette-light", "palette-dark"):
                out.append(Finding("design-markers", "error", where,
                                   "missing <!-- generated:%s:start --> / <!-- generated:%s:end -->: add the pair "
                                   "where the table goes" % (name, name)))
            continue
        text = splice(text, name, body)
    return text, out


# ------------------------------------------------------------------ build


def render(tok, root):
    """``([(key, relative path, text)], findings)`` for every output the tokens name."""
    outputs = []
    found = []
    spec = tok.outputs
    if spec.get("css"):
        outputs.append(("css", spec["css"], css_text(tok)))
    if spec.get("csharp"):
        outputs.append(("csharp", spec["csharp"]["path"], csharp_text(tok)))
    if spec.get("macosAccent"):
        role = spec["macosAccent"]["role"]
        if role not in tok.palette["light"]:
            raise UsageError("no role %s" % role, [Finding("unknown-role", "error", "/outputs/macosAccent/role",
                                                           "there's no \"%s\" role" % role)])
        outputs.append(("macosAccent", spec["macosAccent"]["path"], accent_text(tok)))
    if spec.get("design"):
        path = under(root, spec["design"])
        if not os.path.isfile(path):
            found.append(Finding("design-missing", "error", spec["design"],
                                 "no such file: start it from the design skill's templates/DESIGN.md (it carries "
                                 "the generated markers), or drop outputs.design"))
        else:
            text, problems = design_text(tok, read_text(path), spec["design"])
            found += problems
            if not problems:
                outputs.append(("design", spec["design"], text))
    return outputs, found


def write_outputs(root, outputs, ignored, check, stream=None):
    """Write (or with ``check``, compare) each output. Returns ``(findings, statuses)``.

    An output listed in ``ignored`` (gitignored) that doesn't exist yet isn't stale: a fresh checkout has none.
    """
    stream = stream or sys.stdout
    found = []
    statuses = []
    for key, path, text in outputs:
        full = under(root, path)
        current = read_text(full) if os.path.isfile(full) else None
        if current == text:
            status = "current"
        elif check and current is None and key in ignored:
            status = "absent (ignored)"
        elif check:
            status = "stale"
            found.append(Finding("stale", "error", path,
                                 "out of date: run the generator (without --check) and commit the result"
                                 if current is not None else "missing: run the generator (without --check)"))
        else:
            write_text(full, text)
            status = "written"
        statuses.append({"output": key, "path": path, "status": status})
    return found, statuses


def build(root, tokens_file, check=False, json_output=False, stream=None):
    stream = stream or sys.stdout
    tok = load_tokens(tokens_file, root)
    found = mix_findings(tok)
    if found:
        fnd.print_findings(found, json_output, stream)
        return EXIT_FINDINGS
    outputs, problems = render(tok, root)
    found += problems
    if not outputs and not problems:
        found.append(Finding("no-outputs", "info", rel(tokens_file, root),
                             "outputs names nothing to generate: add css, csharp, macosAccent or design"))
    written, statuses = write_outputs(root, outputs, tok.outputs.get("ignored", []), check)
    found += written
    if json_output:
        fnd.print_findings(found, True, stream, outputs=statuses)
    else:
        for s in statuses:
            mark = {"current": "=", "written": "wrote", "stale": "STALE", "absent (ignored)": "-"}[s["status"]]
            stream.write("  %-5s %s\n" % (mark, s["path"]))
        fnd.print_findings(found, False, stream)
    return fnd.exit_code(found)


# ------------------------------------------------------------------ contrast and show


def contrast(root, tokens_file, json_output=False, quiet=False, stream=None):
    stream = stream or sys.stdout
    tok = load_tokens(tokens_file, root)
    found, pairs = contrast_report(tok)
    excepted = sum(1 for p in pairs if p["status"] == "excepted")
    if json_output:
        fnd.print_findings(found, True, stream, pairs=pairs)
        return fnd.exit_code(found)
    if not quiet:
        context = None
        for p in pairs:
            if p["context"] != context:
                context = p["context"]
                stream.write("\n%s\n" % context)
            tag = {"pass": "PASS", "fail": "FAIL", "excepted": "EXCEPT"}[p["status"]]
            how = ""
            if p["kind"] == "separation":
                how = " (%d degrees of hue)" % p["hue"] if p["byHue"] else " (luminance)"
            stream.write("  %6.2f  %-6s  %-40s %s%s\n" % (p["ratio"], tag, p["pair"], p["label"], how))
        stream.write("\n")
    fnd.print_findings(found, False, stream, summary="%d pairs checked, %d excepted." % (len(pairs), excepted))
    return fnd.exit_code(found)


def show(root, tokens_file, theme=None, platform=None, json_output=False, stream=None):
    stream = stream or sys.stdout
    tok = load_tokens(tokens_file, root)
    if platform and platform not in tok.platforms:
        raise UsageError("no platform %s" % platform, [Finding("unknown-platform", "error", "--platform",
                                                               "the tokens have no \"%s\" platform (they have: %s)"
                                                               % (platform, ", ".join(tok.platforms) or "none"))])
    themes = [theme] if theme else list(THEMES)
    palette = {}
    for t in themes:
        palette[t] = collections.OrderedDict(
            (role, {"css": dc.to_css(c), "hex": dc.to_hex(c), "oklch": [round(x, 6) for x in c]})
            for role, c in tok.merged(platform, t).items())
    scale = collections.OrderedDict((v, x) for g in tok.scale for v, x, _, _ in g.entries)
    if platform:
        scale.update((v, x) for v, x, _, _, _ in tok.platform_scale[platform])
    modes = {m.name: {"default": m.default, "values": {k: dict(d) for k, d in m.values.items()}} for m in tok.modes}
    if json_output:
        fnd.print_findings([], True, stream, platform=platform, palette=palette, scale=scale, modes=modes,
                           platforms=tok.platforms)
        return EXIT_OK
    for t in themes:
        stream.write("Palette: %s%s\n" % (t, " on %s" % PLATFORM_TITLE[platform] if platform else ""))
        width = max([len(r) for r in palette[t]] + [4]) + 2
        for role, v in palette[t].items():
            stream.write("  --%s %-28s %s\n" % (role.ljust(width), v["css"], v["hex"]))
        stream.write("\n")
    stream.write("Scale%s\n" % (" on %s" % PLATFORM_TITLE[platform] if platform else ""))
    for var, value in scale.items():
        stream.write("  --%s: %s\n" % (var, scalar_text(value)))
    for m in tok.modes:
        stream.write("\nMode %s: %s (default), %s\n" % (m.name, m.default, m.selector))
    if tok.platforms:
        stream.write("\nPlatforms: %s\n" % ", ".join(tok.platforms))
    return EXIT_OK


# ------------------------------------------------------------------ init: the project's layout


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def read_csproj(path):
    """What ``init`` needs from a project file: ``sdk``, ``tfms``, ``packages``, ``output``, ``namespace``."""
    info = {"sdk": "", "tfms": [], "packages": [], "output": "", "namespace": "", "useMaui": False}
    try:
        top = ET.parse(path).getroot()
    except (ET.ParseError, OSError):
        return info
    info["sdk"] = top.get("Sdk", "")
    for el in top.iter():
        tag = _local(el.tag)
        text = (el.text or "").strip()
        if tag in ("TargetFramework", "TargetFrameworks") and text:
            info["tfms"] += [t.strip() for t in text.split(";") if t.strip()]
        elif tag == "PackageReference" and el.get("Include"):
            info["packages"].append(el.get("Include"))
        elif tag == "OutputType" and text:
            info["output"] = text
        elif tag == "RootNamespace" and text:
            info["namespace"] = text
        elif tag == "UseMaui" and text.lower() == "true":
            info["useMaui"] = True
    return info


def scan_projects(root):
    """Every ``*.csproj`` under ``root``: ``[{dir, name, info, wwwroot, razor}]``, sorted by path."""
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith("."))
        for f in sorted(filenames):
            if f.endswith(".csproj"):
                path = os.path.join(dirpath, f)
                found.append({"dir": rel(dirpath, root), "name": f[:-len(".csproj")], "info": read_csproj(path),
                              "wwwroot": os.path.isdir(os.path.join(dirpath, "wwwroot"))})
    return sorted(found, key=lambda p: (p["dir"], p["name"]))


def _is_macos(p):
    info = p["info"]
    return any(t.endswith("-macos") for t in info["tfms"]) or "Microsoft.Maui.Platforms.MacOS" in info["packages"]


def _is_head(p):
    info = p["info"]
    heads = ("-macos", "-windows", "-android", "-ios", "-maccatalyst", "-tizen")
    return (any(any(h in t for h in heads) for t in info["tfms"]) or info["output"].lower() in ("exe", "winexe")
            or any(pkg.startswith("Microsoft.Maui.Platforms.") for pkg in info["packages"]))


def _is_test(p):
    return "test" in p["name"].lower() or "Microsoft.NET.Test.Sdk" in p["info"]["packages"]


def _join(*parts):
    return "/".join(x for x in parts if x and x != ".")


def guess_layout(root):
    """Where generated files would go, from the project files alone: ``{ui, core, macos}``, each a project
    ``{dir, name, namespace}`` or None.

    ``ui``: a project with a ``wwwroot`` folder (a Razor class library first). ``core``: a ``*.Core`` project,
    else the first library that isn't a head, a test or the UI. ``macos``: a project targeting ``-macos``.
    """
    projects = scan_projects(root)

    def short(p):
        return None if p is None else {"dir": p["dir"], "name": p["name"],
                                       "namespace": p["info"]["namespace"] or p["name"]}

    with_web = [p for p in projects if p["wwwroot"]]
    ui = next((p for p in with_web if p["info"]["sdk"].endswith(".Razor")), None)
    ui = ui or next((p for p in with_web if not _is_head(p)), None) or (with_web[0] if with_web else None)
    core = next((p for p in projects if p["name"].endswith(".Core") and not _is_test(p)), None)
    core = core or next((p for p in projects if not _is_head(p) and not _is_test(p) and p is not ui), None)
    macos = next((p for p in projects if _is_macos(p)), None)
    return {"ui": short(ui), "core": short(core), "macos": short(macos)}


def read_blueprint(path):
    """``{name, namespace, platforms}`` from ``desktop-blueprint.json`` (read directly; only these fields)."""
    data = load_json(path)
    if not isinstance(data, dict):
        raise UsageError("%s: not a JSON object" % path)
    app = data.get("app") or {}
    platforms = data.get("platforms") or {}
    enabled = [p for p in PLATFORMS if isinstance(platforms.get(p), dict) and platforms[p].get("enabled")]
    namespace = app.get("namespace") or ""
    return {"name": app.get("name"), "namespace": namespace.split(".")[-1] if namespace else None,
            "platforms": enabled}


def project_name(root):
    """A name for a project without a blueprint: its solution's, else its folder's."""
    try:
        names = sorted(f for f in os.listdir(root) if f.endswith((".slnx", ".sln")))
    except OSError:
        names = []
    if names:
        return os.path.splitext(names[0])[0]
    return os.path.basename(os.path.abspath(root)) or "App"


def blueprint_for(root, given):
    """The blueprint's fields, or None. ``--blueprint`` must exist; the default is used only when present."""
    if given:
        path = given if os.path.isabs(given) else os.path.join(root, given)
        return read_blueprint(path)
    path = os.path.join(root, DEFAULT_BLUEPRINT)
    return read_blueprint(path) if os.path.isfile(path) else None


def init(root, out, blueprint=None, stream=None):
    stream = stream or sys.stdout
    target = out if os.path.isabs(out) else os.path.join(root, out)
    if os.path.exists(target):
        stream.write("%s already exists; not overwriting it. Edit it, or move it aside first.\n" % rel(target, root))
        return EXIT_REFUSED
    template = find_resource("templates", "tokens.json")
    if not os.path.isfile(template):
        raise UsageError("the skill's templates/tokens.json isn't here: run init from the skill, not an installed "
                         "copy")
    data = jsonio.load(template)
    bp = blueprint_for(root, blueprint)
    name = (bp or {}).get("name") or project_name(root)
    meta = collections.OrderedDict(data.get("meta", {}))
    meta["name"] = name
    meta["csharpPrefix"] = csharp_prefix({"csharpPrefix": (bp or {}).get("namespace"), "name": name})
    data["meta"] = meta
    notes = []
    if bp is not None:
        platforms = collections.OrderedDict()
        for key, value in data.get("platforms", {}).items():
            if key.startswith("$") or key in bp["platforms"]:
                platforms[key] = value
        if "web" in bp["platforms"] and "web" not in platforms:
            platforms["web"] = {}
        data["platforms"] = platforms
        notes.append("platforms from the blueprint: %s" % (", ".join(bp["platforms"]) or "none"))
    layout = guess_layout(root)
    outputs = collections.OrderedDict((k, v) for k, v in data.get("outputs", {}).items() if k.startswith("$"))
    if layout["ui"]:
        outputs["css"] = _join(layout["ui"]["dir"], "wwwroot/css/tokens.css")
    else:
        notes.append("no project with a wwwroot folder: set outputs.css by hand")
    if layout["core"]:
        outputs["csharp"] = collections.OrderedDict([
            ("path", _join(layout["core"]["dir"], "Theme/Tokens.g.cs")),
            ("namespace", layout["core"]["namespace"] + ".Theme"),
            ("scale", ["radius", "control"])])
    else:
        notes.append("no library for the C# palette: set outputs.csharp by hand")
    if os.path.isfile(os.path.join(root, "DESIGN.md")):
        text = read_text(os.path.join(root, "DESIGN.md"))
        try:
            marked = bool(marker_span(text, "palette-light") and marker_span(text, "palette-dark"))
        except ValueError:
            marked = False
        if marked:
            outputs["design"] = "DESIGN.md"
        else:
            notes.append("DESIGN.md has no generated palette markers: add them, then set outputs.design")
    else:
        notes.append("no DESIGN.md: start it from the design skill's templates/DESIGN.md, then set outputs.design")
    if layout["macos"]:
        outputs["macosAccent"] = collections.OrderedDict([
            ("path", _join(layout["macos"]["dir"], "Assets.xcassets/AccentColor.colorset/Contents.json")),
            ("role", "accent")])
    outputs["ignored"] = []
    data["outputs"] = outputs
    scale = data.get("scale", {})
    if "csharp" in outputs:
        outputs["csharp"]["scale"] = [g for g in outputs["csharp"]["scale"] if g in scale]
    os.makedirs(os.path.dirname(os.path.abspath(target)), exist_ok=True)
    write_text(target, pretty_json(data) + "\n")
    stream.write("wrote %s\n" % rel(target, root))
    for key in OUTPUT_KEYS:
        if key in outputs:
            value = outputs[key]
            stream.write("  outputs.%s: %s\n" % (key, value["path"] if isinstance(value, dict) else value))
    for n in notes:
        stream.write("  note: %s\n" % n)
    return EXIT_OK


# ------------------------------------------------------------------ command line


def parse_args(argv):
    p = argparse.ArgumentParser(prog="tokens.py", description="Generate, check and show an app's design tokens.")
    sub = p.add_subparsers(dest="command")
    sub.required = True
    i = sub.add_parser("init", help="start design/tokens.json from the skill's template")
    i.add_argument("--root", default=".")
    i.add_argument("--out", default=DEFAULT_TOKENS)
    i.add_argument("--blueprint", help="desktop-blueprint.json (default: the root's, when there is one)")
    b = sub.add_parser("build", help="write every output (or check them with --check)")
    b.add_argument("--root", default=".")
    b.add_argument("--tokens")
    b.add_argument("--check", action="store_true", help="write nothing; exit 1 naming each stale output")
    b.add_argument("--json", action="store_true")
    c = sub.add_parser("contrast", help="check every contrast and separation pair, and the gamut")
    c.add_argument("--root", default=".")
    c.add_argument("--tokens")
    c.add_argument("--json", action="store_true")
    c.add_argument("--quiet", action="store_true", help="print only the findings")
    s = sub.add_parser("show", help="print the resolved palette and scale")
    s.add_argument("--root", default=".")
    s.add_argument("--tokens")
    s.add_argument("--theme", choices=THEMES)
    s.add_argument("--platform", choices=PLATFORMS)
    s.add_argument("--json", action="store_true")
    return p.parse_args(argv)


def main(argv=None, stream=None):
    stream = stream or sys.stdout
    args = parse_args(argv)
    root = os.path.abspath(args.root)
    json_output = getattr(args, "json", False)
    try:
        if not os.path.isdir(root):
            raise UsageError("--root %s isn't a folder" % args.root)
        if args.command == "init":
            return init(root, args.out, args.blueprint, stream)
        path = tokens_path(root, args.tokens)
        if args.command == "build":
            return build(root, path, args.check, json_output, stream)
        if args.command == "contrast":
            return contrast(root, path, json_output, args.quiet, stream)
        return show(root, path, args.theme, args.platform, json_output, stream)
    except UsageError as e:
        if json_output:
            fnd.print_findings(e.findings, True, stream)
        else:
            fnd.print_findings(e.findings, False, sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
