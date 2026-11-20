"""Tests for frames.py: drawn frames fitted to each capture (the opening is the capture's exact size), the device
classes and their corner radii, nothing of any maker's drawn, a maker's device art with its see-through screen found
from its alpha, and the order targets come in. No Chrome needed; nothing here reaches a network.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from xml.etree import ElementTree

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import frames  # noqa: E402

# The captures the trial and the demonstration use: a 6.9-inch iPhone, a 16:9 Play phone, a book foldable's inner
# display both ways round, its outer display, and an Android foldable's inner display.
SIZES = {"iphone": (1320, 2868), "android": (1080, 1920), "duo-inner": (2853, 2007),
         "duo-inner-portrait": (2007, 2853), "duo-outer": (1398, 2034), "fold-inner": (1840, 2208)}


def rgba_png(path, width, height, pixel):
    """Write an RGBA PNG whose pixel (x, y) is ``pixel(x, y)`` -> (r, g, b, a)."""
    rows = []
    for y in range(height):
        rows.append(b"\0" + b"".join(bytes(pixel(x, y)) for x in range(width)))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows))) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


def in_rrect(x, y, x0, y0, w, h, r):
    if not (x0 <= x < x0 + w and y0 <= y < y0 + h):
        return False
    cx = min(max(x + 0.5, x0 + r), x0 + w - r)
    cy = min(max(y + 0.5, y0 + r), y0 + h - r)
    return (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 <= r * r


def device_art(path, width=200, height=400, opening=(16, 20, 168, 360), radius=24, island=True):
    """A stand-in for a maker's device art (drawn here, nobody's): a rounded slab on transparency with a
    see-through screen opening and, optionally, an opaque pill inside the opening."""
    ox, oy, ow, oh = opening

    def px(x, y):
        if not in_rrect(x, y, 0, 0, width, height, 40):
            return (0, 0, 0, 0)
        if island and in_rrect(x, y, ox + ow // 2 - 20, oy + 8, 40, 10, 5):
            return (5, 5, 5, 255)
        if in_rrect(x, y, ox, oy, ow, oh, radius):
            return (0, 0, 0, 0)
        return (30, 30, 34, 255)
    rgba_png(path, width, height, px)
    return path


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="frames-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)


class Classes(Case):
    def test_the_table_is_fractions_of_the_short_side(self):
        for name, c in frames.CLASSES.items():
            with self.subTest(name=name):
                self.assertTrue(0 < c["bezel"] < 0.2 and 0 <= c["radius"] <= 0.3, c)
                self.assertTrue(c["about"])
        # A modern phone's display is rounded a lot, a 16:9 phone's barely, a TV's not at all.
        self.assertGreater(frames.CLASSES["phone"]["radius"], 2 * frames.CLASSES["phone-classic"]["radius"])
        self.assertLess(frames.CLASSES["tv"]["radius"], 0.01)

    def test_a_phone_frame_picks_its_class_by_the_captures_shape(self):
        got = dict((k, frames.phone_class(*s)) for k, s in SIZES.items())
        self.assertEqual(got["iphone"], "phone")
        self.assertEqual(got["android"], "phone-classic")
        self.assertEqual(got["duo-outer"], "foldable-outer")
        self.assertEqual(got["fold-inner"], "foldable-inner")
        self.assertEqual(frames.phone_class(2400, 1080), "phone")   # either way round

    def test_a_targets_words_and_device_say_which_display(self):
        self.assertEqual(frames.hint_from_words("iphone-duo-inner", "duo"), "foldable-inner")
        self.assertEqual(frames.hint_from_words("android-fold-outer"), "foldable-outer")
        self.assertIsNone(frames.hint_from_words("iphone", "iphone-6.9"))
        self.assertEqual(frames.class_for("phone", 2853, 2007, hint="foldable-inner"), "foldable-inner")
        self.assertEqual(frames.class_for("phone", 1080, 1920, device="phone"), "phone")
        self.assertEqual(frames.class_for("phone", 1080, 1920, override="foldable-outer"), "foldable-outer")
        self.assertEqual(frames.class_for("tablet", 1080, 1920, hint="foldable-inner"), "tablet")
        with self.assertRaises(frames.FrameError):
            frames.class_for("brick", 100, 200)


class Fitted(Case):
    def test_the_opening_is_the_capture_exactly_for_every_class(self):
        for cls in frames.CLASSES:
            for key, (w, h) in SIZES.items():
                with self.subTest(cls=cls, capture=key):
                    f = frames.fitted("phone", w, h, options={"class": cls})
                    m = f["meta"]
                    s = m["screen"]
                    self.assertEqual((s["width"], s["height"]), (w, h))   # no letterbox, no stretch, nothing cut
                    vb = m["viewBox"]
                    self.assertTrue(s["x"] > 0 and s["y"] > 0 and s["x"] + w < vb[2] and s["y"] + h <= vb[3])
                    self.assertAlmostEqual(m["screenRadius"], round(frames.CLASSES[cls]["radius"] * min(w, h), 2),
                                           places=1)
                    root = ElementTree.fromstring(f["svg"])   # well-formed
                    back = [e for e in root.iter() if e.get("class") == "screen-back"]
                    self.assertEqual(len(back), 1)
                    self.assertEqual((float(back[0].get("width")), float(back[0].get("height"))), (w, h))

    def test_the_bezel_is_even_and_the_body_concentric(self):
        m = frames.fitted("phone", 1320, 2868)["meta"]
        b = m["bezel"]
        self.assertAlmostEqual(b, 0.034 * 1320, places=1)
        self.assertAlmostEqual(m["screen"]["x"], b, places=1)
        self.assertAlmostEqual(m["screen"]["y"], b, places=1)
        self.assertAlmostEqual(m["viewBox"][2], 1320 + 2 * b, places=1)
        self.assertAlmostEqual(m["bodyRadius"], m["screenRadius"] + b, places=1)

    def test_options_set_the_radius_and_bezel(self):
        m = frames.fitted("phone", 1080, 1920, options={"radius": 0.0, "bezel": 0.05})["meta"]
        self.assertEqual(m["screenRadius"], 0)
        self.assertAlmostEqual(m["bezel"], 54, places=1)

    def test_no_apple_only_details_and_hardware_only_when_asked(self):
        plain = frames.fitted("phone", 1080, 2400, "google")
        self.assertEqual((plain["meta"]["hardware"]["buttons"], plain["meta"]["hardware"]["cutout"]), (False, None))
        asked = frames.fitted("phone", 1080, 2400, "google", options={"buttons": True, "cutout": "pill"})
        self.assertTrue(asked["meta"]["hardware"]["buttons"])
        hole = asked["meta"]["hardware"]["cutout"]
        self.assertEqual(hole["shape"], "pill")
        self.assertAlmostEqual(hole["x"] + hole["width"] / 2, 540, places=0)   # centred, in the status bar
        self.assertLess(hole["y"] + hole["height"], 0.08 * 1080)
        apple = frames.fitted("phone", 1320, 2868, "apple", options={"buttons": True, "cutout": "punch-hole"})
        hw = apple["meta"]["hardware"]
        self.assertEqual((hw["buttons"], hw["cutout"], sorted(hw["refused"])), (False, None, ["buttons", "cutout"]))
        self.assertEqual(plain["svg"].count("<rect"), apple["svg"].count("<rect"))
        with self.assertRaises(frames.FrameError):
            frames.fitted("phone", 100, 200, options={"cutout": "island"})

    def test_landscape_and_other_kinds(self):
        for name, size, kind in (("phone-landscape", (2400, 1080), "phone"), ("tablet", (2752, 2064), "tablet"),
                                 ("watch", (410, 502), "watch"), ("tv", (1920, 1080), "tv"),
                                 ("laptop", (2880, 1800), "laptop"), ("desktop", (2560, 1440), "desktop")):
            with self.subTest(name=name):
                m = frames.fitted(name, *size)["meta"]
                self.assertEqual(m["kind"], kind)
                self.assertEqual((m["screen"]["width"], m["screen"]["height"]), size)
        laptop = frames.fitted("laptop", 2880, 1800)["meta"]
        self.assertGreater(laptop["viewBox"][3] - laptop["screen"]["y"] - 1800, laptop["bezel"])   # chin and base


class Art(Case):
    def test_the_largest_enclosed_see_through_region_is_the_screen(self):
        path = device_art(os.path.join(self.tmp, "art.png"))
        found = frames.detect(path)
        self.assertEqual((found["x"], found["y"], found["width"], found["height"]), (16, 20, 168, 360))
        self.assertAlmostEqual(found["radius"], 24, delta=4)

    def test_no_opening_found(self):
        path = os.path.join(self.tmp, "slab.png")
        rgba_png(path, 40, 60, lambda x, y: (0, 0, 0, 0) if x < 4 else (9, 9, 9, 255))
        self.assertIsNone(frames.detect(path))
        with self.assertRaises(frames.FrameError):
            frames.art_meta(path)

    def test_art_meta_detects_or_reads_a_json_or_the_config(self):
        path = device_art(os.path.join(self.tmp, "art.png"))
        meta = frames.art_meta(path, {"maker": "apple"})
        self.assertEqual((meta["drawn"], meta["maker"], meta["screenSource"]), (False, "apple", "detected"))
        self.assertEqual(meta["viewBox"], [0, 0, 200, 400])
        given = frames.art_meta(path, {"screen": {"x": 1, "y": 2, "width": 3, "height": 4}})
        self.assertEqual((given["screen"]["width"], given["screenSource"]), (3, "config"))
        with open(os.path.join(self.tmp, "art.json"), "w") as f:
            json.dump({"screen": {"x": 10, "y": 10, "width": 100, "height": 200}, "viewBox": [0, 0, 200, 400],
                       "drawn": False, "maker": "examplemaker"}, f)
        beside = frames.art_meta(path)
        self.assertEqual((beside["screen"]["x"], beside["maker"], beside["screenSource"]), (10, "examplemaker", "json"))

    def test_an_svg_needs_its_json(self):
        path = os.path.join(self.tmp, "art.svg")
        with open(path, "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        with self.assertRaises(frames.FrameError):
            frames.art_meta(path)

    def test_fit_report(self):
        self.assertEqual(frames.fit_report(168, 360, {"width": 168, "height": 360})["cut"], 0)
        self.assertGreater(frames.fit_report(1080, 1920, {"width": 168, "height": 360})["cut"], 0.1)

    def test_the_cli_writes_the_json_beside_the_art(self):
        path = device_art(os.path.join(self.tmp, "art.png"))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(frames.main(["detect", path, "--maker", "apple", "--write"]), 0)
        with open(os.path.join(self.tmp, "art.json")) as f:
            data = json.load(f)
        self.assertEqual((data["maker"], data["drawn"], data["screen"]["width"]), ("apple", False, 168))
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(frames.main(["classes"]), 0)
        self.assertIn("foldable-inner", out.getvalue())


class Order(Case):
    def test_apple_phones_first_then_foldables_tablets_and_play(self):
        targets = {"ipad": {"store": "apple", "width": 2064, "height": 2752},
                   "android-phone": {"store": "google", "width": 1080, "height": 1920},
                   "iphone-duo-inner": {"store": "apple", "width": 2853, "height": 2007},
                   "iphone": {"store": "apple", "width": 1320, "height": 2868}}
        order = sorted(targets, key=lambda t: frames.target_rank(t, targets[t]))
        self.assertEqual(order, ["iphone", "iphone-duo-inner", "ipad", "android-phone"])
        self.assertEqual(frames.device_kind("watch", {"width": 410, "height": 502}), "watch")
        self.assertEqual(frames.device_kind("x", {"device": "foldable-inner"}), "foldable")


if __name__ == "__main__":
    unittest.main()
