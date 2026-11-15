"""Tests for appstores_lib.chrome (stdlib unittest).

The rendering tests start a real headless Chrome and are skipped where none is installed (CI runners may
not have one); the rest run everywhere.
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))

from appstores_lib import chrome, png  # noqa: E402

try:
    CHROME = chrome.find_chrome()
except chrome.ChromeNotFound:
    CHROME = None

OPAQUE_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body { margin: 0; background: #3366cc; }
.half { height: 50vh; background: #ffffff; }
</style></head><body><div class="half">Sample Recipes</div>
<script>
window.__appstoresReport = {
  css: [innerWidth, innerHeight], dpr: devicePixelRatio,
  title: "Plan meals in minutes — crème", nested: {list: [1, 2.5, null, true]}
};
</script></body></html>
"""

READY_PAGE = """<!doctype html>
<html><body style="margin:0;background:#fff">
<script>
window.__appstoresReady = new Promise(resolve => setTimeout(() => {
  window.__appstoresReport = {waited: true};
  resolve();
}, 150));
</script></body></html>
"""

PLAIN_PAGE = "<!doctype html><html><body style='margin:0;background:#fafafa'>No report</body></html>"


TALL_PAGE = """<!doctype html><html><head><style>html, body { margin: 0; background: #fff; }
.top { height: 1200px; } .end { height: 34px; background: #3366cc; }</style></head>
<body><div class="top"></div><div class="end"></div></body></html>"""

class FindChromeTests(unittest.TestCase):
    def test_chrome_env_pointing_nowhere_is_an_error(self):
        with mock.patch.dict(os.environ, {"CHROME": "/nonexistent/chrome-for-a-test"}):
            with self.assertRaises(chrome.ChromeNotFound) as cm:
                chrome.find_chrome()
        self.assertIn("CHROME", str(cm.exception))

    def test_nothing_found_explains_what_to_install(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHROME", None)
            with mock.patch.object(chrome, "MAC_PATHS", ()), mock.patch.object(chrome.shutil, "which", return_value=None):
                with self.assertRaises(chrome.ChromeNotFound) as cm:
                    chrome.find_chrome()
        self.assertIn("Google Chrome", str(cm.exception))

    def test_path_names_are_tried_in_order(self):
        def which(name):
            return "/opt/bin/chromium" if name == "chromium" else None

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CHROME", None)
            with mock.patch.object(chrome, "MAC_PATHS", ()), mock.patch.object(chrome.shutil, "which", side_effect=which):
                self.assertEqual(chrome.find_chrome(), "/opt/bin/chromium")


class ToUrlTests(unittest.TestCase):
    def test_urls_pass_through_and_paths_become_file_urls(self):
        self.assertEqual(chrome.to_url("https://example.com/a"), "https://example.com/a")
        self.assertEqual(chrome.to_url("about:blank"), "about:blank")
        self.assertEqual(chrome.to_url("data:text/html,hi"), "data:text/html,hi")
        url = chrome.to_url(os.path.join(tempfile.gettempdir(), "a b.html"))
        self.assertTrue(url.startswith("file:///"))
        self.assertIn("a%20b.html", url)


@unittest.skipIf(CHROME is None, "Google Chrome or Chromium isn't installed")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.dir = cls._tmp.name
        cls.pages = {}
        for name, html in (("opaque", OPAQUE_PAGE), ("ready", READY_PAGE), ("plain", PLAIN_PAGE), ("tall", TALL_PAGE)):
            path = os.path.join(cls.dir, name + ".html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            cls.pages[name] = path
        cls.chrome = chrome.Chrome(CHROME)
        cls.chrome.start()

    @classmethod
    def tearDownClass(cls):
        cls.chrome.close()
        cls._tmp.cleanup()

    def out(self, name):
        return os.path.join(self.dir, "out", name)

    def test_png_is_the_exact_size_and_opaque(self):
        out = self.out("phone.png")
        self.chrome.render(self.pages["opaque"], 390, 844, out)
        info = png.info(out)
        self.assertEqual((info.format, info.width, info.height), ("png", 390, 844))
        self.assertFalse(info.has_alpha, "an opaque page makes a PNG without alpha")

    def test_colours_are_srgb_exact(self):
        out = self.out("colours.png")
        self.chrome.render(self.pages["opaque"], 40, 40, out)
        w, h, rgb = png.decode_rgb(out)
        top = rgb[(5 * w + 5) * 3:(5 * w + 5) * 3 + 3]
        bottom = rgb[(35 * w + 5) * 3:(35 * w + 5) * 3 + 3]
        self.assertEqual(top, bytes([255, 255, 255]))
        self.assertEqual(bottom, bytes([0x33, 0x66, 0xCC]))

    def test_scale_lays_out_in_css_pixels(self):
        out = self.out("scaled.png")
        report = self.chrome.render(self.pages["opaque"], 1290, 2796, out, scale=3)
        self.assertEqual(report["css"], [430, 932])
        self.assertEqual(report["dpr"], 3)
        info = png.info(out)
        self.assertEqual((info.width, info.height), (1290, 2796))

    def test_a_scale_that_does_not_divide_still_gives_the_exact_size(self):
        out = self.out("odd.png")
        self.chrome.render(self.pages["opaque"], 301, 201, out, scale=2)
        info = png.info(out)
        self.assertEqual((info.width, info.height), (301, 201))

    def test_full_page_is_as_tall_as_the_page(self):
        out = self.out("tall.png")
        self.chrome.render(self.pages["tall"], 200, 100, out, scale=2, full_page=6000)
        info = png.info(out)
        self.assertEqual((info.width, info.height), (200, 2468))  # 1234 CSS px at 2x
        w, h, rgb = png.decode_rgb(out)
        last = rgb[((h - 2) * w + 5) * 3:((h - 2) * w + 5) * 3 + 3]
        self.assertEqual(last, bytes([0x33, 0x66, 0xCC]), "the bottom of the page is in the picture")

    def test_full_page_stops_at_its_cap(self):
        out = self.out("capped.png")
        self.chrome.render(self.pages["tall"], 300, 100, out, full_page=500)
        info = png.info(out)
        self.assertEqual((info.width, info.height), (300, 500))

    def test_jpeg(self):
        out = self.out("feature.jpg")
        self.chrome.render(self.pages["opaque"], 1024, 500, out, fmt="jpeg", quality=85)
        info = png.info(out)
        self.assertEqual((info.format, info.width, info.height, info.has_alpha), ("jpeg", 1024, 500, False))

    def test_the_report_round_trips(self):
        report = self.chrome.render(self.pages["opaque"], 200, 100, self.out("r.png"))
        self.assertEqual(report["title"], "Plan meals in minutes — crème")
        self.assertEqual(report["nested"], {"list": [1, 2.5, None, True]})
        self.assertEqual(self.chrome.render(self.pages["plain"], 200, 100, self.out("p.png")), {})

    def test_it_waits_for_the_page_to_say_it_is_ready(self):
        self.assertEqual(self.chrome.render(self.pages["ready"], 100, 100, self.out("w.png")), {"waited": True})

    def test_evaluate(self):
        self.assertEqual(self.chrome.evaluate("1 + 2"), 3)
        self.assertEqual(self.chrome.evaluate("Promise.resolve({a: [1, 'b']})"), {"a": [1, "b"]})
        self.assertEqual(self.chrome.evaluate("document.body.textContent", self.pages["plain"]), "No report")
        with self.assertRaises(chrome.ChromeError):
            self.chrome.evaluate("(() => { throw new Error('nope') })()")

    def test_a_missing_page_is_an_error_and_the_browser_carries_on(self):
        with self.assertRaises(chrome.ChromeError):
            self.chrome.render(os.path.join(self.dir, "missing.html"), 100, 100, self.out("m.png"))
        self.assertFalse(os.path.exists(self.out("m.png")))
        self.assertEqual(self.chrome.evaluate("40 + 2"), 42)

    def test_bad_arguments(self):
        with self.assertRaises(ValueError):
            self.chrome.render(self.pages["plain"], 100, 100, self.out("x.gif"), fmt="gif")
        with self.assertRaises(ValueError):
            self.chrome.render(self.pages["plain"], 0, 100, self.out("x.png"))

    def test_targets_are_closed_after_each_render(self):
        self.chrome.render(self.pages["plain"], 50, 50, self.out("t.png"))
        targets = self.chrome.call("Target.getTargets")["targetInfos"]
        pages = [t for t in targets if t.get("type") == "page" and t.get("url") != "about:blank"]
        self.assertEqual(pages, [])


@unittest.skipIf(CHROME is None, "Google Chrome or Chromium isn't installed")
class LifetimeTests(unittest.TestCase):
    def test_close_stops_chrome_and_removes_its_profile(self):
        with chrome.Chrome(CHROME) as c:
            root = c._root
            proc = c._proc
            self.assertTrue(os.path.isdir(root))
            self.assertEqual(c.evaluate("'up'"), "up")
        self.assertFalse(os.path.exists(root))
        self.assertIsNotNone(proc.poll(), "Chrome has exited")
        c.close()  # a second close is harmless

    def test_an_exception_inside_the_block_still_cleans_up(self):
        class Boom(Exception):
            pass

        root = None
        with self.assertRaises(Boom):  # (not RuntimeError: a Chrome that fails to start must fail as itself)
            with chrome.Chrome(CHROME) as c:
                root = c._root
                raise Boom("boom")
        self.assertIsNotNone(root)
        self.assertFalse(os.path.exists(root))



class StartRetryTests(unittest.TestCase):
    def test_a_start_that_fails_twice_says_so(self):
        with tempfile.TemporaryDirectory() as d:
            fake = os.path.join(d, "not-chrome")
            with open(fake, "w") as f:
                f.write("#!/bin/sh\nexit 1\n")
            os.chmod(fake, 0o755)
            with self.assertRaises(chrome.ChromeError) as ctx:
                chrome.Chrome(fake, start_timeout=2).start()
            self.assertIn("tried twice", str(ctx.exception))

if __name__ == "__main__":
    unittest.main()
