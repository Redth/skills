"""Synthetic rendered sets for check.py's and sheet.py's tests: PNGs written with ``zlib`` and ``struct``, a design
config and a render report shaped as ``render.py`` writes them (CONTRACT.md §8.4). Invented data only."""

from __future__ import annotations

import copy
import json
import os
import struct
import zlib

GREEN = (14, 59, 46)
WHITE = (255, 255, 255)
NEAR_WHITE = (242, 242, 242)
DARK = (26, 26, 26)
INK_DARK = (17, 17, 17)


def write_png(path, width, height, fill=GREEN, rects=(), alpha=False):
    """Write an 8-bit RGB (or RGBA, opaque) PNG: ``fill`` with ``rects`` ((x, y, w, h, (r, g, b))) drawn over it."""
    channels = 4 if alpha else 3

    def px(rgb):
        return bytes(rgb) + (b"\xff" if alpha else b"")

    base = px(fill) * width
    rows = []
    spans = [(int(x), int(y), int(w), int(h), px(c)) for x, y, w, h, c in rects]
    for yy in range(height):
        row = bytearray(base)
        for x, y, w, h, c in spans:
            if y <= yy < y + h:
                x0, x1 = max(0, x), min(width, x + w)
                if x1 > x0:
                    row[x0 * channels: x1 * channels] = c * (x1 - x0)
        rows.append(b"\x00" + bytes(row))
    raw = b"".join(rows)

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


TARGETS = {
    "iphone": {"store": "apple", "width": 1320, "height": 2868, "capture": "iphone-6.9"},
    "iphone-medium": {"store": "apple", "width": 1206, "height": 2622, "capture": "iphone-6.3"},
    "android-phone": {"store": "google", "width": 1080, "height": 1920, "capture": "android-phone"},
}

STRINGS = {
    "en-US": {"cap.plan": "Plan a week of meals", "cap.recipe": "Every recipe, step by step",
              "cap.shop": "Your list, sorted by aisle"},
    "de-DE": {"cap.plan": "Eine Woche Essen planen"},
}


def base_config(targets=None, shots=None, locales=None):
    """A design config for "Sample Recipes": three shots, two iPhone targets and a Play phone."""
    return {
        "version": 1,
        "captures": "captures",
        "out": "screenshots",
        "primaryLocale": "en-US",
        "locales": list(locales or ["en-US"]),
        "theme": {"palette": {"background": "#0E3B2E", "ink": "#FFFFFF", "accent": "#FFC94D"},
                  "caption": {"placement": "top", "align": "center", "maxLines": 2, "sizePct": 10.0,
                              "floorPct": 6.0},
                  "frame": "phone"},
        "targets": copy.deepcopy(targets if targets is not None else TARGETS),
        "shots": copy.deepcopy(shots if shots is not None else [
            {"id": "plan", "capture": "plan", "layout": "framed-bleed", "caption": "cap.plan"},
            {"id": "recipe", "capture": "recipe", "layout": "framed-bleed", "caption": "cap.recipe"},
            {"id": "shop", "capture": "shopping", "layout": "framed-bleed", "caption": "cap.shop"},
        ]),
        "panorama": None,
        "stores": {"google": {"frame": "none"}, "apple": {}},
        "strings": copy.deepcopy(STRINGS),
    }


def caption_box(width):
    """The caption's box on a target this wide: 5% margins, near the top."""
    return [round(width * 0.05), round(width * 0.08), round(width * 0.9), round(width * 0.22)]


def text_rects(box, ink):
    """Three bars of ink inside a caption box, covering about a fifth of it: the words, as far as contrast goes."""
    x, y, w, h = box
    return [(x + w * 0.1, y + h * (0.2 + 0.25 * i), w * 0.8, h * 0.08, ink) for i in range(3)]


def file_entry(config, locale, target, shot, **over):
    """A render report entry for one file, as render.py writes it."""
    t = config["targets"][target]
    w, h = t["width"], t["height"]
    store = t["store"]
    strings = config["strings"]
    key = next(s for s in config["shots"] if s["id"] == shot).get("caption")
    text = strings.get(locale, {}).get(key) or strings[config["primaryLocale"]].get(key)
    entry = {
        "path": "%s/%s/%s.png" % (locale, target, shot), "locale": locale, "target": target, "store": store,
        "shot": shot, "layout": next(s for s in config["shots"] if s["id"] == shot).get("layout", "framed-bleed"),
        "width": w, "height": h, "captureFallback": False, "stringFallback": key not in strings.get(locale, {}),
        "caption": {"text": text, "lines": 1, "fontPx": round(w * 0.10, 1), "floorPx": round(w * 0.06, 1),
                    "atFloor": False, "fits": True, "box": caption_box(w), "textShare": 0.12, "missingGlyphs": []},
        "frame": None if store == "google" else {"name": "phone", "box": [round(w * 0.1), round(h * 0.33),
                                                                         round(w * 0.8), round(h * 0.8)]},
        "callout": None, "captureScale": 0.92, "seams": [], "sha256": None,
    }
    for k, v in over.items():
        if k == "caption" and isinstance(v, dict) and isinstance(entry["caption"], dict):
            entry["caption"].update(v)
        else:
            entry[k] = v
    return entry


class SetBuilder:
    """A rendered set in a temp folder: ``config`` and ``files`` (report entries) to change before ``write()``,
    which writes the config, the report and every PNG (``pixels`` per path overrides how one is drawn)."""

    def __init__(self, root, config=None):
        self.root = root
        self.config = config or base_config()
        self.files = []
        self.pixels = {}
        self.listing = None
        for loc in self.config["locales"]:
            for tid in self.config["targets"]:
                for s in self.config["shots"]:
                    if s.get("targets") is None or tid in s["targets"]:
                        self.files.append(file_entry(self.config, loc, tid, s["id"]))

    def find(self, path):
        """The report entry for a path."""
        return next(f for f in self.files if f["path"] == path)

    @property
    def config_path(self):
        return os.path.join(self.root, "store-screenshots.json")

    @property
    def out(self):
        return os.path.join(self.root, self.config.get("out") or "screenshots")

    def write(self, skip_png=()):
        """Write the config, the report and the PNGs (but those in ``skip_png``); return the config's path."""
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config, f, indent=2)
        if self.listing is not None:
            with open(os.path.join(self.root, "store-listing.json"), "w", encoding="utf-8") as f:
                json.dump(self.listing, f, indent=2)
        os.makedirs(self.out, exist_ok=True)
        for entry in self.files:
            if entry["path"] in skip_png:
                continue
            spec = dict(self.pixels.get(entry["path"]) or {})
            w = spec.pop("width", entry["width"])
            h = spec.pop("height", entry["height"])
            fill = spec.pop("fill", GREEN)
            rects = list(spec.pop("rects", []))
            if "box_fill" in spec:
                rects.insert(0, tuple(entry["caption"]["box"]) + (spec.pop("box_fill"),))
            ink = spec.pop("ink", WHITE)
            if isinstance(entry.get("caption"), dict) and entry["caption"].get("box"):
                rects += text_rects(entry["caption"]["box"], ink)
            write_png(os.path.join(self.out, entry["path"]), w, h, fill, rects, **spec)
        report = {"version": 1, "renderedAt": "2026-11-14T10:00:00Z", "config": "store-screenshots.json",
                  "inputsSha256": "0" * 64, "files": self.files}
        with open(os.path.join(self.out, "render-report.json"), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        return self.config_path
