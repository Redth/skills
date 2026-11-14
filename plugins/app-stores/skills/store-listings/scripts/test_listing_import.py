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
        # one display type per device class: the screens are named by the class
        self.assertEqual(d["stores"]["apple"]["platforms"]["IOS"]["screens"], ["iphone", "ipad"])
        self.assertEqual(d["screens"]["iphone"], {"kind": "phone"})
        self.assertEqual(d["screens"]["ipad"], {"kind": "tablet"})
        # "1_iPhone-01" names no moment: shot-NN, in file order
        self.assertEqual([s["id"] for s in d["screenshots"]["shots"]], ["shot-01", "shot-02"])
        self.assertIn("don't say which moment", out)
        base = os.path.join(self.tmp, "project", "screenshots")
        for rel in ("en-US/iphone/shot-01.png", "en-US/iphone/shot-02.png", "en-US/ipad/shot-01.png",
                    "de-DE/iphone/shot-01.png"):
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
        self.assertEqual(slots["tablet10"], "android-tablet")  # the only tablet screen
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
        self.assertEqual(d["stores"]["google"]["slots"]["tablet10"], "android-tablet")
        self.assertEqual(d["stores"]["google"]["graphics"]["featureGraphic"], "graphics/featureGraphic.png")
        # Triple-T's file names are the shot ids
        self.assertEqual([s["id"] for s in d["screenshots"]["shots"]], ["a", "b"])
        self.assert_schema_valid()


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")


def deliver(root, locale, words, shots=()):
    """A fastlane deliver folder: ``metadata/<locale>/<field>.txt`` and ``screenshots/<locale>/<name>`` at
    ``(name, width, height)``."""
    for field, text in words.items():
        write_text(os.path.join(root, "metadata", locale, field + ".txt"), text)
    for name, w, h in shots:
        kit.write_png(os.path.join(root, "screenshots", locale, name), w, h, rgb=(len(name) * 7 % 255, 90, 160))
    return root


IOS_WORDS = {"name": "Sample Recipes", "subtitle": "Plan meals in minutes", "description": "Plan a week of meals.",
             "keywords": "recipes,meal plan", "promotional_text": "Fresh this month.",
             "support_url": "https://example.com/support"}


class ShotIds(unittest.TestCase):
    def test_ids_from_file_names(self):
        import listing_import as imp
        cases = [
            ("01-plan-week-iphone.jpg", None, "plan-week"),
            ("03-recipe-android-phone.png", None, "recipe"),
            ("02-recipe-appletv.jpg", None, "recipe"),
            ("04-pantry-ipad.png", None, "pantry"),
            ("05_APP_IPHONE_67_pantry.png", None, "pantry"),
            ("iPhone 15 Pro Max-01_home.png", None, "home"),
            ("Apple TV 4K-02_menu.png", None, "menu"),
            ("grocery-list-1290x2796.png", None, "grocery-list"),
            ("week-de-DE.png", "de-DE", "week"),
            ("level-2.png", None, "level-2"),
            ("1_iPhone-01.png", None, None),
            ("1_en-US.png", "en-US", None),
            ("screenshot-3.png", None, None),
        ]
        for name, loc, want in cases:
            self.assertEqual(imp.shot_id_from_name(name, loc, ["APP_IPHONE_67"]), want, name)

    def test_a_folder_whose_names_dont_all_say_falls_back_to_numbers(self):
        import listing_import as imp
        self.assertEqual(imp.shot_ids(["01-plan-iphone.png", "02-recipe-iphone.png"]), (["plan", "recipe"], True))
        self.assertEqual(imp.shot_ids(["01-plan-iphone.png", "02-iphone.png"]), (["shot-01", "shot-02"], False))
        self.assertEqual(imp.shot_ids(["plan-iphone.png", "plan-ipad.png"]), (["shot-01", "shot-02"], False))

    def test_merge_order_keeps_each_folders_order(self):
        import listing_import as imp
        order = imp.merge_order([], ["plan", "recipe", "pantry"])
        imp.merge_order(order, ["plan", "cooking", "pantry"])
        self.assertEqual(order, ["plan", "cooking", "recipe", "pantry"])
        imp.merge_order(order, ["intro", "plan"])
        self.assertEqual(order[0], "intro")


class Platforms(ImportTest):
    """Several Apple platforms' fastlane folders into one config; Play's identical slots; each store's locales."""

    def test_names_become_shot_ids_that_mean_the_same_moment_on_every_screen(self):
        root = deliver(os.path.join(self.tmp, "ios"), "en-US", IOS_WORDS, [
            ("01-plan-iphone.png", 1320, 2868), ("02-recipe-iphone.png", 1320, 2868),
            ("01-plan-ipad.png", 2064, 2752), ("02-pantry-ipad.png", 2064, 2752)])
        self.imp("fastlane", root)
        d = self.data()
        self.assertEqual(d["stores"]["apple"]["platforms"]["IOS"]["screens"], ["iphone", "ipad"])
        shots = dict((s["id"], s["screens"]) for s in d["screenshots"]["shots"])
        self.assertEqual(shots, {"plan": None, "recipe": ["iphone"], "pantry": ["ipad"]})
        self.assertEqual(d["screenshots"]["shots"][0]["id"], "plan")
        base = os.path.join(self.tmp, "project", "screenshots", "en-US")
        for rel in ("iphone/plan.png", "iphone/recipe.png", "ipad/plan.png", "ipad/pantry.png"):
            self.assertTrue(os.path.isfile(os.path.join(base, rel)), rel)
        _, report = kit.check_json(self.config, "--stores", "apple")
        self.assertFalse(kit.findings(report, "config.screenshots"), report["findings"])

    def test_two_display_types_of_one_class_keep_their_codes(self):
        root = deliver(os.path.join(self.tmp, "ios"), "en-US", IOS_WORDS, [
            ("01-plan-iphone.png", 1320, 2868), ("01-plan-iphone-small.png", 1206, 2622)])
        self.imp("fastlane", root)
        self.assertEqual(sorted(self.data()["stores"]["apple"]["platforms"]["IOS"]["screens"]),
                         ["iphone-61", "iphone-67"])

    def test_each_platform_keeps_its_own_words(self):
        ios = deliver(os.path.join(self.tmp, "ios"), "en-CA", IOS_WORDS, [("01-plan-iphone.png", 1320, 2868)])
        tv_words = dict(IOS_WORDS, description="Plan a week of meals.\n\nA game controller is required.",
                        support_url="https://example.com/tv")
        tv = deliver(os.path.join(self.tmp, "tvos"), "en-CA", tv_words, [("01-plan-appletv.png", 1920, 1080)])
        mac = deliver(os.path.join(self.tmp, "macos"), "en-CA", dict(IOS_WORDS, keywords="recipes,desktop"))
        self.imp("fastlane", ios)
        out = self.imp("fastlane", tv)  # its screenshots say TV_OS
        code, text, err = kit.run(["import", "--from", "fastlane", mac, "--out", self.config, "--platform", "MAC_OS"])
        self.assertEqual(code, 0, text + err)
        d = self.data()
        en = d["locales"]["en-CA"]
        self.assertEqual(en["description"], "Plan a week of meals.")
        self.assertEqual(en["apple"]["platforms"]["TV_OS"], {
            "description": "Plan a week of meals.\n\nA game controller is required.",
            "supportUrl": "https://example.com/tv"})
        self.assertEqual(en["apple"]["platforms"]["MAC_OS"], {"keywords": ["recipes", "desktop"]})
        self.assertIn("TV_OS's words differ", out)
        plats = d["stores"]["apple"]["platforms"]
        self.assertEqual(plats["TV_OS"]["screens"], ["apple-tv"])
        self.assertEqual(plats["MAC_OS"]["screens"], ["mac"])
        self.assertEqual(d["screens"]["apple-tv"], {"kind": "tv"})
        # again: nothing changes
        before = self.text()
        self.imp("fastlane", tv)
        self.assertEqual(self.text(), before)
        # and the build sends each platform its own
        import listing
        lst = listing.Listing(self.config, d)
        self.assertEqual(lst.resolve("en-CA", "apple.description", "apple", "IOS")[0], "Plan a week of meals.")
        self.assertTrue(lst.resolve("en-CA", "apple.description", "apple", "TV_OS")[0].endswith("is required."))
        self.assertEqual(lst.resolve("en-CA", "apple.supportUrl", "apple", "IOS")[0], "https://example.com/support")
        self.assert_schema_valid()

    def test_each_store_gets_the_locales_its_source_had(self):
        ios = deliver(os.path.join(self.tmp, "ios"), "en-CA", IOS_WORDS)
        self.imp("fastlane", ios)
        android = os.path.join(self.tmp, "supply", "metadata", "android")
        write_text(os.path.join(android, "en-US", "title.txt"), "Sample Recipes: Meal Planner")
        write_text(os.path.join(android, "en-US", "full_description.txt"), "Plan a week of meals.")
        self.imp("supply", os.path.join(self.tmp, "supply"))
        d = self.data()
        self.assertEqual(d["primaryLocale"], "en-CA")
        self.assertEqual(d["stores"]["apple"]["locales"], ["en-CA"])
        self.assertEqual(d["stores"]["apple"]["primaryLocale"], "en-CA")
        self.assertEqual(d["stores"]["google"]["locales"], ["en-US"])
        self.assertEqual(d["stores"]["google"]["defaultLanguage"], "en-US")
        import listing
        report, _, checks = listing.run_check(self.config)
        self.assertEqual(list(checks["apple"].locales), ["en-CA"])
        self.assertEqual(list(checks["google"].locales), ["en-US"])
        self.assertFalse(kit.findings(report.to_json(), "config.locales"))
        # Play's en-US description is the same as en-CA's shared one: it falls back to it
        lst = listing.Listing(self.config, d)
        self.assertEqual(lst.resolve("en-US", "google.fullDescription")[0], "Plan a week of meals.")

    def test_identical_play_slots_share_one_screen(self):
        android = os.path.join(self.tmp, "supply", "metadata", "android", "en-US")
        write_text(os.path.join(android, "title.txt"), "Sample Recipes")
        images = os.path.join(android, "images")
        for i, shot in enumerate(("plan", "recipe")):
            kit.write_png(os.path.join(images, "phoneScreenshots", "0%d-%s-android-phone.png" % (i, shot)), 1080, 1920)
            for slot in ("sevenInchScreenshots", "tenInchScreenshots"):
                kit.write_png(os.path.join(images, slot, "0%d-%s-android-tablet.png" % (i, shot)), 1920, 1200,
                              rgb=(10 * i, 200, 30))
        kit.write_png(os.path.join(images, "tvScreenshots", "01-plan-android-tv.png"), 1920, 1080)
        out = self.imp("supply", os.path.join(self.tmp, "supply"))
        d = self.data()
        slots = d["stores"]["google"]["slots"]
        self.assertEqual((slots["phone"], slots["tablet7"], slots["tablet10"], slots["tv"]),
                         ("android-phone", "android-tablet", "android-tablet", "android-tv"))
        self.assertNotIn("android-tablet7", d["screens"])
        self.assertIn("byte for byte", out)
        shots = dict((s["id"], s["screens"]) for s in d["screenshots"]["shots"])
        self.assertEqual(shots, {"plan": None, "recipe": ["android-phone", "android-tablet"]})

    def test_play_slots_with_their_own_pictures_stay_apart(self):
        android = os.path.join(self.tmp, "supply", "metadata", "android", "en-US")
        write_text(os.path.join(android, "title.txt"), "Sample Recipes")
        images = os.path.join(android, "images")
        kit.write_png(os.path.join(images, "sevenInchScreenshots", "01-plan.png"), 1920, 1200, rgb=(1, 2, 3))
        kit.write_png(os.path.join(images, "tenInchScreenshots", "01-plan.png"), 2560, 1600, rgb=(4, 5, 6))
        self.imp("supply", os.path.join(self.tmp, "supply"))
        slots = self.data()["stores"]["google"]["slots"]
        self.assertEqual((slots["tablet7"], slots["tablet10"]), ("android-tablet7", "android-tablet10"))

    def test_screens_a_later_import_adds_dont_take_shots_they_have_no_picture_for(self):
        ios = deliver(os.path.join(self.tmp, "ios"), "en-US", IOS_WORDS, [
            ("01-plan-iphone.png", 1320, 2868), ("02-draft-iphone.png", 1320, 2868)])
        self.imp("fastlane", ios)
        self.assertEqual([s["screens"] for s in self.data()["screenshots"]["shots"]], [None, None])
        android = os.path.join(self.tmp, "supply", "metadata", "android", "en-US")
        write_text(os.path.join(android, "title.txt"), "Sample Recipes")
        kit.write_png(os.path.join(android, "images", "phoneScreenshots", "01-plan-android-phone.png"), 1080, 1920)
        self.imp("supply", os.path.join(self.tmp, "supply"))
        shots = dict((s["id"], s["screens"]) for s in self.data()["screenshots"]["shots"])
        self.assertEqual(shots, {"plan": None, "draft": ["iphone"]})


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
