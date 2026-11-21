"""Tests for compose.py: the edit (schema, frames, marks, transitions, times), the camera, pan and spotlight worked
out per frame, the style read for the look, the command line; then a few frames rendered through headless Chrome
(skipped where no Chrome is installed) and, with ffmpeg too, a master.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here reaches a network.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import compose  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLE = os.path.join(os.path.dirname(HERE), "examples", "sample-edit.json")

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None


def write_png(path, width, height, colour):
    """A flat ``colour`` PNG (stdlib only), with a darker band across the middle to see it move."""
    r, g, b = colour
    band = (r // 2, g // 2, b // 2)
    rows = []
    for y in range(height):
        c = band if height * 0.45 <= y < height * 0.55 else colour
        rows.append(b"\x00" + bytes(c) * width)
    raw = zlib.compress(b"".join(rows))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def make_take(folder, count, width=60, height=130, colour=(200, 220, 240)):
    os.makedirs(folder, exist_ok=True)
    for i in range(1, count + 1):
        write_png(os.path.join(folder, "frame-%05d.png" % i), width, height, colour)
    return folder


def edit(**over):
    """A small valid edit (frames named by index, not on disk)."""
    e = {
        "name": "t", "width": 886, "height": 1920, "fps": 10, "framePattern": "frame-%05d.png",
        "footage": {"w": 60, "h": 130},
        "segments": [{"frames": "/takes/a", "ops": [["hold", 1, 1.0]]}],
    }
    e.update(over)
    return e


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="compose-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write_edit(self, data, name="edit.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compose.main(list(argv))
        return code, out.getvalue(), err.getvalue()


class SchemaTests(Base):
    def test_schema_uses_only_what_is_checked(self):
        self.assertEqual(schema.unsupported(jsonio.load(compose.SCHEMA)), [])

    def test_example_is_valid(self):
        self.assertEqual(schema.validate(jsonio.load(EXAMPLE), jsonio.load(compose.SCHEMA)), [])

    def test_example_resolves(self):
        e = compose.load_edit(EXAMPLE)
        frames, marks = compose.timeline(e)
        secs = len(frames) / 30.0
        self.assertTrue(compose.MIN_SECONDS <= secs <= compose.MAX_SECONDS, secs)
        self.assertEqual(sorted(marks), sorted(["open", "plan", "drag", "recipe", "card", "shop", "end"]))

    def test_rejects_unknown_op_and_field(self):
        bad = edit(segments=[{"frames": "a", "ops": [["jump", 1]]}])
        self.assertTrue(schema.validate(bad, jsonio.load(compose.SCHEMA)))
        bad = edit(colour="red")
        self.assertTrue(schema.validate(bad, jsonio.load(compose.SCHEMA)))
        bad = edit(overlays=[{"kind": "headline", "lines": ["x"], "in": "@a+b", "out": 2}])
        self.assertTrue(schema.validate(bad, jsonio.load(compose.SCHEMA)))

    def test_load_edit_makes_paths_absolute(self):
        path = self.write_edit(edit(segments=[{"frames": "takes/a", "ops": [["hold", 1, 1]]}],
                                    style="design/style.json"))
        e = compose.load_edit(path)
        self.assertEqual(e["segments"][0]["frames"], os.path.join(self.tmp, "takes", "a"))
        self.assertTrue(os.path.isabs(e["style"]))
        path = self.write_edit(edit(theme={"fontSrc": "fonts/Sans.ttf"}, end={"in": 0, "name": "x", "mark": "icon.png"}))
        e = compose.load_edit(path)
        self.assertEqual(e["theme"]["fontSrc"], os.path.join(self.tmp, "fonts", "Sans.ttf"))
        self.assertEqual(e["end"]["mark"], os.path.join(self.tmp, "icon.png"))

    def test_load_edit_invalid(self):
        path = self.write_edit({"name": "x"})
        with self.assertRaises(compose.EditError):
            compose.load_edit(path)


class FrameTests(unittest.TestCase):
    def test_hold_and_play(self):
        e = edit(segments=[{"frames": "/a", "ops": [["hold", 3, 0.5], ["play", 4, 6]]}])
        frames, _ = compose.build_frames(e)
        self.assertEqual([os.path.basename(f["a"]) for f in frames],
                         ["frame-00003.png"] * 5 + ["frame-00004.png", "frame-00005.png", "frame-00006.png"])
        self.assertTrue(all(f["b"] is None and f["mix"] == 0 for f in frames))

    def test_play_step(self):
        e = edit(segments=[{"frames": "/a", "ops": [["play", 1, 7, 2]]}])
        frames, _ = compose.build_frames(e)
        self.assertEqual([f["a"][-9:-4] for f in frames], ["00001", "00003", "00005", "00007"])

    def test_hold_is_at_least_one_frame(self):
        e = edit(segments=[{"frames": "/a", "ops": [["hold", 1, 0.01]]}])
        self.assertEqual(len(compose.build_frames(e)[0]), 1)

    def test_marks_and_dissolve_overlap(self):
        e = edit(segments=[
            {"frames": "/a", "ops": [["mark", "start"], ["hold", 1, 2.0]]},
            {"dissolve": 0.5},
            {"frames": "/b", "ops": [["mark", "next"], ["play", 1, 10], ["mark", "late"], ["hold", 10, 1.0]]},
        ])
        frames, marks = compose.build_frames(e)
        # 20 + 10 + 10 frames, 5 of them overlapping
        self.assertEqual(len(frames), 35)
        self.assertEqual(marks["start"], 0.0)
        self.assertAlmostEqual(marks["next"], 1.5)          # the next segment starts inside the dissolve
        self.assertAlmostEqual(marks["late"], 2.5)
        mixing = [f for f in frames if f["b"]]
        self.assertEqual(len(mixing), 5)
        self.assertEqual([round(f["mix"], 3) for f in mixing], [round(k / 6.0, 3) for k in range(1, 6)])
        self.assertTrue(all(f["a"].startswith("/a/") and f["b"].startswith("/b/") for f in mixing))
        self.assertTrue(frames[20]["a"].startswith("/b/"))
        self.assertTrue(all("slide" not in f for f in frames))

    def test_slide_holds_the_outgoing_screen(self):
        e = edit(segments=[
            {"frames": "/a", "ops": [["play", 1, 20]]},
            {"slide": 0.4, "shift": 500},
            {"frames": "/b", "footage": "inner", "ops": [["play", 1, 10]]},
        ])
        frames, _ = compose.build_frames(e)
        sliding = [f for f in frames if f.get("slide") is not None]
        self.assertEqual(len(sliding), 4)
        self.assertTrue(all(f["a"].endswith("frame-00016.png") for f in sliding))   # held, not still playing
        self.assertEqual([f["b"][-9:-4] for f in sliding], ["00001", "00002", "00003", "00004"])
        self.assertTrue(all(f["shift"] == 500 and f["fb"] == "inner" and f["fa"] == "main" for f in sliding))
        self.assertEqual(sliding[0]["slide"], 0.2)
        self.assertEqual(frames[-1]["fa"], "inner")

    def test_unknown_op(self):
        with self.assertRaises(compose.EditError):
            compose.build_frames(edit(segments=[{"frames": "/a", "ops": [["jump", 1]]}]))


class TimeTests(unittest.TestCase):
    marks = {"a": 2.0, "b.c": 5.5}

    def test_resolve(self):
        self.assertEqual(compose.resolve(1.25, self.marks), 1.25)
        self.assertEqual(compose.resolve("@a", self.marks), 2.0)
        self.assertEqual(compose.resolve("@a+0.5", self.marks), 2.5)
        self.assertEqual(compose.resolve("@b.c-1.5", self.marks), 4.0)

    def test_resolve_unknown_mark(self):
        with self.assertRaises(compose.EditError) as cm:
            compose.resolve("@nope", self.marks)
        self.assertIn("nope", str(cm.exception))
        with self.assertRaises(compose.EditError):
            compose.resolve("soon", self.marks)

    def test_keys_must_run_forward(self):
        e = edit(camera=[[0, 0], ["@a", 1], [1.0, 0]])
        with self.assertRaises(compose.EditError):
            compose.resolve_times(e, self.marks)

    def test_overlay_must_end_after_it_starts(self):
        e = edit(overlays=[{"kind": "headline", "lines": ["x"], "in": "@a+1", "out": "@a"}])
        with self.assertRaises(compose.EditError):
            compose.resolve_times(e, self.marks)

    def test_camera_and_pan_ends_and_middle(self):
        keys = [[1.0, 0.0], [3.0, 1.0]]
        self.assertEqual(compose.camera_at(keys, 0.0), 0.0)
        self.assertEqual(compose.camera_at(keys, 1.0), 0.0)
        self.assertAlmostEqual(compose.camera_at(keys, 2.0), 0.5)
        self.assertEqual(compose.camera_at(keys, 9.0), 1.0)
        self.assertLess(compose.camera_at(keys, 1.3), 0.3 / 2)   # eased: slow out of a key
        pan = [[0, 0.0], [1, -400.0]]
        self.assertEqual(compose.pan_at(pan, 0), 0.0)
        self.assertEqual(compose.pan_at(pan, 1), -400.0)
        self.assertAlmostEqual(compose.pan_at(pan, 0.5), -200.0)


class SpotlightTests(unittest.TestCase):
    o = {"kind": "spotlight", "rect": [100, 200, 300, 120], "r": 24, "pad": 16, "dim": 0.4, "in": 1.0, "out": 4.0}

    def test_off_outside_its_time(self):
        self.assertIsNone(compose.spotlight_at(self.o, 0.5))
        self.assertIsNone(compose.spotlight_at(self.o, 4.0))

    def test_settled_hole_is_concentric(self):
        s = compose.spotlight_at(self.o, 2.5)
        self.assertAlmostEqual(s["alpha"], 1.0, places=3)
        pad = 16 + (1 - s["alpha"]) * compose.SPOT_SETTLE
        # an even margin on every side, and the corners concentric with the element's own
        self.assertAlmostEqual(100 - s["x"], pad)
        self.assertAlmostEqual(200 - s["y"], pad)
        self.assertAlmostEqual((s["x"] + s["w"]) - 400, pad)
        self.assertAlmostEqual((s["y"] + s["h"]) - 320, pad)
        self.assertAlmostEqual(s["r"], 24 + pad)
        self.assertEqual(s["dim"], 0.4)

    def test_closes_in_as_it_fades_in(self):
        early, late = compose.spotlight_at(self.o, 1.05), compose.spotlight_at(self.o, 1.6)
        self.assertLess(early["alpha"], late["alpha"])
        self.assertGreater(early["w"], late["w"])
        self.assertLessEqual(early["w"], 300 + 2 * (16 + compose.SPOT_SETTLE))


class TimelineTests(unittest.TestCase):
    def test_each_frame_has_camera_pan_and_spot(self):
        e = edit(
            footages={"inner": {"w": 120, "h": 110, "frame": "foldable-inner", "pan": True}},
            segments=[{"frames": "/a", "ops": [["mark", "s"], ["hold", 1, 2.0]]},
                      {"slide": 0.5},
                      {"frames": "/b", "footage": "inner", "ops": [["hold", 1, 2.0]]}],
            camera=[[0, 0], [1.0, 1]],
            pan=[["@s+2", 0], ["@s+3", -300]],
            overlays=[{"kind": "spotlight", "rect": [10, 10, 40, 20], "in": 0.2, "out": 3.5}])
        frames, marks = compose.timeline(e)
        self.assertEqual(len(frames), 35)
        self.assertEqual(frames[0]["k"], 0.0)
        self.assertEqual(frames[12]["k"], 1.0)
        self.assertIsNotNone(frames[12]["spot"])
        self.assertIsNone(frames[-1]["spot"])                      # a panned footage takes no spotlight
        self.assertAlmostEqual(frames[-1]["pan"], -300.0)
        g = e["footages"]["inner"]["frameGeometry"]
        self.assertEqual(g, {"bezel": round(0.028 * 110), "radius": round(0.05 * 110)})
        self.assertEqual(e["footages"]["main"]["frame"], "phone")
        self.assertEqual(e["footages"]["main"]["frameGeometry"], {"bezel": 2, "radius": 7})

    def test_frame_none_draws_no_bezel(self):
        self.assertEqual(compose.frame_geometry({"w": 100, "h": 200, "frame": "none"}), {"bezel": 0, "radius": 0})


class ThemeTests(Base):
    def test_defaults(self):
        t = compose.theme_of(edit())
        self.assertEqual(t["background"], compose.DEFAULT_THEME["background"])
        self.assertIsNone(t["backgroundImage"])

    def test_from_a_style_with_its_relative_paths(self):
        os.makedirs(os.path.join(self.tmp, "design", "baseline"))
        os.makedirs(os.path.join(self.tmp, "fonts"))
        os.makedirs(os.path.join(self.tmp, "art"))
        open(os.path.join(self.tmp, "fonts", "Sans.ttf"), "wb").close()
        open(os.path.join(self.tmp, "art", "bg.png"), "wb").close()
        style = os.path.join(self.tmp, "design", "baseline", "screenshot-style.json")
        with open(style, "w") as f:
            json.dump({"version": 1, "name": "s", "theme": {
                "palette": {"background": "#102030", "accent": "#FFAA00"},
                "fonts": [{"family": "Sans", "src": "fonts/Sans.ttf", "weight": 600}],
                "background": {"kind": "image", "src": "art/bg.png"}}}, f)
        t = compose.theme_of(edit(style=style, theme={"ink": "#EEEEEE"}))
        self.assertEqual(t["background"], "#102030")
        self.assertEqual(t["accent"], "#FFAA00")
        self.assertEqual(t["ink"], "#EEEEEE")                          # the edit's theme over the style
        self.assertEqual(t["background2"], compose.DEFAULT_THEME["background2"])
        self.assertEqual(t["font"], "Sans")
        self.assertEqual(t["fontWeight"], 600)
        self.assertTrue(t["fontSrc"].startswith("file://") and t["fontSrc"].endswith("/fonts/Sans.ttf"))
        self.assertTrue(t["backgroundImage"].endswith("/art/bg.png"))

    def test_style_root_first(self):
        root = os.path.join(self.tmp, "root")
        os.makedirs(os.path.join(root, "art"))
        open(os.path.join(root, "art", "bg.png"), "wb").close()
        style = os.path.join(self.tmp, "style.json")
        with open(style, "w") as f:
            json.dump({"version": 1, "name": "s", "theme": {"background": {"kind": "image", "src": "art/bg.png"}}}, f)
        t = compose.theme_of(edit(style=style, styleRoot=root))
        self.assertIn("/root/art/bg.png", t["backgroundImage"])

    def test_unreadable_style(self):
        with self.assertRaises(compose.EditError):
            compose.theme_of(edit(style=os.path.join(self.tmp, "missing.json")))


class CliTests(Base):
    def test_dry_run(self):
        make_take(os.path.join(self.tmp, "takes", "a"), 12)
        path = self.write_edit(edit(fps=30, segments=[{"frames": "takes/a", "ops": [["hold", 1, 15.0], ["play", 1, 12]]}]))
        code, out, err = self.run_main(path, "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("462 frames, 15.40 s", out)
        self.assertNotIn("warning", out)

    def test_dry_run_warns_on_length(self):
        make_take(os.path.join(self.tmp, "takes", "a"), 2)
        path = self.write_edit(edit(segments=[{"frames": "takes/a", "ops": [["hold", 1, 3.0]]}]))
        code, out, _ = self.run_main(path, "--dry-run", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["frames"], 30)
        code, out, _ = self.run_main(path, "--dry-run")
        self.assertIn("outside the stores' 15-30 s", out)

    def test_invalid_edit_exits_3(self):
        code, _, err = self.run_main(self.write_edit({"name": "x"}), "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("schema", err)

    def test_missing_frames_exit_3(self):
        make_take(os.path.join(self.tmp, "takes", "a"), 3)
        path = self.write_edit(edit(segments=[{"frames": "takes/a", "ops": [["play", 1, 5]]}]))
        code, _, err = self.run_main(path, "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("2 frame file(s) missing", err)

    def test_unknown_mark_exits_3(self):
        make_take(os.path.join(self.tmp, "takes", "a"), 1)
        path = self.write_edit(edit(segments=[{"frames": "takes/a", "ops": [["hold", 1, 1]]}], endOut="@gone"))
        code, _, err = self.run_main(path, "--dry-run")
        self.assertEqual(code, 3)
        self.assertIn("gone", err)

    def test_frames_out_of_range_exit_3(self):
        make_take(os.path.join(self.tmp, "takes", "a"), 1)
        path = self.write_edit(edit(segments=[{"frames": "takes/a", "ops": [["hold", 1, 1]]}]))
        code, _, err = self.run_main(path, "--frames", "0,99", "--stills")
        self.assertEqual(code, 3)
        self.assertIn("99", err)


@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class RenderTests(Base):
    def small_edit(self):
        a = make_take(os.path.join(self.tmp, "takes", "a"), 4, colour=(230, 240, 250))
        b = make_take(os.path.join(self.tmp, "takes", "b"), 4, colour=(250, 220, 200))
        self.assertTrue(a and b)
        return edit(
            fps=10,
            footage={"w": 60, "h": 130, "frame": "phone", "full": 1.6, "float": {"scale": 1.0, "cy": 1100}},
            segments=[{"frames": "takes/a", "ops": [["mark", "s"], ["hold", 1, 1.0], ["play", 1, 4]]},
                      {"slide": 0.4},
                      {"frames": "takes/b", "ops": [["play", 1, 4], ["mark", "end"], ["hold", 4, 1.0]]}],
            camera=[[0, 0], [0.6, 1]],
            overlays=[{"kind": "headline", "lines": ["Plan the", "[whole week]"], "in": 0, "out": 1.2},
                      {"kind": "touch", "at": [30, 60], "in": 0.2, "press": 0.4, "out": 1.0},
                      {"kind": "spotlight", "rect": [5, 50, 50, 30], "r": 6, "pad": 3, "in": 0.1, "out": 1.3}],
            endOut="@end",
            end={"in": "@end+0.2", "name": "Sample Recipes", "by": "by Example Studio",
                 "tagLines": ["A week of meals"], "fine": "Sign-in required."})

    def test_stills(self):
        path = self.write_edit(self.small_edit())
        out = os.path.join(self.tmp, "out")
        code, _, err = self.run_main(path, "--out", out, "--frames", "0,5,12,20", "--stills")
        self.assertEqual(code, 0, err)
        for i in (0, 5, 12, 20):
            info = png.info(os.path.join(out, "t", "still-%05d.png" % i))
            self.assertEqual((info.width, info.height), (886, 1920))

    def test_master(self):
        if not compose.find_ffmpeg():
            self.skipTest("needs ffmpeg")
        path = self.write_edit(self.small_edit())
        out = os.path.join(self.tmp, "out")
        code, out_text, err = self.run_main(path, "--out", out)
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.getsize(os.path.join(out, "t-master.mp4")) > 0)
        self.assertEqual(len([n for n in os.listdir(os.path.join(out, "t")) if n.endswith(".jpg")]), 24)


if __name__ == "__main__":
    unittest.main()
