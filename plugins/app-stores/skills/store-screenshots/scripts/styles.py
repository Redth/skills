"""styles.py: the style file (``screenshot-style.json``) and how it joins the design config.

A style is the look a set keeps across updates: its traits (a fixed vocabulary, shared with
``design/inspiration/inspiration.json``), a theme, roles (``hero``, ``feature``, ...: the layout a kind of shot gets),
store overrides, rules for the words (``copy``) and how far a later render may drift from the approved baseline
(``drift``). The config names it with ``"style"``; ``render.py --style`` puts another in its place for an exploration.

Merging: the config's ``theme`` and ``stores`` go under the style's (the style wins, key by key, into ``palette``,
``caption`` and ``background``); a shot with a ``role`` and no ``layout`` takes the role's layout (and its
``frame``, ``tilt`` and ``at`` where the shot has none). A role's own ``stores`` give it another layout or frame on
one store (a hero that is real UI on Play, which wants the app's UI in the first three); they sit between the
shot's settings and the config's store overrides. Precedence is otherwise as before: target overrides beat store
overrides beat the shot's settings beat the theme.

Stdlib only; used by render.py, check.py, sheet.py and baseline.py.
"""

from __future__ import annotations

import copy
import hashlib
import os

from appstores_lib import jsonio
from appstores_lib import schema

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
STYLE_SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "screenshot-style.schema.json")
CONFIG_SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "store-screenshots.schema.json")
STYLES_DIR = os.path.join(SKILL_DIR, "styles")

DEFAULT_DESIGN = "design"
STYLE_NAME = "screenshot-style.json"
ROLE_KEYS = ("layout", "frame", "tilt", "at", "fold")
ROLE_STORE_KEYS = ("layout", "frame")
ROLE_STORES = "_roleStores"  # on an applied shot: {store: {layout, frame}} from its role, where the shot set none

# How far a render may move from the baseline before check.py says so (screenshot-craft research: device box 1u,
# caption top 0.5u, headline size 5% between releases). Positions are fractions of the slot's width (0.01 = 1u),
# captionSize is relative (0.05 = 5%), textShare an absolute share of the picture, colour a CIE76 delta E.
DEFAULT_DRIFT = {"captionSize": 0.05, "captionPosition": 0.005, "deviceBox": 0.01, "textShare": 0.03,
                 "colour": 2.0}


class StyleError(ValueError):
    """A style that can't be used (missing, not JSON, against its schema, or naming roles that don't exist)."""


def style_schema():
    """The style file's schema."""
    return jsonio.load(STYLE_SCHEMA_PATH)


def _def(schema_doc, name):
    """A schema that validates against one of ``schema_doc``'s ``$defs``."""
    return {"$defs": schema_doc["$defs"], "$ref": "#/$defs/%s" % name}


def validate_style(data, where="style"):
    """Every problem with a style: its own schema, then its theme and stores against the config's schema."""
    problems = ["%s %s" % (where, p) for p in schema.validate(data, style_schema())]
    if problems:
        return problems
    config_schema = jsonio.load(CONFIG_SCHEMA_PATH)
    if isinstance(data.get("theme"), dict):
        problems += ["%s theme%s" % (where, p if p.startswith("/") else " " + p)
                     for p in schema.validate(data["theme"], _def(config_schema, "theme"))]
    for store, spec in (data.get("stores") or {}).items():
        if store.startswith("$") or spec is None:
            continue
        problems += ["%s stores/%s%s" % (where, store, p if p.startswith("/") else " " + p)
                     for p in schema.validate(spec, _def(config_schema, "overrides"))]
    return problems


def validate_inspiration(data):
    """Problems with ``inspiration.json`` (its shape and its traits' vocabulary)."""
    return schema.validate(data, _def(style_schema(), "inspiration"))


def validate_current(data):
    """Problems with ``design/current.json`` (the current set read shot by shot): its shape, its layouts and
    traits' vocabulary, and each set's order (1, 2, 3... with no place twice)."""
    problems = schema.validate(data, _def(style_schema(), "current"))
    if problems:
        return problems
    seen = {}
    for i, shot in enumerate(data.get("shots") or []):
        key = (shot.get("group"), shot["order"])
        if key in seen:
            problems.append("/shots/%d: order %d of %s is shot %d's too" % (
                i, shot["order"], shot.get("group") or "the set", seen[key]))
        seen.setdefault(key, i)
    files = [s["file"] for s in data.get("shots") or []]
    for f in sorted(set(x for x in files if files.count(x) > 1)):
        problems.append("/shots: %s is listed more than once" % f)
    return problems


def trait_vocabulary():
    """``{trait: [values]}`` from the style schema: the one place the vocabulary lives."""
    defs = style_schema()["$defs"]
    out = {}
    for name in defs["traits"]["properties"]:
        if not name.startswith("$"):
            out[name] = list(defs["trait-" + name]["enum"])
    return out


def load_style(path):
    """Read and validate a style file; raise ``StyleError`` with every problem."""
    if not os.path.isfile(path):
        raise StyleError("no style at %s" % path)
    try:
        data = jsonio.load(path)
    except ValueError as e:
        raise StyleError(str(e))
    problems = validate_style(data, os.path.basename(path))
    if problems:
        raise StyleError("%s doesn't match the style schema:\n  %s" % (path, "\n  ".join(problems)))
    return data


def style_sha256(data):
    """The style's hash for the baseline: its canonical JSON without ``locked`` (locking it isn't a change)."""
    view = dict((k, v) for k, v in data.items() if k != "locked")
    return hashlib.sha256(jsonio.canonical(view).encode("utf-8")).hexdigest()


def config_sha256(data):
    """The config's hash (canonical JSON), for saying whether it changed since the baseline."""
    return hashlib.sha256(jsonio.canonical(data).encode("utf-8")).hexdigest()


def _merge(under, over):
    """``over`` merged onto ``under``: nested objects key by key, anything else replaced (``over`` wins)."""
    if not isinstance(under, dict) or not isinstance(over, dict):
        return copy.deepcopy(over)
    out = copy.deepcopy(under)
    for k, v in over.items():
        if k.startswith("$"):
            continue
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def style_path_for(config_path, cfg, override=None):
    """The style file a render uses: ``override`` (``--style``: as given, else beside the config), else the
    config's ``style`` (relative to it), else ``None``."""
    base = os.path.dirname(os.path.abspath(config_path))
    if override:
        if os.path.isabs(override) or os.path.exists(override):
            return os.path.abspath(override)
        return os.path.normpath(os.path.join(base, override))
    if cfg.get("style"):
        return os.path.normpath(os.path.join(base, cfg["style"]))
    return None


def design_dir(config_path, cfg):
    """The design folder (inspiration, directions, explorations, decisions, the baseline): the config's
    ``design``, else ``design/`` beside it."""
    base = os.path.dirname(os.path.abspath(config_path))
    return os.path.normpath(os.path.join(base, (cfg or {}).get("design") or DEFAULT_DESIGN))


def apply(cfg, style):
    """The config as rendered with ``style``: theme and stores merged under the style's, roles turned into
    layouts. Returns a new dict; ``cfg`` isn't changed. Raises ``StyleError`` for a role the style lacks."""
    out = copy.deepcopy(cfg)
    if not style:
        for s in out.get("shots") or []:
            if s.get("role"):
                raise StyleError("shot %s has role %r but the config names no style (add \"style\" or give it a "
                                 "layout)" % (s.get("id"), s["role"]))
        return out
    if style.get("theme"):
        out["theme"] = _merge(out.get("theme") or {}, style["theme"])
    if style.get("stores"):
        stores = copy.deepcopy(out.get("stores") or {})
        for name, spec in style["stores"].items():
            if name.startswith("$"):
                continue
            if spec is None:
                stores[name] = None
            else:
                stores[name] = _merge(stores.get(name) or {}, spec)
        out["stores"] = stores
    roles = style.get("roles") or {}
    for s in out.get("shots") or []:
        role = s.get("role")
        if not role:
            continue
        spec = roles.get(role)
        if not isinstance(spec, dict):
            raise StyleError("shot %s has role %r, which the style doesn't have (its roles: %s)" % (
                s.get("id"), role, ", ".join(k for k in roles if not k.startswith("$")) or "none"))
        per_store = {}
        for store, over in (spec.get("stores") or {}).items():
            if store.startswith("$") or not isinstance(over, dict):
                continue
            keep = dict((k, over[k]) for k in ROLE_STORE_KEYS if over.get(k) is not None and s.get(k) is None)
            if keep:
                per_store[store] = keep
        for key in ROLE_KEYS:
            if s.get(key) is None and spec.get(key) is not None:
                s[key] = spec[key]
        if per_store:
            s[ROLE_STORES] = per_store
    return out


def role_layouts(style):
    """The layouts a style's roles use (on any store)."""
    out = set()
    for k, spec in (style.get("roles") or {}).items():
        if k.startswith("$") or not isinstance(spec, dict):
            continue
        if spec.get("layout"):
            out.add(spec["layout"])
        for store, over in (spec.get("stores") or {}).items():
            if not store.startswith("$") and isinstance(over, dict) and over.get("layout"):
                out.add(over["layout"])
    return sorted(out)


def drift_tolerances(style):
    """The style's ``drift`` over the defaults."""
    out = dict(DEFAULT_DRIFT)
    for k, v in ((style or {}).get("drift") or {}).items():
        if not k.startswith("$") and isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def theme_conflicts(cfg_theme, style_theme, path="theme"):
    """``[(path, config value, style value)]``: every key the config's theme sets to something the style's sets
    otherwise (what a locked style forbids)."""
    out = []
    if not isinstance(cfg_theme, dict) or not isinstance(style_theme, dict):
        return out
    for k, v in cfg_theme.items():
        if k.startswith("$") or k not in style_theme:
            continue
        sv = style_theme[k]
        here = "%s.%s" % (path, k)
        if isinstance(v, dict) and isinstance(sv, dict):
            out += theme_conflicts(v, sv, here)
        elif v != sv:
            out.append((here, v, sv))
    return out


def starting_styles():
    """``{name: (path, data)}`` for the skill's shipped starting points in ``styles/``."""
    out = {}
    if not os.path.isdir(STYLES_DIR):
        return out
    for name in sorted(os.listdir(STYLES_DIR)):
        if name.endswith(".json"):
            path = os.path.join(STYLES_DIR, name)
            out[name[:-5]] = (path, jsonio.load(path))
    return out
