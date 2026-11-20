"""Tests for recapturing after the app changed: the app's revision in the report, ``capture.py --changes`` (what
changed since the last capture and which screens to re-check), ``contains`` in ``wait`` and ``verify`` on every
driver that reads elements, and Android's full-screen (landscape, extract-mode) keyboard closed before a tap.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs git or a device,
reaches a network or waits: fakes answer the commands.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import plistlib
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import test_capture  # noqa: E402
import test_postures  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from appstores_lib import schema  # noqa: E402
from drivers import adb as adb_driver  # noqa: E402
from drivers import appium as appium_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import chrome as chrome_driver  # noqa: E402
from drivers import devflow as devflow_driver  # noqa: E402
from drivers import hosted  # noqa: E402
from drivers import macos as macos_driver  # noqa: E402
from drivers import maestro as maestro_driver  # noqa: E402

HEAD = "c" * 40
THEN = "a" * 40
OLDER = "9" * 40

# A chip whose number is on a child (Android draws it so), beside a field.
CHIP_XML = ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="1">'
            '<node index="0" text="" resource-id="" class="android.widget.FrameLayout" bounds="[0,0][2152,2076]">'
            '<node index="0" text="" resource-id="com.example.samplerecipes:id/servings" content-desc="" '
            'class="android.view.ViewGroup" bounds="[100,200][400,300]">'
            '<node index="0" text="Serves" resource-id="" class="android.widget.TextView" bounds="[110,210][250,290]"/>'
            '<node index="1" text="4" resource-id="" class="android.widget.TextView" bounds="[260,210][390,290]"/>'
            '</node>'
            '<node index="1" text="" resource-id="com.example.samplerecipes:id/servings" content-desc="" '
            'class="android.view.ViewGroup" bounds="[100,400][400,500]">'
            '<node index="0" text="Makes 24" resource-id="" class="android.widget.TextView" '
            'bounds="[110,410][390,490]"/>'
            '</node>'
            '<node index="2" text="Done" resource-id="com.example.samplerecipes:id/done" content-desc="" '
            'class="android.widget.Button" bounds="[1800,1900][2100,2000]"/>'
            '</node></hierarchy>')

IOS_SOURCE = ('<?xml version="1.0" encoding="UTF-8"?><AppiumAUT>'
              '<XCUIElementTypeApplication name="Sample Recipes" label="Sample Recipes">'
              '<XCUIElementTypeOther name="servings" label="Makes 24" value=""/>'
              '<XCUIElementTypeButton name=" " label=""/>'
              '</XCUIElementTypeApplication></AppiumAUT>')

ANDROID_SOURCE = ('<?xml version="1.0" encoding="UTF-8"?><hierarchy>'
                  '<android.view.ViewGroup resource-id="com.example.samplerecipes:id/servings" text="">'
                  '<android.widget.TextView text="Makes 24" resource-id=""/>'
                  '</android.view.ViewGroup></hierarchy>')


def tearDownModule():
    kit.assert_no_residue()


class Case(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        self.run_ = self.hooks.runner
        self.tmp = tempfile.mkdtemp(prefix="capture-update-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.options = base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"))

    def ctx(self, platform="android", **device):
        d = {"id": "dev", "platform": platform, "width": 10, "height": 10, "target": {}}
        d.update(device)
        return base.StepContext(d, {"id": "plan", "steps": []}, "en-US", base.Shot(), 1, None)


# -- contains ---------------------------------------------------------------------------------------------------

class ContainsMatchingTests(unittest.TestCase):
    def test_contains_ignores_case_and_runs_of_space(self):
        self.assertTrue(base.texts_contain(["Makes  24\nservings"], "makes 24 servings"))
        self.assertTrue(base.texts_contain([None, "", "24 oz"], "24"))
        self.assertFalse(base.texts_contain(["Makes 2 4"], "24"))
        self.assertFalse(base.texts_contain(["anything"], "  "))

    def test_an_element_shows_its_own_text_and_its_descendants(self):
        root, elements = base.parse_uiautomator(CHIP_XML)
        found = base.first_containing(root, elements, ("id", "servings"), "24")
        self.assertIsNotNone(found)
        self.assertEqual(found.bounds, (100, 400, 400, 500), "the second chip, the one that shows 24")
        self.assertIsNone(base.first_containing(root, elements, ("id", "servings"), "25"))
        self.assertIsNotNone(base.first_containing(root, elements, ("xpath", "//node[@class='android.view.ViewGroup']"),
                                                   "serves 4"[:6]))
        self.assertIsNone(base.first_containing(root, elements, ("id", "done"), "24"),
                          "a sibling's text isn't the element's")

    def test_an_agent_items_children_count(self):
        e = base.Element(id="servings", attrs={"children": [{"type": "Label", "text": "Makes 24"}]})
        self.assertIn("Makes 24", base.element_texts(e))


class ContainsAdbTests(Case):
    def driver(self):
        self.run_.on(r"exec-out cat /sdcard/appstores-ui.xml", out=CHIP_XML)
        drv = adb_driver.AdbDriver(self.options)
        drv.serial = "emulator-5580"
        drv.screen_size = "2152x2076"
        return drv

    def test_verify_and_wait_take_contains(self):
        drv = self.driver()
        drv.screenshot = lambda device, path: kit.write_png(path, 10, 10)
        device = self.ctx().device
        screen = {"id": "servings", "steps": [{"wait": {"id": "servings", "contains": "Makes 24"}}],
                  "verify": [{"id": "servings", "contains": "24"}, {"keyboard": "any"}]}
        shot = drv.run_screen(device, screen, "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(shot.state_check, "passed")

    def test_a_missing_text_is_a_wrong_state_naming_the_element_and_the_text(self):
        drv = self.driver()
        drv.screenshot = lambda device, path: kit.write_png(path, 10, 10)
        screen = {"id": "servings", "steps": [], "state": "twelve servings",
                  "verify": [{"id": "servings", "contains": "12"}, {"keyboard": "any"}]}
        shot = drv.run_screen(self.ctx().device, screen, "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertEqual(shot.state_check, "failed")
        self.assertIn("id 'servings' containing '12'", shot.reason)
        self.assertIn("twelve servings", shot.reason)

    def test_a_wait_that_never_shows_the_text_fails_its_step(self):
        drv = self.driver()
        drv.screenshot = lambda device, path: kit.write_png(path, 10, 10)
        screen = {"id": "servings", "steps": [{"wait": {"id": "servings", "contains": "12", "timeout": 2}}]}
        shot = drv.run_screen(self.ctx().device, screen, "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("containing '12'", shot.reason)


class ContainsOtherDriversTests(Case):
    def test_appium_reads_the_page_source_on_ios_and_android(self):
        drv = appium_driver.AppiumDriver(self.options)
        drv.inspect_tree = lambda ctx: IOS_SOURCE
        ctx = self.ctx("ios")
        self.assertIsNotNone(drv.find_containing(ctx, ("id", "servings"), "24"))
        self.assertIsNone(drv.find_containing(ctx, ("id", "servings"), "25"))
        self.assertIsNotNone(drv.find_containing(ctx, ("xpath", "//XCUIElementTypeOther"), "makes 24"))
        drv.inspect_tree = lambda ctx: ANDROID_SOURCE
        ctx = self.ctx("android")
        self.assertIsNotNone(drv.find_containing(ctx, ("id", "servings"), "24"),
                             "the child's text counts on Android")

    def test_appium_source_elements_by_family(self):
        root = ET.fromstring(IOS_SOURCE)
        els = appium_driver.source_elements(root, "ios")
        self.assertTrue(any(e.id == "servings" and e.text == "Makes 24" for e in els))

    def test_an_agents_tree_is_read_once_for_contains(self):
        drv = devflow_driver.DRIVER(self.options)
        calls = []

        def tree(device):
            calls.append(1)
            return [{"type": "Grid", "automationId": "root", "children": [
                {"type": "Border", "automationId": "servings", "id": "e1", "children": [
                    {"type": "Label", "text": "Makes", "id": "e2"}, {"type": "Label", "text": "24", "id": "e3"}]}]}]
        drv.tree = tree
        ctx = self.ctx("ios")
        self.assertIsNotNone(drv.find_containing(ctx, ("id", "servings"), "24"))
        self.assertIsNone(drv.find_containing(ctx, ("id", "servings"), "Makes 25"))
        self.assertIsNotNone(drv.find_containing(ctx, ("text", "Makes"), "makes"))
        self.assertEqual(len(calls), 3)

    def test_chrome_passes_contains_to_the_page(self):
        drv = chrome_driver.DRIVER(self.options)
        seen = []

        def evaluate(expr, dry=None, **kw):
            seen.append(expr)
            return {"x": 5, "y": 5, "width": 4, "height": 4}
        drv.evaluate = evaluate
        self.assertIsNotNone(drv.find_containing(self.ctx("web"), ("css", ".chip"), "24"))
        q = json.loads(seen[-1][seen[-1].rindex("(") + 1:-1])
        self.assertEqual(q["contains"], "24")
        self.assertIn("function shows(e)", seen[-1])
        drv.find(self.ctx("web"), ("css", ".chip"))
        self.assertNotIn("contains", json.loads(seen[-1][seen[-1].rindex("(") + 1:-1]))

    def test_macos_reads_the_element_and_everything_in_it(self):
        drv = macos_driver.DRIVER(self.options)
        drv.process = "Sample Recipes"
        scripts = []

        def osascript(script, js=False, **kw):
            scripts.append(script)
            return "texts:\nservings chip\nmissing value\nMakes 24"
        drv.osascript = osascript
        self.assertIsNotNone(drv.find_containing(self.ctx("macos"), ("id", "servings"), "24"))
        self.assertIsNone(drv.find_containing(self.ctx("macos"), ("id", "servings"), "25"))
        self.assertIn("entire contents of e", scripts[-1])
        drv.osascript = lambda script, js=False, **kw: "missing"
        self.assertIsNone(drv.find_containing(self.ctx("macos"), ("id", "servings"), "24"))

    def test_maestro_skips_a_wait_it_cannot_check_and_says_what_to_do(self):
        drv = maestro_driver.DRIVER(self.options)
        why = drv.unsupported({"id": "s", "steps": [{"wait": {"id": "servings", "contains": "24"}}]},
                              {"id": "d", "platform": "android"})
        self.assertIn("can't read what an element shows", why)
        self.assertIn('{"text": "24"}', why)

    def test_a_driver_that_cannot_read_contains_reports_verify_unchecked(self):
        class Plain(base.Driver):
            NAME = "plain"
            FINDERS = ("id",)
            CONTAINS = False

            def find(self, ctx, query):
                return base.Element(id=query[1])

            def screenshot(self, device, path):
                kit.write_png(path, 10, 10)
        shot = Plain(self.options).run_screen(self.ctx().device, {"id": "s", "steps": [], "verify": {
            "id": "servings", "contains": "24"}}, "en-US")
        self.assertEqual(shot.status, "taken")
        self.assertEqual(shot.state_check, "unchecked")
        self.assertTrue(any("containing '24'" in w for w in shot.warnings), shot.warnings)


class ContainsPlanTests(unittest.TestCase):
    def plan(self, verify=None, steps=None):
        return kit.sample_plan([{"id": "phone", "platform": "android", "driver": "adb", "width": 1, "height": 1}],
                               [{"id": "servings", "steps": steps or [], "verify": verify or {"id": "x"}}])

    def test_the_schema_takes_contains_on_wait_and_verify_only(self):
        sch = capture.load_schema()
        ok = self.plan(verify=[{"id": "servings", "contains": "24"}, {"label": "Servings", "contains": "24"}],
                       steps=[{"wait": {"id": "servings", "contains": "24", "timeout": 3}}])
        self.assertEqual(schema.validate(ok, sch), [])
        bad = self.plan(steps=[{"tap": {"id": "servings", "contains": "24"}}])
        self.assertNotEqual(schema.validate(bad, sch), [])

    def test_staging_md_says_what_it_contains(self):
        md = capture.staging_markdown(self.plan(verify={"id": "servings", "contains": "24"}))
        self.assertIn("id `servings` containing `24`", md)


# -- the full-screen keyboard ------------------------------------------------------------------------------------

class FullScreenFoldable(test_postures.FakeFoldable):
    """An open foldable in landscape: text entry puts the keyboard full screen (extract mode), and a tap while
    it's up lands on it."""

    def __init__(self, **kw):
        test_postures.FakeFoldable.__init__(self, **kw)
        self.fullscreen = True
        self.taps = []
        self.tapped_keyboard = 0

    def shell(self, text):
        if text == "dumpsys input_method":
            return ("      mImeWindowVis=%d\n      mInputShown=%s\n"
                    "  mFullscreenApplied=%s mIsFullscreen=%s mExtractViewHidden=false\n" % (
                        3 if self.keyboard else 0, "true" if self.keyboard else "false",
                        "true" if self.fullscreen else "false", "true" if self.fullscreen else "false"))
        if text.startswith("input tap "):
            if self.keyboard and self.fullscreen:
                self.tapped_keyboard += 1
            else:
                self.taps.append(text)
            return ""
        return test_postures.FakeFoldable.shell(self, text)


class FullScreenKeyboardTests(test_postures.Case):
    def prepared(self, fullscreen=True):
        fold = FullScreenFoldable().install(self.run_)
        fold.fullscreen = fullscreen
        self.run_.on(r"exec-out cat /sdcard/appstores-ui.xml", out=CHIP_XML)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(target={"avd": "appstores-fold", "statusBarCheck": False})
        drv.prepare(device, {})
        return fold, drv, device

    def test_the_parser_reads_the_input_methods_own_flag(self):
        self.assertTrue(adb_driver.keyboard_fullscreen("mFullscreenApplied=true mIsFullscreen=true"))
        self.assertFalse(adb_driver.keyboard_fullscreen("mIsFullscreen=false"))
        self.assertIsNone(adb_driver.keyboard_fullscreen("mInputShown=true"))

    def test_a_tap_closes_a_full_screen_keyboard_first(self):
        fold, drv, device = self.prepared()
        fold.keyboard = True
        shot = drv.run_screen(device, self.screen([{"tap": {"id": "done"}}], verify={"keyboard": "any"}), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(fold.tapped_keyboard, 0, "the Done tap landed on the keyboard")
        self.assertEqual(fold.taps, ["input tap 1950 1950"])
        self.assertEqual(fold.navigated_back, 0, "back pressed with the keyboard down navigates")
        self.assertTrue(any("full screen" in l for l in self.hooks.log), self.hooks.log)

    def test_a_keyboard_on_part_of_the_screen_is_left_for_the_tap(self):
        fold, drv, device = self.prepared(fullscreen=False)
        fold.keyboard = True
        before = len(self.run_.matching(r"KEYCODE_BACK"))
        drv.run_screen(device, self.screen([{"tap": {"id": "done"}}], verify={"keyboard": "any"}), "en-US")
        self.assertEqual(len(self.run_.matching(r"KEYCODE_BACK")), before)
        self.assertTrue(fold.keyboard)

    def test_hide_keyboard_closes_a_full_screen_keyboard_and_nothing_else(self):
        fold, drv, device = self.prepared()
        fold.keyboard = True
        shot = drv.run_screen(device, self.screen([{"hideKeyboard": True}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertFalse(fold.keyboard)
        self.assertEqual(fold.navigated_back, 0)

    def test_a_hosted_driver_asks_its_adb_host_before_a_tap(self):
        calls = []

        class Host(object):
            serial = "emulator-5580"
            STEPS = ()

            def clear_fullscreen_keyboard(self, ctx):
                calls.append(ctx.index)

        drv = appium_driver.AppiumDriver(self.options)
        drv._host_name, drv._host = "adb", Host()
        drv.ref = lambda ctx, value, timeout=None: "el-1"
        drv.wd = lambda *a, **kw: None
        drv.sid = lambda: "/session/s1"
        ctx = base.StepContext(self.device(driver="appium"), {"id": "s", "steps": []}, "en-US", base.Shot(), 3, None)
        drv.step_tap(ctx, {"id": "done"})
        self.assertEqual(calls, [3])
        host_less = hosted.HostedDriver(self.options)
        host_less._host_name, host_less._host = None, None
        host_less.before_tap(ctx)   # nothing to ask: no error


# -- the app's revision and --changes ------------------------------------------------------------------------------

DIFF = """diff --git a/src/Pages/ServingsPage.xaml b/src/Pages/ServingsPage.xaml
index 1111111..2222222 100644
--- a/src/Pages/ServingsPage.xaml
+++ b/src/Pages/ServingsPage.xaml
@@ -12 +12,3 @@
-    <Entry AutomationId="servingsEntry" Placeholder="Amount" />
+    <Label AutomationId="servingsChip" Text="{Binding Amount}" />
+    <Button AutomationId="addServing" Text="Add" />
diff --git a/src/Pages/MenuPage.xaml b/src/Pages/MenuPage.xaml
deleted file mode 100644
index 3333333..0000000
--- a/src/Pages/MenuPage.xaml
+++ /dev/null
@@ -1,2 +0,0 @@
--- a comment that starts like a header
-    <Button AutomationId="settingsButton" />
diff --git a/src/Pages/HistoryPage.xaml b/src/Pages/HistoryPage.xaml
--- a/src/Pages/HistoryPage.xaml
+++ b/src/Pages/HistoryPage.xaml
@@ -3 +3 @@
-    <Label AutomationId="historyTitle" Text="History" FontSize="20" />
+    <Label AutomationId="historyTitle" Text="History" FontSize="22" />
"""


class ChangesTests(test_capture.CaptureCase):
    def git_repo(self, head=HEAD, revs=(THEN, OLDER), diff=DIFF, counts=None):
        """Answer git as a checkout at ``head`` that knows ``revs``."""
        counts = counts or {THEN: 120, OLDER: 240}
        r = self.hooks.runner
        r.on(r"^git -C \S+ rev-parse HEAD$", out=head + "\n")
        for rev in revs:
            r.on(r"^git -C \S+ rev-parse --verify --quiet '?%s" % rev, out=rev + "\n")
            r.on(r"^git -C \S+ rev-list --count %s\.\.HEAD$" % rev, out="%d\n" % counts.get(rev, 1))
        r.on(r"^git -C \S+ rev-parse --verify --quiet '?v1\.4", out=OLDER + "\n")
        r.on(r"^git -C \S+ log -1 --format=%cs", out="2026-10-02\n")
        r.on(r"^git -C \S+ log -1 --format=%cI", out="2026-11-19T10:00:00+00:00\n")
        r.on(r"^git -C \S+ describe", out="v1.5-120-gccccccc\n")
        r.on(r"^git -C \S+ status --porcelain", out="")
        r.on(r"^git -C \S+ log --oneline", out="ccccccc Servings: a row of chips\nbbbbbbb Menu: settings moved\n")
        r.on(r"^git -C \S+ diff --stat", out=" src/Pages/ServingsPage.xaml | 3 ++-\n src/Pages/MenuPage.xaml | 2 --\n")
        r.on(r"^git -C \S+ diff --name-only", out="src/Pages/ServingsPage.xaml\nsrc/Pages/MenuPage.xaml\n"
                                                  "src/Pages/HistoryPage.xaml\n")
        r.on(r"^git -C \S+ diff --unified=0", out=diff)

    def update_plan(self):
        screens = [
            {"id": "servings", "sources": ["src/Pages/ServingsPage.xaml"],
             "steps": [{"launch": {}}, {"name": "amount", "type": {"id": "servingsEntry", "text": "24"}}],
             "verify": {"id": "ingredientsCard"}},
            {"id": "menu", "steps": [{"launch": {}}, {"tap": {"xpath": "//*[@name='settingsButton']"}}],
             "verify": {"id": "settingsTitle"}},
            {"id": "history", "steps": [{"launch": {}}], "verify": {"id": "historyTitle"}},
            {"id": "overview", "steps": [{"launch": {}}], "verify": {"id": "overviewTitle"}}]
        return self.plan(screens=screens, appSource={"repo": ".", "paths": ["src/Pages"]})

    def test_changed_lines_reads_headers_only_after_diff_git(self):
        lines = capture.changed_lines(DIFF)
        self.assertEqual(sorted(lines), ["src/Pages/HistoryPage.xaml", "src/Pages/MenuPage.xaml",
                                         "src/Pages/ServingsPage.xaml"])
        self.assertIn("-- a comment that starts like a header", lines["src/Pages/MenuPage.xaml"]["-"])

    def test_a_run_records_the_apps_revision(self):
        self.git_repo()
        app = os.path.join(self.tmp, "build", "Sample.app")
        os.makedirs(app)
        with open(os.path.join(app, "Info.plist"), "wb") as f:
            plistlib.dump({"CFBundleShortVersionString": "1.5", "CFBundleVersion": "120"}, f)
        plan = kit.sample_plan([{"id": "phone", "platform": "ios", "driver": "fake", "width": 120, "height": 260}],
                               [{"id": "plan", "steps": [{"launch": {}}]}])
        plan["app"]["ios"]["app"] = "build/Sample.app"
        path = kit.write_plan(self.tmp, plan)
        self.assertEqual(self.main("--plan", path), 0)
        report = self.report()
        self.assertEqual(report["app"]["revision"], HEAD)
        self.assertEqual(report["app"]["describe"], "v1.5-120-gccccccc")
        self.assertFalse(report["app"]["dirty"])
        self.assertEqual(report["app"]["builds"], {"ios": {"version": "1.5", "build": "120"}})
        self.assertEqual(self.shot("en-US", "phone", "plan")["appRevision"], HEAD)

    def test_no_checkout_records_nothing_and_still_captures(self):
        path = self.plan()
        self.assertEqual(self.main("--plan", path), 0)
        self.assertNotIn("app", self.report())
        self.assertNotIn("appRevision", self.shot("en-US", "phone", "plan"))

    def test_a_run_warns_when_the_app_moved_since_the_kept_shots(self):
        self.git_repo()
        path = self.update_plan()
        jsonio.dump({"version": 1, "app": {"revision": THEN}, "shots": [
            {"locale": "en-US", "device": "phone", "screen": "overview", "status": "taken", "appRevision": THEN}]},
            os.path.join(self.tmp, "captures", "capture-report.json"))
        with contextlib.redirect_stderr(io.StringIO()):
            self.main("--plan", path, "--screens", "overview")
        self.assertTrue(any("the app changed since the last capture" in l and "--changes" in l
                            for l in self.logged), self.logged)

    def test_changes_lists_commits_files_and_the_screens_to_recheck(self):
        self.git_repo()
        path = self.update_plan()
        jsonio.dump({"version": 1, "shots": [
            {"locale": "en-US", "device": "phone", "screen": "servings", "status": "taken", "appRevision": THEN},
            {"locale": "en-US", "device": "phone", "screen": "menu", "status": "taken", "appRevision": OLDER},
            {"locale": "en-US", "device": "phone", "screen": "history", "status": "missed"}]},
            os.path.join(self.tmp, "captures", "capture-report.json"))
        self.assertEqual(self.main("--plan", path, "--changes"), 0)
        out = self.stdout
        self.assertIn("9999999999 (2026-10-02) -> cccccccccc (HEAD), 240 commits in all", out, "from the oldest kept shot")
        self.assertIn("taken at 2 revisions", out)
        self.assertIn("ccccccc Servings: a row of chips", out)
        self.assertIn("src/Pages/ServingsPage.xaml | 3 ++-", out)
        servings = [l for l in out.splitlines() if l.strip().startswith("servings:")][0]
        self.assertIn("its sources changed (src/Pages/ServingsPage.xaml)", servings)
        self.assertIn('step "amount" (type)\'s id `servingsEntry` was removed (and isn\'t added back anywhere) in '
                      "src/Pages/ServingsPage.xaml", servings)
        menu = [l for l in out.splitlines() if l.strip().startswith("menu:")][0]
        self.assertIn("step 2 (tap)'s xpath `settingsButton` was removed", menu)
        history = [l for l in out.splitlines() if l.strip().startswith("history:")][0]
        self.assertIn("verify's id `historyTitle` is on a changed line in src/Pages/HistoryPage.xaml", history)
        self.assertIn("the rest (overview)", out)
        self.assertIn("build the app clean", out)
        self.assertIn("stepsPatch", out)
        git_calls = [l for l in self.hooks.runner.lines if l.startswith("git ")]
        self.assertTrue(all(l.endswith(" -- src/Pages") for l in git_calls if " diff " in l or "log --oneline" in l),
                        "the screen's source is under appSource.paths: looked at once (%s)" % git_calls)

    def test_changes_since_a_named_revision(self):
        self.git_repo()
        path = self.update_plan()
        self.assertEqual(self.main("--plan", path, "--changes", "v1.4"), 0)
        self.assertIn("9999999999", self.stdout)

    def test_changes_without_a_revision_or_a_checkout_is_usage(self):
        path = self.update_plan()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.main("--plan", path, "--changes"), 3)
        self.assertIn("isn't a git checkout", err.getvalue())
        self.git_repo()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(self.main("--plan", path, "--changes"), 3)
        self.assertIn("pass --changes <revision>", err.getvalue())

    def test_the_schema_takes_app_source_and_screen_sources(self):
        plan = jsonio.load(self.update_plan())
        self.assertEqual(schema.validate(plan, capture.load_schema()), [])
        plan["appSource"]["branch"] = "main"
        self.assertNotEqual(schema.validate(plan, capture.load_schema()), [])


if __name__ == "__main__":
    unittest.main()
