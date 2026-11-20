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
import check_testkit as tk  # noqa: E402
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

    def test_frames_are_fitted_to_the_capture_and_old_names_still_work(self):
        res = render.Resolver(kit.base_config(), os.path.join(self.tmp, "x.json"))
        for name, size in (("phone", (2000, 900)), ("phone-landscape", (1080, 1920)), ("tablet-landscape", (900, 1200)),
                           ("tablet", (2752, 2064)), ("watch", (410, 502)), ("tv", (1920, 1080)),
                           ("laptop", (2880, 1800)), ("desktop", (2560, 1440))):
            with self.subTest(name=name, size=size):
                f = res.frame(name, size)
                meta = f["meta"]
                self.assertEqual((f["kind"], meta["fitted"], meta["drawn"], meta["maker"]), ("svg", True, True, None))
                # The screen opening is the capture's exact size: nothing letterboxed, stretched or cut.
                self.assertEqual((meta["screen"]["width"], meta["screen"]["height"]), size)
                s, vb = meta["screen"], meta["viewBox"]
                self.assertTrue(0 <= s["x"] and s["x"] + s["width"] <= vb[2] and s["y"] + s["height"] <= vb[3])
                self.assertIn('class="screen-back"', f["svg"])
        self.assertIsNone(res.frame("none", (100, 200)))

    def test_a_shots_layout_per_target(self):
        cfg = kit.base_config()
        cfg["targets"]["duo"] = {"store": "apple", "width": 640, "height": 450, "capture": "duo",
                                 "layouts": {"plan": "fold"}}
        res = render.Resolver(render.load_config(self.project(cfg)), os.path.join(self.tmp, "p", "x.json"))
        shot = cfg["shots"][0]
        self.assertEqual(res.settings(shot, "duo")["layout"], "fold")
        self.assertEqual(res.settings(shot, "phone")["layout"], "framed-bleed")
        cfg["targets"]["duo"]["layouts"] = {"nope": "fold"}
        with self.assertRaises(render.UsageError):
            render.load_config(self.project(cfg, name="q"))

    def test_frames_draw_nothing_of_any_makers(self):
        res = render.Resolver(kit.base_config(), os.path.join(self.tmp, "x.json"))
        for store in ("apple", "google"):
            f = res.frame({"name": "phone", "buttons": True, "cutout": "punch-hole"}, (1080, 2400), store)
            hw = f["meta"]["hardware"]
            if store == "apple":
                self.assertEqual((hw["buttons"], hw["cutout"]), (False, None))
                self.assertEqual(sorted(hw["refused"]), ["buttons", "cutout"])
            else:
                self.assertTrue(hw["buttons"])
                self.assertEqual(hw["cutout"]["shape"], "punch-hole")
        plain = res.frame("phone", (1080, 2400), "google")["meta"]["hardware"]
        self.assertEqual((plain["buttons"], plain["cutout"]), (False, None))

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



@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class FitAndFoldTests(Base):
    """Frames fitted to their captures (never clipping one), a maker's art used straight, the fold layout, the
    hero beside its words on wide slots, and the style knobs (tilt angles, caption width, accents across lines)."""

    BAR = (22, 84, 140)

    def corner_capture(self, path, w=540, h=960):
        """A 16:9 capture whose status bar has its clock in the very top-left corner (as Android draws it)."""
        tk.write_png(path, w, h, fill=(244, 246, 250), rects=[(0, 0, w, 34, self.BAR), (6, 4, 40, 14, (255, 255, 255)),
                                                            (w - 44, 6, 36, 12, (255, 255, 255))])
        return path

    def test_a_capture_is_never_clipped_by_the_frames_corners(self):
        cfg = kit.base_config()
        cfg["targets"] = {"play": {"store": "google", "width": 540, "height": 960, "capture": "android"},
                          "round": {"store": "google", "width": 540, "height": 960, "capture": "android",
                                    "frame": {"name": "phone", "class": "phone"}}}
        cfg["stores"]["google"] = {"frame": "phone"}
        root = os.path.join(self.tmp, "p")
        self.corner_capture(os.path.join(root, "captures", "en-US", "android", "plan.png"), 1080, 1920)
        code, report, lines = self.run_render(kit.make_project(root, cfg, captures={}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        play = self.entry(report, "en-US/play/plan.png")["frame"]
        self.assertEqual(play["class"], "phone-classic")   # a 16:9 capture: nearly square corners
        self.assertEqual(play["corners"]["clippedPx"], 0)
        forced = self.entry(report, "en-US/round/plan.png")["frame"]
        self.assertEqual(forced["class"], "phone")
        self.assertTrue(forced["corners"]["reduced"])        # a modern phone's radius would cut the clock: shrunk
        self.assertLess(forced["screenRadius"], forced["corners"]["radiusFrom"])
        self.assertEqual(forced["corners"]["clippedPx"], 0)

    def test_a_makers_art_is_found_and_used_straight(self):
        import test_frames
        root = os.path.join(self.tmp, "p")
        os.makedirs(os.path.join(root, "bezels"))
        test_frames.device_art(os.path.join(root, "bezels", "phone-art.png"), 400, 800, (32, 40, 336, 720), 48)
        cfg = kit.base_config()
        cfg["targets"]["phone"].update({"width": 320, "height": 693})
        cfg["theme"]["frame"] = {"art": "bezels/phone-art.png", "maker": "apple"}
        cfg["shots"][0]["layout"] = "framed"
        code, report, lines = self.run_render(kit.make_project(root, cfg, captures={"en-US/phone/plan": (336, 720)}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        frame = self.entry(report, "en-US/phone/plan.png")["frame"]
        self.assertEqual((frame["kind"], frame["drawn"], frame["maker"]), ("art", False, "apple"))
        self.assertEqual(frame["art"]["screenSource"], "detected")
        self.assertEqual(frame["art"]["fit"]["cut"], 0)           # the capture fits the opening exactly
        self.assertLessEqual(frame["art"]["scale"], 1.0)           # the art is never drawn larger than it is
        self.assertFalse(frame["cropped"] or frame["tilted"] or frame["threeD"])
        box = frame["box"]
        self.assertAlmostEqual(box[2] / box[3], 400 / 800.0, places=2)   # never stretched

    def fold_config(self, sizes, outer=False):
        cfg = kit.base_config()
        cfg["targets"] = dict((name, {"store": "apple", "width": w, "height": h, "capture": "fold-" + name,
                                      "device": "foldable-inner"}) for name, (w, h) in sizes.items())
        shot = {"id": "fold", "capture": "inner", "layout": "fold", "caption": "cap.plan"}
        if outer:
            shot["fold"] = {"outer": {"capture": "cover", "device": "cover"}}
        cfg["shots"] = [shot]
        return cfg

    def test_the_fold_layout_at_every_aspect_class(self):
        sizes = {"tall": (300, 650), "mid": (450, 600), "square": (400, 400), "wide": (640, 450)}
        captures = {}
        for name, (w, h) in sizes.items():
            captures["en-US/fold-%s/inner" % name] = (1000, 1100) if name != "wide" else (1400, 1000)
        code, report, lines = self.run_render(self.project(self.fold_config(sizes), captures))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        for f in report["files"]:
            with self.subTest(path=f["path"]):
                fr = f["frame"]
                self.assertEqual(f["layout"], "fold")
                self.assertTrue(fr["threeD"])
                self.assertEqual(fr["fold"]["pose"], "open")
                self.assertEqual(fr["fold"]["angle"], 120)
                self.assertEqual(fr["fold"]["hinge"], "vertical")
                b = fr["box"]
                self.assertTrue(b[0] >= 0 and b[1] >= 0 and b[0] + b[2] <= f["width"] and b[1] + b[3] <= f["height"],
                                b)
                self.assertFalse(fr["cropped"])
                self.assertLessEqual(f["captureScale"], 1.0)
                self.assertGreater(f["uiShare"], 0.1)
                self.assertTrue(f["caption"]["fits"])
                self.assertLess(f["caption"]["box"][1] + f["caption"]["box"][3], b[1] + 2)   # words above

    def test_a_portrait_inner_display_folds_across_and_the_outer_shows_on_the_back(self):
        cfg = self.fold_config({"duo": (500, 700)}, outer=True)
        cfg["shots"].append({"id": "flex", "capture": "inner", "layout": "fold", "caption": "cap.plan"})
        captures = {"en-US/fold-duo/inner": (1000, 1420), "en-US/cover/cover": (700, 1020)}
        code, report, lines = self.run_render(self.project(cfg, captures))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        cover = self.entry(report, "en-US/duo/fold.png")["frame"]["fold"]
        self.assertEqual((cover["pose"], cover["angle"]), ("cover", 70))
        self.assertGreater(cover["outer"]["box"][2], 10)
        self.assertLessEqual(cover["outer"]["captureScale"], 1.0)
        flex = self.entry(report, "en-US/duo/flex.png")["frame"]["fold"]
        self.assertEqual((flex["hinge"], flex["pose"]), ("horizontal", "open"))

    def test_a_wide_hero_keeps_the_app_in_view_with_a_wide_logo(self):
        root = os.path.join(self.tmp, "p")
        os.makedirs(os.path.join(root, "art"))
        tk.write_png(os.path.join(root, "art", "wordmark.png"), 300, 80, fill=(255, 255, 255), alpha=True)
        cfg = kit.base_config()
        cfg["theme"]["hero"] = {"logo": "art/wordmark.png", "fit": "wide"}
        cfg["targets"] = {"wide": {"store": "apple", "width": 700, "height": 492, "capture": "duo",
                                   "device": "foldable-inner"},
                          "tall": {"store": "apple", "width": 300, "height": 650, "capture": "phone"}}
        cfg["shots"] = [{"id": "hero", "capture": "plan", "layout": "hero", "caption": "cap.plan"}]
        code, report, lines = self.run_render(kit.make_project(root, cfg, captures={
            "en-US/duo/plan": (1400, 984), "en-US/phone/plan": (600, 1300)}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        wide = self.entry(report, "en-US/wide/hero.png")
        self.assertGreaterEqual(wide["uiShare"], 0.3)                 # not a sliver: the app in use
        cap, box = wide["caption"]["box"], wide["frame"]["box"]
        self.assertLess(cap[0] + cap[2], box[0] + 2)                  # the words beside the device
        self.assertFalse(wide.get("errors"))

    def test_style_knobs_tilt_angles_caption_width_and_accents_across_lines(self):
        cfg = kit.base_config()
        cfg["shots"] = [{"id": "flat", "capture": "plan", "layout": "tilt", "caption": "a",
                         "tilt": {"side": "left", "y": 0, "x": 0, "z": 0}},
                        {"id": "turned", "capture": "plan", "layout": "tilt", "caption": "a"},
                        {"id": "narrow", "capture": "plan", "layout": "framed-bleed", "caption": "b",
                         "captionStyle": {"maxWidthPct": 50, "maxLines": 4}}]
        cfg["strings"] = {"en-US": {"a": "Plan your *whole week\nof meals*", "b": "Plan a week of meals"}}
        code, report, lines = self.run_render(self.project(cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        flat, turned = self.entry(report, "en-US/phone/flat.png"), self.entry(report, "en-US/phone/turned.png")
        self.assertEqual(flat["caption"]["text"], "Plan your whole week of meals")
        self.assertEqual(flat["caption"]["accent"], "#FFC94D")
        self.assertNotEqual(flat["sha256"], turned["sha256"])          # the angles reached the page
        self.assertEqual(flat["tilt"], "left")
        self.assertLessEqual(self.entry(report, "en-US/phone/narrow.png")["caption"]["box"][2], 150 + 1)


@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class TrialRegressionTests(Base):
    """What the real trial of fitted frames found: a simulator capture's black corner tip squaring every iPhone
    frame, a set radius overruled, a squarish logo capped small, a caption box that couldn't widen, one shot's layout
    per target, and the cache missing a target's frame."""

    BAR = FitAndFoldTests.BAR

    def simulator_capture(self, path, w=660, h=1434):
        """An iOS simulator capture: a light screen whose very top-left corner tip holds 15 pure-black pixels (the
        framebuffer's own), the clock well inside the corner."""
        rects = [(0, 0, 4, 1, (0, 0, 0)), (0, 1, 4, 1, (0, 0, 0)), (0, 2, 4, 1, (0, 0, 0)), (0, 3, 3, 1, (0, 0, 0)),
                 (60, 24, 50, 18, (20, 20, 20)), (w - 100, 26, 60, 14, (20, 20, 20))]
        tk.write_png(path, w, h, fill=(242, 241, 246), rects=rects)
        return path

    def test_a_simulators_black_corner_tip_keeps_the_corners_round(self):
        root = os.path.join(self.tmp, "p")
        cfg = kit.base_config()
        cfg["targets"]["phone"].update({"width": 330, "height": 717})
        self.simulator_capture(os.path.join(root, "captures", "en-US", "phone", "plan.png"))
        code, report, lines = self.run_render(kit.make_project(root, cfg, captures={}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        frame = self.entry(report, "en-US/phone/plan.png")["frame"]
        self.assertEqual(frame["class"], "phone")
        self.assertFalse(frame["corners"]["reduced"], frame)       # not squared by the tip
        self.assertAlmostEqual(frame["screenRadius"], 0.12 * 660, delta=1)
        self.assertEqual(frame["corners"]["clippedPx"], 0)

    def test_a_radius_the_config_sets_always_wins(self):
        root = os.path.join(self.tmp, "p")
        cfg = kit.base_config()
        cfg["targets"]["phone"].update({"width": 540, "height": 960, "frame": {"name": "phone", "radius": 0.1}})
        FitAndFoldTests.corner_capture(self, os.path.join(root, "captures", "en-US", "phone", "plan.png"), 1080, 1920)
        code, report, lines = self.run_render(kit.make_project(root, cfg, captures={}))
        frame = self.entry(report, "en-US/phone/plan.png")["frame"]
        self.assertAlmostEqual(frame["screenRadius"], 108, delta=1)  # kept, though the clock sits in the corner
        self.assertTrue(frame["corners"]["radiusSet"])
        self.assertGreater(frame["corners"]["clippedPx"], 0)         # reported, for check.py to warn

    def test_a_squarish_logo_takes_its_width_and_the_caption_box_can_widen(self):
        root = os.path.join(self.tmp, "p")
        os.makedirs(os.path.join(root, "art"))
        tk.write_png(os.path.join(root, "art", "mark.png"), 200, 190, fill=(255, 255, 255), alpha=True)
        cfg = kit.base_config()
        cfg["theme"]["hero"] = {"logo": "art/mark.png", "fit": "wide", "widthPct": 42}
        cfg["shots"] = [{"id": "hero", "capture": "plan", "layout": "hero", "caption": "cap.plan"},
                        {"id": "wide", "capture": "plan", "layout": "framed-bleed", "caption": "cap.plan",
                         "captionStyle": {"widthPct": 94}}]
        code, report, lines = self.run_render(kit.make_project(root, cfg))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        logo = self.entry(report, "en-US/phone/hero.png")["caption"]["logo"]
        self.assertEqual(logo["kind"], "logo")
        self.assertAlmostEqual(logo["box"][2], 0.42 * 300, delta=2)    # 42u wide, though nearly square
        block = self.entry(report, "en-US/phone/wide.png")["caption"]["blockBox"]
        self.assertAlmostEqual(block[2], 0.94 * 300, delta=2)           # wider than the layout's 84u
        self.assertGreaterEqual(block[0], 0.02 * 300 - 1)

    def hero_project(self, caption, hero=None, target_hero=None, maxlines=None, name="p", size=None):
        root = os.path.join(self.tmp, name)
        os.makedirs(os.path.join(root, "art"), exist_ok=True)
        tk.write_png(os.path.join(root, "art", "mark.png"), 200, 200, fill=(255, 255, 255), alpha=True)
        cfg = kit.base_config()
        cfg["theme"]["hero"] = hero or {"logo": "art/mark.png", "fit": "wide", "widthPct": 42}
        if maxlines:
            cfg["theme"]["caption"]["maxLines"] = maxlines
        if size:
            cfg["theme"]["caption"].update({"sizePct": size, "floorPct": size})
        cfg["targets"] = {"wide": {"store": "apple", "width": 700, "height": 492, "capture": "duo",
                                   "device": "foldable-inner"}}
        if target_hero:
            cfg["targets"]["wide"]["hero"] = target_hero
        cfg["shots"] = [{"id": "hero", "capture": "plan", "layout": "hero", "caption": "c"}]
        cfg["strings"] = {"en-US": {"c": caption}}
        return kit.make_project(root, cfg, captures={"en-US/duo/plan": (1400, 984)})

    def test_a_tall_logo_shrinks_before_the_words_leave_a_wide_hero(self):
        hero = {"logo": "art/mark.png", "fit": "wide", "widthPct": 55}
        words = "Plan your *week*,\nshop by aisle,\ncook it all\ntonight"
        code, report, lines = self.run_render(self.hero_project(words, hero=hero, maxlines=4))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        f = self.entry(report, "en-US/wide/hero.png")
        cap = f["caption"]
        self.assertTrue(cap["fits"], cap)
        self.assertEqual(cap["outside"], [])
        self.assertIsNotNone(cap["logo"]["shrunk"])                  # the mark gave way, not the slot's edge
        block = cap["blockBox"]
        self.assertLessEqual(block[1] + block[3], 492 + 1)
        self.assertGreaterEqual(block[1], -1)

    def test_words_that_still_leave_the_slot_dont_fit(self):
        words = "\n".join(["Plan", "your", "whole", "week", "of", "meals"])
        root = self.hero_project(words, maxlines=5, size=18)
        code, report, lines = self.run_render(root)
        cap = self.entry(report, "en-US/wide/hero.png")["caption"]
        self.assertIn("caption", cap["outside"])
        self.assertFalse(cap["fits"])
        self.assertEqual(code, render.EXIT_ERRORS)
        self.assertTrue(any("runs off the slot" in line for line in lines), lines)
        import check
        found = [x for _, x in check.run_check(root).findings if x.rule_id == "design.caption.outside"]
        self.assertEqual([x.severity for x in found], ["error"])

    def test_a_targets_hero_logo_overrides_the_themes(self):
        code, report, lines = self.run_render(self.hero_project("Plan your week", target_hero={"widthPct": 10}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        logo = self.entry(report, "en-US/wide/hero.png")["caption"]["logo"]
        self.assertAlmostEqual(logo["box"][2], 0.10 * 700, delta=2)

    def test_one_shot_folds_on_the_foldable_and_not_elsewhere(self):
        cfg = kit.base_config()
        cfg["targets"]["duo"] = {"store": "apple", "width": 640, "height": 450, "capture": "duo",
                                 "device": "foldable-inner", "layouts": {"plan": "fold"}}
        code, report, lines = self.run_render(self.project(cfg, {"en-US/phone/plan": (300, 650),
                                                                 "en-US/duo/plan": (1400, 985)}))
        self.assertEqual(code, render.EXIT_OK, "\n".join(lines))
        self.assertEqual(self.entry(report, "en-US/duo/plan.png")["layout"], "fold")
        self.assertEqual(self.entry(report, "en-US/phone/plan.png")["layout"], "framed-bleed")

    def test_a_targets_frame_setting_renders_again(self):
        cfg = kit.base_config()
        path = self.project(cfg)
        code, first, _ = self.run_render(path)
        self.assertEqual(first["rendered"], 1)
        cfg["targets"]["phone"]["frame"] = {"name": "phone"}   # draws the same, but the config changed
        path = self.project(cfg)
        code, again, _ = self.run_render(path)
        self.assertEqual(again["rendered"], 1)
        code, still, _ = self.run_render(path)
        self.assertEqual(still["rendered"], 0)

if __name__ == "__main__":
    unittest.main()
