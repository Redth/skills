"""Tests for sheet.py: the mocks' pages from a synthetic rendered set (check_testkit); rendering through Chrome
only when Chrome is installed."""

from __future__ import annotations

import contextlib
import io
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check_testkit as tk  # noqa: E402
import sheet  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402


def have_chrome():
    try:
        chrome.find_chrome()
        return True
    except chrome.ChromeNotFound:
        return False


class SheetCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sheet-test-")
        self.set = tk.SetBuilder(self.tmp)
        self.set.listing = {"app": {"name": "Sample Recipes", "copyright": "2026 Example Studio"},
                            "primaryLocale": "en-US",
                            "locales": {"en-US": {"apple": {"subtitle": "Plan meals in minutes"},
                                                  "google": {"title": "Sample Recipes: Meal Planner"}}},
                            "stores": {"google": {"slots": {"phone": "android-phone"}}}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sheet.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def page(self, name):
        with open(os.path.join(self.set.out, "sheets", name), encoding="utf-8") as f:
            return f.read()


class Pages(SheetCase):
    def test_the_pages_and_their_names(self):
        path = self.set.write()
        code, out, _ = self.main("--config", path)
        self.assertEqual(code, 0, out)
        names = sorted(os.listdir(os.path.join(self.set.out, "sheets")))
        self.assertEqual(names, ["contact-sheet.html", "mocks.css", "play-listing-en-US.html",
                                 "product-page-en-US-iphone-medium.html", "product-page-en-US-iphone.html",
                                 "search-row-en-US.html"])

    def test_every_mock_says_it_is_an_approximation(self):
        self.main("--config", self.set.write())
        for name in ("search-row-en-US.html", "product-page-en-US-iphone.html", "play-listing-en-US.html"):
            self.assertIn("Approximation, not", self.page(name))

    def test_the_search_row_shows_three_shots_at_their_width_in_points(self):
        self.main("--config", self.set.write())
        html = self.page("search-row-en-US.html")
        widths = re.findall(r'<img src="\.\./en-US/iphone/\w+\.png" alt="\w+" style="width:([\d.]+)px', html)
        self.assertEqual(len(widths), 3)
        self.assertAlmostEqual(float(widths[0]), 118.0, places=1)
        self.assertIn("11.8 pt", html)
        self.assertNotIn("under 11", html.split("<table>")[1])
        self.assertIn("Sample Recipes", html)
        self.assertIn("Plan meals in minutes", html)

    def test_small_captions_are_flagged_in_the_search_row(self):
        for f in self.set.files:
            f["caption"]["fontPx"] = round(f["width"] * 0.08, 1)
        self.main("--config", self.set.write())
        html = self.page("search-row-en-US.html")
        self.assertIn("9.4 pt", html)
        self.assertIn("under 11", html)
        self.assertIn("3 under 11 pt", html)

    def test_a_landscape_phone_fills_the_row(self):
        config = tk.base_config(targets={"iphone-wide": {"store": "apple", "width": 2868, "height": 1320,
                                                         "capture": "iphone-6.9"}})
        self.set = tk.SetBuilder(self.tmp, config)
        self.main("--config", self.set.write())
        html = self.page("search-row-en-US.html")
        widths = re.findall(r'<img src="\.\./en-US/iphone-wide/\w+\.png" alt="\w+" style="width:([\d.]+)px', html)
        self.assertEqual([float(w) for w in widths], [370.0])

    def test_the_play_row_and_the_product_page(self):
        self.main("--config", self.set.write())
        play = self.page("play-listing-en-US.html")
        self.assertIn("Sample Recipes: Meal Planner", play)
        self.assertIn("Example Studio", play)
        self.assertEqual(len(re.findall(r'<img src="\.\./en-US/android-phone/', play)), 3)
        product = self.page("product-page-en-US-iphone.html")
        self.assertIn("end of the first screen (874 pt)", product)
        self.assertEqual(len(re.findall(r'<img src="\.\./en-US/iphone/', product)), 3)

    def test_no_apple_phone_no_search_row(self):
        config = tk.base_config(targets={"android-phone": tk.TARGETS["android-phone"]})
        self.set = tk.SetBuilder(self.tmp, config)
        self.main("--config", self.set.write())
        names = os.listdir(os.path.join(self.set.out, "sheets"))
        self.assertNotIn("search-row-en-US.html", names)
        self.assertIn("play-listing-en-US.html", names)

    def test_the_contact_sheet_badges_fallbacks_seams_and_missing_files(self):
        config = tk.base_config(locales=["en-US", "de-DE"])
        config["panorama"] = {"shots": ["recipe", "shop"], "seam": 6}
        self.set = tk.SetBuilder(self.tmp, config)
        for f in self.set.files:
            if f["locale"] == "de-DE":
                f["captureFallback"] = True
        self.set.find("en-US/iphone/plan.png")["caption"].update(atFloor=True)
        self.set.find("en-US/iphone/recipe.png")["captureScale"] = 1.3
        self.main("--config", self.set.write(skip_png=("en-US/iphone/shop.png",)))
        html = self.page("contact-sheet.html")
        self.assertEqual(html.count('<section class="target">'), 3)
        self.assertEqual(html.count('class="seam"'), 6)  # one seam per target and locale
        self.assertIn("capture: en-US</span>", html)
        self.assertIn("words: en-US</span>", html)
        self.assertIn(">caption at floor</span>", html)
        self.assertIn(">upscaled 1.30x</span>", html)
        self.assertIn(">not rendered</span>", html)

    def test_usage_errors_and_no_chrome(self):
        code, _, err = self.main("--config", os.path.join(self.tmp, "nope.json"))
        self.assertEqual(code, 3)
        self.assertIn("no design config", err)
        path = self.set.write()

        def missing():
            raise chrome.ChromeNotFound("no Chrome here")
        with mock.patch.object(sheet.chrome, "find_chrome", missing):
            code, _, err = self.main("--config", path, "--png")
        self.assertEqual(code, 3)
        self.assertIn("no Chrome here", err)
        self.assertTrue(os.path.isfile(os.path.join(self.set.out, "sheets", "contact-sheet.html")))


@unittest.skipUnless(have_chrome(), "needs Google Chrome or Chromium")
class Compare(SheetCase):
    """--compare against the live set (a folder of its pictures, no render report) and sheets for an exploration."""

    def live(self, with_notes=False):
        root = self.tmp
        for device, size in (("iphone", (132, 287)), ("android", (108, 192))):
            for n in (1, 2):
                tk.write_png(os.path.join(root, "live", device, "Screenshot-%d.png" % n), *size)
        if with_notes:
            jsonio.dump({"version": 1, "source": "live", "shots": [
                {"file": "iphone/Screenshot-1.png", "group": "iphone", "order": 1, "screen": "shopping list",
                 "capture": "shopping", "caption": "Shop by aisle", "layout": "framed-bleed", "traits": {},
                 "verdict": "keep", "notes": None},
                {"file": "iphone/Screenshot-2.png", "group": "iphone", "order": 2, "screen": None, "capture": None,
                 "caption": None, "layout": None, "traits": {}, "verdict": None, "notes": None}],
                "summary": {"traits": {}, "look": None, "whatWorks": [], "whatDoesnt": [], "notes": None,
                            "confirmedByUser": False}}, os.path.join(root, "design", "current.json"))

    def test_the_live_set_needs_no_render_report(self):
        path = self.set.write()
        self.live()
        code, out, err = self.main("--config", path, "--compare", "live")
        self.assertEqual(code, 0, err)
        page = self.page("compare-iphone.html")
        self.assertIn("Live now", page)
        self.assertIn("../../live/iphone/Screenshot-1.png", page)
        self.assertIn("paired by its place in the set (#1)", page)
        self.assertIn("../../live/android/Screenshot-1.png", self.page("compare-android-phone.html"))

    def test_shots_pair_by_the_screen_they_show_from_current_json(self):
        path = self.set.write()
        self.live(with_notes=True)
        code, out, err = self.main("--config", path, "--compare", "current")
        self.assertEqual(code, 0, err)
        page = self.page("compare-iphone.html")
        # "shop" is the third shot but the live set's first: it pairs by its capture, not its place.
        shop = page.index("<h3>shop")
        self.assertIn("paired by the same screen (shopping)", page[shop:])
        self.assertIn("Live now", page[shop:])
        self.assertIn("live words: &ldquo;Shop by aisle&rdquo;", page)
        self.assertIn("../../live/iphone/Screenshot-1.png", page[shop:])

    def test_an_explorations_sheets_go_beside_it(self):
        path = self.set.write()
        explore = os.path.join(self.tmp, "design", "explore", "a")
        shutil.copytree(self.set.out, explore)
        code, out, err = self.main("--config", path, "--out", "design/explore/a")
        self.assertEqual(code, 0, err)
        self.assertTrue(os.path.isfile(os.path.join(explore, "sheets", "contact-sheet.html")))
        with open(os.path.join(explore, "sheets", "contact-sheet.html"), encoding="utf-8") as f:
            sheet_html = f.read()
        self.assertLess(sheet_html.index(">iphone "), sheet_html.index(">android-phone "))


class Rendering(SheetCase):
    def test_png_sheets(self):
        code, out, err = self.main("--config", self.set.write(), "--png")
        self.assertEqual(code, 0, err)
        folder = os.path.join(self.set.out, "sheets")
        search = png.info(os.path.join(folder, "search-row-en-US.png"))
        self.assertEqual(search.width, 402 * sheet.PHONE_SCALE)
        self.assertGreater(search.height, 400 * sheet.PHONE_SCALE)
        for name in ("product-page-en-US-iphone.png", "product-page-en-US-iphone-medium.png",
                     "play-listing-en-US.png", "contact-sheet.png"):
            self.assertTrue(os.path.isfile(os.path.join(folder, name)), name)
        self.assertEqual(png.info(os.path.join(folder, "contact-sheet.png")).width, sheet.CONTACT_WIDTH)
        self.assertIn("approximations", out)


if __name__ == "__main__":
    unittest.main()
