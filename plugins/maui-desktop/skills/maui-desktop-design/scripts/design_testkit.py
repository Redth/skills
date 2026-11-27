"""Helpers for the design skill's tests: copying an eval fixture into a temp folder, running a script's ``main``
in-process, and parsers that turn generated files back into plain data (so two generators can be compared by
value rather than by formatting). Stdlib only; nothing here reaches a network."""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
FILES = os.path.join(SKILL_DIR, "evals", "files")
TEMPLATES = os.path.join(SKILL_DIR, "templates")

if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


def fixture(name, dest, fresh=True):
    """Copy ``evals/files/<name>`` to ``dest`` (which must not exist) and return ``dest``.

    With ``fresh``, anything a generator may have left in the fixture (someone ran ``build`` in it) is
    undone in the copy: the generated ``src/`` outputs go and DESIGN.md's tables are emptied, so a test
    always starts from what's committed."""
    shutil.copytree(os.path.join(FILES, name), dest, ignore=shutil.ignore_patterns("__pycache__"))
    if fresh:
        _unbuild(dest)
    return dest


def _unbuild(root):
    tokens_file = os.path.join(root, "design", "tokens.json")
    generated = []
    for name in ("tokens.json", "icons.json"):
        path = os.path.join(root, "design", name)
        if os.path.isfile(path):
            outputs = load(path).get("outputs", {})
            for key, value in outputs.items():
                if key in ("design", "ignored") or key.startswith("$"):
                    continue
                generated.append(value["path"] if isinstance(value, dict) else value)
    for rel in generated:
        path = os.path.join(root, *rel.split("/"))
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.isfile(path):
            os.unlink(path)
        parent = os.path.dirname(path)
        while os.path.abspath(parent) != os.path.abspath(root) and os.path.isdir(parent) and not os.listdir(parent):
            os.rmdir(parent)  # the folders a build made for its outputs
            parent = os.path.dirname(parent)
    design = os.path.join(root, "DESIGN.md")
    if os.path.isfile(tokens_file) and os.path.isfile(design):
        text = read(design)
        text = re.sub(r"(<!-- generated:([\w-]+):start -->)\n.*?(<!-- generated:\2:end -->)",
                      lambda m: m.group(1) + "\n" + m.group(3), text, flags=re.S)
        write(design, text)


def run(module, argv):
    """Run ``module.main(argv)`` in-process; return ``(exit code, stdout, stderr)``."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = module.main(argv, stream=out)
        except SystemExit as e:  # argparse
            code = e.code
    return code, out.getvalue(), err.getvalue()


def run_json(module, argv):
    """Run with ``--json`` and parse what it printed."""
    code, out, err = run(module, argv + ["--json"])
    try:
        return code, json.loads(out)
    except ValueError:
        raise AssertionError("not JSON (exit %s):\n%s\n%s" % (code, out, err))


def ids(report):
    """The finding ids in a ``--json`` report."""
    return [f["id"] for f in report["findings"]]


def write(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return path


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def load(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def dump(value, path):
    return write(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def make_layout(root, design_md=True):
    """A Sample Notes project the older way: the Windows head doubles as a UI project (it has a wwwroot), with
    a Razor class library, a Core library, an AppKit head and a test project beside it; and a DESIGN.md
    carrying the palette markers."""
    csproj = '<Project Sdk="%s">\n  <PropertyGroup>\n%s  </PropertyGroup>\n</Project>\n'
    write(os.path.join(root, "SampleNotes.slnx"), "<Solution />\n")
    write(os.path.join(root, "src/SampleNotes/SampleNotes.csproj"), csproj % (
        "Microsoft.NET.Sdk", "    <TargetFrameworks>net11.0-windows10.0.19041.0</TargetFrameworks>\n"
                             "    <OutputType>WinExe</OutputType>\n    <UseMaui>true</UseMaui>\n"))
    os.makedirs(os.path.join(root, "src/SampleNotes/wwwroot"))
    write(os.path.join(root, "src/SampleNotes.Ui/SampleNotes.Ui.csproj"), csproj % (
        "Microsoft.NET.Sdk.Razor", "    <TargetFramework>net11.0</TargetFramework>\n"))
    os.makedirs(os.path.join(root, "src/SampleNotes.Ui/wwwroot"))
    write(os.path.join(root, "src/SampleNotes.Core/SampleNotes.Core.csproj"), csproj % (
        "Microsoft.NET.Sdk", "    <TargetFramework>net11.0</TargetFramework>\n"))
    write(os.path.join(root, "src/SampleNotes.MacOS/SampleNotes.MacOS.csproj"), csproj % (
        "Microsoft.NET.Sdk", "    <TargetFramework>net11.0-macos</TargetFramework>\n    <UseMaui>true</UseMaui>\n"))
    write(os.path.join(root, "tests/SampleNotes.Core.Tests/SampleNotes.Core.Tests.csproj"), csproj % (
        "Microsoft.NET.Sdk", "    <TargetFramework>net11.0</TargetFramework>\n"))
    if design_md:
        write(os.path.join(root, "DESIGN.md"), "# Sample Notes\n\n<!-- generated:palette-light:start -->\n"
              "<!-- generated:palette-light:end -->\n\n<!-- generated:palette-dark:start -->\n"
              "<!-- generated:palette-dark:end -->\n")
    return root


def make_blueprint(root, platforms):
    """A minimal ``desktop-blueprint.json`` for Sample Notes with ``platforms`` enabled."""
    return dump({"version": 1, "app": {"name": "Sample Notes", "id": "com.example.samplenotes",
                                       "namespace": "SampleNotes"},
                 "platforms": {p: {"enabled": p in platforms} for p in ("macos", "windows", "linux", "web")}},
                os.path.join(root, "desktop-blueprint.json"))


# ------------------------------------------------------------------ parsers


_HEX_COMMENT = re.compile(r"/\*\s*(#[0-9a-fA-F]{3,8})\s*\*/")
_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def parse_css(text):
    """A stylesheet as ``({context: {property: value}}, {context: {property: hex comment}})``.

    A context is its selectors joined with `` > `` (``@media (prefers-color-scheme: dark) > :root:not(…)``),
    whitespace collapsed. Only custom properties and ``color-scheme`` are kept; empty contexts are dropped.
    """
    text = _HEX_COMMENT.sub(lambda m: "\x00%s\x00" % m.group(1), text)
    text = _COMMENT.sub("", text)
    values, hexes = {}, {}
    stack, pending = [], ""
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        if line.endswith("{"):
            selector = " ".join((pending + " " + line[:-1]).split())
            stack.append(selector)
            pending = ""
        elif line == "}":
            stack.pop()
        elif line.endswith(","):
            pending += " " + line
        elif line.startswith("--") or line.startswith("color-scheme"):
            hx = None
            if "\x00" in line:
                line, hx = line.split("\x00")[0].strip(), line.split("\x00")[1]
            name, _, value = line.partition(":")
            ctx = " > ".join(stack)
            values.setdefault(ctx, {})[name.strip()] = " ".join(value.strip().rstrip(";").split())
            if hx:
                hexes.setdefault(ctx, {})[name.strip()] = hx.lower()
    return values, hexes


_CS_ROW = re.compile(r"\[\w+\.(\w+)\]\s*=\s*new\((\d+),\s*(\d+),\s*(\d+)(?:,\s*(\d+))?\)")


def parse_cs_colors(text, table):
    """A generated C# palette table (``Light``, ``Dark``, ``MacOSLight``…) as ``{Role: [r, g, b(, a)]}``."""
    m = re.search(r"IReadOnlyDictionary<\w+, \w+> %s = new Dictionary<\w+, \w+>\s*\{(.*?)\};" % table, text, re.S)
    if not m:
        raise AssertionError("no %s table" % table)
    out = {}
    for row in _CS_ROW.finditer(m.group(1)):
        out[row.group(1)] = [int(x) for x in row.groups()[1:] if x is not None]
    return out


_CS_STRING_ROW = re.compile(r'\[IconRef\.(\w+)\]\s*=\s*("(?:[^"\\]|\\.)*")')


def parse_cs_strings(text, table):
    """A generated C# string table (``SfSymbols``, ``GtkNames``…) as ``{Member: value}``."""
    m = re.search(r"IReadOnlyDictionary<IconRef, string> %s = new Dictionary<IconRef, string>\s*\{(.*?)\};" % table,
                  text, re.S)
    if not m:
        raise AssertionError("no %s table" % table)
    return {row.group(1): json.loads(row.group(2)) for row in _CS_STRING_ROW.finditer(m.group(1))}


def marker_rows(text, name):
    """The lines between a DESIGN.md marker pair."""
    start = "<!-- generated:%s:start -->" % name
    end = "<!-- generated:%s:end -->" % name
    i, j = text.index(start) + len(start), text.index(end)
    return [line for line in text[i:j].split("\n") if line.strip()]


def svg_body(text):
    """The ``<svg …>…</svg>`` element of a generated sprite or Razor file, as a list of lines."""
    i, j = text.index("<svg"), text.rindex("</svg>") + len("</svg>")
    return text[i:j].split("\n")
