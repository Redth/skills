"""Tests for render.py: the config and its resolution (no Chrome needed), then rendering through headless Chrome
(skipped where no Chrome is installed): every layout at every aspect class, captions shrinking to their floor,
hyphenation, right-to-left, panoramas, the cache, fallbacks and upscaling.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here reaches a network.
"""

from __future__ import annotations

import contextlib
import copy
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render  # noqa: E402
import render_testkit as kit  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from appstores_lib import schema  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None

BROWSER = None


def setUpModule():
    global BROWSER
    if CHROME:
        BROWSER = chrome.Chrome()
        BROWSER.start()


def tearDownModule():
    if BROWSER:
        BROWSER.close()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="render-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def project(self, cfg=None, captures=None, name="p"):
        return kit.make_project(os.path.join(self.tmp, name), cfg, captures)

    def run_render(self, config, **kw):
        lines = []
        code, report = render.run(config, browser=BROWSER, log=lines.append, **kw)
        return code, report, lines

    def entry(self, report, path):
        for f in report["files"]:
            if f["path"] == path:
                return f
        self.fail("no %s in the report: %s" % (path, [f["path"] for f in report["files"]]))


# ------------------------------------------------------------------------------------------------ no Chrome

class ConfigTests(Base):
    def test_schema_uses_only_supported_keywords(self):
        self.assertEqual(schema.unsupported(render.load_schema()), [])

    def test_eval_fixtures_and_sample_validate(self):
        paths = glob.glob(os.path.join(kit.FILES, "*", "store-screenshots.json"))
        self.assertTrue(paths)
        for p in paths:
            with self.subTest(p=os.path.relpath(p, kit.FILES)):
                render.load_config(p)

    def test_system_fonts_need_no_caption_font(self):
        cfg = kit.base_config()
        cfg["theme"]["fonts"] = []
        cfg["theme"]["caption"].pop("font", None)
        render.load_config(self.project(cfg))

    def test_invalid_config_is_usage(self):
        cfg = kit.base_config()
        cfg["shots"][0]["layout"] = "spiral"
        path = self.project(cfg)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(render.main(["--config", path]), render.EXIT_USAGE)
        self.assertIn("layout", err.getvalue())

    def test_missing_config_is_usage(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(render.main(["--config", os.path.join(self.tmp, "nope.json")]), render.EXIT_USAGE)

    def test_unknown_frame_and_target_names_are_usage(self):
        cfg = kit.base_config()
        cfg["theme"]["frame"] = "brick"
        with self.assertRaises(render.UsageError):
            render.load_config(self.project(cfg))
        cfg = kit.base_config()
        cfg["shots"][0]["targets"] = ["tablet"]
        with self.assertRaises(render.UsageError):
            render.load_config(self.project(cfg, name="q"))

    def test_no_chrome_is_usage(self):
        path = self.project()
        with mock.patch.dict(os.environ, {"CHROME": os.path.join(self.tmp, "no-chrome")}):
            with contextlib.redirect_stderr(io.StringIO()) as err, contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(render.main(["--config", path]), render.EXIT_USAGE)
        self.assertIn("CHROME", err.getvalue())

    def test_precedence_target_beats_store_beats_shot_beats_theme(self):
        cfg = kit.base_config()
        cfg["theme"]["frame"] = "phone"
        cfg["theme"]["caption"]["sizePct"] = 8.0
        cfg["shots"][0].update({"layout": "framed", "frame": "tablet"})
        cfg["targets"]["play"] = {"store": "google", "width": 300, "height": 650, "capture": "phone"}
        cfg["targets"]["solo"] = {"store": "google", "width": 300, "height": 650, "capture": "phone",
                                  "layout": "band", "frame": "watch", "caption": {"sizePct": 7.0}}
        cfg["stores"]["google"] = {"frame": "none", "layout": "fullbleed", "caption": {"sizePct": 9.0}}
        res = render.Resolver(cfg, os.path.join(self.tmp, "x.json"))
        shot = cfg["shots"][0]
        apple = res.settings(shot, "phone")
        self.assertEqual((apple["layout"], apple["frame"], apple["style"]["sizePct"]), ("framed", "tablet", 8.0))
        store = res.settings(shot, "play")
        self.assertEqual((store["layout"], store["frame"], store["style"]["sizePct"]), ("fullbleed", "none", 9.0))
        target = res.settings(shot, "solo")
        self.assertEqual((target["layout"], target["frame"], target["style"]["sizePct"]), ("band", "watch", 7.0))
        cfg["stores"]["google"]["caption"] = False
        self.assertFalse(res.settings(shot, "play")["words"])

    def test_string_and_capture_fallbacks_resolve(self):
        cfg = kit.base_config()
        cfg["locales"] = ["en-US", "de-DE"]
        cfg["shots"][0]["kicker"] = "brand"
        cfg["strings"] = {"en-US": {"cap.plan": "Plan meals", "brand": "Sample Recipes"},
                          "de-DE": {"cap.plan": "Essen planen"}}
        path = self.project(cfg)
        res = render.Resolver(render.load_config(path), path)
        units = res.units(locales=["de-DE"])
        self.assertEqual(len(units), 1)
        u = units[0]
        self.assertEqual(u["fallbacks"]["strings"], ["brand"])
        self.assertEqual(u["fallbacks"]["captures"], [os.path.join("captures", "en-US", "phone", "plan.png")])
        self.assertEqual(u["job"]["slots"][0]["caption"]["text"], "Essen planen")

    def test_frame_variant_follows_the_capture_shape(self):
        res = render.Resolver(kit.base_config(), os.path.join(self.tmp, "x.json"))
        self.assertEqual(res.frame("phone", (2000, 900))["name"], "phone-landscape")
        self.assertEqual(res.frame("tablet-landscape", (900, 1200))["name"], "tablet")
        self.assertIsNone(res.frame("none", (100, 200)))

    def test_frames_are_generic_and_complete(self):
        names = render.builtin_frames()
        for n in ("phone", "phone-landscape", "tablet", "tablet-landscape", "laptop", "desktop", "tv", "watch"):
            self.assertIn(n, names)
            meta = jsonio.load(os.path.join(render.FRAMES_DIR, n + ".json"))
            self.assertTrue(meta["drawn"])
            self.assertIsNone(meta["maker"])
            s, vb = meta["screen"], meta["viewBox"]
            self.assertTrue(0 <= s["x"] and s["x"] + s["width"] <= vb[2] and s["y"] + s["height"] <= vb[3], n)
            with open(os.path.join(render.FRAMES_DIR, n + ".svg"), encoding="utf-8") as f:
                svg = f.read()
            self.assertIn('class="s"', svg)

    def test_rtl_languages(self):
        self.assertTrue(render.is_rtl("ar-SA"))
        self.assertTrue(render.is_rtl("he"))
        self.assertFalse(render.is_rtl("de-DE"))
        self.assertEqual([render.aspect_class(*s) for s in ((1320, 2868), (2064, 2752), (400, 400), (1920, 1080))],
                         ["tall", "mid", "square", "wide"])


# ------------------------------------------------------------------------------------------------ Chrome

@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class RenderTests(Base):
    SIZES = {"tall": (300, 650), "mid": (450, 600), "square": (400, 400), "wide": (640, 360)}

    def test_every_layout_at_every_aspect_class(self):
        cfg = kit.base_config()
        cfg["targets"] = {name: {"store": "apple", "width": w, "height": h, "capture": "dev-" + name}
                          for name, (w, h) in self.SIZES.items()}
        cfg["shots"] = []
        for layout in render.LAYOUTS:
            shot = {"id": layout, "capture": "screen", "layout": layout, "caption": "cap", "kicker": "kick",
                    "proof": "proof"}
            if layout == "callout":
                shot["callout"] = {"rect": [0.05, 0.3, 0.9, 0.08], "scale": 1.3}
            if layout == "pair":
                shot["pair"] = "second"
            if layout == "tilt":
                shot["tilt"] = "right"
            cfg["shots"].append(shot)
        cfg["strings"] = {"en-US": {"cap": "Plan your week", "kick": "Sample Recipes", "proof": "Lists in one place"}}
        captures = {}
        for name, (w, h) in self.SIZES.items():
            for screen in ("screen", "second"):
                captures["en-US/dev-%s/%s" % (name, screen)] = (w * 2, h * 2)   # never upscaled
        code, report, lines = self.run_render(self.project(cfg, captures))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        self.assertEqual(len(report["files"]), len(render.LAYOUTS) * len(self.SIZES))
        out = os.path.join(self.tmp, "p", "out")
        for f in report["files"]:
            with self.subTest(path=f["path"]):
                meta = png.info(os.path.join(out, f["path"]))
                self.assertEqual((meta.width, meta.height), (f["width"], f["height"]))
                self.assertEqual(meta.color_type, 2)
                self.assertFalse(meta.has_alpha)
                self.assertEqual(f["aspectClass"], f["target"])
                self.assertLessEqual(f["captureScale"], 1.0)
                if f["layout"] == "gameplay":
                    self.assertIsNone(f["caption"])
                else:
                    self.assertTrue(f["caption"]["fits"], f["caption"])
                    self.assertEqual(f["caption"]["text"], "Plan your week")
                    self.assertGreater(f["caption"]["textShare"], 0)
                    self.assertEqual(f["caption"]["missingGlyphs"], [])
                if f["layout"] in ("framed", "framed-bleed", "tilt", "pair", "callout", "hero"):
                    self.assertEqual(f["frame"]["kind"], "drawn")
                    self.assertTrue(f["frame"]["name"].startswith("phone"))
                if f["layout"] == "pair":
                    self.assertEqual(len(f["frames"]), 2)
                if f["layout"] == "callout":
                    self.assertIsNotNone(f["callout"])
                    self.assertGreater(f["callout"]["box"][2], 0)
                if f["layout"] == "tilt":
                    self.assertTrue(f["frame"]["tilted"])
                if f["layout"] == "framed":
                    self.assertFalse(f["frame"]["cropped"])
                if f["layout"] == "framed-bleed":
                    self.assertTrue(f["frame"]["cropped"])

    def test_caption_shrinks_and_reports_its_floor(self):
        cfg = kit.base_config()
        cfg["shots"] = [{"id": "short", "capture": "plan", "caption": "a"},
                        {"id": "longer", "capture": "plan", "caption": "b"},
                        {"id": "toolong", "capture": "plan", "caption": "c"}]
        cfg["strings"] = {"en-US": {"a": "Plan meals", "b": "Plan a whole week of family dinners in just minutes",
                                    "c": "Every recipe you love, organised step by step with timers, notes, "
                                         "photos and a shopping list"}}
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_ERRORS)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "p", "out", "render-report.json")))
        short = self.entry(report, "en-US/phone/short.png")["caption"]
        self.assertEqual(short["fontPx"], short["sizePx"])
        self.assertAlmostEqual(short["sizePx"], 300 * 0.08, places=1)
        self.assertFalse(short["atFloor"])
        longer = self.entry(report, "en-US/phone/longer.png")["caption"]
        self.assertLess(longer["fontPx"], longer["sizePx"])
        self.assertTrue(longer["fits"])
        self.assertLessEqual(longer["lines"], 2)
        too = self.entry(report, "en-US/phone/toolong.png")["caption"]
        self.assertTrue(too["atFloor"])
        self.assertFalse(too["fits"])
        self.assertAlmostEqual(too["fontPx"], too["floorPx"], places=1)
        self.assertTrue(any("doesn't fit" in line for line in lines))

    def test_caption_colours_are_reported(self):
        cfg = kit.base_config()
        cfg["shots"][0].update({"kicker": "k", "proof": "p"})
        cfg["strings"]["en-US"].update({"cap.plan": "Plan *meals* fast", "k": "Brand", "p": "In one place"})
        cfg["shots"].append({"id": "plain", "capture": "plan", "caption": "plain"})
        cfg["strings"]["en-US"]["plain"] = "Plan meals"
        code, report, lines = self.run_render(self.project(cfg))
        cap = self.entry(report, "en-US/phone/plan.png")["caption"]
        self.assertEqual((cap["ink"], cap["accent"]), ("#FFFFFF", "#FFC94D"))
        self.assertEqual(cap["kicker"]["ink"], "#FFC94D")
        self.assertEqual(cap["proof"]["ink"], "#FFFFFF")
        self.assertIsNone(self.entry(report, "en-US/phone/plain.png")["caption"]["accent"])

    LONG_DE = "Lebensmittelvorratsverwaltung leicht gemacht"
    SOFT_DE = "Lebens\u00admittel\u00advorrats\u00adverwaltung leicht gemacht"

    def test_a_long_german_word_hyphenates_or_fits(self):
        cfg = kit.base_config()
        cfg["locales"] = ["en-US", "de-DE"]
        cfg["strings"]["de-DE"] = {"cap.plan": self.LONG_DE}
        code, report, lines = self.run_render(self.project(cfg), locales=["de-DE"])
        cap = self.entry(report, "de-DE/phone/plan.png")["caption"]
        if cap["hyphenationAvailable"]:
            self.assertEqual(code, render.EXIT_OK, "\n".join(lines) + json.dumps(cap))
            self.assertTrue(cap["fits"])
            self.assertTrue(cap["hyphenated"] or cap["fontPx"] < cap["sizePx"])
            self.assertLessEqual(cap["box"][0] + cap["box"][2], 300)
            self.assertGreaterEqual(cap["box"][0], 0)
            return
        # This Chrome has no German dictionary (Linux builds often don't): the message says what to do, and the
        # same words with soft hyphens at the break points fit.
        self.assertIs(cap["hyphenationAvailable"], False)
        self.assertEqual(code, render.EXIT_ERRORS)
        self.assertTrue(any("this Chrome can't hyphenate de" in line and "soft hyphens" in line for line in lines),
                        lines)
        cfg["strings"]["de-DE"] = {"cap.plan": self.SOFT_DE}
        code, report, lines = self.run_render(self.project(cfg, name="soft"), locales=["de-DE"])
        cap = self.entry(report, "de-DE/phone/plan.png")["caption"]
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines) + json.dumps(cap))
        self.assertTrue(cap["fits"])

    def test_no_dictionary_says_to_add_soft_hyphens(self):
        # A language no Chrome has a hyphenation dictionary for: the probe says so on every platform.
        cfg = kit.base_config()
        cfg["locales"] = ["en-US", "zz-ZZ"]
        cfg["strings"]["zz-ZZ"] = {"cap.plan": "Plimbarovastikulanderiomentaz voka"}
        code, report, lines = self.run_render(self.project(cfg), locales=["zz-ZZ"])
        cap = self.entry(report, "zz-ZZ/phone/plan.png")["caption"]
        self.assertIs(cap["hyphenationAvailable"], False)
        self.assertFalse(cap["fits"])
        self.assertEqual(code, render.EXIT_ERRORS)
        self.assertTrue(any("this Chrome can't hyphenate zz: add soft hyphens" in line for line in lines), lines)
        cfg["strings"]["zz-ZZ"] = {"cap.plan": "Plimba&shy;rovasti&shy;kulande&shy;riomentaz voka"}
        code, report, lines = self.run_render(self.project(cfg, name="soft"), locales=["zz-ZZ"])
        cap = self.entry(report, "zz-ZZ/phone/plan.png")["caption"]
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines) + json.dumps(cap))
        self.assertTrue(cap["fits"] and cap["softHyphens"])
        self.assertEqual(cap["text"], "Plimbarovastikulanderiomentaz voka")

    def test_soft_hyphens_break_even_where_hyphenation_works(self):
        # Hyphenation (where this Chrome has it for English) finds no break in a word without vowels: the soft
        # hyphens are what break it.
        cfg = kit.base_config()
        cfg["shots"] = [{"id": "plain", "capture": "plan", "caption": "a"},
                        {"id": "soft", "capture": "plan", "caption": "b"}]
        cfg["strings"]["en-US"] = {"a": "Mmmmmmmmmmmmmmmmmmmmmm",
                                   "b": "Mmmmmmmmmmm\u00admmmmmmmmmmm"}
        code, report, lines = self.run_render(self.project(cfg))
        plain = self.entry(report, "en-US/phone/plain.png")["caption"]
        soft = self.entry(report, "en-US/phone/soft.png")["caption"]
        self.assertFalse(plain["fits"])
        self.assertTrue(soft["fits"], soft)
        self.assertTrue(soft["softHyphens"])
        self.assertEqual(soft["text"], "Mmmmmmmmmmmmmmmmmmmmmm")
        self.assertEqual(soft["missingGlyphs"], [])
        self.assertGreater(soft["lines"], 1)

    def test_right_to_left_mirrors_the_layout(self):
        cfg = kit.base_config()
        cfg["locales"] = ["en-US", "he-IL"]
        cfg["theme"]["caption"]["align"] = "start"
        cfg["shots"] = [{"id": "pair", "capture": "plan", "layout": "pair", "pair": "second", "caption": "c"}]
        cfg["strings"] = {"en-US": {"c": "Plan your week"}, "he-IL": {"c": "תכננו את השבוע"}}
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        en = self.entry(report, "en-US/phone/pair.png")
        he = self.entry(report, "he-IL/phone/pair.png")
        self.assertEqual((en["dir"], he["dir"]), ("ltr", "rtl"))
        ex, _, ew, _ = en["caption"]["box"]
        hx, _, hw, _ = he["caption"]["box"]
        self.assertLess(ex, 300 - (ex + ew))            # English hugs the left margin
        self.assertLess(300 - (hx + hw), hx)            # Hebrew hugs the right
        self.assertLess(abs(ex - (300 - (hx + hw))), 6)
        main_en = [f for f in en["frames"] if f["role"] == "main"][0]["box"]
        main_he = [f for f in he["frames"] if f["role"] == "main"][0]["box"]
        self.assertLess(main_en[0], main_he[0])         # the main device moves to the other side
        self.assertEqual(he["caption"]["missingGlyphs"], [])

    def test_panorama_slots_line_up_across_seams(self):
        cfg = kit.base_config()
        cfg["theme"]["background"] = {"kind": "gradient", "angle": 100}
        cfg["theme"]["palette"]["background2"] = "#E8B04A"
        cfg["shots"] = [{"id": i, "capture": "plan", "layout": "framed-bleed", "caption": "c"} for i in ("a", "b", "c")]
        cfg["strings"] = {"en-US": {"c": "Plan"}}
        cfg["panorama"] = {"shots": ["a", "b", "c"], "background": None, "seam": 6}
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        a, b, c = (self.entry(report, "en-US/phone/%s.png" % i) for i in "abc")
        self.assertEqual([s["edge"] for s in a["seams"]], ["right"])
        self.assertEqual([s["edge"] for s in b["seams"]], ["left", "right"])
        self.assertEqual([s["edge"] for s in c["seams"]], ["left"])
        self.assertTrue(all(s["clear"] for s in a["seams"] + b["seams"] + c["seams"]), b["seams"])
        self.assertEqual(b["panorama"], {"shots": ["a", "b", "c"], "index": 1, "seam": 6})
        out = os.path.join(self.tmp, "p", "out", "en-US", "phone")
        wa, ha, ra = png.decode_rgb(os.path.join(out, "a.png"))
        wb, hb, rb = png.decode_rgb(os.path.join(out, "b.png"))
        left = kit.column(ra, wa, ha, wa - 1, 0, ha // 3)
        right = kit.column(rb, wb, hb, 0, 0, ha // 3)
        steps = kit.column(ra, wa, ha, wa - 2, 0, ha // 3)
        diff = sum(abs(p - q) for x, y in zip(left, right) for p, q in zip(x, y)) / (3.0 * len(left))
        within = sum(abs(p - q) for x, y in zip(steps, left) for p, q in zip(x, y)) / (3.0 * len(left))
        self.assertLess(diff, within + 2.5)             # the picture continues across the seam
        far = kit.column(rb, wb, hb, wb - 1, 0, ha // 3)
        moved = sum(abs(p - q) for x, y in zip(right, far) for p, q in zip(x, y)) / (3.0 * len(left))
        self.assertGreater(moved, diff + 5)             # and isn't just a flat colour

    @unittest.skipUnless(sys.platform == "darwin", "which characters draw as a missing-glyph box depends on the fonts")
    def test_missing_glyphs_are_reported(self):
        cfg = kit.base_config()
        cfg["strings"]["en-US"]["cap.plan"] = "Plan \u0378 meals"
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(self.entry(report, "en-US/phone/plan.png")["caption"]["missingGlyphs"], ["\u0378"])
        self.assertTrue(any("doesn't draw" in line for line in lines))

    def test_unchanged_files_come_from_the_cache(self):
        cfg = kit.base_config()
        cfg["shots"].append({"id": "recipe", "capture": "plan", "layout": "framed", "caption": "cap.recipe"})
        cfg["strings"]["en-US"]["cap.recipe"] = "Every recipe"
        path = self.project(cfg)
        code, first, _ = self.run_render(path)
        self.assertEqual((code, first["rendered"]), (0, 2))
        code, second, _ = self.run_render(path)
        self.assertEqual((second["rendered"], second["unchanged"]), (0, 2))
        self.assertEqual(second["inputsSha256"], first["inputsSha256"])
        cfg["strings"]["en-US"]["cap.recipe"] = "Every recipe, step by step"
        with open(path, "w") as f:
            json.dump(cfg, f)
        code, third, _ = self.run_render(path)
        self.assertEqual((third["rendered"], third["unchanged"]), (1, 1))
        self.assertNotEqual(third["inputsSha256"], first["inputsSha256"])
        code, forced, _ = self.run_render(path, force=True)
        self.assertEqual(forced["rendered"], 2)
        os.unlink(os.path.join(self.tmp, "p", "out", "en-US", "phone", "plan.png"))
        code, again, _ = self.run_render(path)
        self.assertEqual(again["rendered"], 1)

    def test_fallbacks_are_reported(self):
        cfg = kit.base_config()
        cfg["locales"] = ["en-US", "de-DE"]
        cfg["shots"][0]["proof"] = "proof"
        cfg["shots"].append({"id": "recipe", "capture": "recipe", "caption": "cap.plan"})
        cfg["strings"] = {"en-US": {"cap.plan": "Plan meals", "proof": "In one place"},
                          "de-DE": {"cap.plan": "Essen planen"}}
        captures = {"en-US/phone/plan": (300, 650), "en-US/phone/recipe": (300, 650),
                    "de-DE/phone/recipe": (300, 650)}
        code, report, lines = self.run_render(self.project(cfg, captures))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        plan = self.entry(report, "de-DE/phone/plan.png")
        self.assertTrue(plan["captureFallback"])
        self.assertTrue(plan["stringFallback"])
        self.assertEqual(plan["fallbacks"]["strings"], ["proof"])
        self.assertEqual(plan["capture"], os.path.join("captures", "en-US", "phone", "plan.png"))
        recipe = self.entry(report, "de-DE/phone/recipe.png")
        self.assertFalse(recipe["captureFallback"])
        self.assertFalse(recipe["stringFallback"])
        self.assertFalse(self.entry(report, "en-US/phone/plan.png")["captureFallback"])
        self.assertTrue(any(line.startswith("fallback:") and "proof" in line for line in lines))

    def test_upscaling_is_reported(self):
        captures = {"en-US/phone/plan": (120, 260)}
        code, report, lines = self.run_render(self.project(captures=captures))
        f = self.entry(report, "en-US/phone/plan.png")
        self.assertGreater(f["captureScale"], 1.5)
        self.assertTrue(any("upscaled" in line for line in lines))

    def test_missing_capture_fails_that_file(self):
        code, report, lines = self.run_render(self.project(captures={}))
        self.assertEqual(code, render.EXIT_ERRORS)
        self.assertEqual(report["files"], [])
        self.assertIn("no capture", report["errors"][0]["error"])

    def test_a_users_own_device_art_is_used_as_it_is(self):
        root = os.path.join(self.tmp, "p")
        art = kit.write_capture(os.path.join(root, "bezels", "my-phone.png"), 340, 700)
        jsonio.dump({"name": "my phone", "drawn": False, "maker": "apple", "viewBox": [0, 0, 340, 700],
                     "screen": {"x": 20, "y": 20, "width": 300, "height": 660}, "screenRadius": 30},
                    os.path.join(root, "bezels", "my-phone.json"))
        cfg = kit.base_config()
        cfg["theme"]["frame"] = "bezels/my-phone.png"
        cfg["shots"][0]["layout"] = "framed"
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        frame = self.entry(report, "en-US/phone/plan.png")["frame"]
        self.assertEqual((frame["kind"], frame["drawn"], frame["maker"], frame["name"]),
                         ("art", False, "apple", "bezels/my-phone.png"))
        self.assertFalse(frame["cropped"] or frame["tilted"])
        self.assertTrue(os.path.isfile(art))

    def test_store_overrides_drop_words_and_frames(self):
        cfg = kit.base_config()
        cfg["targets"]["play"] = {"store": "google", "width": 300, "height": 534, "capture": "phone"}
        cfg["stores"]["google"] = {"frame": "none", "caption": False}
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        play = self.entry(report, "en-US/play/plan.png")
        self.assertIsNone(play["caption"])
        self.assertEqual(play["frame"]["kind"], "none")
        self.assertEqual(self.entry(report, "en-US/phone/plan.png")["frame"]["kind"], "drawn")

    def test_the_recipes_eval_fixture_renders(self):
        src = os.path.join(kit.FILES, "recipes")
        dst = os.path.join(self.tmp, "recipes")
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("screenshots"))
        code, report, lines = self.run_render(os.path.join(dst, "store-screenshots.json"))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        self.assertEqual(len(report["files"]), 12)
        for f in report["files"]:
            meta = png.info(os.path.join(dst, "screenshots", f["path"]))
            self.assertEqual((meta.width, meta.height, meta.has_alpha), (f["width"], f["height"], False))


if __name__ == "__main__":
    unittest.main()
