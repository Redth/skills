"""Tests for ``listing.py import``: fastlane (deliver), supply, Triple-T and Expo into one config, merging, and
never copying App Review's contact or demo account. Fixtures: ``evals/files/*-import/`` (words only; the
pictures are drawn here)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import listing_testkit as kit  # noqa: E402

FASTLANE = os.path.join(kit.FILES, "fastlane-import", "fastlane")
SUPPLY = os.path.join(kit.FILES, "supply-import", "fastlane", "metadata", "android")
TRIPLE_T = os.path.join(kit.FILES, "triple-t-import", "app")
EXPO = os.path.join(kit.FILES, "expo-import", "store.config.json")

# What fastlane's review_information and Expo's apple.review hold (invented, but personal in a real project)
PERSONAL = ("Reviewer", "review@example.com", "555 0100", "Testfirst", "Testlast", "not-a-real-password",
            "demo-user@example.com")


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="listing-import-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.config = os.path.join(self.tmp, "project", "store-listing.json")
        os.makedirs(os.path.dirname(self.config))

    def imp(self, source, path):
        code, out, err = kit.run(["import", "--from", source, path, "--out", self.config])
        self.assertEqual(code, 0, out + err)
        return out

    def data(self):
        with open(self.config, encoding="utf-8") as f:
            return json.load(f)

    def text(self):
        with open(self.config, encoding="utf-8") as f:
            return f.read()

    def assert_no_personal(self):
        text = self.text()
        for value in PERSONAL:
            self.assertNotIn(value, text)

    def assert_schema_valid(self):
        code, report = kit.check_json(self.config)
        self.assertFalse(kit.findings(report, "config.schema"), report["findings"])
        return report

    def copy_tree(self, src, name):
        dst = os.path.join(self.tmp, name)
        shutil.copytree(src, dst)
        return dst


class Fastlane(ImportTest):
    def test_words_urls_and_categories(self):
        out = self.imp("fastlane", FASTLANE)
        d = self.data()
        self.assertEqual(d["app"]["name"], "Sample Recipes")
        self.assertEqual(d["app"]["copyright"], "2026 Example Studio")
        self.assertEqual(d["app"]["urls"]["support"], "https://example.com/support")
        self.assertEqual(d["primaryLocale"], "en-US")
        en = d["locales"]["en-US"]
        self.assertEqual(en["apple"]["subtitle"], "Plan meals in minutes")
        self.assertEqual(en["apple"]["keywords"], ["recipes", "meal plan", "Sample Recipes", "grocery", "android"])
        self.assertEqual(en["apple"]["whatsNew"], "Bug fixes and improvements.")
        self.assertTrue(en["description"].startswith("Plan a week"))
        self.assertNotIn("name", en["apple"])  # it's app.name
        de = d["locales"]["de-DE"]
        self.assertNotIn("name", de.get("apple", {}))  # falls back
        self.assertEqual(de["apple"]["subtitle"], "Mahlzeiten in Minuten planen")
        self.assertEqual(d["stores"]["apple"]["categories"]["primary"], "FOOD_AND_DRINK")
        self.assertEqual(d["stores"]["apple"]["categories"]["secondary"], "LIFESTYLE")
        self.assertIn("Bug fixes and improvements", out)  # flagged to rewrite
        self.assertIn("--from supply", out)
        self.assert_schema_valid()

    def test_review_information_is_never_copied(self):
        out = self.imp("fastlane", FASTLANE)
        self.assert_no_personal()
        review = self.data()["stores"]["apple"]["review"]
        self.assertEqual(review["contact"], {"firstNameEnv": "APPLE_REVIEW_FIRST_NAME",
                                             "lastNameEnv": "APPLE_REVIEW_LAST_NAME",
                                             "phoneEnv": "APPLE_REVIEW_PHONE", "emailEnv": "APPLE_REVIEW_EMAIL"})
        self.assertTrue(review["notes"].startswith("No sign-in needed"))
        self.assertIn("Not copied", out)
        self.assertIn("APPLE_REVIEW_PHONE", out)
        for value in PERSONAL:
            self.assertNotIn(value, out)

    def test_the_check_then_finds_what_evals_expect(self):
        self.imp("fastlane", FASTLANE)
        _, report = kit.check_json(self.config, "--stores", "apple")
        self.assertTrue(kit.findings(report, "apple.metadata.other_platforms", "error", "apple.keywords"))
        repeats = kit.findings(report, "apple.keywords.repeats_name")
        self.assertTrue(repeats)
        self.assertIn("recipes", repeats[0]["message"])

    def test_screenshots_go_to_slots_by_size(self):
        root = self.copy_tree(os.path.join(kit.FILES, "fastlane-import"), "fl")
        shots = os.path.join(root, "fastlane", "screenshots")
        kit.write_png(os.path.join(shots, "en-US", "1_iPhone-01.png"), 1320, 2868)
        kit.write_png(os.path.join(shots, "en-US", "1_iPhone-02.png"), 1320, 2868)
        kit.write_png(os.path.join(shots, "en-US", "2_iPad-01.png"), 2064, 2752)
        kit.write_png(os.path.join(shots, "en-US", "odd.png"), 1000, 1000)
        kit.write_png(os.path.join(shots, "de-DE", "1_iPhone-01.png"), 1320, 2868)
        out = self.imp("fastlane", os.path.join(root, "fastlane"))
        d = self.data()
        self.assertEqual(d["stores"]["apple"]["platforms"]["IOS"]["screens"], ["iphone-67", "ipad-pro-3gen-129"])
        self.assertEqual(d["screens"]["iphone-67"], {"kind": "phone"})
        self.assertEqual(d["screens"]["ipad-pro-3gen-129"], {"kind": "tablet"})
        self.assertEqual([s["id"] for s in d["screenshots"]["shots"]], ["shot-01", "shot-02"])
        base = os.path.join(self.tmp, "project", "screenshots")
        for rel in ("en-US/iphone-67/shot-01.png", "en-US/iphone-67/shot-02.png", "en-US/ipad-pro-3gen-129/shot-01.png",
                    "de-DE/iphone-67/shot-01.png"):
            self.assertTrue(os.path.isfile(os.path.join(base, rel)), rel)
        self.assertIn("odd.png (1000x1000) fits no App Store slot", out)

    def test_running_it_twice_changes_nothing(self):
        self.imp("fastlane", FASTLANE)
        before = self.text()
        out = self.imp("fastlane", FASTLANE)
        self.assertEqual(self.text(), before)
        self.assertNotIn("Took", out)
        self.assertIn("Merged into", out)

    def test_merge_never_overwrites(self):
        kit.make_sample(os.path.join(self.tmp, "project"), pictures=False)
        before = self.data()
        out = self.imp("fastlane", FASTLANE)
        d = self.data()
        self.assertEqual(d["locales"]["en-US"]["apple"]["subtitle"], before["locales"]["en-US"]["apple"]["subtitle"])
        self.assertEqual(d["locales"]["en-US"]["apple"]["keywords"], before["locales"]["en-US"]["apple"]["keywords"])
        self.assertEqual(d["locales"]["en-US"]["description"], before["locales"]["en-US"]["description"])
        self.assertIsNone(d["locales"]["en-US"]["apple"]["description"])  # no override sneaked in
        self.assertIn("Kept what the config already had", out)
        self.assertIn("locales.de-DE.description", out)
        self.assertEqual(d["stores"]["google"], before["stores"]["google"])

    def test_nothing_to_import_is_exit_3(self):
        empty = os.path.join(self.tmp, "empty")
        os.makedirs(empty)
        code, _, err = kit.run(["import", "--from", "fastlane", empty, "--out", self.config])
        self.assertEqual(code, 3)
        self.assertIn("no fastlane deliver metadata", err)
        code, _, _ = kit.run(["import", "--from", "expo", os.path.join(self.tmp, "nope"), "--out", self.config])
        self.assertEqual(code, 3)


class Supply(ImportTest):
    def test_fastlane_then_supply_makes_one_config(self):
        self.imp("fastlane", FASTLANE)
        out = self.imp("supply", os.path.join(FASTLANE, "metadata", "android"))
        d = self.data()
        self.assertTrue(d["stores"]["apple"]["enabled"])
        self.assertTrue(d["stores"]["google"]["enabled"])
        self.assertEqual(d["locales"]["en-US"]["google"]["title"], "Sample Recipes: Meal Planner")
        self.assertNotIn("fullDescription", d["locales"]["en-US"]["google"])  # same as the shared description
        self.assertEqual(d["stores"]["google"]["defaultLanguage"], "en-US")
        self.assertIn("app.ids.google.package", out)
        self.assert_no_personal()
        self.assert_schema_valid()

    def test_play_default_is_one_of_plays_languages(self):
        # An App Store listing in en-CA imported first, then Play's in en-US and de-DE: Play's default is en-US,
        # not the config's primary (which Play has no listing in).
        meta = os.path.join(self.tmp, "deliver", "metadata", "en-CA")
        os.makedirs(meta)
        with open(os.path.join(meta, "name.txt"), "w", encoding="utf-8") as f:
            f.write("Sample Recipes\n")
        self.imp("fastlane", os.path.join(self.tmp, "deliver"))
        out = self.imp("supply", SUPPLY)
        d = self.data()
        self.assertEqual(d["primaryLocale"], "en-CA")
        self.assertEqual(d["stores"]["google"]["defaultLanguage"], "en-US")
        self.assertIn("defaultLanguage is en-US", out)

    def test_supply_words_pictures_and_changelog(self):
        root = self.copy_tree(os.path.join(kit.FILES, "supply-import"), "sp")
        android = os.path.join(root, "fastlane", "metadata", "android")
        for i in range(3):
            kit.write_png(os.path.join(android, "en-US", "images", "phoneScreenshots", "%d_en-US.png" % (i + 1)),
                          1080, 1920)
        kit.write_png(os.path.join(android, "en-US", "images", "tenInchScreenshots", "1_en-US.png"), 1920, 1080)
        kit.write_png(os.path.join(android, "en-US", "images", "icon.png"), 512, 512)
        kit.write_png(os.path.join(android, "en-US", "images", "featureGraphic.png"), 1024, 500)
        kit.write_png(os.path.join(android, "de-DE", "images", "featureGraphic.png"), 1024, 500, rgb=(9, 9, 9))
        out = self.imp("supply", os.path.join(root, "fastlane"))
        d = self.data()
        self.assertEqual(d["app"]["name"], "Sample Recipes")
        g = d["locales"]["en-US"]["google"]
        self.assertEqual(g["video"], "https://www.youtube.com/watch?v=AAAAAAAAAAA")
        self.assertEqual(g["releaseNotes"], "Pantry suggestions, and the grocery list sorts by aisle.")
        self.assertIn("changelogs/12.txt", out)
        self.assertNotIn("description", d["locales"]["de-DE"])  # the same as en-US's: falls back
        self.assertEqual(d["locales"]["de-DE"]["google"]["title"], "Sample Recipes: Essensplaner")
        slots = d["stores"]["google"]["slots"]
        self.assertEqual(slots["phone"], "android-phone")
        self.assertEqual(slots["tablet10"], "android-tablet10")
        self.assertEqual(d["stores"]["google"]["graphics"]["icon"], "graphics/icon.png")
        self.assertEqual(d["stores"]["google"]["graphics"]["featureGraphic"], "graphics/featureGraphic.png")
        self.assertIn("de-DE has its own featureGraphic", out)
        project = os.path.join(self.tmp, "project")
        self.assertTrue(os.path.isfile(os.path.join(project, "screenshots/en-US/android-phone/shot-03.png")))
        self.assertTrue(os.path.isfile(os.path.join(project, "graphics/icon.png")))
        report = self.assert_schema_valid()
        self.assertFalse(kit.findings(report, "google.icon.required"))
        self.assertFalse(kit.findings(report, "google.screenshots.minimum"))


class TripleT(ImportTest):
    def test_triple_t(self):
        root = self.copy_tree(os.path.join(kit.FILES, "triple-t-import"), "tt")
        play = os.path.join(root, "app", "src", "main", "play")
        gfx = os.path.join(play, "listings", "en-US", "graphics")
        kit.write_png(os.path.join(gfx, "phone-screenshots", "a.png"), 1080, 1920)
        kit.write_png(os.path.join(gfx, "phone-screenshots", "b.png"), 1080, 1920)
        kit.write_png(os.path.join(gfx, "large-tablet-screenshots", "a.png"), 1920, 1080)
        kit.write_png(os.path.join(gfx, "icon", "icon.png"), 512, 512)
        kit.write_png(os.path.join(gfx, "feature-graphic", "feature.png"), 1024, 500)
        out = self.imp("triple-t", os.path.join(root, "app"))
        d = self.data()
        self.assertEqual(d["primaryLocale"], "en-US")
        self.assertEqual(d["app"]["contact"]["email"], "support@example.com")
        self.assertEqual(d["app"]["contact"]["website"], "https://example.com")
        self.assertEqual(d["locales"]["en-US"]["google"]["releaseNotes"],
                         "Pantry suggestions, and the grocery list sorts by aisle.")
        self.assertIn("release-notes/en-US/production.txt", out)
        self.assertEqual(d["locales"]["de-DE"]["description"], "Plane eine Woche voller Mahlzeiten in Minuten.")
        self.assertEqual(d["stores"]["google"]["slots"]["phone"], "android-phone")
        self.assertEqual(d["stores"]["google"]["slots"]["tablet10"], "android-tablet10")
        self.assertEqual(d["stores"]["google"]["graphics"]["featureGraphic"], "graphics/featureGraphic.png")
        self.assert_schema_valid()


class Expo(ImportTest):
    def test_expo(self):
        out = self.imp("expo", EXPO)
        d = self.data()
        self.assertEqual(d["app"]["name"], "Sample Recipes")
        en = d["locales"]["en-US"]
        self.assertEqual(en["apple"]["keywords"], ["cooking", "dinner ideas", "grocery list"])
        self.assertEqual(en["apple"]["promotionalText"], "Plan a whole week from what's already in your fridge.")
        self.assertEqual(en["apple"]["whatsNew"], "The grocery list now sorts by aisle.")
        self.assertNotIn("name", d["locales"]["de-DE"].get("apple", {}))
        a = d["stores"]["apple"]
        self.assertEqual(a["categories"]["primary"], "GAMES")
        self.assertEqual(a["categories"]["primarySubcategories"], ["GAMES_PUZZLE", "GAMES_WORD"])
        self.assertEqual(a["categories"]["secondary"], "EDUCATION")
        self.assertEqual(a["ageRating"], {"violenceCartoonOrFantasy": "NONE", "contests": "INFREQUENT_OR_MILD",
                                          "gambling": False})
        self.assertIn("seventeenPlus", out)
        self.assertEqual(a["review"]["notes"], "Sign in with the demo account to see shared lists.")
        self.assertEqual(a["review"]["demoAccount"], {"usernameEnv": "APPLE_REVIEW_DEMO_USER",
                                                      "passwordEnv": "APPLE_REVIEW_DEMO_PASSWORD"})
        self.assert_no_personal()
        for value in PERSONAL:
            self.assertNotIn(value, out)
        report = self.assert_schema_valid()
        self.assertFalse(kit.findings(report, "apple.categories.subcategories.known"))
        self.assertFalse(kit.findings(report, "apple.age_rating.values"))

    def test_expo_folder_path(self):
        self.imp("expo", os.path.dirname(EXPO))
        self.assertEqual(self.data()["app"]["copyright"], "2026 Example Studio")


if __name__ == "__main__":
    unittest.main()
