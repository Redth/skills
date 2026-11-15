"""Tests for starting from the current set and previewing the starting styles: sheet.py --current (a pulled listing's
folders and a repository's), design/current.json's shape, the inspiration board's current-set card, --draft,
sheet.py --styles (its roles, configs and made-up screens; rendered only where Chrome is installed), and a style
role's per-store layout (the starting styles' hero is real UI on Google Play). Synthetic files only."""

from __future__ import annotations

import contextlib
import copy
import io
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import check  # noqa: E402
import check_testkit as tk  # noqa: E402
import render  # noqa: E402
import samples  # noqa: E402
import sheet  # noqa: E402
import styles  # noqa: E402
from appstores_lib import chrome  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import png  # noqa: E402
from test_baseline import Project  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None

PULLED = {
    "apple/screenshots/en-US/APP_IPHONE_67": ["01.png", "02.png", "03.png", "10.png"],
    "apple/screenshots/de-DE/APP_IPHONE_67": ["01.png"],
    "google/screenshots/en-US/phone": ["01.png", "02.png"],
}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def jpeg_header(width, height):
    """A JPEG's start: SOI, then a baseline SOF0 with the size (enough for the header reader)."""
    sof = struct.pack(">BHHB", 8, height, width, 3) + b"\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    return b"\xff\xd8" + b"\xff\xc0" + struct.pack(">H", len(sof) + 2) + sof + b"\xff\xd9"


def webp_header(width, height):
    """A WebP's start with a VP8X chunk giving the canvas size."""
    body = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", 4 + len(chunk)) + b"WEBP" + chunk


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="current-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sheet.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def pulled(self):
        """``<tmp>/app/existing/...`` as push.py pull writes it, plus a graphic that isn't a screenshot."""
        root = os.path.join(self.tmp, "app")
        for folder, names in PULLED.items():
            for n in names:
                tk.write_png(os.path.join(root, "existing", folder, n), 43, 93, (30 + len(n), 79, 214))
        tk.write_png(os.path.join(root, "existing", "google", "graphics", "icon.png"), 32, 32)
        return root

    def repo_folder(self):
        """``<tmp>/repo/assets/screenshots/<device>/Screenshot-N.png`` with N past 9."""
        root = os.path.join(self.tmp, "repo")
        for device in ("iphone", "android"):
            for n in (1, 2, 10, 3):
                tk.write_png(os.path.join(root, "assets", "screenshots", device, "Screenshot-%d.png" % n), 43, 93)
        return root

    def config_in(self, root):
        path = os.path.join(root, "store-screenshots.json")
        os.makedirs(root, exist_ok=True)
        return path


class Groups(Case):
    def test_a_pulled_listing_groups_by_store_locale_and_slot_app_store_first(self):
        root = self.pulled()
        groups = sheet.current_groups(os.path.join(root, "existing"))
        self.assertEqual([g["id"] for g in groups], ["apple/de-DE/APP_IPHONE_67", "apple/en-US/APP_IPHONE_67",
                                                     "google/en-US/phone"])
        en = groups[1]
        self.assertEqual((en["store"], en["locale"], en["slot"]), ("apple", "en-US", "APP_IPHONE_67"))
        self.assertEqual(en["files"], ["apple/screenshots/en-US/APP_IPHONE_67/%s" % n
                                       for n in ("01.png", "02.png", "03.png", "10.png")])
        everything = [f for g in groups for f in g["files"]]
        self.assertFalse(any("icon" in f for f in everything))  # the graphics aren't screenshots

    def test_one_slot_of_a_pulled_listing_is_still_named_by_its_path(self):
        root = self.pulled()
        groups = sheet.current_groups(os.path.join(root, "existing", "google", "screenshots", "en-US", "phone"))
        self.assertEqual([(g["id"], g["files"]) for g in groups], [("google/en-US/phone", ["01.png", "02.png"])])

    def test_a_repository_folder_groups_by_device_in_number_order(self):
        root = self.repo_folder()
        groups = sheet.current_groups(os.path.join(root, "assets", "screenshots"))
        self.assertEqual([g["id"] for g in groups], ["android", "iphone"])
        self.assertEqual(groups[1]["files"], ["iphone/Screenshot-%d.png" % n for n in (1, 2, 3, 10)])
        self.assertIsNone(groups[1]["store"])
        flat = sheet.current_groups(os.path.join(root, "assets", "screenshots", "iphone"))
        self.assertEqual(flat[0]["id"], "iphone")
        self.assertEqual(flat[0]["files"], ["Screenshot-1.png", "Screenshot-2.png", "Screenshot-3.png",
                                            "Screenshot-10.png"])

    def test_sizes_from_png_jpeg_and_webp_headers(self):
        folder = os.path.join(self.tmp, "pics")
        tk.write_png(os.path.join(folder, "a.png"), 43, 93)
        with open(os.path.join(folder, "b.jpg"), "wb") as f:
            f.write(jpeg_header(1290, 2796))
        with open(os.path.join(folder, "c.webp"), "wb") as f:
            f.write(webp_header(1080, 1920))
        with open(os.path.join(folder, "d.png"), "wb") as f:
            f.write(b"not a picture")
        self.assertEqual(sheet.image_size(os.path.join(folder, "a.png")), (43, 93))
        self.assertEqual(sheet.image_size(os.path.join(folder, "b.jpg")), (1290, 2796))
        self.assertEqual(sheet.image_size(os.path.join(folder, "c.webp")), (1080, 1920))
        self.assertIsNone(sheet.image_size(os.path.join(folder, "d.png")))
        self.assertEqual(len(sheet.current_groups(folder)[0]["files"]), 4)


class CurrentJson(Case):
    def good(self):
        return {"version": 1, "source": "existing", "shots": [
            {"file": "apple/screenshots/en-US/APP_IPHONE_67/01.png", "group": "apple/en-US/APP_IPHONE_67",
             "order": 1, "screen": "the week's plan", "capture": "plan", "caption": "Plan a week of meals\nin minutes",
             "layout": "band", "traits": {"captionPosition": "top", "captionSize": "quiet"}, "verdict": "keep",
             "notes": "people quote it"},
            {"file": "apple/screenshots/en-US/APP_IPHONE_67/02.png", "group": "apple/en-US/APP_IPHONE_67",
             "order": 2, "screen": None, "caption": None, "layout": None, "traits": {}, "verdict": None}],
            "summary": {"traits": {"mood": "warm"}, "look": "evolve", "whatWorks": ["one line"],
                        "whatDoesnt": ["small words"], "notes": None, "confirmedByUser": False}}

    def test_a_filled_file_validates(self):
        self.assertEqual(styles.validate_current(self.good()), [])

    def test_the_vocabulary_and_the_users_words_are_enforced(self):
        for path, value in ((("shots", 0, "verdict"), "maybe"), (("shots", 0, "layout"), "carousel"),
                            (("shots", 0, "traits", "mood"), "grumpy"), (("summary", "look"), "refresh"),
                            (("shots", 0, "order"), 0), (("shots", 0, "colour"), "red")):
            with self.subTest(path=path):
                data = self.good()
                here = data
                for k in path[:-1]:
                    here = here[k]
                here[path[-1]] = value
                self.assertTrue(styles.validate_current(data))

    def test_a_place_or_a_file_twice_is_refused(self):
        data = self.good()
        data["shots"][1]["order"] = 1
        self.assertTrue(any("order 1" in p for p in styles.validate_current(data)))
        data = self.good()
        data["shots"][1]["file"] = data["shots"][0]["file"]
        data["shots"][1]["group"] = "elsewhere"
        self.assertTrue(any("more than once" in p for p in styles.validate_current(data)))

    def test_the_schema_uses_only_supported_keywords_and_shares_the_layouts(self):
        defs = styles.style_schema()["$defs"]
        self.assertEqual(defs["layout"]["enum"], ["fullbleed", "band", "framed", "framed-bleed", "tilt", "pair",
                                                  "callout", "hero", "gameplay"])
        config_layouts = jsonio.load(styles.CONFIG_SCHEMA_PATH)["$defs"]["layout"]
        self.assertEqual(sorted(defs["layout"]["enum"]), sorted(x for x in config_layouts["enum"] if x))


class CurrentSheet(Case):
    def test_the_first_run_writes_a_skeleton_and_the_page(self):
        root = self.pulled()
        config = self.config_in(root)
        code, out, err = self.main("--config", config, "--current", "existing")
        self.assertEqual(code, 0, err)
        self.assertIn("wrote a skeleton", out)
        data = jsonio.load(os.path.join(root, "design", "current.json"))
        self.assertEqual(styles.validate_current(data), [])
        self.assertEqual(data["source"], "existing")
        self.assertEqual(len(data["shots"]), 7)
        self.assertTrue(all(s["verdict"] is None and s["caption"] is None for s in data["shots"]))
        self.assertFalse(data["summary"]["confirmedByUser"])
        self.assertEqual([s["order"] for s in data["shots"] if s["group"] == "apple/en-US/APP_IPHONE_67"],
                         [1, 2, 3, 4])
        page = read(os.path.join(root, "design", "sheets", "current.html"))
        self.assertEqual(page.count('<div class="current-shot '), 7)
        self.assertIn("App Store <small>en-US &middot; APP_IPHONE_67 &middot; 4 shots", page)
        self.assertIn("Google Play <small>en-US &middot; phone", page)
        self.assertIn("../../existing/apple/screenshots/en-US/APP_IPHONE_67/10.png", page)
        self.assertNotIn("icon.png", page)
        self.assertIn("Not confirmed yet", page)
        self.assertIn("verdict: the user", page)
        self.assertEqual(page.count("first three</span>"), 3 + 1 + 2)

    def test_a_filled_file_is_shown_and_found_without_naming_the_folder(self):
        root = self.repo_folder()
        config = self.config_in(root)
        self.main("--config", config, "--current", "assets/screenshots")
        path = os.path.join(root, "design", "current.json")
        data = jsonio.load(path)
        first = next(s for s in data["shots"] if s["file"] == "iphone/Screenshot-1.png")
        first.update(screen="the week's plan", caption="Plan a week of meals\nin minutes", layout="band",
                     verdict="keep", traits={"captionSize": "quiet"})
        data["shots"] = [s for s in data["shots"] if s["file"] != "iphone/Screenshot-10.png"]
        data["shots"].append({"file": "iphone/gone.png", "group": "iphone", "order": 9})
        data["summary"].update(look="evolve", whatWorks=["one line a shot"], confirmedByUser=True)
        jsonio.dump(data, path)
        code, out, err = self.main("--config", config, "--current")
        self.assertEqual(code, 0, err)
        page = read(os.path.join(root, "design", "sheets", "current.html"))
        self.assertIn("&ldquo;Plan a week of meals<br>in minutes&rdquo;", page)
        self.assertIn('class="tag verdict keep">keep', page)
        self.assertIn("<b>captionSize</b>quiet", page)
        self.assertIn("not in current.json", page)          # Screenshot-10 is in the folder, not the file
        self.assertIn("iphone/gone.png", out)               # and the other way round
        self.assertIn("evolves this look", page)
        self.assertIn("Confirmed by the user", page)

    def test_usage_errors(self):
        root = os.path.join(self.tmp, "empty")
        config = self.config_in(root)
        code, _, err = self.main("--config", config, "--current")
        self.assertEqual(code, 3)
        self.assertIn("say which folder", err)
        code, _, err = self.main("--config", config, "--current", "existing")
        self.assertEqual(code, 3)
        self.assertIn("push.py pull", err)
        os.makedirs(os.path.join(root, "nothing"))
        code, _, err = self.main("--config", config, "--current", "nothing")
        self.assertEqual(code, 3)
        self.assertIn("no pictures", err)
        jsonio.dump({"version": 1, "source": "x", "shots": [{"file": "a.png", "order": 1, "verdict": "maybe"}]},
                    os.path.join(root, "design", "current.json"))
        code, _, err = self.main("--config", config, "--current", "nothing")
        self.assertEqual(code, 3)
        self.assertIn("verdict", err)

    def test_the_inspiration_board_shows_the_current_set_as_one_example(self):
        root = self.pulled()
        config = self.config_in(root)
        self.main("--config", config, "--current", "existing")
        data = jsonio.load(os.path.join(root, "design", "current.json"))
        data["shots"][0]["verdict"] = "keep"
        data["summary"].update(look="replace", whatDoesnt=["small words"])
        jsonio.dump(data, os.path.join(root, "design", "current.json"))
        code, _, err = self.main("--config", config, "--inspiration")   # no inspiration.json: the current set alone
        self.assertEqual(code, 0, err)
        page = read(os.path.join(root, "design", "sheets", "inspiration.html"))
        self.assertIn("The current set", page)
        self.assertIn("one example among the others", page)
        self.assertIn("Move away from it.", page)
        self.assertIn("small words", page)
        self.assertIn("7 shots, 1 kept", page)


class Drafts(Case):
    def test_draft_directions_are_headed_as_drafts(self):
        p = Project(os.path.join(self.tmp, "p"))
        p.fake_render()
        shutil.copytree(p.out, os.path.join(p.root, "design", "explore", "bold"))
        code, _, err = self.main("--config", p.config_path, "--directions", "design/explore/bold", "--draft")
        self.assertEqual(code, 0, err)
        page = read(os.path.join(p.root, "design", "sheets", "directions.html"))
        self.assertIn("Drafts for you to correct.", page)
        self.assertIn("Directions (drafts)", page)
        self.main("--config", p.config_path, "--directions", "design/explore/bold")
        self.assertNotIn("Drafts for you", read(os.path.join(p.root, "design", "sheets", "directions.html")))


class StylePreview(Case):
    def test_each_style_previews_three_shots_in_its_roles(self):
        found = styles.starting_styles()
        roles = dict((n, sheet.preview_roles(d)) for n, (_, d) in found.items())
        self.assertEqual(roles["brand-bold"], (["hero", "feature", "whole"], False))
        self.assertEqual(roles["game-key-art"], (["key-art", "gameplay", "gameplay"], False))
        self.assertEqual(roles["game-banner"], (["banner", "gameplay", "banner"], False))
        self.assertEqual(roles["panoramic-strip"], (["hero", "strip", "strip"], True))
        for name, (r, _) in roles.items():
            self.assertEqual(len(r), 3, name)

    def test_every_preview_config_resolves_with_its_style(self):
        root = os.path.join(self.tmp, "preview")
        w, h = sheet.PREVIEW_SIZE
        caps = os.path.join(root, "captures", "en-US", "phone")
        os.makedirs(caps)
        for kind in samples.APP_SCREENS:
            samples.write(os.path.join(caps, kind + ".png"), samples.app_screen(kind, w, h))
        for kind in samples.GAME_SCREENS:
            samples.write(os.path.join(caps, kind + ".png"), samples.game_screen(kind, w, h))
        for kind in samples.APP_SCREENS + samples.GAME_SCREENS:
            meta = png.info(os.path.join(caps, kind + ".png"))
            self.assertEqual((meta.width, meta.height, meta.has_alpha), (w, h, False))
        for name, (path, data) in styles.starting_styles().items():
            with self.subTest(style=name):
                folder = os.path.join(root, name)
                os.makedirs(folder)
                config = os.path.join(folder, "store-screenshots.json")
                jsonio.dump(sheet.preview_config(data), config)
                res, wanted = render.expected(config, style=path)
                self.assertEqual(len(wanted), 3)
                self.assertTrue(all(v for v in wanted.values()), wanted)
                game = name.startswith("game-")
                self.assertEqual(res.cfg["shots"][0]["capture"], "run" if game else "list")

    def test_no_chrome_is_usage(self):
        def missing():
            raise chrome.ChromeNotFound("no Chrome here")
        original = sheet.chrome.find_chrome
        sheet.chrome.find_chrome = missing
        try:
            code, _, err = self.main("--styles", "--design", os.path.join(self.tmp, "design"))
        finally:
            sheet.chrome.find_chrome = original
        self.assertEqual(code, 3)
        self.assertIn("need Chrome", err)


class HeroOnPlay(Case):
    """A style's role may take another layout on one store; the app starting styles' hero is real UI on Play."""

    def project(self, style_name):
        p = Project(os.path.join(self.tmp, style_name))
        p.style = copy.deepcopy(styles.starting_styles()[style_name][1])
        p.config["shots"][0]["role"] = "hero"
        p.config["strings"]["en-US"]["cap.plan"] = "Plan meals in minutes"
        return p

    def test_the_hero_is_a_hero_on_apple_and_the_app_on_play(self):
        p = self.project("brand-bold")
        p.write()
        cfg = render.load_config(p.config_path)
        res = render.Resolver(cfg, p.config_path)
        self.assertEqual(res.settings(cfg["shots"][0], "iphone")["layout"], "hero")
        self.assertEqual(res.settings(cfg["shots"][0], "android-phone")["layout"], "framed-bleed")
        self.assertEqual(res.settings(cfg["shots"][0], "android-phone")["frame"], "none")  # the store's frame still

    def test_brand_bold_no_longer_warns_on_plays_first_shot(self):
        for name in ("brand-bold", "minimal-editorial", "dark-pro", "playful-saturated", "photo-lifestyle"):
            with self.subTest(style=name):
                p = self.project(name)
                report = p.fake_render()
                layouts = dict(((f["target"], f["shot"]), f["layout"]) for f in report["files"])
                self.assertEqual(layouts[("iphone", "plan")], "hero")
                self.assertNotEqual(layouts[("android-phone", "plan")], "hero")
                found = check.run_check(p.config_path)
                ids = [f.rule_id for _, f in found.findings]
                self.assertNotIn("google.design.ui_first", ids, found.to_text())

    def test_without_the_roles_store_layout_play_warns(self):
        p = self.project("brand-bold")
        del p.style["roles"]["hero"]["stores"]
        p.fake_render()
        found = check.run_check(p.config_path)
        self.assertIn("google.design.ui_first", [f.rule_id for _, f in found.findings])

    def test_a_shots_own_layout_and_the_configs_store_override_still_win(self):
        p = self.project("brand-bold")
        p.config["shots"][0]["layout"] = "hero"
        p.write()
        cfg = render.load_config(p.config_path)
        res = render.Resolver(cfg, p.config_path)
        self.assertEqual(res.settings(cfg["shots"][0], "android-phone")["layout"], "hero")
        p.config["shots"][0].pop("layout")
        p.config["stores"]["google"] = {"layout": "band"}
        p.write()
        cfg = render.load_config(p.config_path)
        res = render.Resolver(cfg, p.config_path)
        self.assertEqual(res.settings(cfg["shots"][0], "android-phone")["layout"], "band")

    def test_a_roles_store_layout_counts_among_the_styles_layouts(self):
        style = styles.starting_styles()["dark-pro"][1]
        self.assertIn("framed", styles.role_layouts(style))
        bad = copy.deepcopy(style)
        bad["roles"]["hero"]["stores"]["google"]["layout"] = "carousel"
        self.assertTrue(styles.validate_style(bad))


@unittest.skipUnless(CHROME, "needs Google Chrome or Chromium")
class Rendering(Case):
    def test_the_styles_sheet_renders_every_starting_style(self):
        design = os.path.join(self.tmp, "design")
        code, out, err = self.main("--styles", "--png", "--design", design)
        self.assertEqual(code, 0, err)
        page = read(os.path.join(design, "sheets", "styles.html"))
        found = styles.starting_styles()
        self.assertEqual(page.count('<section class="card">'), len(found))
        for name in found:
            self.assertIn("styles/%s.json" % name, page)
            self.assertTrue(os.path.isfile(os.path.join(design, "sheets", sheet.PREVIEW_DIR, name, "render", "en-US",
                                                        "iphone", "shot1.png")), name)
        self.assertIn("Suits", page)
        self.assertNotIn("Drafts for you", page)
        meta = png.info(os.path.join(design, "sheets", "styles.png"))
        self.assertEqual(meta.width, sheet.DESIGN_WIDTH * 2)
        self.assertGreater(meta.height, 3000)

    def test_the_current_sheet_renders(self):
        root = self.pulled()
        code, _, err = self.main("--config", self.config_in(root), "--current", "existing", "--png")
        self.assertEqual(code, 0, err)
        meta = png.info(os.path.join(root, "design", "sheets", "current.png"))
        self.assertEqual(meta.width, sheet.CURRENT_WIDTH * 2)


if __name__ == "__main__":
    unittest.main()
