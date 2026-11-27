"""The blueprint: ``desktop-blueprint.json``, its defaults, consistency rules and decisions log (CONTRACT.md 2, 7.2).

- ``load(path)``; ``validate(bp, schema) -> [Finding]`` (id ``schema``); ``consistency(bp) -> [Finding]``
  (the 7.2 rules, ids exactly as there).
- ``value(bp, path, platform=None)``: a field's value, a per-platform object resolved for ``platform``
  (its key, else ``"*"``, else the field's default).
- ``defaults(kind)``: the 2.4 table (plus the values every kind shares) as a blueprint-shaped dict.
- ``draft(detection, kind=None, overrides=None)``: a first blueprint from ``detect.scan``'s dict.
- ``set_path(bp, path, value) -> was``; ``mark_decided(bp, path)``; ``append_decision(...)`` (2.3 format).
- ``integration_platforms(bp, name)``: the enabled platforms an integration is on.
- ``QUESTIONS``: the interview, group by group, each question naming the fields it settles.

Stdlib only; nothing here reads the project (detection does) or the clock unless asked for today's date.
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import re

from . import findings as _findings
from . import jsonio
from . import schema as _schema

PLATFORMS = ("macos", "windows", "linux", "web")
DESKTOP = ("macos", "windows", "linux")
PLATFORM_NAMES = {"macos": "macOS", "windows": "Windows", "linux": "Linux", "web": "Web", "*": "every platform"}
KINDS = ("tool", "monitor", "document", "launcher", "dashboard")
PER_PLATFORM = ("chrome.sidebar", "chrome.toolbar", "chrome.menuBar", "look.fidelity")
PLATFORM_MAPS = ("distribution.channels", "distribution.signing")
INTEGRATIONS = ("tray", "closeToTray", "launchAtLogin", "notifications", "badge", "progress", "singleInstance",
                "deepLinks", "fileTypes", "globalHotkey", "contextMenus", "fileDrop", "windowState", "autoUpdate")
UPDATE_CHANNELS = ("mac-app-store", "microsoft-store", "msix", "flatpak", "snap")
PACKAGE_CHANNELS = ("deb", "rpm")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*$")
DEFAULT_LOG = "docs/desktop/decisions.md"
DEFAULT_MINIMUM = {"macos": "14.0", "windows": "10.0.19041"}
DEFAULT_CHANNELS = {"macos": ["direct"], "windows": ["installer"], "linux": ["appimage"]}
LOG_HEADING = "# Desktop decisions\n"

_MISSING = object()

# 2.4: field -> (tool, monitor, document, launcher, dashboard)
_BY_KIND = (
    ("chrome.sidebar", ("native", "native", "native", "none", "native")),
    ("chrome.toolbar", ("native", "native", "native", "none", "native")),
    ("chrome.commandPalette", (True, True, True, True, False)),
    ("chrome.multiWindow", (False, False, True, False, False)),
    ("integrations.tray", (False, True, False, True, False)),
    ("integrations.closeToTray", (False, True, False, True, False)),
    ("integrations.launchAtLogin", (False, True, False, True, False)),
    ("integrations.notifications", (True, True, False, False, True)),
    ("integrations.badge", (False, True, False, False, False)),
    ("integrations.progress", (True, False, False, False, False)),
    ("integrations.singleInstance", (True, True, True, True, True)),
    ("integrations.globalHotkey", (False, False, False, True, False)),
    ("integrations.windowState", (True, True, True, False, True)),
)
# 2.4: the same for every kind.
_FOR_ALL = (
    ("chrome.search", "toolbar"),
    ("chrome.menuBar", {"macos": "standard", "windows": "none", "linux": "none"}),
    ("chrome.dialogs", "native-frame"),
    ("chrome.settings", "dialog"),
    ("look.fidelity", "adaptive"),
    ("look.accent", "brand"),
    ("look.theme", "system-with-override"),
    ("look.density", False),
    ("integrations.deepLinks", False),
    ("integrations.fileTypes", []),
    ("integrations.contextMenus", "web"),
    ("integrations.fileDrop", False),
    ("integrations.autoUpdate", True),
    ("engineering.devHost", True),
    ("engineering.gallery", True),
    ("engineering.devflow", True),
    ("engineering.accessibility", "wcag-aa"),
    ("stack.sharing", "rcl"),
)
KIND_FIELDS = tuple(p for p, _v in _BY_KIND)
# The order fields are written in (2.2).
_ORDER = {
    "": ("$schema", "$comment", "version", "confirmedByUser", "decided", "app", "platforms", "stack", "chrome",
         "look", "integrations", "distribution", "engineering", "decisionsLog"),
    "app": ("name", "id", "namespace", "kind", "existing"),
    "stack": ("dotnet", "content", "componentLibrary", "sharing", "backends"),
    "chrome": ("sidebar", "toolbar", "search", "menuBar", "dialogs", "settings", "commandPalette", "multiWindow"),
    "look": ("fidelity", "accent", "theme", "density"),
    "integrations": INTEGRATIONS,
    "engineering": ("devHost", "gallery", "devflow", "crashReporting", "accessibility", "locales"),
}


# --- reading --------------------------------------------------------------------------------------------

def load(path):
    """Read a blueprint (``jsonio.load``: ``JsonError`` when it isn't JSON, ``OSError`` when it can't be read)."""
    return jsonio.load(path)


def split(path):
    """A field path's parts (``"chrome.sidebar.linux"`` -> ``["chrome", "sidebar", "linux"]``).

    Raises ``ValueError`` for an empty path or an empty part."""
    parts = (path or "").split(".")
    if not path or any(not p or not re.match(r"^[A-Za-z*][A-Za-z0-9_*-]*$", p) for p in parts):
        raise ValueError("not a field path: %r (use dots between names, e.g. chrome.sidebar.linux)" % path)
    return parts


def get(bp, path, default=_MISSING):
    """The raw value at a field path, or ``default`` (a private sentinel unless given) when it isn't there."""
    node = bp
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def missing(value):
    return value is _MISSING


def kind_of(bp):
    kind = get(bp, "app.kind", "tool")
    return kind if kind in KINDS else "tool"


def is_platform_map(path, node):
    """True when ``node`` at ``path`` is keyed by platform (a per-platform field's object form)."""
    if not isinstance(node, dict):
        return False
    if path in PER_PLATFORM or path in PLATFORM_MAPS:
        return True
    keys = [k for k in node if not k.startswith("$")]
    return bool(keys) and all(k in PLATFORMS or k == "*" for k in keys)


def _resolve(node, platform):
    if platform in node:
        return node[platform]
    if "*" in node:
        return node["*"]
    return _MISSING


def value(bp, path, platform=None):
    """A field's value, falling back to its default for the blueprint's kind (``None`` when it has none).

    With ``platform``, a per-platform object resolves to that platform's key, else its ``"*"`` key, else the
    field's default for that platform; a single value applies to every platform.
    """
    defs = defaults(kind_of(bp))
    node = get(bp, path)
    if missing(node):
        node = get(defs, path)
    if missing(node):
        return None
    if platform and is_platform_map(path, node):
        got = _resolve(node, platform)
        if missing(got):
            d = get(defs, path)
            if is_platform_map(path, d):
                got = _resolve(d, platform)
            elif not missing(d):
                got = d
        return None if missing(got) else got
    return node


def enabled(bp, desktop_only=False):
    """The enabled platforms, in ``PLATFORMS`` order (without ``web`` when ``desktop_only``)."""
    plats = bp.get("platforms") if isinstance(bp.get("platforms"), dict) else {}
    out = [p for p in PLATFORMS if isinstance(plats.get(p), dict) and plats[p].get("enabled") is True]
    return [p for p in out if p != "web"] if desktop_only else out


def integration_platforms(bp, name):
    """The enabled desktop platforms integration ``name`` is on: ``true`` means all of them; an object with
    ``platforms`` names them (as written: a disabled one is the ``per-platform-key`` rule's business); a
    non-empty list (``fileTypes``) means all; ``contextMenus`` counts when ``native``."""
    v = value(bp, "integrations." + name)
    desktop = enabled(bp, desktop_only=True)
    if v is True:
        return desktop
    if isinstance(v, dict):
        plats = v.get("platforms")
        return [p for p in plats if isinstance(p, str)] if isinstance(plats, list) else desktop
    if isinstance(v, list):
        return desktop if v else []
    if name == "contextMenus" and v == "native":
        return desktop
    return []


# --- defaults -------------------------------------------------------------------------------------------

def _put(tree, path, val):
    node = tree
    parts = path.split(".")
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = copy.deepcopy(val)


def defaults(kind):
    """The 2.4 defaults for ``kind`` as a nested dict (``chrome``, ``look``, ``integrations``, ``engineering``,
    ``stack``). Raises ``ValueError`` for an unknown kind."""
    if kind not in KINDS:
        raise ValueError("app.kind must be one of %s, not %r" % (", ".join(KINDS), kind))
    i = KINDS.index(kind)
    out = {}
    for path, values in _BY_KIND:
        _put(out, path, values[i])
    for path, val in _FOR_ALL:
        _put(out, path, val)
    return ordered(out)


def default_value(kind, path, platform=None):
    """One field's default (resolved for ``platform`` when it's per-platform), or ``None``."""
    node = get(defaults(kind if kind in KINDS else "tool"), path)
    if missing(node):
        return None
    if platform and is_platform_map(path, node):
        got = _resolve(node, platform)
        return None if missing(got) else got
    return node


def ordered(bp, prefix=""):
    """``bp`` with keys in the contract's order (unknown keys after, as they were)."""
    if not isinstance(bp, dict):
        return bp
    order = _ORDER.get(prefix)
    keys = list(bp)
    if order:
        keys = [k for k in order if k in bp] + [k for k in bp if k not in order]
    return {k: ordered(bp[k], (prefix + "." + k) if prefix else k) for k in keys}


# --- drafting -------------------------------------------------------------------------------------------

def _pascal(name):
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    out = "".join(w[:1].upper() + w[1:] for w in words)
    return out if out and not out[0].isdigit() else ("App" + out if out else "App")


def _collapse(per, everywhere):
    """A per-platform value: one value when every platform agrees, else an object keyed by platform."""
    vals = [per[p] for p in everywhere if p in per]
    if vals and all(v == vals[0] for v in vals) and len(vals) == len(everywhere):
        return vals[0]
    return {p: per[p] for p in everywhere if p in per}



def channels_for(tags, plat):
    """The distribution channels a platform's detected tags (``detect`` distribution) amount to."""
    tags = tags or []
    out = []
    if plat == "macos":
        if any(t in tags for t in ("codesign", "notarize", "dmg")):
            out.append("direct")
        for t in ("homebrew", "mac-app-store"):
            if t in tags:
                out.append(t)
    elif plat == "windows":
        if any(t in tags for t in ("inno-setup", "wix", "velopack")):
            out.append("installer")
        for t in ("winget", "msix", "microsoft-store"):
            if t in tags:
                out.append(t)
    else:
        out = [t for t in ("deb", "rpm", "flatpak", "appimage", "snap") if t in tags]
    return out


def draft(detection, kind=None, overrides=None):
    """A first blueprint: the 2.4 defaults for ``kind`` (``monitor`` when detection found a tray icon, else
    ``tool``), overridden where detection found something (a convention found wins over a default; nothing
    found leaves the default as the proposal), then by ``overrides``.

    ``overrides`` maps field paths to values (``{"app.name": "Sample Notes"}``); its ``"platforms"`` key, a
    list such as ``["macos", "windows"]``, says which desktop platforms are enabled. The draft has
    ``confirmedByUser: false`` and ``decided: []``.
    """
    det = detection or {}
    overrides = dict(overrides or {})
    integ = det.get("integrations") or {}
    if kind is None:
        kind = overrides.pop("app.kind", None) or ("monitor" if integ.get("tray") else "tool")
    else:
        overrides.pop("app.kind", None)
    d = defaults(kind)
    existing = bool(det.get("projects"))
    heads = det.get("heads") or {}
    detected = [p for p in DESKTOP if heads.get(p)]
    plat_list = overrides.pop("platforms", None)
    if plat_list:
        on = [p for p in DESKTOP if p in plat_list]
    else:
        on = detected or list(DESKTOP)
    web_on = True  # engineering.devHost defaults to true: the browser dev host is a platform
    app_det = det.get("app") or {}

    name = overrides.pop("app.name", None) or app_det.get("name")
    if not name:
        base = os.path.basename(os.path.abspath(det.get("root") or ".")) or "App"
        name = re.sub(r"[-_]+", " ", base).strip() or "App"
    app = {"name": name}
    app_id = overrides.pop("app.id", None) or app_det.get("id")
    if app_id:
        app["id"] = app_id
    app["namespace"] = overrides.pop("app.namespace", None) or app_det.get("namespace") or _pascal(name)
    app["kind"] = kind
    app["existing"] = existing

    minimums = app_det.get("minimums") or {}
    home = on[0] if on else None
    platforms = {}
    for p in DESKTOP:
        entry = {"enabled": p in on}
        if p in on:
            if p == home:
                entry["home"] = True
            if p in DEFAULT_MINIMUM:
                entry["minimum"] = minimums.get(p) or DEFAULT_MINIMUM[p]
            if p == "linux":
                entry["desktop"] = "gnome"
        platforms[p] = entry
    platforms["web"] = {"enabled": web_on, "role": "devhost"}

    dstack = det.get("stack") or {}
    sharing_kind = (det.get("sharing") or {}).get("kind")
    stack = {
        "dotnet": _dotnet(det) or "11.0",
        "content": dstack.get("content") or "blazor",
        "componentLibrary": dstack.get("componentLibrary") or "custom",
        "sharing": sharing_kind if existing and sharing_kind else d["stack"]["sharing"],
    }
    backends = {p: (det.get("backends") or {}).get(p) for p in on}
    backends = {p: b for p, b in backends.items() if b}
    if backends:
        stack["backends"] = backends

    chrome = copy.deepcopy(d["chrome"])
    shell = det.get("shell") or {}
    sb = shell.get("sidebar") or {}
    found = {p: sb[p] for p in on if sb.get(p) in ("native", "web")}
    if found:
        per = {p: found.get(p, d["chrome"]["sidebar"]) for p in on}
        if len(set(per.values())) == 1:
            chrome["sidebar"] = per[on[0]]
        else:
            if web_on:
                per["web"] = "web"
            chrome["sidebar"] = per
    tb = (shell.get("toolbar") or {}).get("kind")
    if tb in ("declared", "imperative"):
        chrome["toolbar"] = "native"
    elif tb == "web":
        chrome["toolbar"] = "web"
    menu = {p: d["chrome"]["menuBar"].get(p, "none") for p in on}
    for p, v in (shell.get("menuBar") or {}).items():
        if p in menu and v == "custom-items":
            menu[p] = "standard"
    chrome["menuBar"] = menu
    dlg = det.get("dialogs") or {}
    if dlg.get("kind") in ("session", "page-subclass"):
        chrome["dialogs"] = "mixed" if (dlg.get("webOverlays") or 0) > (dlg.get("count") or 0) else "native-frame"
    elif dlg.get("kind") == "web":
        chrome["dialogs"] = "web"
    if shell.get("commandPalette"):
        chrome["commandPalette"] = True
    if shell.get("multiWindow"):
        chrome["multiWindow"] = True

    look = copy.deepcopy(d["look"])
    design = det.get("design") or {}
    selectors = design.get("platformSelectors") or {}
    heavy = [p for p in on if (selectors.get(p) or 0) >= 100]
    if heavy:
        per = {p: ("native-faithful" if p in heavy else "adaptive") for p in on}
        look["fidelity"] = _collapse(per, on)

    integrations = copy.deepcopy(d["integrations"])
    plats_found = det.get("integrationPlatforms") or {}
    for key in INTEGRATIONS:
        if not integ.get(key):
            continue
        where = [p for p in plats_found.get(key, ["*"])]
        if key == "contextMenus":
            integrations[key] = "native"
            continue
        if key == "fileTypes":
            continue
        if key == "deepLinks":
            schemes = det.get("deepLinkSchemes") or []
            if schemes and SCHEME.match(schemes[0]):
                integrations[key] = {"scheme": schemes[0]}
            continue
        if integrations.get(key):
            continue  # already on everywhere by default
        mine = [p for p in on if p in where]
        if "*" in where or set(on) <= set(mine):
            integrations[key] = True
        elif mine:
            integrations[key] = {"platforms": mine}

    dist = det.get("distribution") or {}
    channels, signing = {}, {}
    for p in on:
        channels[p] = channels_for(dist.get(p), p) or list(DEFAULT_CHANNELS[p])
        tags = dist.get(p) or []
        if p == "macos":
            signing[p] = "available" if "codesign" in tags else "later"
        elif p == "windows":
            signing[p] = "available" if "signing" in tags else "later"
        else:
            signing[p] = "none"

    eng = copy.deepcopy(d["engineering"])
    deng = det.get("engineering") or {}
    eng["crashReporting"] = deng.get("crashReporting") or "none"
    eng["locales"] = ["en"]

    bp = {
        "version": 1,
        "confirmedByUser": False,
        "decided": [],
        "app": app,
        "platforms": platforms,
        "stack": stack,
        "chrome": chrome,
        "look": look,
        "integrations": integrations,
        "distribution": {"channels": channels, "signing": signing},
        "engineering": eng,
        "decisionsLog": DEFAULT_LOG,
    }
    for path, val in overrides.items():
        set_path(bp, path, val)
    prune(bp)
    return ordered(bp)


def _dotnet(det):
    sdk = (det.get("dotnet") or {}).get("sdk")
    if sdk:
        m = re.match(r"^(\d+)\.(\d+)", sdk)
        if m:
            return "%s.%s" % (m.group(1), m.group(2))
    best = None
    for tfm in (det.get("dotnet") or {}).get("tfms") or []:
        m = re.match(r"^net(\d+)\.(\d+)", tfm)
        if m:
            v = (int(m.group(1)), int(m.group(2)))
            best = v if best is None or v > best else best
    return "%d.%d" % best if best else None


def prune(bp):
    """Drop the keys of per-platform objects (and distribution maps) that name a platform that isn't enabled.
    Used on drafts only: in a user's blueprint such a key is reported (``per-platform-key``), never removed."""
    on = set(enabled(bp))
    for path in PER_PLATFORM + PLATFORM_MAPS:
        node = get(bp, path)
        if isinstance(node, dict):
            for k in list(node):
                if k != "*" and not k.startswith("$") and k not in on:
                    del node[k]
    return bp


# --- changing -------------------------------------------------------------------------------------------

WEB_CHROME = ("chrome.sidebar", "chrome.toolbar")


def for_web(path, val):
    """What a per-platform value means on the web platform: the browser has no native sidebar or toolbar (a
    native one there is the web version) and no menu bar (``None``)."""
    if path in WEB_CHROME and val == "native":
        return "web"
    if path == "chrome.menuBar":
        return None
    return val


def spread(bp, path, val):
    """A single per-platform value written out for every enabled platform (``for_web`` for the web one)."""
    out = {}
    for p in enabled(bp):
        v = for_web(path, val) if p == "web" else val
        if v is not None:
            out[p] = v
    return out


def effective(bp, path):
    """What a field path holds now, counting defaults and per-platform fallback: the ``was`` of a change."""
    parts = path.split(".")
    if len(parts) > 1 and parts[-1] in PLATFORMS + ("*",):
        parent = ".".join(parts[:-1])
        if parent in PER_PLATFORM or parent in PLATFORM_MAPS or is_platform_map(parent, get(bp, parent)):
            return value(bp, parent, parts[-1] if parts[-1] != "*" else None)
    raw = get(bp, path)
    if not missing(raw):
        return raw
    d = get(defaults(kind_of(bp)), path)
    return None if missing(d) else d


def set_path(bp, path, val):
    """Set a field (creating objects on the way) and return what it was (``effective``). Setting one platform
    of a per-platform field that holds a single value (``chrome.sidebar.linux`` while ``chrome.sidebar`` is
    ``"native"``) first spreads that value over every enabled platform.

    Raises ``ValueError`` for a malformed path, or one that runs through a value that isn't an object."""
    parts = split(path)
    was = effective(bp, path)
    node = bp
    for i, key in enumerate(parts[:-1]):
        here = ".".join(parts[: i + 1])
        nxt = parts[i + 1]
        sub = node.get(key, _MISSING) if isinstance(node, dict) else _MISSING
        spreadable = here in PER_PLATFORM and nxt in PLATFORMS + ("*",)
        if missing(sub):
            current = get(defaults(kind_of(bp)), here) if here in PER_PLATFORM else _MISSING
            if spreadable and not missing(current) and not isinstance(current, dict):
                sub = spread(bp, here, current)
            elif spreadable and isinstance(current, dict):
                sub = {p: v for p, v in current.items() if p in enabled(bp) or p == "*"}
            else:
                sub = {}
            node[key] = sub
        elif not isinstance(sub, dict):
            if spreadable:
                sub = spread(bp, here, sub)
                node[key] = sub
            else:
                raise ValueError("%s holds %s, not an object, so %s can't be set" % (
                    here, json.dumps(sub), path))
        node = sub
    if not isinstance(node, dict):
        raise ValueError("can't set %s" % path)
    node[parts[-1]] = copy.deepcopy(val)
    return was


def is_decided(bp, path):
    """True when ``path`` or a field above it is in ``decided``."""
    decided = bp.get("decided") or []
    parts = path.split(".")
    return any(".".join(parts[: i + 1]) in decided for i in range(len(parts)))


def mark_decided(bp, path):
    """Add ``path`` to ``decided`` (once). Returns whether it was added."""
    decided = bp.setdefault("decided", [])
    if path in decided:
        return False
    decided.append(path)
    return True


def format_value(val):
    """A value as the decisions log writes it: strings bare, everything else as compact JSON, ``(unset)``."""
    if val is None or missing(val):
        return "(unset)"
    if isinstance(val, str):
        return val
    return json.dumps(val, ensure_ascii=False, separators=(", ", ": "))


def _quote(reason):
    reason = (reason or "").strip()
    if not reason:
        return "(none given)"
    if len(reason) > 1 and reason[0] in "\"“" and reason[-1] in "\"”":
        return reason
    return '"%s"' % reason


def decision_entry(path, val, was, by, reason, date):
    """One 2.3 entry (ends with a newline)."""
    return "## %s: %s = %s\n\n- **By:** %s\n- **Reason:** %s\n- **Was:** %s\n" % (
        date, path, format_value(val), by, _quote(reason), format_value(was))


def append_decision(log_path, path, val, was, by, reason, date=None):
    """Append a decision to the log (2.3), creating its folder and the file (with a ``# Desktop decisions``
    heading) when missing. ``by`` is ``user`` or ``proposal``; ``date`` a ``datetime.date`` or
    ``YYYY-MM-DD`` (default today). Returns the entry written."""
    if by not in ("user", "proposal"):
        raise ValueError("by must be user or proposal, not %r" % by)
    if date is None:
        date = datetime.date.today()
    if isinstance(date, (datetime.date, datetime.datetime)):
        date = date.strftime("%Y-%m-%d")
    entry = decision_entry(path, val, was, by, reason, date)
    folder = os.path.dirname(os.path.abspath(log_path))
    os.makedirs(folder, exist_ok=True)
    if os.path.isfile(log_path):
        with open(log_path, "r", encoding="utf-8") as f:
            old = f.read()
        if not old:
            sep = LOG_HEADING + "\n"
        elif old.endswith("\n\n"):
            sep = ""
        elif old.endswith("\n"):
            sep = "\n"
        else:
            sep = "\n\n"
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write(sep + entry)
    else:
        with open(log_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(LOG_HEADING + "\n" + entry)
    return entry


def log_path(bp, blueprint_path):
    """The decisions log's path: the blueprint's ``decisionsLog`` (default ``docs/desktop/decisions.md``),
    relative to the blueprint's folder."""
    rel_path = bp.get("decisionsLog") or DEFAULT_LOG
    base = os.path.dirname(os.path.abspath(blueprint_path))
    return os.path.join(base, *rel_path.replace("\\", "/").split("/"))


# --- checking -------------------------------------------------------------------------------------------

def validate(bp, schema_doc):
    """Schema findings (id ``schema``, severity ``error``), one a message from ``schema.validate``."""
    out = []
    for msg in _schema.validate(bp, schema_doc):
        where, _sep, text = msg.partition(": ")
        out.append(_findings.Finding("schema", "error", where, text or msg))
    return out


def _f(rule, severity, where, message):
    return _findings.Finding(rule, severity, where, message)


def consistency(bp):
    """The 7.2 consistency rules, as findings (ids exactly as there). Expects a schema-valid blueprint."""
    out = []
    on = enabled(bp)
    desktop = [p for p in on if p != "web"]
    if not desktop:
        out.append(_f("no-platform", "error", "platforms",
                      "No desktop platform is enabled: enable at least one of macos, windows and linux."))
    homes = [p for p in PLATFORMS if isinstance(get(bp, "platforms." + p), dict) and get(bp, "platforms." + p).get("home") is True]
    if len(homes) > 1:
        out.append(_f("two-homes", "error", "platforms",
                      "%s are all marked home: only one platform gets the most polish." % ", ".join(homes)))
    if "macos" in desktop and value(bp, "chrome.menuBar", "macos") == "none":
        out.append(_f("macos-menu-bar", "error", "chrome.menuBar.macos",
                      "A macOS app always has a menu bar: choose minimal, standard or full."))
    links = value(bp, "integrations.deepLinks")
    if links is True or isinstance(links, dict):
        scheme = links.get("scheme") if isinstance(links, dict) else None
        if not isinstance(scheme, str) or not SCHEME.match(scheme):
            out.append(_f("deep-link-scheme", "error", "integrations.deepLinks",
                          "Deep links need a scheme: lower-case letters, digits, '+', '.' or '-', starting with a "
                          "letter (such as \"samplenotes\")%s." % (
                              ", not %s" % json.dumps(scheme) if scheme is not None else "")))
    for path in PER_PLATFORM + PLATFORM_MAPS:
        node = get(bp, path)
        if isinstance(node, dict):
            for k in node:
                if k == "*" or k.startswith("$") or k in on:
                    continue
                out.append(_f("per-platform-key", "error", "%s.%s" % (path, k),
                              "%s names %s, which isn't enabled: remove the key or enable the platform." % (path, k)))
    for name in INTEGRATIONS:
        v = get(bp, "integrations." + name)
        if isinstance(v, dict) and isinstance(v.get("platforms"), list):
            for p in v["platforms"]:
                if p not in on:
                    out.append(_f("per-platform-key", "error", "integrations.%s.platforms" % name,
                                  "integrations.%s is on for %s, which isn't enabled." % (name, p)))
    if "linux" in desktop:
        native = [f for f in ("sidebar", "toolbar") if value(bp, "chrome." + f, "linux") == "native"]
        if native:
            out.append(_f("gtk-native-chrome", "info", "chrome.%s.linux" % native[0],
                          "A native %s on Linux: the GTK backend has none, so the Linux head builds %s itself." % (
                              " and ".join(native), "them" if len(native) > 1 else "it")))
        if "linux" in integration_platforms(bp, "tray"):
            out.append(_f("tray-gnome", "warning", "integrations.tray",
                          "Stock GNOME shows no tray icon without an extension: keep everything reachable from the "
                          "window on Linux."))
        if "linux" in integration_platforms(bp, "globalHotkey"):
            out.append(_f("hotkey-wayland", "warning", "integrations.globalHotkey",
                          "On Wayland a global hotkey works only through the GlobalShortcuts portal, and the user "
                          "must approve it."))
    if "macos" in desktop and value(bp, "distribution.signing", "macos") != "available":
        needs = [n for n in ("notifications", "launchAtLogin") if "macos" in integration_platforms(bp, n)]
        if needs:
            words = {"notifications": "notifications", "launchAtLogin": "starting at login"}
            text = " and ".join(words[n] for n in needs)
            out.append(_f("unsigned-macos", "warning", "distribution.signing.macos",
                          "On macOS, %s need%s a signed app, and distribution.signing.macos isn't \"available\"." % (
                              text, "s" if needs == ["launchAtLogin"] else "")))
    update_on = integration_platforms(bp, "autoUpdate")
    for p in desktop:
        if p not in update_on:
            continue
        chans = value(bp, "distribution.channels", p) or []
        owned = [c for c in chans if c in UPDATE_CHANNELS]
        if owned:
            out.append(_f("update-owned-by-channel", "warning", "integrations.autoUpdate",
                          "%s ships through %s, which update%s the app itself: switch auto-update off for that "
                          "channel." % (PLATFORM_NAMES[p], ", ".join(owned), "s" if len(owned) == 1 else "")))
        packages = [c for c in chans if c in PACKAGE_CHANNELS]
        if packages:
            out.append(_f("update-package-repo", "info", "integrations.autoUpdate",
                          "%s ships as %s: installed from a package repository, the package manager updates it; "
                          "downloaded as a file, the in-app check should open the download rather than replace "
                          "the app." % (PLATFORM_NAMES[p], ", ".join(packages))))
    if "linux" in desktop and "linux" in integration_platforms(bp, "launchAtLogin"):
        if "flatpak" in (value(bp, "distribution.channels", "linux") or []):
            out.append(_f("flatpak-autostart", "warning", "integrations.launchAtLogin",
                          "Starting at login from a Flatpak needs the Background portal."))
    faithful = [p for p in on if value(bp, "look.fidelity", p) == "native-faithful"]
    if faithful:
        out.append(_f("faithful-cost", "warning", "look.fidelity",
                      "native-faithful on %s means a component layer per platform: budget it for each one." %
                      ", ".join(PLATFORM_NAMES[p] for p in faithful)))
    if value(bp, "stack.sharing") in ("links", "symlinks"):
        out.append(_f("sharing-not-rcl", "warning", "stack.sharing",
                      "The heads share the UI by %s: a Razor class library is simpler to keep in step." %
                      ("compile links" if value(bp, "stack.sharing") == "links" else "symlinks")))
    if value(bp, "stack.content") == "other":
        out.append(_f("content-other", "info", "stack.content",
                      "Content other than Blazor is out of scope for now: the skills stop at structure."))
    return out


# --- the interview --------------------------------------------------------------------------------------

def _q(qid, ask, paths, options=(), per_platform=False):
    return {"id": qid, "ask": ask, "paths": tuple(paths), "options": tuple(options), "perPlatform": per_platform}


YES_NO = ("yes", "no")
CHANNELS = ("direct", "homebrew", "mac-app-store", "installer", "winget", "msix", "microsoft-store", "deb", "rpm",
            "flatpak", "appimage", "snap")

QUESTIONS = (
    {"group": "Product", "questions": (
        _q("kind", "What kind of app is it?", ["app.kind"], KINDS),
        _q("platforms", "Which platforms, and which gets the most polish?",
           ["platforms.*.enabled", "platforms.*.home"], DESKTOP),
        _q("minimums", "Minimum OS versions?", ["platforms.*.minimum"]),
        _q("existing", "New app or existing?", ["app.existing"], ("new", "existing")),
    )},
    {"group": "Chrome (per platform)", "questions": (
        _q("sidebar", "Sidebar: native, web or none?", ["chrome.sidebar"], ("native", "web", "none"), True),
        _q("toolbar", "Toolbar: native or web?", ["chrome.toolbar"], ("native", "web", "none"), True),
        _q("search", "Where does search live?", ["chrome.search"], ("toolbar", "content", "none")),
        _q("menuBar", "Menu bar: none, minimal, standard or full?", ["chrome.menuBar"],
           ("none", "minimal", "standard", "full"), True),
        _q("dialogs", "Dialogs: a native frame with a web body, web only, or mixed?", ["chrome.dialogs"],
           ("native-frame", "web", "mixed")),
        _q("settings", "Settings as a window, a dialog or a page?", ["chrome.settings"], ("window", "dialog", "page")),
        _q("commandPalette", "A command palette?", ["chrome.commandPalette"], YES_NO),
        _q("multiWindow", "More than one window?", ["chrome.multiWindow"], YES_NO),
    )},
    {"group": "Look", "questions": (
        _q("fidelity", "How platform-specific should content look: unified, adaptive or native-faithful?",
           ["look.fidelity"], ("unified", "adaptive", "native-faithful"), True),
        _q("accent", "Accent: one brand colour, each platform's default, or the user's OS accent?",
           ["look.accent"], ("brand", "platform", "system")),
        _q("theme", "Theme: follow the system, with or without a manual override?", ["look.theme"],
           ("system", "system-with-override")),
        _q("density", "A density setting (comfortable or compact)?", ["look.density"], YES_NO),
    )},
    {"group": "Background and integrations", "questions": (
        _q("tray", "A tray or menu-bar icon? Keep running when the window closes? Start at login?",
           ["integrations.tray", "integrations.closeToTray", "integrations.launchAtLogin"], YES_NO),
        _q("notifications", "OS notifications? A dock or taskbar badge, and progress?",
           ["integrations.notifications", "integrations.badge", "integrations.progress"], YES_NO),
        _q("launching", "Single instance? Deep links (with what scheme)? File types?",
           ["integrations.singleInstance", "integrations.deepLinks", "integrations.fileTypes"]),
        _q("hotkey", "A global hotkey?", ["integrations.globalHotkey"], YES_NO),
        _q("desktop", "Native context menus? File drop? Remember window size and position?",
           ["integrations.contextMenus", "integrations.fileDrop", "integrations.windowState"]),
        _q("update", "Auto-update?", ["integrations.autoUpdate"], YES_NO),
    )},
    {"group": "Distribution", "questions": (
        _q("channels", "Channels per OS?", ["distribution.channels"], CHANNELS, True),
        _q("signing", "Signing identities available?", ["distribution.signing"], ("available", "later", "none"), True),
    )},
    {"group": "Engineering", "questions": (
        _q("content", "Content technology and component library?", ["stack.content", "stack.componentLibrary"],
           ("blazor", "other")),
        _q("sharing", "How do the heads share the UI: a Razor class library, or keep what's there?",
           ["stack.sharing"], ("rcl", "links", "symlinks", "single")),
        _q("devHost", "A browser dev host and a component gallery?", ["engineering.devHost", "engineering.gallery"],
           YES_NO),
        _q("devflow", "DevFlow for agent-driven inspection?", ["engineering.devflow"], YES_NO),
        _q("crashReporting", "Crash reporting?", ["engineering.crashReporting"], ("none", "a service's name")),
        _q("accessibility", "Accessibility target and locales?", ["engineering.accessibility", "engineering.locales"],
           ("wcag-aa", "wcag-aaa", "none")),
    )},
)


def expand_path(bp, path):
    """A question's field path with ``*`` replaced by each desktop platform (``platforms.*.minimum`` skips
    Linux, which has none)."""
    if "*" not in path:
        return [path]
    out = []
    for p in DESKTOP:
        if path.endswith(".minimum") and p == "linux":
            continue
        out.append(path.replace("*", p))
    return out


def open_questions(bp):
    """``[(group, question, [undecided paths])]`` for every question with a field still undecided."""
    out = []
    for group in QUESTIONS:
        for q in group["questions"]:
            todo = [p for path in q["paths"] for p in expand_path(bp, path) if not is_decided(bp, p)]
            if todo:
                out.append((group["group"], q, todo))
    return out
