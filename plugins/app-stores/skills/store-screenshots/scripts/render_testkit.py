"""Helpers for render.py's tests: synthetic captures (PNG, drawn with zlib alone), small configs in a temp folder,
and reading pixels back. Stdlib only; nothing here reaches a network."""

from __future__ import annotations

import copy
import json
import os
import struct
import zlib

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
FILES = os.path.join(SKILL_DIR, "evals", "files")

_CACHE = {}


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def capture_png(width, height, top=(246, 241, 232), bar=(14, 59, 46), accent=(242, 169, 59), alpha=False):
    """A plausible app screen: a dark header bar, then rows of cards (an accent tile and two grey lines) on a light
    ground. Opaque RGB (or RGBA with ``alpha``), exactly ``width`` x ``height``."""
    key = (width, height, top, bar, accent, alpha)
    if key in _CACHE:
        return _CACHE[key]
    px = 4 if alpha else 3

    def pix(c):
        return bytes(c) + (b"\xff" if alpha else b"")

    header = max(1, height // 8)
    row_h = max(4, height // 12)
    rows = []
    blank = pix(top) * width
    head = pix(bar) * width
    m = max(1, width // 20)
    tile = max(2, row_h * 6 // 10)
    for y in range(height):
        if y < header:
            rows.append(head)
            continue
        r = (y - header) % row_h
        if r < row_h // 6 or r > row_h - row_h // 6:
            rows.append(blank)
            continue
        line = bytearray(blank)
        card = pix((255, 255, 255))
        line[m * px:(width - m) * px] = card * (width - 2 * m)
        if r < row_h // 6 + tile:
            line[2 * m * px:(2 * m + tile) * px] = pix(accent) * tile
            lx = 2 * m + tile + m
            if r % 6 < 3:
                line[lx * px:(width - 3 * m) * px] = pix((70, 70, 70)) * max(0, width - 3 * m - lx)
        rows.append(bytes(line))
    raw = b"".join(b"\x00" + row for row in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
    data = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b"")
    _CACHE[key] = data
    return data


def write_capture(path, width, height, **kw):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(capture_png(width, height, **kw))
    return path


def base_config():
    """A small config: one tall target, the sample palette, no bundled fonts."""
    return {
        "version": 1,
        "captures": "captures",
        "out": "out",
        "primaryLocale": "en-US",
        "locales": ["en-US"],
        "theme": {
            "fonts": [],
            "palette": {"background": "#0E3B2E", "ink": "#FFFFFF", "accent": "#FFC94D"},
            "background": {"kind": "glow"},
            "caption": {"placement": "top", "align": "center", "maxLines": 2, "weight": 800, "sizePct": 8.0,
                        "floorPct": 6.0},
            "frame": "phone",
        },
        "targets": {"phone": {"store": "apple", "width": 300, "height": 650, "capture": "phone"}},
        "shots": [{"id": "plan", "capture": "plan", "layout": "framed-bleed", "caption": "cap.plan"}],
        "panorama": None,
        "stores": {"apple": {}, "google": {"frame": "none"}},
        "strings": {"en-US": {"cap.plan": "Plan a week of meals in minutes"}},
    }


def make_project(root, cfg=None, captures=None):
    """Write ``cfg`` (default ``base_config()``) to ``root/store-screenshots.json`` and the captures it needs:
    ``captures`` maps ``locale/device/screen`` to ``(width, height)``; by default every target's capture device
    gets every shot's screen in the primary locale, at the target's size. Returns the config's path."""
    cfg = copy.deepcopy(cfg or base_config())
    os.makedirs(root, exist_ok=True)
    if captures is None:
        captures = {}
        for t in cfg["targets"].values():
            for s in cfg["shots"]:
                for screen in [s["capture"]] + ([s["pair"]] if isinstance(s.get("pair"), str) else []):
                    captures["%s/%s/%s" % (cfg["primaryLocale"], t["capture"], screen)] = (t["width"], t["height"])
    for key, (w, h) in captures.items():
        write_capture(os.path.join(root, cfg.get("captures") or "captures", key + ".png"), w, h)
    path = os.path.join(root, "store-screenshots.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    return path


def column(rgb, width, height, x, y0=0, y1=None):
    """The pixels of column ``x`` (rows y0..y1) from ``png.decode_rgb``'s bytes, as (r, g, b) tuples."""
    y1 = height if y1 is None else y1
    out = []
    for y in range(y0, y1):
        i = (y * width + x) * 3
        out.append((rgb[i], rgb[i + 1], rgb[i + 2]))
    return out
