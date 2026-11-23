"""Tests for listing.py check, build and preview, against the eval fixtures and synthetic pictures.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here reaches a network;
the PNG rendering test is skipped where no Chrome is installed, the ffprobe one where no ffmpeg is.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import listing  # noqa: E402
import listing_testkit as kit  # noqa: E402
from appstores_lib import chrome  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None

ENV_CLEAN = {"APPLE_REVIEW_PHONE": "", "FFPROBE": ""}


class TempDir(unittest.TestCase):
    """Each test gets a temp folder; the review variables are cleared so the machine's don't leak in."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="listing-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        patcher = mock.patch.dict(os.environ, {})
        patcher.start()
        self.addCleanup(patcher.stop)
        for key in ENV_CLEAN:
            os.environ.pop(key, None)

    def sample(self, **kw):
        return kit.make_sample(os.path.join(self.tmp, "project"), **kw)

    def fixture(self, name):
        return kit.make_sample(os.path.join(self.tmp, name), fixture=name, pictures=False)


class SampleCheck(TempDir):
    def test_the_sample_project_passes(self):
        config = self.sample()
        code, report = kit.check_json(config)
        self.assertEqual(code, 0, [f for f in report["findings"] if f["severity"] == "error"])
        self.assertEqual(report["stores"], ["apple", "google"])
        for key in ("findings", "fallbacks", "relaxed"):
            self.assertIn(key, report)
        for f in report["findings"]:
            for key in ("rule_id", "severity", "where", "message", "source", "status"):
                self.assertIn(key, f)

    def test_text_output_groups_by_store_and_severity(self):
        config = self.sample()
        code, out, _ = kit.run(["check", "--config", config])
        self.assertEqual(code, 0)
        self.assertIn("App Store (apple): 0 errors", out)
        self.assertIn("Google Play (google): 0 errors", out)
        self.assertIn("  Warnings:", out)
        self.assertIn("Result: 0 errors", out)

    def test_unverified_rules_only_warn_and_say_so(self):
        config = self.sample()
        _, report = kit.check_json(config)
        duo = kit.findings(report, "apple.screenshots.iphone_duo.required")
        self.assertTrue(duo)
        for f in duo:
            self.assertEqual(f["severity"], "warning")
            self.assertEqual(f["status"], "unverified")
            self.assertIn("unverified", f["message"])

    def test_screenshot_fallbacks_are_reported_not_findings(self):
        config = self.sample()
        _, report = kit.check_json(config)
        whats = [(fb["store"], fb["locale"], fb["what"]) for fb in report["fallbacks"]]
        self.assertIn(("apple", "de-DE", "screenshot iphone/recipe"), whats)
        self.assertIn(("google", "de-DE", "screenshot android-phone/week"), whats)
        self.assertNotIn(("apple", "de-DE", "screenshot iphone/week"), whats)  # de-DE has its own
        self.assertFalse([f for f in report["findings"] if "fall" in f["message"].lower()])

    def test_word_fallbacks_are_reported(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"]["de-DE"]["apple"].pop("promotionalText"))
        _, report = kit.check_json(config)
        self.assertIn({"store": "apple", "locale": "de-DE", "what": "apple.promotionalText", "from": "en-US"},
                      report["fallbacks"])
        # de-DE's Play full description is its own shared description, not a fallback
        self.assertNotIn("google.fullDescription", [fb["what"] for fb in report["fallbacks"]
                                                    if fb["locale"] == "de-DE"])

    def test_whats_new_on_an_update_isnt_decided_offline(self):
        config = self.sample()
        _, report = kit.check_json(config)
        self.assertIn("apple.whats_new.required", [n["id"] for n in report["notChecked"]])

    def test_checklist_items_are_listed_never_errors(self):
        config = self.sample()
        _, report = kit.check_json(config)
        ids = [c["id"] for c in report["checklist"]]
        self.assertIn("apple.screenshots.in_use", ids)
        self.assertIn("google.forms.data_safety", ids)
        self.assertNotIn("apple.tv.controller", ids)  # TV_OS isn't shipped
        self.assertFalse([f for f in report["findings"] if f["rule_id"] in ids])

    def test_stores_option_limits_the_check(self):
        config = self.fixture("over-limit")
        code, report = kit.check_json(config, "--stores", "apple")
        self.assertEqual(report["stores"], [])
        self.assertTrue(any("isn't enabled" in n for n in report["notes"]))
        self.assertEqual(code, 0)


class EvalFixtures(TempDir):
    """The findings evals.json expects for its fixtures."""

    def test_over_limit_short_description(self):
        config = self.fixture("over-limit")
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        length = kit.findings(report, "google.short_description.length")
        self.assertEqual(len(length), 1)
        self.assertEqual(length[0]["severity"], "error")
        self.assertEqual(length[0]["where"], "en-US google.shortDescription")
        self.assertIn("87 characters", length[0]["message"])
        promo = kit.findings(report, "google.short_description.promotional")
        self.assertEqual(len(promo), 1)
        self.assertIn('"free"', promo[0]["message"])
        # the missing pictures stay visible
        self.assertTrue(kit.findings(report, "google.feature_graphic.required", "error"))
        self.assertTrue(kit.findings(report, "google.icon.required", "error"))
        self.assertTrue(kit.findings(report, "google.screenshots.minimum", "error"))

    def test_over_limit_fixed_words_pass_the_word_rules(self):
        config = self.fixture("over-limit")
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["google"].update(
            shortDescription="Plan a week of family meals in minutes, with one grocery list."))
        _, report = kit.check_json(config)
        self.assertFalse([f for f in report["findings"] if f["rule_id"].startswith("google.short_description")])

    def test_price_word_in_apple_subtitle_but_not_description(self):
        config = self.fixture("price-words")
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        prices = kit.findings(report, "apple.metadata.prices")
        self.assertEqual([f["where"] for f in prices], ["en-US apple.subtitle"])
        self.assertEqual(prices[0]["severity"], "error")
        self.assertIn('"free"', prices[0]["message"])
        about_desc = [f for f in report["findings"] if "description" in f["where"] and f["severity"] == "error"]
        self.assertEqual(about_desc, [])

    def test_invalid_configs_fail_the_schema_first(self):
        folder = os.path.join(kit.FILES, "invalid")
        for name in sorted(os.listdir(folder)):
            with self.subTest(name):
                code, report = kit.check_json(os.path.join(folder, name))
                self.assertEqual(code, 1)
                self.assertTrue(report["findings"])
                self.assertEqual(set(f["rule_id"] for f in report["findings"]), {"config.schema"})
                self.assertEqual(report["stores"], [])

    def test_secret_in_config_names_the_field(self):
        code, report = kit.check_json(os.path.join(kit.FILES, "invalid", "secret-in-config.json"))
        self.assertIn("serviceAccountKey", report["findings"][0]["message"])


class Pictures(TempDir):
    def test_wrong_size_picture_names_the_nearest_sizes(self):
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "screenshots", "en-US", "iphone", "week.png"), 1200, 2600)
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        size = kit.findings(report, "apple.screenshots.size")
        self.assertEqual(len(size), 1)
        self.assertEqual(size[0]["where"], "screenshots/en-US/iphone/week.png")
        self.assertIn("1200x2600", size[0]["message"])
        self.assertIn("1206x2622 (APP_IPHONE_61)", size[0]["message"])

    def test_alpha_channel_is_an_error(self):
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "screenshots", "en-US", "iphone", "pantry.png"), 1206, 2622,
                      alpha=True)
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        fmt = kit.findings(report, "apple.screenshots.format", "error")
        self.assertEqual(len(fmt), 1)
        self.assertIn("alpha", fmt[0]["message"])

    def test_play_icon_alpha_is_only_a_warning(self):
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "graphics", "icon-512.png"), 512, 512, alpha=True)
        code, report = kit.check_json(config)
        self.assertEqual(code, 0)
        self.assertTrue(kit.findings(report, "google.icon.transparency", "warning"))

    def test_play_icon_opaque_alpha_channel_is_fine(self):
        # Play asks for a 32-bit PNG icon: an alpha channel with every pixel opaque isn't transparency
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "graphics", "icon-512.png"), 512, 512, alpha=255)
        code, report = kit.check_json(config)
        self.assertEqual(code, 0)
        self.assertFalse(kit.findings(report, "google.icon.transparency"))

    def test_apple_slot_by_size_first_listed_wins(self):
        config = self.sample()
        ipad = os.path.join(self.tmp, "project", "screenshots", "en-US", "ipad")
        for name in os.listdir(ipad):
            kit.write_png(os.path.join(ipad, name), 2048, 2732)  # fits both 13-inch slots
        report, _, checks = listing.run_check(config)
        slots = checks["apple"].pictures[("IOS", "en-US")]
        self.assertEqual(len(slots["APP_IPAD_PRO_3GEN_129"]), 4)
        self.assertNotIn("APP_IPAD_PRO_129", slots)

    def test_landscape_is_accepted_unless_the_slot_says_otherwise(self):
        self.assertTrue(listing.fits((2622, 1206), [[1206, 2622]]))
        self.assertFalse(listing.fits((2622, 1206), [[1206, 2622]], "portrait"))
        self.assertTrue(listing.fits((1280, 800), [[1280, 800]], "landscape"))
        self.assertFalse(listing.fits((800, 1280), [[1280, 800]], "landscape"))
        self.assertFalse(listing.fits((500, 1024), [[1024, 500]], "asListed"))

    def test_play_phone_screenshot_too_long(self):
        config = self.sample()
        phone = os.path.join(self.tmp, "project", "screenshots", "en-US", "android-phone")
        kit.write_png(os.path.join(phone, "week.png"), 1000, 2500)
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        f = kit.findings(report, "google.screenshots.phone.size")
        self.assertEqual(len(f), 1)
        self.assertIn("2.50x", f[0]["message"])

    def test_feature_graphic_wrong_size(self):
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "graphics", "feature-1024x500.png"), 500, 1024)
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue(kit.findings(report, "google.feature_graphic.size", "error"))

    def test_too_few_tablet_shots_warns_and_relax_turns_it_off(self):
        config = self.sample()
        tablet = os.path.join(self.tmp, "project", "screenshots", "en-US", "android-tablet")
        os.unlink(os.path.join(tablet, "pantry.png"))
        os.unlink(os.path.join(tablet, "grocery-list.png"))
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "google.screenshots.tablet10.count", "warning"))
        kit.edit_config(config, lambda d: d["rules"]["relax"].append(
            {"id": "google.screenshots.tablet10.count", "reason": "Two tablet shots for now."}))
        _, report = kit.check_json(config)
        self.assertFalse(kit.findings(report, "google.screenshots.tablet10.count"))
        self.assertIn({"store": "google", "id": "google.screenshots.tablet10.count",
                       "reason": "Two tablet shots for now."}, report["relaxed"])
        code, out, _ = kit.run(["check", "--config", config])
        self.assertIn("Relaxed by the config", out)
        self.assertIn("Two tablet shots for now.", out)

    def test_relaxing_an_unknown_rule_warns(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["rules"]["relax"].append({"id": "google.no.such_rule", "reason": "x"}))
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "config.relax", "warning"))

    def test_relaxing_a_screenshot_design_rule_isnt_unknown(self):
        """``store-screenshots`` relaxes its design rules (the rules data's ``design`` tables) through the same
        ``rules.relax``: the listing check knows those ids, lists them as relaxed and warns only for an id the
        rules data has nowhere."""
        config = self.sample()
        kit.edit_config(config, lambda d: d["rules"]["relax"].extend([
            {"id": "google.design.frames", "reason": "Our framed set, by choice."},
            {"id": "apple.design.in_use_majority", "reason": "Two feature shots."},
            {"id": "google.design.framez", "reason": "typo"}]))
        _, report = kit.check_json(config)
        unknown = [f["message"] for f in kit.findings(report, "config.relax", "warning")]
        self.assertEqual(len(unknown), 1, unknown)
        self.assertIn("google.design.framez", unknown[0])
        self.assertIn("did you mean google.design.frames?", unknown[0])
        self.assertIn({"store": "google", "id": "google.design.frames", "reason": "Our framed set, by choice.",
                       "for": "store-screenshots"}, report["relaxed"])
        self.assertIn({"store": "apple", "id": "apple.design.in_use_majority", "reason": "Two feature shots.",
                       "for": "store-screenshots"}, report["relaxed"])
        code, out, _ = kit.run(["check", "--config", config])
        self.assertIn("google.design.frames: Our framed set, by choice. (a screenshot design rule", out)
        self.assertNotIn("relaxes google.design.frames", out)

    def test_play_needs_two_screenshots_across_slots(self):
        config = self.sample(pictures=True)
        kit.edit_config(config, lambda d: d["stores"]["google"]["slots"].update(phone=None, tablet10=None))
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue(kit.findings(report, "google.screenshots.minimum", "error"))

    def test_required_apple_slot_is_a_finding(self):
        config = self.sample()
        shutil.rmtree(os.path.join(self.tmp, "project", "screenshots", "en-US", "ipad"))
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        f = kit.findings(report, "apple.screenshots.ipad_13.required", "error")
        self.assertTrue(f)
        self.assertIn("2064x2752", f[0]["message"])
        self.assertTrue(kit.findings(report, "config.screenshots", "warning", "ipad"))

    def test_a_file_that_isnt_a_picture(self):
        config = self.sample()
        with open(os.path.join(self.tmp, "project", "screenshots", "en-US", "iphone", "week.png"), "w") as f:
            f.write("not a picture")
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue(kit.findings(report, "config.files", "error", "iphone/week.png"))

    def test_android_tv_needs_its_words_and_banner(self):
        config = self.sample()
        kit.write_png(os.path.join(self.tmp, "project", "screenshots", "en-US", "tv", "week.png"), 1920, 1080)

        def change(d):
            d["screens"]["tv"] = {"kind": "tv"}
            d["stores"]["google"]["slots"]["tv"] = "tv"
            d["screenshots"]["shots"][0]["stores"] = None
        kit.edit_config(config, change)
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "google.full_description.android_tv", "error"))
        self.assertTrue(kit.findings(report, "google.tv_banner.required", "error"))


class Words(TempDir):
    def test_keywords_count_bytes(self):
        config = self.sample()
        words = ["köstlich•gericht%d" % i for i in range(5)]  # 16 characters, 19 bytes each
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["apple"].update(keywords=words))
        code, report = kit.check_json(config)
        joined = ",".join(words)
        self.assertLessEqual(len(joined), 100)
        self.assertGreater(len(joined.encode("utf-8")), 100)
        f = kit.findings(report, "apple.keywords.length")
        self.assertEqual(len(f), 1)
        self.assertIn("bytes", f[0]["message"])
        self.assertEqual(code, 1)

    def test_each_keyword_and_duplicates(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["apple"].update(
            keywords=["tv", "dinner", "Dinner", "a,b"]))
        _, report = kit.check_json(config)
        each = kit.findings(report, "apple.keywords.each_length")
        self.assertEqual(len(each), 1)
        self.assertIn('"tv"', each[0]["where"])
        self.assertTrue(kit.findings(report, "apple.keywords.commas"))
        dup = kit.findings(report, "apple.keywords.duplicates")
        self.assertTrue(dup)
        self.assertIn("Dinner", dup[0]["message"])

    def test_keywords_repeating_the_name(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["apple"].update(keywords=["recipes", "pantry"]))
        _, report = kit.check_json(config)
        f = kit.findings(report, "apple.keywords.repeats_name", where="en-US")
        self.assertTrue(f)
        self.assertIn('"recipes"', f[0]["message"])
        self.assertNotIn("pantry", f[0]["message"])

    def test_other_platforms_in_apple_words(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["apple"].update(keywords=["android", "pantry"]))
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "apple.metadata.other_platforms", "error"))

    def test_extra_forbidden_words(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["rules"].update(extraForbiddenWords=["aisle"]))
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        f = kit.findings(report, "config.extra_forbidden_words")
        self.assertTrue(f)
        self.assertTrue(any("google.releaseNotes" in x["where"] for x in f))

    def test_categories_and_age_rating_values(self):
        config = self.sample()

        def change(d):
            d["stores"]["apple"]["categories"].update(primary="FOOD", primarySubcategories=["GAMES_PUZZLE"])
            d["stores"]["apple"]["ageRating"].update(contests="SOMETIMES", gambling="no", madeUp=True)
            d["stores"]["google"]["category"] = "COOKING"
        kit.edit_config(config, change)
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "apple.categories.known", where="primary"))
        self.assertTrue(kit.findings(report, "apple.categories.subcategories.known"))
        ages = [f["where"] for f in kit.findings(report, "apple.age_rating.values")]
        self.assertIn("stores.apple.ageRating.contests", ages)
        self.assertIn("stores.apple.ageRating.gambling", ages)
        self.assertIn("stores.apple.ageRating.madeUp", ages)
        self.assertTrue(kit.findings(report, "google.categories.known"))

    def test_games_subcategories_are_known(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["stores"]["apple"]["categories"].update(
            primary="GAMES", primarySubcategories=["GAMES_PUZZLE", "GAMES_WORD"]))
        _, report = kit.check_json(config)
        self.assertFalse(kit.findings(report, "apple.categories.subcategories.known"))

    def test_review_phone_from_the_environment_is_checked_not_printed(self):
        config = self.sample()
        os.environ["APPLE_REVIEW_PHONE"] = "5550100"
        code, report = kit.check_json(config)
        f = kit.findings(report, "apple.review.phone.format")
        self.assertEqual(len(f), 1)
        self.assertIn("APPLE_REVIEW_PHONE", f[0]["where"])
        self.assertNotIn("5550100", json.dumps(report))
        os.environ["APPLE_REVIEW_PHONE"] = "+1 555 0100"
        _, report = kit.check_json(config)
        self.assertFalse(kit.findings(report, "apple.review.phone.format"))

    def test_html_in_description_warns(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d.update(locales=dict(d["locales"], **{"en-US": dict(
            d["locales"]["en-US"], description="<b>Plan</b> a week of meals.")})))
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "apple.description.html", "warning"))

    def test_a_locale_the_store_doesnt_offer(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"].update({"eo": {"description": "Planu semajnon."}}))
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue(kit.findings(report, "config.locales", "error", "eo"))

    def test_primary_locale_must_be_a_locale(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d.update(primaryLocale="fr-FR"))
        code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue(kit.findings(report, "config.primary_locale"))


class Video(TempDir):
    def add_preview(self, config, name="iphone.mp4", data=b"\0" * 64):
        path = os.path.join(os.path.dirname(config), "previews", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        kit.edit_config(config, lambda d: d["stores"]["apple"]["platforms"]["IOS"].update(
            previews={"iphone": [{"file": "previews/" + name, "posterFrame": "00:00:05:00"}]}))
        return path

    def test_without_ffprobe_the_video_isnt_checked_and_says_so(self):
        config = self.sample()
        self.add_preview(config)
        with mock.patch.object(listing, "find_ffprobe", return_value=None):
            code, report = kit.check_json(config)
        self.assertEqual(code, 0)
        f = kit.findings(report, "apple.previews.video", "warning")
        self.assertEqual(len(f), 1)
        self.assertIn("ffprobe", f[0]["message"])

    def test_container_is_checked_without_ffprobe(self):
        config = self.sample()
        self.add_preview(config, "iphone.avi")
        with mock.patch.object(listing, "find_ffprobe", return_value=None):
            code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        self.assertTrue([f for f in kit.findings(report, "apple.previews.video", "error") if ".avi" in f["message"]])

    def test_parse_probe(self):
        got = listing.parse_probe({
            "streams": [{"codec_type": "video", "codec_name": "h264", "avg_frame_rate": "60/1", "width": 886,
                         "height": 1920}, {"codec_type": "audio", "codec_name": "aac"}],
            "format": {"duration": "12.5"}})
        self.assertEqual(got, {"codec": "h264", "fps": 60.0, "seconds": 12.5, "size": (886, 1920), "audio": True})

    def test_probed_video_is_held_to_the_rules(self):
        config = self.sample()
        self.add_preview(config)
        probe = {"codec": "hevc", "fps": 60.0, "seconds": 9.0, "size": (1080, 1920), "audio": False}
        with mock.patch.object(listing, "probe_video", return_value=probe):
            code, report = kit.check_json(config)
        self.assertEqual(code, 1)
        msgs = " | ".join(f["message"] for f in kit.findings(report, "apple.previews.video", "error"))
        for part in ("hevc", "60.00 fps", "9.0 s", "1080x1920"):
            self.assertIn(part, msgs)
        self.assertTrue(kit.findings(report, "apple.previews.audio_track", "warning"))

    @unittest.skipIf(listing.shutil.which("ffmpeg") is None or listing.find_ffprobe() is None, "ffmpeg isn't installed")
    def test_real_video_through_ffprobe(self):
        config = self.sample()
        path = self.add_preview(config)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=blue:s=886x1920:r=30:d=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", path], check=True)
        code, report = kit.check_json(config)
        msgs = " | ".join(f["message"] for f in kit.findings(report, "apple.previews.video", "error"))
        self.assertIn("at least 15 s", msgs)
        self.assertNotIn("886x1920", msgs)


class Builds(TempDir):
    """A temp folder and a build into it."""

    def build(self, config, out=None):
        out = out or os.path.join(self.tmp, "out")
        code, text, err = kit.run(["build", "--config", config, "--out", out])
        return code, out, text, err


class Build(Builds):

    def test_build_writes_the_layouts_and_manifest(self):
        config = self.sample()
        code, out, text, err = self.build(config)
        self.assertEqual(code, 0, text + err)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        self.assertEqual(m["version"], 1)
        self.assertEqual(m["config"], "project/store-listing.json")
        a = m["apple"]
        self.assertEqual(a["bundleId"], "com.example.samplerecipes")
        self.assertEqual(a["primaryLocale"], "en-US")
        self.assertEqual(a["app"]["localizations"]["en-US"]["name"], "Sample Recipes")
        self.assertEqual(a["app"]["localizations"]["de-DE"]["subtitle"], "Mahlzeiten schnell planen")
        self.assertEqual(a["app"]["categories"]["primary"], "FOOD_AND_DRINK")
        ios = a["platforms"]["IOS"]
        self.assertEqual(ios["localizations"]["en-US"]["keywords"].split(",")[:2], ["cooking", "dinner ideas"])
        self.assertTrue(ios["localizations"]["de-DE"]["description"].startswith("Plane"))
        iphone = ios["screenshots"]["en-US"]["APP_IPHONE_61"]
        self.assertEqual(len(iphone), 5)
        self.assertEqual(iphone[0]["file"], "apple/IOS/screenshots/en-US/01_APP_IPHONE_61_week.png")
        for entry in iphone + ios["screenshots"]["de-DE"]["APP_IPAD_PRO_3GEN_129"]:
            path = os.path.join(out, entry["file"])
            with open(path, "rb") as f:
                data = f.read()
            self.assertEqual(entry["md5"], hashlib.md5(data).hexdigest())
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(entry["size"], len(data))
        self.assertEqual(a["review"]["contact"]["phoneEnv"], "APPLE_REVIEW_PHONE")
        self.assertIsNone(a["review"]["demoAccount"])  # null in the config: no demo account needed
        self.assertNotIn("privacyPolicyText", a["app"]["localizations"]["en-US"])
        self.assertEqual(a["auth"], {"keyIdEnv": "ASC_KEY_ID", "issuerIdEnv": "ASC_ISSUER_ID",
                                     "privateKeyEnv": "ASC_PRIVATE_KEY"})
        self.assertEqual(m["google"]["auth"], {"serviceAccountEnv": "GOOGLE_PLAY_SERVICE_ACCOUNT"})
        g = m["google"]
        self.assertEqual(g["package"], "com.example.samplerecipes")
        self.assertEqual(g["defaultLanguage"], "en-US")
        self.assertEqual(g["details"]["contactEmail"], "support@example.com")
        self.assertEqual(g["listings"]["de-DE"]["title"], "Sample Recipes: Essensplaner")
        self.assertTrue(g["listings"]["en-US"]["fullDescription"].startswith("Plan a week"))
        self.assertIsNone(g["listings"]["en-US"]["video"])  # unset: Play's video is left as it is
        self.assertEqual(len(g["images"]["en-US"]["phoneScreenshots"]), 5)
        self.assertEqual(len(g["images"]["en-US"]["tenInchScreenshots"]), 4)
        self.assertEqual(g["images"]["en-US"]["icon"][0]["file"], "google/metadata/android/en-US/images/icon.png")
        self.assertEqual(g["dataSafetyCsv"], None)
        for rel in ("apple/IOS/metadata/en-US/subtitle.txt", "apple/IOS/metadata/de-DE/keywords.txt",
                    "apple/IOS/metadata/en-US/release_notes.txt", "apple/IOS/metadata/copyright.txt",
                    "google/metadata/android/en-US/title.txt", "google/metadata/android/de-DE/short_description.txt",
                    "google/metadata/android/en-US/images/phoneScreenshots/01_week.png",
                    "google/metadata/android/de-DE/images/featureGraphic.png", "checklist.md"):
            self.assertTrue(os.path.isfile(os.path.join(out, rel)), rel)
        with open(os.path.join(out, "apple/IOS/metadata/en-US/keywords.txt")) as f:
            self.assertNotIn(", ", f.read())

    def test_auth_names_and_demo_account_come_from_the_config(self):
        config = self.sample()

        def change(d):
            d["stores"]["apple"]["auth"] = {"keyIdEnv": "SR_ASC_KEY_ID"}
            d["stores"]["google"]["auth"] = {"serviceAccountEnv": "SR_PLAY_KEY"}
            d["stores"]["apple"]["review"]["demoAccount"] = {"usernameEnv": "SR_DEMO_USER",
                                                             "passwordEnv": "SR_DEMO_PASSWORD"}
        kit.edit_config(config, change)
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        self.assertEqual(m["apple"]["auth"], {"keyIdEnv": "SR_ASC_KEY_ID", "issuerIdEnv": "ASC_ISSUER_ID",
                                              "privateKeyEnv": "ASC_PRIVATE_KEY"})
        self.assertEqual(m["google"]["auth"], {"serviceAccountEnv": "SR_PLAY_KEY"})
        self.assertEqual(m["apple"]["review"]["demoAccount"], {"usernameEnv": "SR_DEMO_USER",
                                                               "passwordEnv": "SR_DEMO_PASSWORD"})

    def test_a_review_without_demo_account_leaves_it_out(self):
        config = self.sample()

        def change(d):
            d["stores"]["apple"]["review"] = {}
        kit.edit_config(config, change)
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        self.assertNotIn("demoAccount", m["apple"]["review"])  # push.py plan then leaves App Review's alone

    def test_de_de_gets_its_own_shot_and_the_rest_fall_back(self):
        config = self.sample()
        code, out, _, _ = self.build(config)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        de = m["apple"]["platforms"]["IOS"]["screenshots"]["de-DE"]["APP_IPHONE_61"]
        en = m["apple"]["platforms"]["IOS"]["screenshots"]["en-US"]["APP_IPHONE_61"]
        self.assertNotEqual(de[0]["md5"], en[0]["md5"])
        self.assertEqual(de[1]["md5"], en[1]["md5"])

    def test_pictures_are_copied_unchanged(self):
        config = self.sample()
        src = os.path.join(self.tmp, "project", "graphics", "feature-1024x500.png")
        with open(src, "rb") as f:
            before = f.read()
        code, out, _, _ = self.build(config)
        with open(os.path.join(out, "google/metadata/android/en-US/images/featureGraphic.png"), "rb") as f:
            self.assertEqual(f.read(), before)
        with open(src, "rb") as f:
            self.assertEqual(f.read(), before)

    def test_build_is_deterministic_but_for_builtAt(self):
        config = self.sample()
        _, out1, _, _ = self.build(config, os.path.join(self.tmp, "out1"))
        _, out2, _, _ = self.build(config, os.path.join(self.tmp, "out2"))

        def tree(root):
            files = {}
            for dirpath, _, names in os.walk(root):
                for n in names:
                    p = os.path.join(dirpath, n)
                    rel = os.path.relpath(p, root)
                    with open(p, "rb") as f:
                        data = f.read()
                    if rel == "listing.json":
                        d = json.loads(data)
                        d.pop("builtAt")
                        data = json.dumps(d).encode()
                    files[rel] = hashlib.sha256(data).hexdigest()
            return files
        self.assertEqual(tree(out1), tree(out2))

    def test_a_rebuild_drops_stale_files(self):
        config = self.sample()
        _, out, _, _ = self.build(config)
        stale = os.path.join(out, "apple", "IOS", "screenshots", "en-US", "05_APP_IPHONE_61_cooking-mode.png")
        self.assertTrue(os.path.isfile(stale))
        kit.edit_config(config, lambda d: d["screenshots"]["shots"].pop())
        code, out, _, _ = self.build(config)
        self.assertEqual(code, 0)
        self.assertFalse(os.path.exists(stale))

    def test_errors_stop_the_build(self):
        config = self.fixture("over-limit")
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 1)
        self.assertIn("Not built", text)
        self.assertFalse(os.path.exists(os.path.join(out, "listing.json")))

    def test_build_wont_overwrite_a_folder_that_isnt_a_build(self):
        config = self.sample()
        out = os.path.join(self.tmp, "elsewhere")
        os.makedirs(os.path.join(out, "apple"))
        code, _, _, err = self.build(config, out)
        self.assertEqual(code, 3)
        self.assertIn("doesn't look like a build folder", err)

    def test_checklist_has_rules_forms_and_drafted_answers(self):
        config = self.sample()
        _, out, _, _ = self.build(config)
        with open(os.path.join(out, "checklist.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("## App Store", text)
        self.assertIn("## Google Play", text)
        self.assertIn("`apple.screenshots.in_use`", text)
        self.assertIn("`google.forms.data_safety`", text)
        self.assertIn("App Privacy", text)
        self.assertIn("No data collected: recipes, plans and lists stay on the device.", text)
        self.assertIn("`googleTargetAudience`: 18 and over", text)
        self.assertIn("A phone showing a week of planned dinners", text)  # alt text to enter by hand
        self.assertIn("Category to choose: `FOOD_AND_DRINK`", text)

    def test_apple_tv_gets_its_privacy_text(self):
        config = self.sample()
        root = os.path.dirname(config)
        kit.write_png(os.path.join(root, "screenshots", "en-US", "tv", "week.png"), 1920, 1080)
        with open(os.path.join(root, "privacy.txt"), "w", encoding="utf-8") as f:
            f.write("Sample Recipes keeps your recipes on your devices.\n")

        def change(d):
            d["screens"]["tv"] = {"kind": "tv"}
            d["stores"]["apple"]["platforms"]["TV_OS"] = {"screens": ["tv"]}
        kit.edit_config(config, change)
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "apple.tv_privacy_text.required", "error"))
        kit.edit_config(config, lambda d: d["stores"]["apple"].update(tvPrivacyText="privacy.txt"))
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        locs = m["apple"]["app"]["localizations"]
        self.assertEqual(locs["en-US"]["privacyPolicyText"], "Sample Recipes keeps your recipes on your devices.")
        self.assertNotIn("privacyPolicyText", locs["de-DE"])
        self.assertNotIn("tvPrivacyText", m["apple"])
        self.assertEqual(len(m["apple"]["platforms"]["TV_OS"]["screenshots"]["en-US"]["APP_APPLE_TV"]), 1)
        self.assertTrue(os.path.isfile(os.path.join(out, "apple/TV_OS/metadata/en-US/apple_tv_privacy_policy.txt")))

    def test_preview_record_and_mime(self):
        config = self.sample()
        Video.add_preview(self, config)
        with mock.patch.object(listing, "find_ffprobe", return_value=None):
            code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json")) as f:
            m = json.load(f)
        prev = m["apple"]["platforms"]["IOS"]["previews"]["de-DE"]["IPHONE_61"]
        self.assertEqual(prev[0]["mime"], "video/mp4")
        self.assertEqual(prev[0]["posterFrame"], "00:00:05:00")
        self.assertTrue(os.path.isfile(os.path.join(out, prev[0]["file"])))


class Preview(TempDir):
    def built(self):
        config = self.sample()
        out = os.path.join(self.tmp, "out")
        code, text, err = kit.run(["build", "--config", config, "--out", out])
        self.assertEqual(code, 0, text + err)
        return out

    def test_html_pages_per_store_and_locale(self):
        out = self.built()
        code, text, err = kit.run(["preview", "--out", out])
        self.assertEqual(code, 0, err)
        folder = os.path.join(out, "preview")
        for name in ("index.html", "apple-IOS-en-US.html", "apple-IOS-de-DE.html", "google-en-US.html",
                     "google-de-DE.html", "preview.css"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        with open(os.path.join(folder, "apple-IOS-en-US.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("An approximation of the App Store", page)
        self.assertIn("Plan meals in minutes", page)
        self.assertIn('class="search-shots"', page)
        self.assertEqual(page.count("01_APP_IPHONE_61_week.png"), 2)  # search row and carousel
        self.assertIn("03_APP_IPHONE_61_grocery-list.png", page)
        with open(os.path.join(folder, "google-de-DE.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn("Sample Recipes: Essensplaner", page)
        self.assertIn("featureGraphic.png", page)

    def test_preview_needs_a_build(self):
        code, _, err = kit.run(["preview", "--out", os.path.join(self.tmp, "nothing")])
        self.assertEqual(code, 3)
        self.assertIn("build", err)

    def test_png_without_chrome_is_an_environment_error(self):
        out = self.built()
        with mock.patch.object(chrome, "find_chrome", side_effect=chrome.ChromeNotFound("no Chrome here")):
            code, _, err = kit.run(["preview", "--out", out, "--png"])
        self.assertEqual(code, 3)
        self.assertIn("no Chrome here", err)
        self.assertTrue(os.path.isfile(os.path.join(out, "preview", "index.html")))

    @unittest.skipIf(CHROME is None, "Google Chrome or Chromium isn't installed")
    def test_png_rendering(self):
        out = self.built()
        code, text, err = kit.run(["preview", "--out", out, "--png"])
        self.assertEqual(code, 0, err)
        from appstores_lib import png
        info = png.info(os.path.join(out, "preview", "apple-IOS-en-US.png"))
        self.assertEqual(info.width, 780)
        self.assertTrue(1688 < info.height <= 12000, info.height)  # the whole page, at 2x
        info = png.info(os.path.join(out, "preview", "google-en-US-desktop.png"))
        self.assertEqual(info.width, 1280)
        self.assertTrue(os.path.isfile(os.path.join(out, "preview", "google-de-DE-phone.png")))


class PlatformWords(Builds):
    """App Store Connect keeps a version's words per platform: locales.<loc>.apple.platforms.<P> overrides them."""

    TV_DESCRIPTION = "Plan a week of meals from the couch.\n\nA game controller isn't needed: the Siri Remote does it all."

    def with_tv(self, config, override=None):
        root = os.path.dirname(config)
        kit.write_png(os.path.join(root, "screenshots", "en-US", "tv", "week.png"), 1920, 1080)
        with open(os.path.join(root, "privacy.txt"), "w", encoding="utf-8") as f:
            f.write("Sample Recipes keeps your recipes on your devices.\n")

        def change(d):
            d["screens"]["tv"] = {"kind": "tv"}
            d["stores"]["apple"]["platforms"]["TV_OS"] = {"screens": ["tv"]}
            d["stores"]["apple"]["tvPrivacyText"] = "privacy.txt"
            d["screenshots"]["shots"][0]["$comment"] = "the only shot on the TV"
            for shot in d["screenshots"]["shots"][1:]:
                shot["screens"] = [s for s in (shot["screens"] or list(d["screens"])) if s != "tv"]
            if override is not None:
                d["locales"]["en-US"]["apple"]["platforms"] = {"TV_OS": override}
        kit.edit_config(config, change)

    def manifest(self, out):
        with open(os.path.join(out, "listing.json"), encoding="utf-8") as f:
            return json.load(f)

    def test_each_platform_gets_its_own_words(self):
        config = self.sample()
        self.with_tv(config, {"description": self.TV_DESCRIPTION, "keywords": ["couch", "recipes"],
                              "supportUrl": "https://example.com/tv-support"})
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        m = self.manifest(out)
        ios, tv = m["apple"]["platforms"]["IOS"]["localizations"], m["apple"]["platforms"]["TV_OS"]["localizations"]
        self.assertTrue(ios["en-US"]["description"].startswith("Plan a week of meals in minutes."))
        self.assertEqual(tv["en-US"]["description"], self.TV_DESCRIPTION)
        self.assertEqual(tv["en-US"]["keywords"], "couch,recipes")
        self.assertEqual(tv["en-US"]["supportUrl"], "https://example.com/tv-support")
        self.assertEqual(ios["en-US"]["supportUrl"], "https://example.com/support")
        # what TV_OS doesn't override is the locale's own words
        self.assertEqual(tv["en-US"]["promotionalText"], ios["en-US"]["promotionalText"])
        # de-DE has its own shared description: it beats en-US's TV override
        self.assertTrue(tv["de-DE"]["description"].startswith("Plane eine Woche"))
        with open(os.path.join(out, "apple/TV_OS/metadata/en-US/description.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), self.TV_DESCRIPTION)
        with open(os.path.join(out, "apple/TV_OS/metadata/en-US/support_url.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read(), "https://example.com/tv-support")
        with open(os.path.join(out, "apple/IOS/metadata/en-US/description.txt"), encoding="utf-8") as f:
            self.assertTrue(f.read().startswith("Plan a week of meals in minutes."))

    def test_a_locale_without_an_override_takes_the_primarys_for_that_platform(self):
        config = self.sample()
        self.with_tv(config, {"promotionalText": "Now on the big screen."})
        kit.edit_config(config, lambda d: d["locales"]["de-DE"]["apple"].pop("promotionalText"))
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        tv = self.manifest(out)["apple"]["platforms"]["TV_OS"]["localizations"]
        self.assertEqual(tv["de-DE"]["promotionalText"], "Now on the big screen.")

    def test_rules_run_on_each_platforms_words(self):
        config = self.sample()
        self.with_tv(config, {"description": self.TV_DESCRIPTION + " Also on Android.", "promotionalText": "x" * 171})
        _, report = kit.check_json(config)
        others = kit.findings(report, "apple.metadata.other_platforms", where="apple.description")
        self.assertEqual([f["where"] for f in others], ["en-US apple.description (TV_OS)"])
        promo = kit.findings(report, "apple.promotional_text.length")
        self.assertEqual([f["where"] for f in promo], ["en-US apple.promotionalText (TV_OS)"])

    def test_the_same_words_on_every_platform_are_checked_once(self):
        config = self.sample()
        self.with_tv(config)
        kit.edit_config(config, lambda d: d["locales"]["en-US"].update(
            description=d["locales"]["en-US"]["description"] + " Also on Android."))
        _, report = kit.check_json(config)
        others = kit.findings(report, "apple.metadata.other_platforms", where="apple.description")
        self.assertEqual([f["where"] for f in others], ["en-US apple.description"])

    def test_words_for_a_platform_not_shipped_warn(self):
        config = self.sample()
        kit.edit_config(config, lambda d: d["locales"]["en-US"]["apple"].update(
            platforms={"MAC_OS": {"description": "On the Mac."}}))
        _, report = kit.check_json(config)
        found = kit.findings(report, "config.platforms", "warning", "locales.en-US.apple.platforms.MAC_OS")
        self.assertTrue(found)


class StoreLocales(Builds):
    """Each store gets its own locales (stores.<store>.locales) and falls back to its own primary first."""

    def test_each_store_gets_only_its_locales(self):
        config = self.sample()

        def change(d):
            d["stores"]["apple"]["locales"] = ["de-DE"]
            d["stores"]["apple"]["primaryLocale"] = "de-DE"
            d["stores"]["google"]["locales"] = ["en-US"]
        kit.edit_config(config, change)
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json"), encoding="utf-8") as f:
            m = json.load(f)
        self.assertEqual(m["apple"]["primaryLocale"], "de-DE")
        self.assertEqual(list(m["apple"]["app"]["localizations"]), ["de-DE"])
        self.assertEqual(list(m["apple"]["platforms"]["IOS"]["localizations"]), ["de-DE"])
        self.assertEqual(list(m["apple"]["platforms"]["IOS"]["screenshots"]), ["de-DE"])
        self.assertEqual(m["google"]["defaultLanguage"], "en-US")
        self.assertEqual(list(m["google"]["listings"]), ["en-US"])
        self.assertEqual(list(m["google"]["images"]), ["en-US"])
        self.assertFalse(os.path.exists(os.path.join(out, "apple/IOS/metadata/en-US")))
        self.assertFalse(os.path.exists(os.path.join(out, "google/metadata/android/de-DE")))

    def test_fields_fall_back_to_the_stores_primary_then_the_configs(self):
        config = self.sample()

        def change(d):
            d["locales"]["fr-FR"] = {"apple": {"subtitle": "Vos repas en quelques minutes"}}
            d["locales"]["fr-CA"] = {"$comment": "nothing of its own"}
            d["stores"]["apple"]["locales"] = ["fr-FR", "fr-CA"]
            d["stores"]["apple"]["primaryLocale"] = "fr-FR"
            d["stores"]["google"]["locales"] = ["en-US"]
        kit.edit_config(config, change)
        code, report = kit.check_json(config)
        self.assertEqual(code, 0, kit.findings(report, severity="error"))
        self.assertIn({"store": "apple", "locale": "fr-CA", "what": "apple.subtitle", "from": "fr-FR"},
                      report["fallbacks"])
        self.assertIn({"store": "apple", "locale": "fr-CA", "what": "apple.description", "from": "en-US"},
                      report["fallbacks"])
        code, out, text, _ = self.build(config)
        self.assertEqual(code, 0, text)
        with open(os.path.join(out, "listing.json"), encoding="utf-8") as f:
            m = json.load(f)
        locs = m["apple"]["app"]["localizations"]
        self.assertEqual(list(locs), ["fr-FR", "fr-CA"])
        self.assertEqual(locs["fr-CA"]["subtitle"], "Vos repas en quelques minutes")
        self.assertEqual(locs["fr-FR"]["name"], "Sample Recipes")
        words = m["apple"]["platforms"]["IOS"]["localizations"]
        self.assertTrue(words["fr-CA"]["description"].startswith("Plan a week of meals"))

    def test_a_stores_primary_must_be_one_of_its_locales(self):
        config = self.sample(pictures=False)
        kit.edit_config(config, lambda d: d["stores"]["google"].update(locales=["de-DE"]))
        _, report = kit.check_json(config)
        found = kit.findings(report, "config.default_language", "error")
        self.assertTrue(found and "stores.google.locales" in found[0]["message"], report["findings"])
        kit.edit_config(config, lambda d: (d["stores"]["google"].pop("locales"),
                                           d["stores"]["apple"].update(locales=["de-DE"])))
        _, report = kit.check_json(config)
        self.assertTrue(kit.findings(report, "config.primary_locale", "error", "primaryLocale"))
        kit.edit_config(config, lambda d: d["stores"]["apple"].update(locales=["de-DE", "fr-FR"],
                                                                     primaryLocale="de-DE"))
        _, report = kit.check_json(config)
        self.assertFalse(kit.findings(report, "config.primary_locale"))
        self.assertTrue(kit.findings(report, "config.locales", "error", "stores.apple.locales[1]"))


class PreviewPages(Builds):
    def built(self, config):
        code, out, text, err = self.build(config)
        self.assertEqual(code, 0, text + err)
        code, _, err = kit.run(["preview", "--out", out])
        self.assertEqual(code, 0, err)
        return out

    def test_plays_developer_line_is_who_made_it_not_the_package(self):
        out = self.built(self.sample())
        with open(os.path.join(out, "preview", "google-en-US.html"), encoding="utf-8") as f:
            page = f.read()
        self.assertIn('<div class="dev">Example Studio</div>', page)
        self.assertNotIn("com.example.samplerecipes", page)

    def test_descriptions_show_whole_lines_never_a_cut_word(self):
        out = self.built(self.sample())
        with open(os.path.join(out, "preview", "preview.css"), encoding="utf-8") as f:
            css = f.read()
        for selector in (".as .description", ".as .whats-new", ".gp .full"):
            rule = css[css.index(selector + " {"):]
            rule = rule[:rule.index("}")]
            # Chrome's line clamp can cut a word and glue an ellipsis on: these clip after whole lines
            self.assertNotIn("line-clamp", rule, selector)
            self.assertIn("max-height", rule, selector)

    @unittest.skipIf(CHROME is None, "Google Chrome or Chromium isn't installed")
    def test_wide_pages_are_rendered_whole(self):
        config = self.sample()
        PlatformWords.with_tv(self, config, {"description": "\n\n".join(["A long paragraph of words."] * 30)})
        out = self.built(config)
        code, _, err = kit.run(["preview", "--out", out, "--png"])
        self.assertEqual(code, 0, err)
        from appstores_lib import png
        info = png.info(os.path.join(out, "preview", "apple-TV_OS-en-US.png"))
        self.assertEqual(info.width, 1280)
        self.assertTrue(1100 < info.height <= 6000, info.height)  # down past the screenshots to What's New
        w, h, rgb = png.decode_rgb(os.path.join(out, "preview", "apple-TV_OS-en-US.png"))
        bottom = rgb[(h - 1) * w * 3:h * w * 3]
        self.assertEqual(set(bottom), {255}, "the page ends inside the picture (white below the last words)")


class CommandLine(TempDir):
    def test_missing_config_is_exit_3(self):
        code, _, err = kit.run(["check", "--config", os.path.join(self.tmp, "nope.json")])
        self.assertEqual(code, 3)
        self.assertIn("no config", err)

    def test_unknown_store_is_exit_3(self):
        config = self.sample(pictures=False)
        code, _, _ = kit.run(["check", "--config", config, "--stores", "nokia"])
        self.assertEqual(code, 3)

    def test_bad_usage_is_exit_3(self):
        code, _, _ = kit.run(["frobnicate"])
        self.assertEqual(code, 3)

    def test_runs_as_a_script(self):
        config = self.fixture("price-words")
        proc = subprocess.run([sys.executable, os.path.join(kit.SCRIPTS_DIR, "listing.py"), "check", "--config",
                               config, "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(proc.returncode, 1, proc.stderr)
        report = json.loads(proc.stdout.decode())
        self.assertTrue(kit.findings(report, "apple.metadata.prices"))

    def test_broken_json_is_a_check_error(self):
        path = os.path.join(self.tmp, "store-listing.json")
        with open(path, "w") as f:
            f.write("{ nope")
        code, out, _ = kit.run(["check", "--config", path])
        self.assertEqual(code, 1)
        self.assertIn("config.json", out)


if __name__ == "__main__":
    unittest.main()
