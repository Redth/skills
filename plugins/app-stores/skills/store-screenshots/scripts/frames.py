#!/usr/bin/env python3
"""frames.py: device frames fitted to each capture, and a maker's device art with its screen found.

    frames.py classes                       the device classes and their numbers
    frames.py detect ART.png [--write]      find a device art's see-through screen (``--write``: the JSON beside it)
    frames.py draw CLASS WxH [--out F.svg]  draw a fitted frame, to look at

**Drawn frames are fitted, not stretched.** Each is drawn for the capture it holds: the screen opening is the
capture's exact size (its aspect, so nothing is letterboxed, stretched or cut), the screen's corners are rounded by
the device class's radius, and the bezel is the same thickness all round (a laptop's chin aside). Nothing in them is
any maker's: no notch, island, home button, camera bump or brand shape; side buttons only when asked, and never on an
Apple target (Apple's marketing guidelines name volume controls among details unique to its products); a generic
punch-hole or pill camera only when asked, never on an Apple target.

The class comes from the frame's name and the capture's shape (a ``phone`` frame on a 16:9 capture is a
``phone-classic``, on a near-square one a ``foldable-inner``), or a target's ``device``, or the frame object's
``class``. The numbers (``CLASSES``) are fractions of the screen's short side and are approximations of the
devices of each class, not any one device's measurements.

**A maker's device art** (a PNG the user downloaded: Apple Design Resources, a maker's own device art where its
licence allows) is used as it is: never stretched, never redrawn. Its screen is the largest see-through region
the art encloses (found from the PNG's alpha with ``appstores_lib.png``), unless a JSON beside it, or the frame
object, says where the screen is. The capture goes under it at the opening's size.

Stdlib only; nothing here reaches a network.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
FRAMES_DIR = os.path.join(SKILL_DIR, "frames")

# Device classes. Every length is a fraction of the screen's short side: ``bezel`` the frame's thickness around
# the screen, ``radius`` the screen's corner radius, ``realShortMm`` the screen's short side in millimetres (for a
# pair's true relative scale). Approximations of each class's devices (2024-2026 models), not measurements of any
# one: a modern phone's display is rounded at about an eighth of its width, a 16:9 phone's nearly square, a
# tablet's and a laptop's slightly, a watch's a lot, a TV's not at all.
CLASSES = {
    "phone": {"kind": "phone", "bezel": 0.034, "radius": 0.12, "realShortMm": 70,
              "about": "a modern phone (18:9 and taller): thin even bezels, a display rounded at the corners"},
    "phone-classic": {"kind": "phone", "bezel": 0.04, "radius": 0.045, "realShortMm": 66,
                      "about": "a 16:9 phone (the long side 1.6 to 1.85 times the short): nearly square display "
                               "corners, so a status bar's clock in the corner stays whole"},
    "foldable-outer": {"kind": "phone", "bezel": 0.036, "radius": 0.1, "realShortMm": 68,
                       "about": "a foldable's outer (cover) display: a phone's rounded corners"},
    "foldable-inner": {"kind": "foldable", "bezel": 0.028, "radius": 0.05, "realShortMm": 140,
                       "about": "a foldable's inner display, unfolded (about square): gently rounded corners"},
    "tablet": {"kind": "tablet", "bezel": 0.045, "radius": 0.03, "realShortMm": 170,
               "about": "a tablet: even bezels, slightly rounded display corners"},
    "watch": {"kind": "watch", "bezel": 0.12, "radius": 0.24, "realShortMm": 36,
              "about": "a smartwatch: a rounded case and strap stubs, no crown or buttons"},
    "tv": {"kind": "tv", "bezel": 0.014, "radius": 0.004, "realShortMm": 680,
           "about": "a television: a hairline bezel, square corners, two feet"},
    "laptop": {"kind": "laptop", "bezel": 0.034, "radius": 0.016, "realShortMm": 200,
               "about": "a laptop: a lid with a thicker chin over a base"},
    "desktop": {"kind": "desktop", "bezel": 0.028, "radius": 0.008, "realShortMm": 330,
                "about": "a desktop monitor: thin bezels on a stand"},
}

# The drawn frames a config may name, and the class each one draws (a phone frame picks its class by the
# capture's shape: ``phone_class``). The -landscape names are kept for configs that use them: the orientation
# always follows the capture.
NAMES = {
    "phone": "auto-phone", "phone-landscape": "auto-phone",
    "phone-classic": "phone-classic", "foldable-outer": "foldable-outer", "foldable-inner": "foldable-inner",
    "tablet": "tablet", "tablet-landscape": "tablet",
    "watch": "watch", "tv": "tv", "laptop": "laptop", "desktop": "desktop",
}
CUTOUTS = ("none", "punch-hole", "pill")
FINISHES = {
    "dark": {"band": ("#5b5f68", "#2c2f35", "#1c1e22", "#34373e", "#4c5059"), "glass": "#08090b",
             "edge": "#26282d", "strap": "#1d1f23"},
    "light": {"band": ("#f4f5f7", "#c9ccd2", "#aeb2b9", "#d4d7dc", "#eceef1"), "glass": "#0b0c0e",
              "edge": "#b9bcc2", "strap": "#d9dbdf"},
}


class FrameError(ValueError):
    """A frame that can't be used (an unknown name, art with no screen to find)."""


def ratio(width, height):
    """The capture's long side over its short side."""
    return max(width, height) / float(max(1, min(width, height)))


def phone_class(width, height):
    """The phone class a capture's shape suggests: 18:9 and taller a modern ``phone``; 16:9 and the like
    ``phone-classic`` (its status bar sits in the very corner); about 3:2 a ``foldable-outer``; about square a
    ``foldable-inner``."""
    r = ratio(width, height)
    if r >= 1.85:
        return "phone"
    if r >= 1.6:
        return "phone-classic"
    if r >= 1.3:
        return "foldable-outer"
    return "foldable-inner"


def builtin_names():
    """The drawn frames' names a config may use."""
    return sorted(NAMES)


def is_builtin(name):
    return isinstance(name, str) and name in NAMES


def class_for(name, width, height, device=None, override=None, hint=None):
    """The device class a frame draws for a capture: the frame object's ``class``, else the target's ``device``
    (when it names a class), else the frame's own (a phone frame's by ``hint``, the target's words, else by the
    capture's shape)."""
    for c in (override, device):
        if c in CLASSES:
            return c
    cls = NAMES.get(name)
    if cls is None:
        raise FrameError("no drawn frame called %s (drawn frames: %s)" % (name, ", ".join(builtin_names())))
    if cls != "auto-phone":
        return cls
    return hint if hint in ("foldable-inner", "foldable-outer") else phone_class(width, height)


def hint_from_words(*names):
    """A foldable's display from words in a target's id or capture device: inner, unfolded or open is the inner
    display; outer, cover or folded the outer one. ``None`` when nothing says."""
    words = set(re.split(r"[^a-z0-9]+", " ".join(str(n or "") for n in names).lower()))
    if words & {"inner", "unfolded", "open", "main"} and words & {"fold", "foldable", "duo", "flip", "inner",
                                                                 "unfolded"}:
        return "foldable-inner"
    if words & {"outer", "cover", "folded"} and words & {"fold", "foldable", "duo", "flip", "outer", "cover"}:
        return "foldable-outer"
    return None


def _n(v):
    """A number for SVG: two decimals, no trailing zeros."""
    s = ("%.2f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _rect(x, y, w, h, rx, extra=""):
    return '<rect x="%s" y="%s" width="%s" height="%s" rx="%s"%s/>' % (
        _n(x), _n(y), _n(max(0, w)), _n(max(0, h)), _n(max(0, min(rx, w / 2.0, h / 2.0))), extra)


def fitted(name, width, height, store=None, device=None, options=None, hint=None):
    """A drawn frame fitted to a ``width`` x ``height`` capture, for the page: ``{"name", "kind": "svg", "svg",
    "meta"}``. The screen opening is exactly the capture (in the SVG's units, which are the capture's pixels);
    ``meta`` carries the class, the radius used, and what hardware was drawn. ``options`` (the frame object):
    ``class``, ``radius`` and ``bezel`` (fractions of the short side), ``buttons`` (side buttons, never on Apple
    targets), ``cutout`` (``punch-hole`` | ``pill``, never on Apple targets), ``finish`` (``dark`` | ``light``)."""
    options = options or {}
    cls = class_for(name, width, height, device, options.get("class"), hint)
    spec = CLASSES[cls]
    kind = spec["kind"]
    w, h = float(width), float(height)
    s = min(w, h)
    portrait = h >= w
    radius_frac = options.get("radius")
    radius_frac = spec["radius"] if not isinstance(radius_frac, (int, float)) else max(0.0, min(0.5, radius_frac))
    bezel_frac = options.get("bezel")
    bezel_frac = spec["bezel"] if not isinstance(bezel_frac, (int, float)) else max(0.004, min(0.3, bezel_frac))
    r = radius_frac * s
    b = bezel_frac * s
    apple = store == "apple"
    refused = []
    buttons = bool(options.get("buttons")) and kind in ("phone", "foldable")
    if buttons and apple:
        buttons = False
        refused.append("buttons")
    cutout = options.get("cutout") or "none"
    if cutout not in CUTOUTS:
        raise FrameError("cutout must be one of %s, not %s" % (", ".join(CUTOUTS), cutout))
    if cutout != "none" and (apple or kind not in ("phone", "foldable")):
        if apple:
            refused.append("cutout")
        cutout = "none"
    finish = FINISHES.get(options.get("finish") or "dark", FINISHES["dark"])

    # The bezel on each side (a laptop's chin and a tv's even hairline), then room around the body for buttons,
    # feet, a stand, a base or a strap.
    bl = br = bt = bb = b
    if kind == "laptop":
        bt, bb = b * 1.3, b * 1.75
    body_r = r + b if kind not in ("tv", "desktop", "laptop") else max(r + b * 0.5, b * 0.6)
    ml = mr = mt = mb = 0.0
    press = b * 0.32
    if buttons:
        if portrait:
            mr = press
        else:
            mt = press
    extra_bottom = 0.0
    if kind == "tv":
        extra_bottom = s * 0.06
    elif kind == "desktop":
        extra_bottom = s * 0.22
    elif kind == "laptop":
        extra_bottom = s * 0.045
    elif kind == "watch":
        mt = mb = s * 0.42
    mb += extra_bottom
    body_w, body_h = w + bl + br, h + bt + bb
    if kind == "laptop":
        side = body_w * 0.055
        ml = mr = side
    vw, vh = ml + body_w + mr, mt + body_h + mb
    bx, by = ml, mt
    sx, sy = bx + bl, by + bt

    g = finish["band"]
    defs = (
        '<defs><linearGradient id="band" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="%s"/><stop offset="0.18" stop-color="%s"/><stop offset="0.55" stop-color="%s"/>'
        '<stop offset="0.85" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient>'
        '<linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffffff" '
        'stop-opacity="0.34"/><stop offset="0.5" stop-color="#ffffff" stop-opacity="0.10"/><stop offset="1" '
        'stop-color="#ffffff" stop-opacity="0.24"/></linearGradient>'
        '<linearGradient id="deck" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="%s"/>'
        '<stop offset="0.3" stop-color="%s"/><stop offset="1" stop-color="%s"/></linearGradient></defs>'
        % (g[0], g[1], g[2], g[3], g[4], g[4], g[2], g[1]))
    parts = []
    if buttons:
        # Generic side keys: a long rocker and a short key on the long right edge (the top edge turned).
        def key(at, length):
            if portrait:
                return _rect(bx + body_w - press * 2, by + body_h * at, press * 3, body_h * length, press,
                             ' fill="url(#band)"')
            return _rect(bx + body_w * (1 - at - length), by - press, body_w * length, press * 3, press,
                         ' fill="url(#band)"')
        parts.append(key(0.2, 0.11))
        parts.append(key(0.37, 0.06))
    if kind == "watch":
        strap_w = body_w * 0.7
        strap_x = bx + (body_w - strap_w) / 2
        parts.append(_rect(strap_x, 0, strap_w, mt + body_h * 0.5, strap_w * 0.18,
                           ' fill="%s"' % finish["strap"]))
        parts.append(_rect(strap_x, by + body_h * 0.5, strap_w, body_h * 0.5 + mb, strap_w * 0.18,
                           ' fill="%s"' % finish["strap"]))
    if kind == "tv":
        foot_w, foot_h = body_w * 0.07, extra_bottom * 0.9
        for fx in (0.13, 0.87):
            cx = bx + body_w * fx
            parts.append('<path d="M%s %s L%s %s L%s %s L%s %s Z" fill="url(#deck)"/>' % (
                _n(cx - foot_w * 0.2), _n(by + body_h), _n(cx + foot_w * 0.2), _n(by + body_h),
                _n(cx + foot_w * 0.5), _n(by + body_h + foot_h), _n(cx - foot_w * 0.5), _n(by + body_h + foot_h)))
    if kind == "desktop":
        neck_w, foot_w = body_w * 0.11, body_w * 0.34
        neck_h = extra_bottom * 0.82
        parts.append(_rect(bx + (body_w - neck_w) / 2, by + body_h - b, neck_w, neck_h + b, 0,
                           ' fill="url(#deck)"'))
        parts.append(_rect(bx + (body_w - foot_w) / 2, by + body_h + neck_h - extra_bottom * 0.02, foot_w,
                           extra_bottom * 0.2, extra_bottom * 0.08, ' fill="url(#band)"'))
    # The body: the band (the device's edge), a sheen on it, the glass inside it, the screen's black.
    rim = max(1.0, b * 0.28) if kind not in ("tv", "desktop") else max(1.0, b * 0.35)
    parts.append(_rect(bx, by, body_w, body_h, body_r, ' fill="url(#band)"'))
    parts.append(_rect(bx + 1.25, by + 1.25, body_w - 2.5, body_h - 2.5, body_r - 1.25,
                       ' fill="none" stroke="url(#sheen)" stroke-width="2.5"'))
    parts.append(_rect(bx + rim, by + rim, body_w - 2 * rim, body_h - 2 * rim, max(0.0, body_r - rim),
                       ' fill="%s"' % finish["glass"]))
    parts.append(_rect(bx + rim + 0.75, by + rim + 0.75, body_w - 2 * rim - 1.5, body_h - 2 * rim - 1.5,
                       max(0.0, body_r - rim - 0.75),
                       ' fill="none" stroke="#ffffff" stroke-opacity="0.07" stroke-width="1.5"'))
    parts.append(_rect(sx, sy, w, h, r, ' class="screen-back" fill="#000000"'))
    if kind == "laptop":
        deck_y = by + body_h - b * 0.25
        deck_h = extra_bottom + b * 0.25
        x0, x1 = 0.0, vw
        parts.append('<path d="M%s %s H%s V%s Q%s %s %s %s H%s Q%s %s %s %s Z" fill="url(#deck)"/>' % (
            _n(x0), _n(deck_y), _n(x1), _n(deck_y + deck_h * 0.5), _n(x1), _n(deck_y + deck_h),
            _n(x1 - deck_h * 2.4), _n(deck_y + deck_h), _n(x0 + deck_h * 2.4), _n(x0), _n(deck_y + deck_h),
            _n(x0), _n(deck_y + deck_h * 0.5)))
        parts.append(_rect(x0, deck_y, x1 - x0, max(1.0, deck_h * 0.07), 0,
                           ' fill="#ffffff" fill-opacity="0.32"'))
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %s %s" width="%s" height="%s">%s%s</svg>'
           % (_n(vw), _n(vh), _n(vw), _n(vh), defs, "".join(parts)))
    hole = None
    if cutout != "none":
        d = 0.034 * s
        if portrait:
            cx, cy = w / 2.0, max(d * 0.9, 0.036 * s)
            cw, ch = (d, d) if cutout == "punch-hole" else (d * 2.9, d)
        else:
            cx, cy = max(d * 0.9, 0.036 * s), h / 2.0
            cw, ch = (d, d) if cutout == "punch-hole" else (d, d * 2.9)
        hole = {"shape": cutout, "x": round(cx - cw / 2, 2), "y": round(cy - ch / 2, 2), "width": round(cw, 2),
                "height": round(ch, 2)}
    real_short = spec["realShortMm"]
    meta = {
        "name": name, "class": cls, "kind": kind, "fitted": True, "drawn": True, "maker": None,
        "orientation": "portrait" if portrait else "landscape",
        "viewBox": [0, 0, round(vw, 2), round(vh, 2)],
        "screen": {"x": round(sx, 2), "y": round(sy, 2), "width": w, "height": h},
        "screenRadius": round(r, 2), "radiusFraction": round(radius_frac, 4), "bodyRadius": round(body_r, 2),
        "bezel": round(b, 2), "rim": round(rim, 2), "realWidthMm": round(real_short * vw / s, 1),
        "hardware": {"buttons": buttons, "cutout": hole, "refused": refused,
                     "finish": options.get("finish") or "dark"},
        "finishColours": {"band": list(finish["band"]), "glass": finish["glass"], "edge": finish["edge"]},
    }
    return {"name": name, "kind": "svg", "svg": svg, "meta": meta}


# ------------------------------------------------------------------------------------------------ order

# Where a target's device comes in sheets and reports: phones first (what most shoppers see), then foldables,
# tablets, computers, TVs and watches; the App Store before Play.
DEVICE_RANK = {"phone": 0, "foldable": 1, "tablet": 2, "laptop": 3, "desktop": 3, "tv": 4, "watch": 5}
STORE_RANK = {"apple": 0, "google": 1}


def target_rank(target_id, target):
    """Where a target comes in reports and sheets: ``(store, device)`` ranks, the App Store's phones first."""
    target = target or {}
    return (STORE_RANK.get(target.get("store"), len(STORE_RANK)), DEVICE_RANK.get(device_kind(target_id, target), 3))


def device_kind(target_id, target):
    """A target's kind of device (phone, foldable, tablet, laptop, desktop, tv, watch): its ``device`` class if it
    names one, else words in its id and capture device, else its shape."""
    target = target or {}
    cls = CLASSES.get(target.get("device") or "")
    if cls:
        return cls["kind"]
    words = set(_words((str(target_id) + " " + str(target.get("capture") or "")).lower()))
    for kind, names in (("watch", {"watch", "wear"}), ("tv", {"tv", "appletv", "television"}),
                        ("desktop", {"mac", "desktop", "pc", "windows"}), ("laptop", {"laptop", "chromebook"}),
                        ("tablet", {"ipad", "tablet", "tablet7", "tablet10", "tab"})):
        if words & names:
            return kind
    w, h = target.get("width") or 1, target.get("height") or 1
    a = w / float(h)
    if words & {"fold", "duo", "foldable", "unfolded", "inner", "outer", "cover"}:
        return "foldable" if 0.7 < a < 1.45 else "phone"
    if words & {"phone", "iphone", "android", "pixel", "galaxy", "handset"} or a < 0.6:
        return "phone"
    if a < 0.85:
        return "tablet"
    return "foldable" if a <= 1.2 else "desktop"


def _words(text):
    return [w for w in re.split(r"[^a-z0-9]+", text) if w]


# ------------------------------------------------------------------------------------------------ maker's art

_ART_CACHE = {}
_CLEAR = bytes(1 if a < 128 else 0 for a in range(256))


def find_opening(width, height, alpha):
    """The largest see-through region the picture encloses (one not touching its edge): ``{"x", "y", "width",
    "height", "area"}`` for its bounding box and pixel count, or ``None`` when there's none. ``alpha`` is one
    byte a pixel (``png.decode_alpha``); below 128 counts as see-through. Rows are read as runs and joined where
    they touch the row above, so a full-size device art is read in a moment."""
    clear = alpha.translate(_CLEAR)
    parent = []

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    runs = []
    prev = []
    pattern = re.compile(b"\x01+")
    for y in range(height):
        row = clear[y * width:(y + 1) * width]
        cur = []
        for m in pattern.finditer(row):
            rid = len(parent)
            parent.append(rid)
            cur.append((m.start(), m.end(), rid))
            runs.append((y, m.start(), m.end(), rid))
        i = j = 0
        while i < len(prev) and j < len(cur):
            a0, a1, ai = prev[i]
            b0, b1, bi = cur[j]
            if a0 < b1 and b0 < a1:
                ra, rb = find(ai), find(bi)
                if ra != rb:
                    parent[rb] = ra
            if a1 < b1:
                i += 1
            else:
                j += 1
        prev = cur
    comps = {}
    for y, x0, x1, rid in runs:
        root = find(rid)
        c = comps.get(root)
        if c is None:
            c = comps[root] = [x0, y, x1, y + 1, 0, False]
        c[0] = min(c[0], x0)
        c[1] = min(c[1], y)
        c[2] = max(c[2], x1)
        c[3] = max(c[3], y + 1)
        c[4] += x1 - x0
        if x0 == 0 or x1 == width or y == 0 or y == height - 1:
            c[5] = True
    enclosed = [c for c in comps.values() if not c[5]]
    if not enclosed:
        return None
    best = max(enclosed, key=lambda c: c[4])
    box = {"x": best[0], "y": best[1], "width": best[2] - best[0], "height": best[3] - best[1], "area": best[4]}
    box["radius"] = _corner_radius(width, clear, box)
    return box


def _corner_radius(width, clear, box):
    """The opening's corner radius, from how far along each corner's diagonal the see-through starts: a quarter
    circle of radius r meets the diagonal r(1 - 1/sqrt 2) in from the corner."""
    found = []
    limit = min(box["width"], box["height"]) // 2
    corners = ((box["x"], box["y"], 1, 1), (box["x"] + box["width"] - 1, box["y"], -1, 1),
               (box["x"], box["y"] + box["height"] - 1, 1, -1),
               (box["x"] + box["width"] - 1, box["y"] + box["height"] - 1, -1, -1))
    for x0, y0, dx, dy in corners:
        for t in range(limit):
            if clear[(y0 + dy * t) * width + x0 + dx * t]:
                found.append(t / (1 - 1 / math.sqrt(2)))
                break
    return round(sum(found) / len(found), 1) if found else 0.0


def art_meta(path, options=None):
    """A maker's device art as the page draws it: its ``viewBox`` (the picture's pixels), its ``screen`` (the
    opening) and ``screenRadius``, ``drawn: false`` and its ``maker``. The screen comes from the frame object's
    ``screen``, else a JSON beside the art (``<art>.json``, the drawn frames' shape), else the art's largest
    enclosed see-through region. Raises ``FrameError`` when none of these gives one."""
    options = options or {}
    meta_path = os.path.splitext(path)[0] + ".json"
    meta = {}
    source = None
    if os.path.isfile(meta_path):
        try:
            meta = jsonio.load(meta_path)
        except ValueError as e:
            raise FrameError("%s: %s" % (meta_path, e))
        if not isinstance(meta, dict):
            raise FrameError("%s isn't a JSON object" % meta_path)
        source = "json"
    for key in ("screen", "screenRadius", "viewBox", "maker", "drawn"):
        if options.get(key) is not None:
            meta[key] = options[key]
            source = source or "config"
    if os.path.splitext(path)[1].lower() == ".png":
        info = png.info(path)
        meta.setdefault("viewBox", [0, 0, info.width, info.height])
        if not isinstance(meta.get("screen"), dict):
            found = detect(path)
            if found is None:
                raise FrameError("found no see-through screen in %s: give the screen's rectangle (x, y, width, "
                                 "height in its pixels) in the frame's \"screen\" or a JSON beside it" % path)
            meta["screen"] = {k: found[k] for k in ("x", "y", "width", "height")}
            meta.setdefault("screenRadius", found["radius"])
            source = "detected"
    for key in ("viewBox", "screen"):
        if key not in meta:
            raise FrameError("frame art %s needs its %r: an SVG's screen can't be found by itself (put it in a JSON "
                             "beside the art)" % (os.path.basename(path), key))
    meta.setdefault("drawn", False)
    meta.setdefault("maker", None)
    meta.setdefault("screenRadius", 0)
    meta["screenSource"] = source
    return meta


def detect(path):
    """``find_opening`` on a PNG's alpha, remembered per file (path, size and time) for the run."""
    st = os.stat(path)
    key = (os.path.abspath(path), st.st_size, st.st_mtime)
    if key not in _ART_CACHE:
        w, h, alpha = png.decode_alpha(path)
        _ART_CACHE[key] = find_opening(w, h, alpha)
    return _ART_CACHE[key]


def fit_report(capture_w, capture_h, screen):
    """How a capture fits a device art's opening: the two aspects and the share of the capture cut to fill it
    (0 when they match; a capture is never stretched)."""
    ca = capture_w / float(capture_h)
    sa = screen["width"] / float(screen["height"])
    cut = 1 - min(ca, sa) / max(ca, sa)
    return {"captureAspect": round(ca, 4), "screenAspect": round(sa, 4), "cut": round(cut, 4)}


# ------------------------------------------------------------------------------------------------ the CLI

def main(argv=None):
    p = argparse.ArgumentParser(prog="frames.py", description="Fitted device frames, and finding a device art's "
                                "screen.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("classes", help="the device classes and their numbers")
    d = sub.add_parser("detect", help="find a device art's see-through screen")
    d.add_argument("art")
    d.add_argument("--maker", help="whose art it is (apple, google, samsung…), written with --write")
    d.add_argument("--write", action="store_true", help="write <art>.json beside it (then it isn't searched again)")
    dr = sub.add_parser("draw", help="draw a fitted frame as an SVG, to look at")
    dr.add_argument("frame", help="a drawn frame or class name (phone, tablet, foldable-inner…)")
    dr.add_argument("size", help="the capture's WIDTHxHEIGHT")
    dr.add_argument("--out", help="the SVG to write (default: print it)")
    args = p.parse_args(argv)
    if args.cmd == "classes":
        for name, c in CLASSES.items():
            print("%-15s bezel %.3f  radius %.3f  (%s)" % (name, c["bezel"], c["radius"], c["about"]))
        return 0
    if args.cmd == "detect":
        try:
            found = detect(args.art)
        except (png.ImageError, OSError) as e:
            print("error: %s" % e, file=sys.stderr)
            return 3
        if not found:
            print("error: no enclosed see-through region in %s" % args.art, file=sys.stderr)
            return 1
        info = png.info(args.art)
        meta = {"name": os.path.basename(args.art), "drawn": False, "maker": args.maker,
                "viewBox": [0, 0, info.width, info.height],
                "screen": {k: found[k] for k in ("x", "y", "width", "height")}, "screenRadius": found["radius"]}
        if args.write:
            out = os.path.splitext(args.art)[0] + ".json"
            jsonio.dump(meta, out)
            print("wrote %s" % out)
        else:
            sys.stdout.write(jsonio.dumps(meta))
        return 0
    if args.cmd == "draw":
        m = re.match(r"^(\d+)x(\d+)$", args.size)
        if not m:
            print("error: size is WIDTHxHEIGHT", file=sys.stderr)
            return 3
        name = args.frame if args.frame in NAMES else "phone"
        f = fitted(name, int(m.group(1)), int(m.group(2)), options={"class": args.frame}
                   if args.frame in CLASSES and args.frame not in NAMES else None)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(f["svg"])
            print("wrote %s (%s)" % (args.out, f["meta"]["class"]))
        else:
            print(f["svg"])
        return 0
    p.print_help()
    return 3


if __name__ == "__main__":
    sys.exit(main())
