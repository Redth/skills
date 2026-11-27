"""Reading .NET project files without MSBuild: what a project targets, references and includes.

Nothing here runs ``dotnet``. A project file is parsed as XML (``xml.etree.ElementTree``), with a regex
fallback for a file that isn't well-formed. Conditions are recorded, never evaluated: a property set under
two conditions keeps the last value in ``properties`` and both in ``conditional``; ``target_frameworks`` is
every framework the file names under any condition, so a head that only targets macOS when built on a Mac
still says so.

- ``read_project(path, central=None) -> Project``
- ``central_versions(root) -> {package id: version}`` from ``Directory.Packages.props``
- ``central_versions_for(project_path, root)``: the nearest ``Directory.Packages.props`` above a project
- ``cpm_enabled(root)``: whether central package management is switched on
- ``sdk_version(root)``: ``sdk.version`` from ``global.json`` (comments tolerated), or ``None``
- ``walk(root)``: the project tree as ``(relative path, absolute path, is_link)``, skipping build output,
  dependencies and vendored folders, never following a symlink
- ``project_files(root)`` and ``solution_files(root)``: the ``.csproj`` / ``.slnx`` and ``.sln`` files
"""

from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET

# Folders never descended into (by name, anywhere in the tree).
SKIP_DIRS = frozenset([
    "bin", "obj", "node_modules", ".git", ".vs", ".idea", ".vscode", "packages", "artifacts", "TestResults",
    "__pycache__", "third_party", "third-party", "ThirdParty",
])
# Folders skipped by their path's tail: vendored web assets.
SKIP_TAILS = (("wwwroot", "lib"), ("wwwroot", "vendor"), ("wwwroot", "_content"))
# Dot-folders are skipped (editor state, scratch copies) except these.
KEEP_DOT_DIRS = frozenset([".github"])

PROJECT_EXTS = (".csproj", ".fsproj", ".vbproj")
SOLUTION_EXTS = (".slnx", ".sln")


def rel(path, root):
    """``path`` relative to ``root`` with ``/`` separators, whatever the OS."""
    return os.path.relpath(path, root).replace(os.sep, "/")


def _skip_dir(name, parts):
    if name in SKIP_DIRS:
        return True
    if name.startswith(".") and name not in KEEP_DOT_DIRS:
        return True
    for tail in SKIP_TAILS:
        if tuple(parts[-len(tail):]) == tail:
            return True
    return False


def walk(root):
    """Yield ``(relative path, absolute path, is_link)`` for every file and symlink under ``root``.

    Relative paths use ``/``. Symlinked folders are yielded (``is_link`` true) but never entered, so a
    link back up the tree can't loop. Folders in ``SKIP_DIRS``, dot-folders other than ``.github`` and
    vendored ``wwwroot/lib``, ``wwwroot/vendor`` and ``wwwroot/_content`` are skipped. Sorted, so the
    order is the same on every OS.
    """
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = os.path.relpath(dirpath, root)
        parts = [] if here == "." else here.replace(os.sep, "/").split("/")
        keep = []
        for d in sorted(dirnames):
            full = os.path.join(dirpath, d)
            if os.path.islink(full):
                yield "/".join(parts + [d]), full, True
                continue
            if _skip_dir(d, parts + [d]):
                continue
            keep.append(d)
        dirnames[:] = keep
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            yield "/".join(parts + [f]), full, os.path.islink(full)


def project_files(root):
    """The project files under ``root`` (relative, ``/``-separated, sorted)."""
    return [r for r, _a, link in walk(root) if not link and r.lower().endswith(PROJECT_EXTS)]


def solution_files(root):
    """The ``.slnx`` and ``.sln`` files under ``root`` (relative, ``/``-separated, sorted; shallowest first)."""
    found = [r for r, _a, link in walk(root) if not link and r.lower().endswith(SOLUTION_EXTS)]
    return sorted(found, key=lambda p: (p.count("/"), p))


def read_text(path, limit=4 * 1024 * 1024):
    """A file's text (UTF-8, undecodable bytes replaced, a byte-order mark dropped, ``\\r\\n`` read as ``\\n``),
    or ``None`` past ``limit`` bytes or when it can't be read."""
    try:
        if os.path.getsize(path) > limit:
            return None
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    text = data.decode("utf-8", errors="replace")
    if text.startswith("﻿"):
        text = text[1:]
    return text.replace("\r\n", "\n")


class Project(object):
    """What a project file says, read without evaluating it.

    - ``path``: as given; ``sdk``: the SDK named on ``<Project Sdk>``, an ``<Import Sdk>`` or ``<Sdk Name>``
      (the first; ``sdks`` has them all).
    - ``properties``: name -> value, the last one in the file winning; ``conditional``: name -> list of
      ``(value, condition or None)`` in file order.
    - ``target_frameworks``: every framework named by ``TargetFramework`` or ``TargetFrameworks`` under
      any condition, in file order, without repeats.
    - ``package_refs``: ``(id, version or None, condition or None)``; a version missing from the reference
      comes from ``central`` (central package management) when given.
    - ``project_refs``: the ``ProjectReference`` includes, with ``/`` separators.
    - ``items``: kind -> list of ``(include, attrs)``; ``attrs`` holds the item's attributes and metadata
      elements (``Link``, ``Exclude``, ``Condition``…). Every item kind is kept.
    - ``imports``: ``(project, sdk or None, condition or None)``.
    - ``error``: why the XML couldn't be parsed (the regex fallback filled in what it could), else ``None``.
    """

    def __init__(self, path):
        self.path = path
        self.sdk = None
        self.sdks = []
        self.properties = {}
        self.conditional = {}
        self.target_frameworks = []
        self.package_refs = []
        self.project_refs = []
        self.items = {}
        self.imports = []
        self.error = None

    def prop(self, name, default=None):
        """A property's value (the last one set), or ``default``."""
        return self.properties.get(name, default)

    def has_true(self, name):
        """True when the property is set to ``true`` under any condition."""
        return any((v or "").strip().lower() == "true" for v, _c in self.conditional.get(name, []))

    def values(self, name):
        """Every value the property is given, under any condition, in file order."""
        return [v for v, _c in self.conditional.get(name, [])]

    def package_ids(self):
        return [p[0] for p in self.package_refs]

    def package(self, package_id):
        """The version referenced for a package id (case-insensitive), ``""`` when referenced without one,
        ``None`` when not referenced."""
        for pid, ver, _c in self.package_refs:
            if pid.lower() == package_id.lower():
                return ver or ""
        return None

    def as_dict(self):
        return {
            "path": self.path, "sdk": self.sdk, "properties": dict(self.properties),
            "targetFrameworks": list(self.target_frameworks),
            "packageRefs": [list(p) for p in self.package_refs], "projectRefs": list(self.project_refs),
            "items": {k: [[i, dict(a)] for i, a in v] for k, v in self.items.items()},
            "imports": [list(i) for i in self.imports], "error": self.error,
        }


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _both(a, b):
    if a and b:
        return "(%s) and (%s)" % (a, b)
    return a or b or None


def _add_sdk(project, sdk):
    for name in (s.strip() for s in (sdk or "").split(";")):
        if name and name not in project.sdks:
            project.sdks.append(name)
            if project.sdk is None:
                project.sdk = name


def _add_property(project, name, value, condition):
    value = (value or "").strip()
    project.properties[name] = value
    project.conditional.setdefault(name, []).append((value, condition))
    if name in ("TargetFramework", "TargetFrameworks"):
        for tfm in value.split(";"):
            tfm = tfm.strip()
            if tfm and "$(" not in tfm and tfm not in project.target_frameworks:
                project.target_frameworks.append(tfm)


_PROP_REF = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_.-]*)\)")


def expand(value, properties):
    """Replace ``$(Name)`` with a property's value where it's known (one level; unknown ones are kept)."""
    if not value or "$(" not in value:
        return value
    return _PROP_REF.sub(lambda m: properties.get(m.group(1), m.group(0)), value)


def _norm_include(value):
    return (value or "").strip().replace("\\", "/")


def _parse_xml(project, text, central):
    root = ET.fromstring(text)
    _add_sdk(project, root.get("Sdk"))
    for child in root:
        tag = _local(child.tag)
        cond = child.get("Condition")
        if tag == "Sdk":
            _add_sdk(project, child.get("Name"))
        elif tag == "Import":
            if child.get("Sdk"):
                _add_sdk(project, child.get("Sdk"))
            project.imports.append((_norm_include(child.get("Project")), child.get("Sdk"), cond))
        elif tag == "PropertyGroup":
            for prop in child:
                name = _local(prop.tag)
                if name:
                    _add_property(project, name, "".join(prop.itertext()), _both(cond, prop.get("Condition")))
        elif tag == "ItemGroup":
            for item in child:
                _add_item(project, item, _both(cond, item.get("Condition")))
        elif tag == "Choose":
            # <Choose><When Condition>…</When><Otherwise>…</Otherwise></Choose>: read every branch.
            for branch in child:
                bcond = _both(cond, branch.get("Condition") or ("otherwise" if _local(branch.tag) == "Otherwise" else None))
                for group in branch:
                    gtag = _local(group.tag)
                    gcond = _both(bcond, group.get("Condition"))
                    if gtag == "PropertyGroup":
                        for prop in group:
                            _add_property(project, _local(prop.tag), "".join(prop.itertext()),
                                          _both(gcond, prop.get("Condition")))
                    elif gtag == "ItemGroup":
                        for item in group:
                            _add_item(project, item, _both(gcond, item.get("Condition")))
    _resolve_versions(project, central)


def _add_item(project, item, condition):
    kind = _local(item.tag)
    if not kind:
        return
    attrs = {k: v for k, v in item.attrib.items()}
    for meta in item:
        name = _local(meta.tag)
        if name:
            attrs[name] = "".join(meta.itertext()).strip()
    if condition:
        attrs["Condition"] = condition
    include = item.get("Include") or item.get("Update") or ""
    project.items.setdefault(kind, []).append((_norm_include(include), attrs))


def _resolve_versions(project, central):
    central = central or {}
    lowered = {k.lower(): v for k, v in central.items()}
    for include, attrs in project.items.get("PackageReference", []):
        if not include:
            continue
        version = attrs.get("VersionOverride") or attrs.get("Version")
        if version:
            version = expand(version, project.properties)
        else:
            version = lowered.get(include.lower())
        project.package_refs.append((include, version or None, attrs.get("Condition")))
    for include, _attrs in project.items.get("ProjectReference", []):
        if include:
            project.project_refs.append(include)


_RX_SDK = re.compile(r"""<Project\b[^>]*\bSdk\s*=\s*["']([^"']+)["']""")
_RX_IMPORT_SDK = re.compile(r"""<Import\b[^>]*\bSdk\s*=\s*["']([^"']+)["']""")
_RX_PROP = re.compile(r"<(TargetFrameworks?|OutputType|UseMaui|RootNamespace|ApplicationId|ApplicationTitle|"
                      r"IsTestProject|PackAsTool|SupportedOSPlatformVersion|WindowsPackageType)\b[^>]*>([^<]*)</\1>")
_RX_ITEM = re.compile(r"""<(PackageReference|ProjectReference|Compile|RazorComponent|BundleResource|Content)\b"""
                      r"""[^>]*\b(?:Include|Update)\s*=\s*["']([^"']+)["']([^>]*)>""")
_RX_VERSION = re.compile(r"""\bVersion\s*=\s*["']([^"']+)["']""")


def _parse_regex(project, text, central):
    """What a regex can get out of a file ElementTree rejects."""
    for m in _RX_SDK.finditer(text):
        _add_sdk(project, m.group(1))
    for m in _RX_IMPORT_SDK.finditer(text):
        _add_sdk(project, m.group(1))
    for m in _RX_PROP.finditer(text):
        _add_property(project, m.group(1), m.group(2), None)
    for m in _RX_ITEM.finditer(text):
        attrs = {}
        v = _RX_VERSION.search(m.group(3) or "")
        if v:
            attrs["Version"] = v.group(1)
        project.items.setdefault(m.group(1), []).append((_norm_include(m.group(2)), attrs))
    _resolve_versions(project, central)


def read_project(path, central=None):
    """Read a project, ``.props`` or ``.targets`` file into a ``Project`` (see its docstring).

    ``central`` is ``{package id: version}`` for central package management (``central_versions``); a
    ``PackageReference`` without its own version takes it from there. A file that can't be read raises
    ``OSError``; one that isn't well-formed XML is read by regex and has ``error`` set.
    """
    text = read_text(path)
    if text is None:
        raise OSError("can't read %s" % path)
    project = Project(path)
    try:
        _parse_xml(project, text, central)
    except ET.ParseError as e:
        project = Project(path)
        project.error = "not well-formed XML: %s" % e
        _parse_regex(project, text, central)
    return project


def _props_path(root):
    return os.path.join(root, "Directory.Packages.props")


def _read_central(path):
    try:
        project = read_project(path)
    except OSError:
        return {}
    out = {}
    for kind in ("PackageVersion", "GlobalPackageReference"):
        for include, attrs in project.items.get(kind, []):
            version = attrs.get("Version")
            if include and version:
                out[include] = expand(version, project.properties)
    return out


def central_versions(root):
    """``{package id: version}`` from ``<root>/Directory.Packages.props`` (``PackageVersion`` and
    ``GlobalPackageReference`` items; ``$(Property)`` versions expanded from the same file). ``{}`` when
    there's no such file."""
    path = _props_path(root)
    return _read_central(path) if os.path.isfile(path) else {}


def central_versions_for(project_path, root):
    """The central versions that apply to a project: the nearest ``Directory.Packages.props`` in its folder
    or above, up to ``root``. ``{}`` when there's none."""
    root = os.path.abspath(root)
    here = os.path.dirname(os.path.abspath(project_path))
    while True:
        path = _props_path(here)
        if os.path.isfile(path):
            return _read_central(path)
        if here == root or len(here) <= len(root):
            return {}
        parent = os.path.dirname(here)
        if parent == here:
            return {}
        here = parent


def cpm_enabled(root):
    """True when ``<root>/Directory.Packages.props`` turns on ``ManagePackageVersionsCentrally``."""
    path = _props_path(root)
    if not os.path.isfile(path):
        return False
    try:
        return read_project(path).has_true("ManagePackageVersionsCentrally")
    except OSError:
        return False


def strip_json_comments(text):
    """JSON text without ``//`` and ``/* */`` comments (outside strings) or trailing commas, as
    ``global.json`` allows."""
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(c)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def sdk_version(root):
    """``sdk.version`` from ``<root>/global.json``, or ``None`` (no file, no version, or not JSON)."""
    path = os.path.join(root, "global.json")
    text = read_text(path) if os.path.isfile(path) else None
    if text is None:
        return None
    try:
        data = json.loads(strip_json_comments(text))
    except ValueError:
        return None
    sdk = data.get("sdk") if isinstance(data, dict) else None
    version = sdk.get("version") if isinstance(sdk, dict) else None
    return version if isinstance(version, str) and version else None


_TFM = re.compile(r"^net(\d+)\.(\d+)(?:-([a-z]+)([\d.]*))?$", re.IGNORECASE)


def parse_tfm(tfm):
    """``(major, minor, platform or None, platform version or None)`` for a modern target framework such as
    ``net11.0-windows10.0.19041.0``; ``None`` for anything else (``netstandard2.0``, ``net48``)."""
    m = _TFM.match((tfm or "").strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower() or None, m.group(4) or None


def tfm_platform(tfm):
    """The platform part of a target framework (``macos``, ``windows``, ``maccatalyst``…), or ``None``."""
    parsed = parse_tfm(tfm)
    return parsed[2] if parsed else None
