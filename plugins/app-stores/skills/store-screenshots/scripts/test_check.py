"""Tests for check.py: synthetic render reports and PNGs (check_testkit), one problem at a time."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check  # noqa: E402
import check_testkit as tk  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import schema  # noqa: E402


class CheckCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="check-test-")
        self.set = tk.SetBuilder(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_check(self, **kw):
        path = self.set.write(**kw)
        return check.run_check(path)

    def ids(self, report, severity=None):
        return [f.rule_id for _, f in report.findings if severity is None or f.severity == severity]

    def finding(self, report, rule_id):
        for _, f in report.findings:
            if f.rule_id == rule_id:
                return f
        self.fail("no %s finding in %s" % (rule_id, self.ids(report)))


class CleanSet(CheckCase):
    def test_a_clean_set_has_no_errors(self):
        report = self.run_check()
        self.assertEqual(report.errors, [], report.to_text())
        self.assertEqual(report.stores, ["apple", "google"])

    def test_contrast_and_search_size_are_measured(self):
        report = self.run_check()
        measured = dict((m["path"], m) for m in report.to_json()["measured"])
        plan = measured["en-US/iphone/plan.png"]
        self.assertGreater(plan["contrast"], 7)
        self.assertAlmostEqual(plan["searchPt"], 11.8, places=1)
        self.assertNotIn("searchPt", measured["en-US/android-phone/plan.png"])

    def test_the_checklist_lists_what_a_person_judges(self):
        report = self.run_check()
        ids = [c["id"] for c in report.checklist]
        for item in ("look.first_three", "look.content", "look.marks", "look.alt_text", "apple.screenshots.in_use",
                     "google.screenshots.content"):
            self.assertIn(item, ids)
        self.assertNotIn("look.rtl", ids)
        self.assertNotIn("google.screenshots.wear.plain", ids)  # no Wear target
        marks = next(c for c in report.checklist if c["id"] == "look.marks")["item"]
        self.assertIn("Google Play: none", marks)

    def test_rtl_locales_add_their_item(self):
        self.set = tk.SetBuilder(self.tmp, tk.base_config(locales=["en-US", "ar-SA"]))
        report = self.run_check()
        self.assertIn("look.rtl", [c["id"] for c in report.checklist])


class Pixels(CheckCase):
    def test_wrong_size(self):
        self.set.pixels["en-US/iphone/plan.png"] = {"width": 1300, "height": 2800}
        report = self.run_check()
        self.assertIn("design.size", self.ids(report, "error"))
        self.assertIn("apple.screenshots.size", self.ids(report, "error"))
        self.assertIn("1300x2800", self.finding(report, "design.size").message)

    def test_a_target_no_display_type_takes(self):
        self.set.config["targets"]["iphone"].update(width=1000, height=2000)
        for f in self.set.files:
            if f["target"] == "iphone":
                f.update(width=1000, height=2000)
        report = self.run_check()
        f = self.finding(report, "apple.screenshots.size")
        self.assertEqual(f.severity, "error")
        self.assertIn("isn't an App Store screenshot size", f.message)

    def test_alpha_is_an_error_on_both_stores(self):
        self.set.pixels["en-US/iphone/plan.png"] = {"alpha": True}
        self.set.pixels["en-US/android-phone/plan.png"] = {"alpha": True}
        report = self.run_check()
        self.assertIn("apple.screenshots.format", self.ids(report, "error"))
        self.assertIn("google.screenshots.format", self.ids(report, "error"))

    def test_a_file_missing_on_disk_and_one_never_rendered(self):
        self.set.files = [f for f in self.set.files if f["path"] != "en-US/iphone/shop.png"]
        report = self.run_check(skip_png=("en-US/iphone/recipe.png",))
        messages = [f.message for _, f in report.findings if f.rule_id == "design.missing"]
        self.assertTrue(any("not rendered: shop" in m for m in messages), messages)
        self.assertTrue(any("not on disk" in m for m in messages), messages)

    def test_a_file_changed_since_the_report(self):
        self.set.find("en-US/iphone/plan.png")["sha256"] = "a" * 64
        report = self.run_check()
        self.assertIn("design.report.stale", self.ids(report, "warning"))

    def test_upscaled_capture_is_a_warning(self):
        self.set.find("en-US/iphone/plan.png")["captureScale"] = 1.25
        report = self.run_check()
        f = self.finding(report, "design.capture.upscaled")
        self.assertEqual(f.severity, "warning")
        self.assertIn("1.25x", f.message)


class Counts(CheckCase):
    def test_too_many_for_play(self):
        shots = [{"id": "s%d" % i, "capture": "c", "layout": "framed-bleed", "caption": "cap.plan",
                  "targets": ["android-phone"]} for i in range(9)]
        self.set = tk.SetBuilder(self.tmp, tk.base_config(targets={"android-phone": tk.TARGETS["android-phone"]},
                                                          shots=shots))
        report = self.run_check()
        f = self.finding(report, "google.screenshots.count")
        self.assertEqual(f.severity, "error")
        self.assertIn("9", f.message)

    def test_too_many_for_apple(self):
        shots = [{"id": "s%d" % i, "capture": "c", "layout": "framed-bleed", "caption": "cap.plan",
                  "targets": ["iphone-medium"]} for i in range(11)]
        self.set = tk.SetBuilder(self.tmp, tk.base_config(targets={"iphone-medium": tk.TARGETS["iphone-medium"]},
                                                          shots=shots))
        report = self.run_check()
        self.assertIn("apple.screenshots.count", self.ids(report, "error"))

    def test_too_few_for_play(self):
        shots = [{"id": "plan", "capture": "plan", "layout": "framed-bleed", "caption": "cap.plan"}]
        self.set = tk.SetBuilder(self.tmp, tk.base_config(shots=shots))
        report = self.run_check()
        f = self.finding(report, "google.screenshots.minimum")
        self.assertEqual(f.severity, "error")
        self.assertNotIn("apple.screenshots.count", self.ids(report))

    def test_a_required_apple_size_missing(self):
        del self.set.config["targets"]["iphone-medium"]
        self.set.files = [f for f in self.set.files if f["target"] != "iphone-medium"]
        report = self.run_check()
        self.assertIn("apple.screenshots.iphone_61.required", self.ids(report, "error"))

    def test_play_tablets_want_four(self):
        self.set.config["targets"]["android-tablet"] = {"store": "google", "width": 1920, "height": 1080,
                                                        "capture": "android-tablet"}
        self.set = tk.SetBuilder(self.tmp, self.set.config)
        for f in self.set.files:
            if f["target"] == "android-tablet":
                f["caption"] = None
        report = self.run_check()
        self.assertIn("google.screenshots.tablet10.count", self.ids(report, "warning"))


class Captions(CheckCase):
    def test_at_the_floor_is_a_warning(self):
        self.set.find("en-US/iphone/plan.png")["caption"].update(atFloor=True, fontPx=79.2)
        report = self.run_check()
        f = self.finding(report, "design.caption.floor")
        self.assertEqual(f.severity, "warning")
        self.assertIn("79.2 px", f.message)

    def test_not_fitting_is_an_error(self):
        self.set.find("en-US/iphone/plan.png")["caption"].update(atFloor=True, fits=False)
        report = self.run_check()
        self.assertEqual(self.finding(report, "design.caption.fit").severity, "error")
        self.assertNotIn("design.caption.floor", self.ids(report))

    def test_three_lines_is_an_error(self):
        self.set.find("en-US/iphone/plan.png")["caption"]["lines"] = 3
        report = self.run_check()
        self.assertEqual(self.finding(report, "design.caption.lines").severity, "error")

    def test_three_lines_the_theme_allows_is_a_warning(self):
        self.set.config["theme"]["caption"]["maxLines"] = 3
        self.set.find("en-US/iphone/plan.png")["caption"]["lines"] = 3
        report = self.run_check()
        self.assertEqual(self.finding(report, "design.caption.lines").severity, "warning")

    def test_long_captions_warn(self):
        self.set.find("en-US/iphone/plan.png")["caption"]["text"] = "Plan a whole week of meals in just a few minutes"
        report = self.run_check()
        self.assertEqual(self.finding(report, "design.caption.words").severity, "warning")

    def test_missing_glyphs(self):
        self.set.find("en-US/iphone/plan.png")["caption"]["missingGlyphs"] = ["न", "म"]
        report = self.run_check()
        f = self.finding(report, "design.glyphs")
        self.assertEqual(f.severity, "error")
        self.assertIn("U+0928", f.message)

    def test_a_small_caption_in_apples_search_row(self):
        for f in self.set.files:
            if f["target"] == "iphone":
                f["caption"]["fontPx"] = 105.6  # 8% of the width
        report = self.run_check()
        warnings = [f for _, f in report.findings if f.rule_id == "design.caption.search_size"]
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0].where, "en-US/iphone")
        self.assertIn("9.4 pt (plan), 9.4 pt (recipe), 9.4 pt (shop)", warnings[0].message)
        self.assertEqual(warnings[0].severity, "warning")

    def test_text_share_over_googles_limit(self):
        for f in self.set.files:
            f["caption"]["textShare"] = 0.26
        report = self.run_check()
        f = self.finding(report, "google.design.max_text_share")
        self.assertEqual(f.severity, "warning")
        self.assertIn("26%", f.message)
        self.assertFalse(any(s == "apple" and f.rule_id.endswith("max_text_share") for s, f in report.findings))


class Words(CheckCase):
    def test_a_price_in_an_apple_caption_is_an_error(self):
        for f in self.set.files:
            if f["shot"] == "plan":
                f["caption"]["text"] = "Plan meals for $4.99"
        report = self.run_check()
        f = self.finding(report, "apple.metadata.prices")
        self.assertEqual(f.severity, "error")
        self.assertIn("(iphone, iphone-medium)", f.where)
        self.assertEqual(len([1 for _, x in report.findings if x.rule_id == "apple.metadata.prices"]), 1)

    def test_an_award_on_google_follows_the_rules(self):
        for f in self.set.files:
            if f["shot"] == "recipe":
                f["caption"]["text"] = "Award-winning recipes"
        report = self.run_check()
        f = self.finding(report, "google.captions.promotional")
        self.assertEqual(f.severity, "error")
        self.assertIn("android-phone", f.where)
        apple = [f for s, f in report.findings if s == "apple" and "award" in f.message.lower()]
        self.assertTrue(apple and all(f.severity == "warning" for f in apple))

    def test_a_url_in_an_apple_caption(self):
        self.set.find("en-US/iphone/plan.png")["caption"]["text"] = "More at example.com"
        report = self.run_check()
        self.assertIn("apple.captions.urls", self.ids(report, "warning"))

    def test_a_hero_proof_line_is_checked_from_the_strings(self):
        self.set.config["shots"][0]["proof"] = "cap.proof"
        self.set.config["strings"]["en-US"]["cap.proof"] = "The #1 meal planner"
        report = self.run_check()
        f = self.finding(report, "google.captions.promotional")
        self.assertIn("proof", f.where)

    def test_relaxed_by_the_listing(self):
        for f in self.set.files:
            f["caption"]["text"] = "Gluten-free recipes"
        self.set.listing = {"rules": {"relax": [{"id": "apple.metadata.prices", "reason": "gluten-free"}]}}
        report = self.run_check()
        self.assertNotIn("apple.metadata.prices", self.ids(report))
        self.assertIn("google.captions.promotional", self.ids(report))
        self.assertEqual(report.to_json()["relaxed"], [{"id": "apple.metadata.prices", "reason": "gluten-free"}])


class Contrast(CheckCase):
    def set_caption(self, ink_hex, box_fill, ink_rgb):
        self.set.config["theme"]["palette"]["ink"] = ink_hex
        for f in self.set.files:
            self.set.pixels[f["path"]] = {"box_fill": box_fill, "ink": ink_rgb}

    def test_dark_words_on_a_light_box_pass(self):
        self.set_caption("#111111", tk.NEAR_WHITE, tk.INK_DARK)
        report = self.run_check()
        self.assertNotIn("design.contrast", self.ids(report))

    def test_light_words_on_a_light_box_fail(self):
        self.set_caption("#FFFFFF", tk.NEAR_WHITE, tk.WHITE)
        report = self.run_check()
        f = self.finding(report, "design.contrast")
        self.assertEqual(f.severity, "error")
        self.assertIn("1.1:1", f.message)

    def test_light_words_on_a_dark_box_pass(self):
        self.set_caption("#FFFFFF", tk.DARK, tk.WHITE)
        report = self.run_check()
        self.assertNotIn("design.contrast", self.ids(report))

    def test_dark_words_on_a_dark_box_fail(self):
        self.set_caption("#111111", tk.DARK, tk.INK_DARK)
        report = self.run_check()
        self.assertIn("design.contrast", self.ids(report, "error"))

    def test_the_reports_ink_beats_the_theme(self):
        self.set_caption("#FFFFFF", tk.NEAR_WHITE, tk.INK_DARK)
        for f in self.set.files:
            f["caption"]["ink"] = "rgb(17, 17, 17)"
        report = self.run_check()
        self.assertNotIn("design.contrast", self.ids(report))

    def test_colours_and_ratios(self):
        self.assertEqual(check.parse_colour("#fff"), (255, 255, 255))
        self.assertEqual(check.parse_colour("#0E3B2E"), (14, 59, 46))
        self.assertEqual(check.parse_colour("#0E3B2E80"), (14, 59, 46))
        self.assertEqual(check.parse_colour("rgba(10, 20, 30, 0.5)"), (10, 20, 30))
        self.assertEqual(check.parse_colour([1, 2, 3]), (1, 2, 3))
        self.assertIsNone(check.parse_colour("not a colour"))
        ratio = check.contrast_ratio(check.luminance((255, 255, 255)), check.luminance((0, 0, 0)))
        self.assertAlmostEqual(ratio, 21.0, places=3)
        pixels = bytes([0, 0, 0] * 6 + [255, 255, 255] * 4)  # 10 px: 6 black, 4 white
        self.assertEqual(check.median_luminance(pixels, 10, 1, [0, 0, 10, 1]), 0.0)


class Frames(CheckCase):
    def wear_set(self, **entry):
        config = tk.base_config(targets={"android-phone": tk.TARGETS["android-phone"],
                                         "watch": {"store": "google", "width": 450, "height": 450,
                                                   "capture": "wear"}})
        self.set = tk.SetBuilder(self.tmp, config)
        for f in self.set.files:
            if f["target"] == "watch":
                f.update(entry)

    def test_a_frame_on_wear_is_an_error(self):
        self.wear_set(frame={"name": "watch", "box": [40, 40, 370, 370]}, caption=None, layout="gameplay")
        report = self.run_check()
        f = self.finding(report, "google.design.frames")
        self.assertEqual(f.severity, "error")
        self.assertIn("wear", f.message)
        self.assertIn("google.screenshots.wear.plain", [c["id"] for c in report.checklist])

    def test_words_and_backgrounds_on_wear_are_errors(self):
        self.wear_set(layout="band")
        report = self.run_check()
        self.assertIn("google.design.captions", self.ids(report, "error"))
        self.assertIn("google.design.backgrounds", self.ids(report, "error"))

    def test_a_plain_wear_shot_passes(self):
        self.wear_set(caption=None, frame=None, layout="gameplay")
        report = self.run_check()
        self.assertEqual([i for i in self.ids(report) if "design" in i and "watch" in i], [])
        self.assertEqual(report.errors, [], report.to_text())

    def test_a_frame_on_play_is_discouraged(self):
        for f in self.set.files:
            if f["store"] == "google":
                f["frame"] = {"name": "phone", "box": [100, 600, 880, 1500]}
        report = self.run_check()
        f = self.finding(report, "google.design.frames")
        self.assertEqual(f.severity, "warning")

    def user_frame(self, maker="apple"):
        """A user's own device art beside the config: an SVG and its JSON saying it isn't drawn."""
        folder = os.path.join(self.tmp, "bezels")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "my-phone.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        with open(os.path.join(folder, "my-phone.json"), "w") as f:
            json.dump({"name": "my-phone", "drawn": False, "maker": maker,
                       "screen": {"x": 10, "y": 10, "width": 100, "height": 200}}, f)
        return "bezels/my-phone.svg"

    def test_apple_bezels_tilted_or_cropped_are_errors(self):
        name = self.user_frame()
        for f in self.set.files:
            if f["store"] == "apple":
                f["frame"] = {"name": name, "box": [100, 700, 1000, 1800]}
                f["layout"] = "framed"
        f = self.set.find("en-US/iphone/plan.png")
        f["layout"] = "tilt"
        r = self.set.find("en-US/iphone/recipe.png")
        r["layout"] = "framed-bleed"
        r["frame"]["box"] = [100, 900, 1120, 2300]
        report = self.run_check()
        found = dict((x.where, x) for _, x in report.findings if x.rule_id == "apple.design.device_art")
        self.assertEqual(sorted(found), ["en-US/iphone/plan.png", "en-US/iphone/recipe.png"])
        self.assertEqual(found["en-US/iphone/plan.png"].severity, "error")
        self.assertIn("tilted", found["en-US/iphone/plan.png"].message)
        self.assertIn("cropped", found["en-US/iphone/recipe.png"].message)

    def test_a_callout_over_an_apple_bezel_is_an_error(self):
        f = self.set.find("en-US/iphone/plan.png")
        f["layout"] = "framed"
        f["frame"] = {"name": "my-bezel", "drawn": False, "maker": "apple", "box": [100, 900, 1000, 1900]}
        f["callout"] = {"box": [60, 1200, 1200, 300]}
        report = self.run_check()
        self.assertIn("callout", self.finding(report, "apple.design.device_art").message)

    def test_device_art_on_play_is_a_warning(self):
        name = self.user_frame(maker="examplemaker")
        f = self.set.find("en-US/android-phone/plan.png")
        f["frame"] = {"name": name, "box": [100, 300, 880, 1500]}
        report = self.run_check()
        found = self.finding(report, "google.design.device_art")
        self.assertEqual(found.severity, "warning")
        self.assertIn("examplemaker", found.message)

    def test_drawn_frames_are_fine_on_apple(self):
        report = self.run_check()
        self.assertFalse([i for i in self.ids(report) if i.startswith("apple.design.")])

    def test_play_tablets_are_best_without_words(self):
        self.set.config["targets"]["android-tablet"] = {"store": "google", "width": 1920, "height": 1080,
                                                        "capture": "android-tablet"}
        self.set = tk.SetBuilder(self.tmp, self.set.config)
        report = self.run_check()
        f = self.finding(report, "google.design.captions")
        self.assertEqual(f.severity, "warning")
        self.assertIn("tablet10", f.message)

    def test_play_tv_needs_one_unaltered_shot(self):
        self.set.config["targets"]["tv"] = {"store": "google", "width": 1920, "height": 1080, "capture": "tv"}
        self.set = tk.SetBuilder(self.tmp, self.set.config)
        report = self.run_check()
        self.assertIn("unaltered", self.finding(report, "google.design.captions").message)
        self.setUp()
        self.set.config["targets"]["tv"] = {"store": "google", "width": 1920, "height": 1080, "capture": "tv"}
        self.set = tk.SetBuilder(self.tmp, self.set.config)
        tv = self.set.find("en-US/tv/shop.png")
        tv.update(caption=None, layout="gameplay")
        report = self.run_check()
        self.assertNotIn("google.design.captions", self.ids(report))


class Sets(CheckCase):
    def test_apple_wants_more_than_half_in_use(self):
        for f in self.set.files:
            if f["shot"] in ("plan", "recipe"):
                f["layout"] = "hero"
        report = self.run_check()
        f = self.finding(report, "apple.design.in_use_majority")
        self.assertEqual(f.severity, "error")
        self.assertIn("1 of 3", f.message)
        self.assertIn("google.design.ui_first", self.ids(report, "warning"))

    def test_one_hero_is_fine_on_apple(self):
        self.set.config["shots"][0]["layout"] = "hero"
        for f in self.set.files:
            if f["shot"] == "plan":
                f["layout"] = "hero"
        report = self.run_check()
        self.assertNotIn("apple.design.in_use_majority", self.ids(report))

    def test_seams(self):
        f = self.set.find("en-US/iphone/plan.png")
        f["seams"] = [{"edge": "right", "x": 1320}]
        f["caption"]["box"] = [700, 200, 600, 300]
        f["frame"]["box"] = [132, 946, 1180, 2289]
        report = self.run_check()
        seams = [x for _, x in report.findings if x.rule_id == "design.seams"]
        self.assertEqual(sorted(x.severity for x in seams), ["error", "warning"])  # the caption and the frame

    def test_fallbacks_are_listed_not_found(self):
        config = tk.base_config(locales=["en-US", "de-DE"])
        self.set = tk.SetBuilder(self.tmp, config)
        for f in self.set.files:
            if f["locale"] == "de-DE":
                f["captureFallback"] = True
        report = self.run_check()
        fallbacks = report.to_json()["fallbacks"]
        words = [fb for fb in fallbacks if fb["what"] == "words"]
        captures = [fb for fb in fallbacks if fb["what"] == "capture"]
        self.assertEqual(sorted(fb["shot"] for fb in words), ["recipe", "shop"])
        self.assertEqual(len(captures), 3)
        self.assertEqual(captures[0]["targets"], ["android-phone", "iphone", "iphone-medium"])
        self.assertEqual(captures[0]["from"], "en-US")
        self.assertEqual(report.errors, [])
        self.assertIn("Fell back to the primary locale", report.to_text())

    def test_the_listing_says_which_play_slot(self):
        self.set.config["targets"]["big-android"] = {"store": "google", "width": 1080, "height": 1920,
                                                     "capture": "big"}
        self.set = tk.SetBuilder(self.tmp, self.set.config)
        self.set.listing = {"stores": {"google": {"slots": {"phone": "android-phone", "tablet7": "big-android"},
                                                  "category": "FOOD_AND_DRINK"}}}
        report = self.run_check()
        self.assertIn("google.design.captions", self.ids(report))  # tablet7 words: discouraged
        self.assertFalse([n for n in report.notes if "a guess" in n])
        self.assertIn("google.screenshots.featuring.app", self.ids(report, "warning"))
        self.assertFalse([n for n in report.not_checked if n["id"].startswith("google.screenshots.featuring")])


class RenderShape(CheckCase):
    """Entries as render.py writes them: seams with their own verdict, kicker and proof inside the caption,
    a pair's frames list, the page's errors."""

    def test_the_seams_verdict(self):
        f = self.set.find("en-US/iphone/plan.png")
        f["seams"] = [{"edge": "right", "x": 1320, "marginPx": 79.2, "clear": False, "intruders": ["proof", "frame"]}]
        report = self.run_check()
        seams = sorted((x.severity, x.message.split(" comes")[0]) for _, x in report.findings
                       if x.rule_id == "design.seams")
        self.assertEqual(seams, [("error", "the proof"), ("warning", "the frame")])

    def test_kicker_and_proof_inside_the_caption(self):
        for f in self.set.files:
            if f["shot"] == "plan":
                f["caption"]["kicker"] = {"text": "New", "box": [0, 0, 10, 10], "fontPx": 40}
                f["caption"]["proof"] = {"text": "Loved by home cooks", "box": [0, 0, 10, 10], "fontPx": 40}
        report = self.run_check()
        f = self.finding(report, "google.captions.promotional")
        self.assertIn("kicker", f.where)
        self.assertIn('"New"', f.message)

    def test_a_pairs_second_frame_is_checked_too(self):
        f = self.set.find("en-US/iphone/plan.png")
        f["layout"] = "pair"
        drawn = {"name": "phone", "box": [50, 900, 500, 1100], "kind": "drawn", "drawn": True, "maker": None}
        art = {"name": "bezels/x.png", "box": [700, 900, 500, 1100], "kind": "art", "drawn": False,
               "maker": "apple", "tilted": True, "cropped": False}
        f["frame"], f["frames"] = drawn, [drawn, art]
        report = self.run_check()
        self.assertIn("tilted", self.finding(report, "apple.design.device_art").message)

    def test_the_pages_errors(self):
        self.set.find("en-US/iphone/plan.png")["errors"] = ["capture captures/en-US/iphone-6.9/plan.png failed to load"]
        report = self.run_check()
        self.assertIn("failed to load", self.finding(report, "design.render.errors").message)


class Cli(CheckCase):
    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = check.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_and_json(self):
        path = self.set.write()
        code, out, _ = self.main("--config", path, "--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(sorted(data), sorted(["config", "stores", "findings", "fallbacks", "relaxed", "checklist",
                                              "notChecked", "notes", "measured", "summary"]))
        self.assertEqual(data["summary"]["errors"], 0)
        self.set.find("en-US/iphone/plan.png")["caption"]["fits"] = False
        path = self.set.write()
        code, out, _ = self.main("--config", path)
        self.assertEqual(code, 1)
        self.assertIn("Errors:", out)
        self.assertIn("[design.caption.fit]", out)
        self.assertIn("Result: 1 error", out)

    def test_a_report_named_beside_the_config_without_its_pictures(self):
        path = self.set.write()
        beside = os.path.join(self.tmp, "render-report.json")
        os.replace(os.path.join(self.set.out, "render-report.json"), beside)
        shutil.rmtree(self.set.out)
        self.set.find("en-US/iphone/recipe.png")["caption"]["fits"] = False
        with open(beside, "w") as f:
            json.dump({"version": 1, "files": self.set.files}, f)
        code, out, _ = self.main("--config", path, "--report", beside, "--json")
        self.assertEqual(code, 1)
        data = json.loads(out)
        missing = [f for f in data["findings"] if f["rule_id"] == "design.missing"]
        self.assertEqual(len(missing), 3)  # one per target, naming its shots
        self.assertIn("plan, recipe, shop", missing[0]["message"])
        self.assertIn("design.caption.fit", [f["rule_id"] for f in data["findings"]])

    def test_usage_errors(self):
        code, _, err = self.main("--config", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(code, 3)
        self.assertIn("no design config", err)
        path = self.set.write()
        os.unlink(os.path.join(self.set.out, "render-report.json"))
        code, _, err = self.main("--config", path)
        self.assertEqual(code, 3)
        self.assertIn("run render.py first", err)
        self.assertEqual(self.main("--bogus")[0], 3)


class RulesData(unittest.TestCase):
    RULES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules")

    def test_the_rules_files_meet_their_schema(self):
        s = jsonio.load(os.path.join(self.RULES, "rules.schema.json"))
        for store in ("apple", "google"):
            self.assertEqual(schema.validate(jsonio.load(os.path.join(self.RULES, store + ".json")), s), [], store)

    def test_every_design_entry_says_where_it_comes_from(self):
        for store in ("apple", "google"):
            design = jsonio.load(os.path.join(self.RULES, store + ".json"))["design"]
            for name, entry in design.items():
                if name.startswith("$"):
                    continue
                for e in [entry] + list((entry.get("bySlot") or {}).values()):
                    self.assertTrue(e["source"].startswith("https://"), (store, name))
                    self.assertIn(e["status"], ("verified", "observed", "unverified"))
                    self.assertRegex(e["checked"], r"^\d{4}-\d{2}-\d{2}$")
        google = jsonio.load(os.path.join(self.RULES, "google.json"))["design"]
        self.assertEqual(google["maxTextShare"]["value"], 0.2)
        self.assertEqual(google["frames"]["bySlot"]["wear"]["value"], "forbidden")
        apple = jsonio.load(os.path.join(self.RULES, "apple.json"))["design"]
        self.assertEqual(apple["inUseMajority"]["value"], 0.5)

    def test_store_bans_reach_captions(self):
        from appstores_lib import rules
        apple = rules.load("apple", self.RULES)
        self.assertIn("apple.metadata.prices", [r.id for r in apple.for_field("captions")])
        google = rules.load("google", self.RULES)
        promo = google.get("google.captions.promotional")
        for word in ("award", "download now", "free", "#1"):
            self.assertIn(word, [w.lower() for w in promo.get("words")])


if __name__ == "__main__":
    unittest.main()
