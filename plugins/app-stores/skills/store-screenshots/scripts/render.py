#!/usr/bin/env python3
"""render.py: render an app's store screenshots from its captures and one design (``store-screenshots.json``).

    render.py [--config store-screenshots.json] [--locales en-US,de-DE] [--targets iphone,ipad]
              [--shots plan,recipe] [--style screenshot-style.json] [--out screenshots] [--force]

With a style (the config's ``"style"``, or ``--style`` for an exploration), the config's theme and stores merge
under the style's (the style wins) and a shot's ``role`` gives its layout (styles.py). ``--out`` renders somewhere
else (``design/explore/<direction>``) without touching the set.

For every locale x target x shot the config asks for, it resolves the settings (theme, then the shot, then the
target's store's overrides, then the target's own), the words (each string falling back to the primary locale's)
and the capture (``<captures>/<locale>/<capture device>/<screen>.png``, falling back to the primary locale's),
writes a job for ``templates/set.html`` and has one headless Chrome draw it at the target's exact pixels. Out come
``<out>/<locale>/<target>/<shot>.png`` (opaque RGB PNGs) and ``<out>/render-report.json``: what each file shows,
its caption's size, lines and fit, its boxes, how much its capture was scaled, the fallbacks and the seams.

A file is drawn again only when what goes into it changed (the settings, words, capture, fonts, frames,
templates): the report keeps each file's ``inputsSha256``. ``--force`` draws everything.

Exit codes: 0 done; 1 a file failed to render or a caption doesn't fit at its floor (the report is still
written); 3 usage or environment (no config, an invalid config, no Chrome).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402
import styles  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
TEMPLATES_DIR = os.path.join(SKILL_DIR, "templates")
FRAMES_DIR = os.path.join(SKILL_DIR, "frames")
SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "store-screenshots.schema.json")
PAGE = os.path.join(TEMPLATES_DIR, "set.html")
REPORT_NAME = "render-report.json"

# Bumped when the way a job is built changes, so old renders aren't taken as current.
RENDERER_VERSION = "1"

EXIT_OK = 0
EXIT_ERRORS = 1
EXIT_USAGE = 3

LAYOUTS = ("fullbleed", "band", "framed", "framed-bleed", "tilt", "pair", "callout", "hero", "gameplay")
DEFAULT_LAYOUT = "framed-bleed"
DEFAULT_FRAME = "phone"
CAPTURE_EXTS = (".png", ".jpg", ".jpeg")
RTL_LANGUAGES = ("ar", "arc", "ckb", "dv", "fa", "he", "iw", "ks", "ku", "ps", "sd", "ug", "ur", "yi")
# 9.5u starts a tall slot's caption at about 11 pt in Apple's search row; 7u is about 12 pt on the product page
# (references/legibility.md, from the screenshot-craft measurements).
DEFAULT_CAPTION = {"placement": "top", "align": "center", "maxLines": 2, "weight": 800, "sizePct": 9.5,
                   "floorPct": 7.0, "font": None, "plate": "solid", "case": None}
DEFAULT_PALETTE = {"background": "#101418", "ink": "#FFFFFF", "accent": "#FFC94D"}


class UsageError(Exception):
    """The config can't be used (missing, not JSON, against the schema, or naming things that don't exist)."""


class EnvironmentProblem(Exception):
    """Something the machine lacks (Chrome)."""


class UnitError(Exception):
    """One file can't be rendered (its capture or a string is missing)."""


# ------------------------------------------------------------------------------------------------ helpers

def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def file_url(path):
    return pathlib.Path(os.path.abspath(path)).as_uri()


def is_rtl(locale):
    """True for a right-to-left language (by the locale's language subtag)."""
    return locale.split("-")[0].lower() in RTL_LANGUAGES


def aspect_class(width, height):
    """The aspect class a slot falls in: tall (w/h < 0.6), mid (0.6-0.85), square (0.85-1.2) or wide (> 1.2)."""
    a = width / float(height)
    if a < 0.6:
        return "tall"
    if a < 0.85:
        return "mid"
    if a <= 1.2:
        return "square"
    return "wide"


def _dir_digest(folder):
    """One hash of every file under ``folder`` (names and bytes), for the cache."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            path = os.path.join(dirpath, name)
            h.update(os.path.relpath(path, folder).encode("utf-8") + b"\0")
            with open(path, "rb") as f:
                h.update(hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def _csv(value):
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


# ------------------------------------------------------------------------------------------------ the config

def load_schema():
    return jsonio.load(SCHEMA_PATH)


def load_raw_config(path):
    """Read and validate a config as written (no style applied); raise ``UsageError`` with every problem."""
    if not os.path.isfile(path):
        raise UsageError("no config at %s (pass --config)" % path)
    try:
        cfg = jsonio.load(path)
    except ValueError as e:
        raise UsageError(str(e))
    problems = schema.validate(cfg, load_schema())
    if problems:
        raise UsageError("%s doesn't match the schema:\n  %s" % (path, "\n  ".join(problems)))
    return cfg


def load_config(path, style=None):
    """Read and validate a config and apply its style (``style``, a path, overrides the config's ``"style"``);
    raise ``UsageError`` with every problem found. The result carries ``_style`` (``None`` or a dict: ``path``,
    ``data``, ``sha256``) and ``_raw`` (the config as written)."""
    raw = load_raw_config(path)
    style_path = styles.style_path_for(path, raw, style)
    data = None
    if style_path:
        try:
            data = styles.load_style(style_path)
        except styles.StyleError as e:
            raise UsageError(str(e))
    try:
        cfg = styles.apply(raw, data)
    except styles.StyleError as e:
        raise UsageError("%s: %s" % (path, e))
    problems = semantic_problems(cfg)
    if problems:
        raise UsageError("%s:\n  %s" % (path, "\n  ".join(problems)))
    cfg["_raw"] = raw
    cfg["_style"] = None if data is None else {"path": style_path, "data": data,
                                                "sha256": styles.style_sha256(data)}
    return cfg


def semantic_problems(cfg):
    """What the schema can't say: names that must match one another."""
    out = []
    locales = cfg["locales"]
    if cfg["primaryLocale"] not in locales:
        out.append("primaryLocale %s isn't in locales" % cfg["primaryLocale"])
    ids = [s["id"] for s in cfg["shots"]]
    seen = set()
    for i in ids:
        if i in seen:
            out.append("shot id %s is used twice" % i)
        seen.add(i)
    targets = cfg["targets"]
    for s in cfg["shots"]:
        for t in s.get("targets") or []:
            if t not in targets:
                out.append("shot %s names target %s, which isn't in targets" % (s["id"], t))
        layouts = [s.get("layout")] + [o.get("layout") for o in (s.get(styles.ROLE_STORES) or {}).values()]
        if "callout" in layouts and not s.get("callout"):
            out.append("shot %s uses the callout layout but has no callout" % s["id"])
    pano = cfg.get("panorama")
    if pano:
        for sid in pano["shots"]:
            if sid not in ids:
                out.append("panorama names shot %s, which isn't in shots" % sid)
    for name, spec in list(targets.items()) + [("stores." + k, v) for k, v in (cfg.get("stores") or {}).items()]:
        if not isinstance(spec, dict):
            continue
        frame = spec.get("frame")
        if isinstance(frame, str) and frame != "none" and not _is_path(frame) and not _builtin_frame(frame):
            out.append("%s: no frame called %s (drawn frames: %s)" % (name, frame, ", ".join(builtin_frames())))
    theme_frame = (cfg.get("theme") or {}).get("frame")
    if isinstance(theme_frame, str) and theme_frame != "none" and not _is_path(theme_frame) \
            and not _builtin_frame(theme_frame):
        out.append("theme.frame: no frame called %s (drawn frames: %s)" % (theme_frame, ", ".join(builtin_frames())))
    return out


def builtin_frames():
    return sorted(n[:-5] for n in os.listdir(FRAMES_DIR) if n.endswith(".json"))


def _builtin_frame(name):
    return os.path.isfile(os.path.join(FRAMES_DIR, name + ".json")) and \
        os.path.isfile(os.path.join(FRAMES_DIR, name + ".svg"))


def _is_path(frame):
    return "/" in frame or "\\" in frame or os.path.splitext(frame)[1].lower() in (".svg", ".png")


# ------------------------------------------------------------------------------------------------ resolving

def _first(*values):
    for v in values:
        if v is not None:
            return v
    return None


class Resolver:
    """Turns the config into one job per file: settings, words, capture and frame, with the fallbacks noted."""

    def __init__(self, cfg, config_path, out=None):
        self.cfg = cfg
        self.base = os.path.dirname(os.path.abspath(config_path))
        self.config_path = config_path
        self.out = os.path.join(self.base, out or cfg.get("out") or "screenshots")
        self.captures = os.path.join(self.base, cfg.get("captures") or "captures")
        self.primary = cfg["primaryLocale"]
        self.theme = cfg.get("theme") or {}
        self.strings = cfg.get("strings") or {}
        self.stores = cfg.get("stores") or {}
        self._digests = {}
        self._frames = {}

    # -- files

    def path(self, rel):
        return os.path.normpath(os.path.join(self.base, rel))

    def digest(self, path):
        if path not in self._digests:
            self._digests[path] = png.sha256(path) if os.path.isfile(path) else "missing"
        return self._digests[path]

    def find_capture(self, locale, device, screen):
        """Return ``(path, fell_back)`` for a capture, or raise ``UnitError``."""
        for loc in (locale, self.primary):
            for ext in CAPTURE_EXTS:
                p = os.path.join(self.captures, loc, device, screen + ext)
                if os.path.isfile(p):
                    return p, loc != locale
            if loc == self.primary:
                break
        raise UnitError("no capture %s/%s/%s.png (nor in %s)" % (locale, device, screen, self.primary))

    def string(self, locale, key, fallbacks):
        """A string by key, falling back to the primary locale's (noted in ``fallbacks``)."""
        mine = self.strings.get(locale) or {}
        if mine.get(key) is not None:
            return mine[key]
        theirs = self.strings.get(self.primary) or {}
        if theirs.get(key) is not None:
            if locale != self.primary:
                fallbacks.append(key)
            return theirs[key]
        raise UnitError("no string %r in %s or %s" % (key, locale, self.primary))

    # -- frames

    def frame(self, name, capture_size):
        """The frame for a capture: ``None`` for none, else a dict for the page. A drawn frame's portrait or
        landscape variant is picked by the capture's shape."""
        if name is None or name == "none":
            return None
        w, h = capture_size
        if _is_path(name):
            return self._user_frame(name)
        if w > h and not name.endswith("-landscape") and _builtin_frame(name + "-landscape"):
            name = name + "-landscape"
        elif h > w and name.endswith("-landscape") and _builtin_frame(name[: -len("-landscape")]):
            name = name[: -len("-landscape")]
        if name not in self._frames:
            meta = jsonio.load(os.path.join(FRAMES_DIR, name + ".json"))
            with open(os.path.join(FRAMES_DIR, name + ".svg"), encoding="utf-8") as f:
                svg = f.read()
            self._frames[name] = {"name": name, "kind": "svg", "svg": svg, "meta": meta}
        return self._frames[name]

    def _user_frame(self, rel):
        path = self.path(rel)
        meta_path = os.path.splitext(path)[0] + ".json"
        if not os.path.isfile(path):
            raise UnitError("no frame art at %s" % rel)
        if not os.path.isfile(meta_path):
            raise UnitError("frame art %s has no JSON beside it (%s) giving its screen"
                            % (rel, os.path.basename(meta_path)))
        meta = jsonio.load(meta_path)
        for key in ("viewBox", "screen"):
            if key not in meta:
                raise UnitError("%s: missing %r" % (os.path.basename(meta_path), key))
        meta.setdefault("drawn", False)
        return {"name": rel, "kind": "image", "url": file_url(path), "meta": meta, "_files": [path, meta_path]}

    # -- settings

    def settings(self, shot, target_id):
        """A shot's layout, frame and caption style for a target: the theme's, then the shot's (its role's), then
        its role's for the target's store, then the store's overrides, then the target's own (each later one
        wins)."""
        target = self.cfg["targets"][target_id]
        store = self.stores.get(target["store"]) or {}
        role_store = (shot.get(styles.ROLE_STORES) or {}).get(target["store"]) or {}
        layers = [shot, store, target]
        layout = _first(target.get("layout"), store.get("layout"), role_store.get("layout"), shot.get("layout"),
                        DEFAULT_LAYOUT)
        frame = _first(target.get("frame"), store.get("frame"), role_store.get("frame"), shot.get("frame"),
                       self.theme.get("frame"), DEFAULT_FRAME)
        style = dict(DEFAULT_CAPTION)
        style.update({k: v for k, v in (self.theme.get("caption") or {}).items() if v is not None})
        words = True
        for layer in layers[1:]:
            cap = layer.get("caption")
            if cap is False:
                words = False
            elif isinstance(cap, dict):
                style.update({k: v for k, v in cap.items() if v is not None})
        if isinstance(shot.get("captionStyle"), dict):
            # A shot's own style sits under the store's and target's overrides.
            merged = dict(DEFAULT_CAPTION)
            merged.update({k: v for k, v in (self.theme.get("caption") or {}).items() if v is not None})
            merged.update({k: v for k, v in shot["captionStyle"].items() if v is not None})
            for layer in layers[1:]:
                if isinstance(layer.get("caption"), dict):
                    merged.update({k: v for k, v in layer["caption"].items() if v is not None})
            style = merged
        if layout == "gameplay":
            words = False
        return {"layout": layout, "frame": frame, "style": style, "words": words}

    def shots_for(self, target_id):
        return [s for s in self.cfg["shots"] if s.get("targets") is None or target_id in s["targets"]]

    # -- jobs

    def slot(self, locale, target_id, shot, files, fallbacks):
        """One slot's part of a page job (and the files it reads, for the cache)."""
        target = self.cfg["targets"][target_id]
        st = self.settings(shot, target_id)
        device = target["capture"]
        cap_path, cap_fell = self.find_capture(locale, device, shot["capture"])
        files.append(cap_path)
        info = png.info(cap_path)
        if cap_fell:
            fallbacks["captures"].append(os.path.relpath(cap_path, self.base))
        frame = self.frame(st["frame"], (info.width, info.height))
        if frame:
            files.extend(frame.get("_files", []))
        caption = None
        if st["words"]:
            texts = {}
            for key in ("caption", "kicker", "proof"):
                if shot.get(key):
                    texts[key] = self.string(locale, shot[key], fallbacks["strings"])
            if texts:
                style = st["style"]
                caption = {"text": texts.get("caption"), "kicker": texts.get("kicker"), "proof": texts.get("proof"),
                           "placement": style.get("placement"), "align": style.get("align"),
                           "maxLines": style.get("maxLines"), "weight": style.get("weight"),
                           "sizePct": style.get("sizePct"), "floorPct": style.get("floorPct"),
                           "font": style.get("font"), "plate": style.get("plate"), "case": style.get("case")}
        pair = None
        if st["layout"] == "pair" and shot.get("pair"):
            spec = shot["pair"]
            if isinstance(spec, str):
                spec = {"capture": spec}
            p_device = spec.get("device") or device
            p_path, p_fell = self.find_capture(locale, p_device, spec["capture"])
            files.append(p_path)
            if p_fell:
                fallbacks["captures"].append(os.path.relpath(p_path, self.base))
            p_info = png.info(p_path)
            p_frame = self.frame(_first(spec.get("frame"), st["frame"]), (p_info.width, p_info.height))
            if p_frame:
                files.extend(p_frame.get("_files", []))
            pair = {"capture": {"url": file_url(p_path), "width": p_info.width, "height": p_info.height},
                    "frame": _page_frame(p_frame)}
        return {
            "shot": shot["id"], "layout": st["layout"], "caption": caption,
            "capture": {"url": file_url(cap_path), "width": info.width, "height": info.height},
            "capturePath": os.path.relpath(cap_path, self.base),
            "frame": _page_frame(frame), "pair": pair,
            "tilt": shot.get("tilt") or ("left" if st["layout"] == "tilt" else None),
            "at": shot.get("at"), "callout": shot.get("callout") if st["layout"] == "callout" else None,
        }

    def theme_job(self, files):
        t = self.theme
        palette = dict(DEFAULT_PALETTE)
        palette.update({k: v for k, v in (t.get("palette") or {}).items() if v is not None})
        bg = dict(t.get("background") or {"kind": "glow"})
        if bg.get("src"):
            p = self.path(bg["src"])
            files.append(p)
            bg["url"] = file_url(p)
            bg.pop("src", None)
        fonts = []
        for f in t.get("fonts") or []:
            p = self.path(f["src"])
            files.append(p)
            fonts.append({"family": f["family"], "url": file_url(p), "weight": f.get("weight"),
                          "style": f.get("style")})
        icon = None
        if t.get("icon"):
            p = self.path(t["icon"])
            files.append(p)
            icon = file_url(p)
        return {"palette": palette, "background": bg, "fonts": fonts, "icon": icon,
                "captionFont": (t.get("caption") or {}).get("font")}

    def units(self, locales=None, targets=None, shots=None):
        """Every file to render: a list of dicts (locale, target, shot, path, the page job, its files, the
        fallbacks), or ``{"error": …}`` entries for files that can't be."""
        cfg = self.cfg
        pano = cfg.get("panorama") or None
        pano_ids = list(pano["shots"]) if pano else []
        out = []
        for locale in cfg["locales"]:
            if locales and locale not in locales:
                continue
            for target_id, target in cfg["targets"].items():
                if targets and target_id not in targets:
                    continue
                shots_here = self.shots_for(target_id)
                group = [s for s in shots_here if s["id"] in pano_ids]
                group.sort(key=lambda s: pano_ids.index(s["id"]))
                for shot in shots_here:
                    if shots and shot["id"] not in shots:
                        continue
                    unit = {"locale": locale, "target": target_id, "store": target["store"], "shot": shot["id"],
                            "width": target["width"], "height": target["height"],
                            "path": "%s/%s/%s.png" % (locale, target_id, shot["id"])}
                    try:
                        unit.update(self._job(locale, target_id, target, shot, group if shot in group else None,
                                              pano))
                    except UnitError as e:
                        unit["error"] = str(e)
                    out.append(unit)
        return out

    def _job(self, locale, target_id, target, shot, group, pano):
        files = []
        fallbacks = {"captures": [], "strings": []}
        theme = self.theme_job(files)
        members = group if group else [shot]
        slots = []
        for s in members:
            fb = {"captures": [], "strings": []} if s is not shot else fallbacks
            slots.append(self.slot(locale, target_id, s, files, fb))
        panorama = None
        if group:
            panorama = {"count": len(group), "seam": pano.get("seam", 6) if pano.get("seam") is not None else 6,
                        "background": None, "shots": [s["id"] for s in group]}
            if pano.get("background"):
                p = self.path(pano["background"])
                files.append(p)
                panorama["background"] = file_url(p)
        index = members.index(shot)
        job = {"version": 1, "index": index, "lang": locale, "dir": "rtl" if is_rtl(locale) else "ltr",
               "slot": {"width": target["width"], "height": target["height"]},
               "theme": theme, "panorama": panorama, "slots": slots}
        return {"job": job, "files": sorted(set(files)), "fallbacks": fallbacks,
                "layout": slots[index]["layout"], "capturePath": slots[index]["capturePath"],
                "role": shot.get("role"), "tilt": slots[index]["tilt"] if slots[index]["layout"] == "tilt" else None}

    def inputs_hash(self, unit, templates_digest):
        """The hash of everything that goes into one file: the job (with each file's path replaced by its
        bytes' hash), the templates and frames, and this script's version."""
        replace = {}
        for p in unit["files"]:
            replace[file_url(p)] = "sha256:" + self.digest(p)

        def scrub(v):
            if isinstance(v, dict):
                return {k: scrub(x) for k, x in v.items() if k != "capturePath"}
            if isinstance(v, list):
                return [scrub(x) for x in v]
            if isinstance(v, str) and v in replace:
                return replace[v]
            return v

        view = {"renderer": RENDERER_VERSION, "templates": templates_digest, "job": scrub(unit["job"]),
                "size": [unit["width"], unit["height"]]}
        return sha256_bytes(jsonio.canonical(view).encode("utf-8"))


def background_summary(theme):
    """What a file's background is, for the report and the baseline's drift check: its ``kind``, its colours
    (``#RRGGBB``, in the order drawn) and, for an image, the image's hash."""
    bg = theme.get("background") or {}
    pal = theme.get("palette") or {}
    kind = bg.get("kind") or "glow"
    colours = [pal.get("background")]
    if kind == "gradient":
        colours = [pal.get("background2") or pal.get("background"), pal.get("background")]
    elif kind == "glow":
        colours = [pal.get("background"), pal.get("accent")]
    out = {"kind": kind, "colours": [c.upper() if isinstance(c, str) else c for c in colours if c]}
    if bg.get("angle") is not None:
        out["angle"] = bg["angle"]
    if kind == "image" and bg.get("url"):
        out["image"] = urllib.parse.unquote(bg["url"].rsplit("/", 1)[-1])
    return out


def _page_frame(frame):
    if frame is None:
        return None
    return {k: v for k, v in frame.items() if not k.startswith("_")}


# ------------------------------------------------------------------------------------------------ rendering

def page_url(job_path):
    return file_url(PAGE) + "?job=" + urllib.parse.quote(file_url(job_path), safe="")


def write_job(job, folder, n):
    path = os.path.join(folder, "job-%04d.js" % n)
    with open(path, "w", encoding="utf-8") as f:
        f.write("window.__appstoresJob = " + json.dumps(job, ensure_ascii=False) + ";\n")
    return path


def file_entry(unit, page, out_path, inputs):
    """The report's entry for one rendered file, from the page's report."""
    fb = unit["fallbacks"]
    entry = {
        "path": unit["path"], "locale": unit["locale"], "target": unit["target"], "store": unit["store"],
        "shot": unit["shot"], "role": unit.get("role"), "layout": unit["layout"], "tilt": unit.get("tilt"),
        "width": unit["width"], "height": unit["height"],
        "aspectClass": aspect_class(unit["width"], unit["height"]),
        "capture": unit["capturePath"],
        "captureFallback": bool(fb["captures"]) and unit["capturePath"] in fb["captures"],
        "stringFallback": bool(fb["strings"]),
        "fallbacks": {"captures": fb["captures"], "strings": fb["strings"]},
        "caption": page.get("caption"),
        "frame": page.get("frame"),
        "callout": page.get("callout"),
        "captureScale": page.get("captureScale"),
        "seams": page.get("seams") or [],
        "background": unit.get("background"),
        "lang": page.get("lang"), "dir": page.get("dir"),
        "sha256": png.sha256(out_path),
        "inputsSha256": inputs,
    }
    if page.get("frames"):
        entry["frames"] = page["frames"]
    if unit["job"].get("panorama"):
        entry["panorama"] = {"shots": unit["job"]["panorama"]["shots"], "index": unit["job"]["index"],
                             "seam": unit["job"]["panorama"]["seam"]}
    if page.get("errors"):
        entry["errors"] = page["errors"]
    return entry


def load_previous(out):
    path = os.path.join(out, REPORT_NAME)
    if not os.path.isfile(path):
        return {}
    try:
        old = jsonio.load(path)
    except ValueError:
        return {}
    return {f.get("path"): f for f in old.get("files") or [] if isinstance(f, dict)}


def expected(config_path, style=None, out=None):
    """What a render of the config (and style) now would write, without rendering: ``(resolver, {path: inputs
    hash})`` for every file it asks for (files that can't be rendered map to ``None``). baseline.py compares it
    with the render report to tell whether the report is current."""
    cfg = load_config(config_path, style)
    res = Resolver(cfg, config_path, out)
    templates_digest = sha256_bytes((_dir_digest(TEMPLATES_DIR) + _dir_digest(FRAMES_DIR)).encode("ascii"))
    found = {}
    for u in res.units():
        found[u["path"]] = None if "error" in u else res.inputs_hash(u, templates_digest)
    return res, found


def style_entry(cfg, config_path):
    """The report's ``style``: the style a render used (``None`` without one)."""
    st = cfg.get("_style")
    if not st:
        return None
    base = os.path.dirname(os.path.abspath(config_path))
    data = st["data"]
    return {"path": os.path.relpath(st["path"], base).replace(os.sep, "/"), "name": data.get("name"),
            "sha256": st["sha256"], "locked": bool(data.get("locked")), "traits": data.get("traits") or {}}


def run(config_path, locales=None, targets=None, shots=None, out=None, force=False, browser=None,
        log=print, now=None, style=None):
    """Render; return ``(exit_code, report)``. ``browser`` is an open ``chrome.Chrome`` to reuse (tests);
    ``style`` a style file to use instead of the config's."""
    cfg = load_config(config_path, style)
    for name, wanted, known in (("locale", locales, cfg["locales"]), ("target", targets, list(cfg["targets"])),
                                ("shot", shots, [s["id"] for s in cfg["shots"]])):
        for w in wanted or []:
            if w not in known:
                raise UsageError("no %s called %s (the config has: %s)" % (name, w, ", ".join(known)))
    res = Resolver(cfg, config_path, out)
    units = res.units(locales, targets, shots)
    templates_digest = sha256_bytes((_dir_digest(TEMPLATES_DIR) + _dir_digest(FRAMES_DIR)).encode("ascii"))
    previous = load_previous(res.out)

    todo, entries, errors = [], {}, []
    for u in units:
        if "error" in u:
            errors.append({"path": u["path"], "error": u["error"]})
            continue
        u["inputs"] = res.inputs_hash(u, templates_digest)
        u["background"] = background_summary(u["job"]["theme"])
        old = previous.get(u["path"])
        out_path = os.path.join(res.out, u["path"])
        if (not force and old and old.get("inputsSha256") == u["inputs"] and os.path.isfile(out_path)
                and old.get("sha256") == png.sha256(out_path) and not old.get("errors")):
            fresh = dict(old)
            fresh.update({"role": u.get("role"), "tilt": u.get("tilt"), "background": u["background"]})
            entries[u["path"]] = fresh
            continue
        todo.append(u)

    rendered = 0
    if todo:
        own = browser is None
        if own:
            try:
                chrome.find_chrome()
            except chrome.ChromeNotFound as e:
                raise EnvironmentProblem(str(e))
            browser = chrome.Chrome()
        work = tempfile.mkdtemp(prefix="store-screenshots-")
        try:
            for n, u in enumerate(todo):
                out_path = os.path.join(res.out, u["path"])
                job_path = write_job(u["job"], work, n)
                try:
                    page = browser.render(page_url(job_path), u["width"], u["height"], out_path, timeout=120)
                except chrome.ChromeError as e:
                    errors.append({"path": u["path"], "error": "Chrome: %s" % e})
                    continue
                meta = png.info(out_path)
                if (meta.width, meta.height) != (u["width"], u["height"]) or meta.has_alpha:
                    errors.append({"path": u["path"], "error": "made a %dx%d picture%s, not %dx%d opaque" % (
                        meta.width, meta.height, " with alpha" if meta.has_alpha else "", u["width"], u["height"])})
                    continue
                entry = file_entry(u, page, out_path, u["inputs"])
                entries[u["path"]] = entry
                rendered += 1
                if entry.get("errors"):
                    errors.extend({"path": u["path"], "error": e} for e in entry["errors"])
        finally:
            shutil.rmtree(work, ignore_errors=True)
            if own:
                browser.close()

    # Files rendered before but outside this run's filters stay in the report while they exist.
    in_run = set(u["path"] for u in units)
    for path, old in previous.items():
        if path not in in_run and path not in entries and os.path.isfile(os.path.join(res.out, path)):
            entries[path] = old
    order = _order(cfg)
    files = sorted(entries.values(), key=lambda e: order(e))
    inputs = sha256_bytes("".join(e.get("inputsSha256", "") for e in files).encode("ascii"))
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    report = {"version": 1, "renderedAt": stamp, "config": os.path.basename(config_path),
              "configSha256": styles.config_sha256(cfg["_raw"]), "style": style_entry(cfg, config_path),
              "inputsSha256": inputs, "rendered": rendered, "unchanged": len(units) - len(todo) - sum(
                  1 for u in units if "error" in u),
              "files": files, "errors": errors}
    os.makedirs(res.out, exist_ok=True)
    jsonio.dump(report, os.path.join(res.out, REPORT_NAME))

    code = EXIT_OK
    for e in errors:
        log("error: %s: %s" % (e["path"], e["error"]))
        code = EXIT_ERRORS
    for e in files:
        cap = e.get("caption") or {}
        if cap and cap.get("fits") is False:
            log("error: %s: the caption doesn't fit in %d lines even at its floor (%.1f px)%s"
                % (e["path"], cap.get("maxLines") or 0, cap.get("floorPx") or 0, fit_hint(e)))
            code = EXIT_ERRORS
        elif cap and cap.get("atFloor"):
            log("note: %s: the caption shrank to its floor (%.1f px)" % (e["path"], cap.get("fontPx") or 0))
        if cap and cap.get("missingGlyphs"):
            log("warning: %s: the caption's font doesn't draw %s (a fallback font or a missing-glyph box does)"
                % (e["path"], " ".join(cap["missingGlyphs"])))
        if e.get("captureScale") and e["captureScale"] > 1.0005:
            log("warning: %s: the capture is shown at %.2fx its size (upscaled): capture at a bigger size"
                % (e["path"], e["captureScale"]))
        if e.get("captureFallback"):
            log("fallback: %s: the capture is %s's" % (e["path"], cfg["primaryLocale"]))
        if e.get("stringFallback"):
            log("fallback: %s: %s from %s" % (e["path"], ", ".join(e["fallbacks"]["strings"]), cfg["primaryLocale"]))
        for seam in e.get("seams") or []:
            if not seam.get("clear"):
                log("warning: %s: %s within the %s seam's margin" % (e["path"], ", ".join(seam["intruders"]),
                                                                       seam["edge"]))
    log("%d rendered, %d unchanged, %d failed: %s" % (rendered, report["unchanged"], len(errors),
                                                       os.path.join(res.out, REPORT_NAME)))
    return code, report


SOFT_HYPHEN_HELP = 'soft hyphens ("\\u00ad" in the JSON, or "&shy;")'


def fit_hint(entry):
    """How to fix a caption that doesn't fit: shorten it, or (where this Chrome can't hyphenate the language)
    mark its break points with soft hyphens, which work in every Chrome."""
    cap = entry.get("caption") or {}
    if cap.get("hyphenationAvailable") is False:
        lang = (entry.get("lang") or entry.get("locale") or "").split("-")[0]
        return "; this Chrome can't hyphenate %s: add %s at the break points, or shorten it" % (
            lang, SOFT_HYPHEN_HELP)
    return ": shorten it"


def _order(cfg):
    locs = list(cfg["locales"])
    tgts = list(cfg["targets"])
    ids = [s["id"] for s in cfg["shots"]]

    def key(e):
        def idx(seq, v):
            return seq.index(v) if v in seq else len(seq)
        return (idx(locs, e.get("locale")), idx(tgts, e.get("target")), idx(ids, e.get("shot")), e.get("path", ""))
    return key


def parser():
    p = argparse.ArgumentParser(prog="render.py", description="Render store screenshots from captures and a design.")
    p.add_argument("--config", default="store-screenshots.json", help="the design config (store-screenshots.json)")
    p.add_argument("--locales", help="only these locales (comma-separated)")
    p.add_argument("--targets", help="only these targets (comma-separated)")
    p.add_argument("--shots", help="only these shots (comma-separated)")
    p.add_argument("--out", help="the output folder, relative to the config (default: its 'out'); for an "
                   "exploration, design/explore/<direction>")
    p.add_argument("--style", help="a screenshot-style.json to render with instead of the config's style (an "
                   "exploration: pair it with --out)")
    p.add_argument("--force", action="store_true", help="render every file, changed or not")
    return p


def main(argv=None, browser=None):
    args = parser().parse_args(argv)
    try:
        code, _ = run(args.config, _csv(args.locales), _csv(args.targets), _csv(args.shots), args.out, args.force,
                      browser=browser, style=args.style)
        return code
    except UsageError as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except EnvironmentProblem as e:
        print("error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except chrome.ChromeError as e:
        print("error: Chrome: %s" % e, file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
