"""Tests for typing at a person's pace (``rate`` on ``type`` and ``fill``: key by key, so a recording shows each key
land) and for a ``scroll`` ``in`` that would otherwise swipe a text field (it taps the field and opens the keyboard).

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs a real tool, reaches
a network or waits: the fake form, Appium server and clock from the other tests answer.
"""

from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture_testkit as kit  # noqa: E402
import test_drivers_cli as cli_tests  # noqa: E402
import test_drivers_inapp as inapp  # noqa: E402
import test_forms  # noqa: E402
from drivers import appium as appium_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import chrome as chrome_driver  # noqa: E402


def tearDownModule():
    kit.assert_no_residue()


class RateTests(unittest.TestCase):
    def test_a_rate_is_keys_a_second(self):
        self.assertIsNone(base.typing_rate({"text": "12"}))
        self.assertEqual(base.typing_rate({"text": "12", "rate": 4}), 4.0)
        for bad in (0, -1, "4", True):
            with self.assertRaises(ValueError):
                base.typing_rate({"text": "12", "rate": bad})

    def test_a_fields_own_rate_wins_over_the_fills(self):
        self.assertEqual(base.fill_rates({"fields": [{"field": "a", "text": "1"}, {"field": "b", "text": "2", "rate": 8}],
                                          "rate": 4}), [4, 8])
        self.assertEqual(base.fill_rates([{"field": "a", "text": "1"}]), [None])

    def test_what_counts_as_a_text_field(self):
        for name in ("XCUIElementTypeTextField", "XCUIElementTypeSecureTextField", "android.widget.EditText",
                     "input", "TEXTAREA", "Microsoft.Maui.Controls.Entry"):
            self.assertTrue(base.is_editable(name), name)
        for name in (None, "", "XCUIElementTypeScrollView", "android.widget.TextView", "div", "Label"):
            self.assertFalse(base.is_editable(name), name)


class AdbRateTests(test_forms.AdbFormCase):
    def test_a_fill_at_a_rate_types_key_by_key_with_pauses(self):
        form, drv, device = self.prepared()
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}], "rate": 4}}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(form.texts["servings"], "12")
        typed = [l for l in self.run_.lines if "input text" in l]
        self.assertEqual([l.split("input text ")[-1].strip("'") for l in typed], ["1", "2"])
        self.assertIn(0.25, self.hooks.time.slept)

    def test_without_a_rate_the_value_goes_in_at_once(self):
        form, drv, device = self.prepared()
        drv.run_screen(device, self.screen([{"fill": [{"field": "servings", "text": "12"}]}]), "en-US")
        self.assertEqual([l.split("input text ")[-1].strip("'") for l in self.run_.lines if "input text" in l],
                         ["12"])

    def test_a_bad_rate_fails_the_step(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen([{"type": {"id": "servings", "text": "12", "rate": 0}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("rate is keys a second", shot.reason)

    def test_text_adb_cant_type_is_refused_before_any_key(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen([{"type": {"id": "servings", "text": "1é2", "rate": 4}}]),
                              "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertEqual(form.texts["servings"], "")

    def test_dry_run_says_its_typed_key_by_key(self):
        form, drv, device = self.prepared()
        lines = []
        base.DRY_RUN = True
        base.LOG = lines.append
        drv.run_screen(device, self.screen([{"fill": {"fields": [{"field": "servings", "text": "12"}], "rate": 4}}]),
                       "en-US")
        self.assertTrue(any("typing '12' key by key, 4 a second" in l for l in lines), lines)


class AppiumRateTests(inapp.Case):
    def prepared(self, platform):
        t = self.transport
        t.on("GET", r"^/status$", body=inapp.answer("appium-status.json"))
        t.on("POST", r"^/session$", body=inapp.answer("appium-session.json"))
        t.on("POST", r"/element$", body=json.dumps({"value": {appium_driver.W3C_ELEMENT: "el-servings"}}))
        t.on("POST", r"/element/el-servings/value$", body='{"value": null}')
        t.on("POST", r"/execute/sync$", body='{"value": null}')
        d = inapp.drivers.get("appium")(self.options())
        dev = self.device("appium", platform=platform, target={"host": "fakehost"})
        d.prepare(dev, {})
        d.apply_locale(dev, "en-US", base.Shot())
        self.transport.calls[:] = []
        return d, dev

    def values(self):
        return [c[2]["text"] for c in self.transport.find("POST", r"/element/el-servings/value$")]

    def test_ios_types_one_value_call_a_key(self):
        d, dev = self.prepared("ios")
        d.step_type(self.ctx(dev), {"id": "servings", "text": "6.8", "rate": 5})
        self.assertEqual(self.values(), ["6", ".", "8"])
        self.assertEqual([s for s in self.hooks.time.slept if s == 0.2], [0.2, 0.2])

    def test_android_does_the_same(self):
        d, dev = self.prepared("android")
        d.step_type(self.ctx(dev), {"id": "servings", "text": "75", "rate": 4})
        self.assertEqual(self.values(), ["7", "5"])

    def test_without_a_rate_one_call_as_before(self):
        d, dev = self.prepared("ios")
        d.step_type(self.ctx(dev), {"id": "servings", "text": "6.8"})
        self.assertEqual(self.values(), ["6.8"])


class AppiumTextFieldScrollTests(inapp.Case):
    """A scroll ``in`` a text field whose pane isn't found again would swipe the field itself: the screen instead."""

    def prepared(self, tag):
        t = self.transport
        t.on("GET", r"^/status$", body=inapp.answer("appium-status.json"))
        t.on("POST", r"^/session$", body=inapp.answer("appium-session.json"))
        t.on("GET", r"/source$", body=json.dumps({"value": test_forms.IOS_SOURCE}))
        t.on("POST", r"/element$", body=[
            (200, json.dumps({"value": {appium_driver.W3C_ELEMENT: "el-servings"}})),
            (404, json.dumps({"value": {"error": "no such element", "message": "gone"}}))])
        t.on("GET", r"/element/el-servings/name$", body=json.dumps({"value": tag}))
        t.on("POST", r"/execute/sync$", body='{"value": null}')
        d = inapp.drivers.get("appium")(self.options())
        dev = self.device("appium", platform="ios", target={"host": "fakehost"})
        d.prepare(dev, {})
        d.apply_locale(dev, "en-US", base.Shot())
        self.transport.calls[:] = []
        return d, dev

    def gestures(self):
        return [c[2]["args"][0] for c in self.transport.find("POST", r"/execute/sync$")
                if c[2]["script"] == "mobile: swipe"]

    def test_a_text_field_is_never_swiped_the_screen_is(self):
        d, dev = self.prepared("XCUIElementTypeTextField")
        ctx = self.ctx(dev)
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "servings"}})
        self.assertEqual([g.get("elementId") for g in self.gestures()], [None])
        self.assertTrue(any("it's a text field, so the screen was scrolled instead" in w for w in ctx.shot.warnings),
                        ctx.shot.warnings)

    def test_anything_else_is_still_scrolled_itself(self):
        d, dev = self.prepared("XCUIElementTypeOther")
        ctx = self.ctx(dev)
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "servings"}})
        self.assertEqual([g.get("elementId") for g in self.gestures()], ["el-servings"])
        self.assertEqual(ctx.shot.warnings, [])


class SwipingDriver(base.Driver):
    """A driver whose scroll is a finger's swipe and whose tree shows nothing that scrolls around the field."""

    NAME = "swiper"
    STEPS = ("scroll",)
    SCROLL_SWIPES = True

    def __init__(self, cls):
        base.Driver.__init__(self, base.Options())
        self.cls = cls
        self.scrolled = []

    def find(self, ctx, query):
        return base.Element(id=query[1], cls=self.cls, bounds=(0, 0, 100, 40))

    def scroll_pane(self, ctx, query, found):
        return found, "none", self.cls

    def scroll_once(self, ctx, direction, within=None):
        self.scrolled.append(within.id if within is not None else None)


class GuardTests(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)

    def ctx(self):
        return base.StepContext({"id": "phone", "platform": "android"}, {"id": "form", "steps": []}, "en-US",
                                base.Shot(), 1, None)

    def test_an_edit_text_with_nothing_scrolling_around_it_scrolls_the_screen(self):
        d, ctx = SwipingDriver("android.widget.EditText"), self.ctx()
        d.step_scroll(ctx, {"direction": "down", "times": 2, "in": {"id": "servings"}})
        self.assertEqual(d.scrolled, [None, None])
        self.assertEqual(len(ctx.shot.warnings), 1)

    def test_a_list_with_nothing_around_it_is_scrolled_itself(self):
        d, ctx = SwipingDriver("android.widget.LinearLayout"), self.ctx()
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "items"}})
        self.assertEqual(d.scrolled, ["items"])
        self.assertEqual(ctx.shot.warnings, [])

    def test_a_driver_that_scrolls_by_a_call_isnt_guarded(self):
        d, ctx = SwipingDriver("android.widget.EditText"), self.ctx()
        d.SCROLL_SWIPES = False
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "servings"}})
        self.assertEqual(d.scrolled, ["servings"])


class LeftOutTests(inapp.Case):
    def test_maestro_says_it_types_at_its_own_pace(self):
        d = inapp.drivers.get("maestro")(self.options())
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        lines = d.write_flow(dev, self.screen([{"fill": {"fields": [{"field": "servings", "text": "12"}], "rate": 4}},
                                               {"type": {"id": "minutes", "text": "45", "rate": 4}}]),
                             "en-US").splitlines()
        self.assertIn('- inputText: "12"', lines)
        self.assertEqual(len([l for l in self.hooks.log if "rate left out" in l]), 2, self.hooks.log)

    def test_an_agents_fill_says_the_rate_is_left_out(self):
        self.agents((10224, "com.example.samplerecipes", None, 41017, "MacCatalyst"))
        self.runner.on(r"ui fill", out='{"success": true}')
        d = inapp.drivers.get("devflow")(self.options())
        ctx = self.ctx(self.device("devflow"))
        d.step_type(ctx, {"id": "servings", "text": "12", "rate": 4})
        self.assertTrue(any("puts a value in at once, so rate is left out" in w for w in ctx.shot.warnings),
                        ctx.shot.warnings)


class ChromeRateTests(cli_tests.DriverCase):
    def test_the_web_inserts_a_character_at_a_time(self):
        fake = cli_tests.FakeChrome(elements={("id", "servings"): {"x": 100, "y": 300, "width": 200, "height": 40}})
        saved = chrome_driver.CHROME_FACTORY
        chrome_driver.CHROME_FACTORY = lambda: fake
        self.addCleanup(setattr, chrome_driver, "CHROME_FACTORY", saved)
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device(id="web-phone", driver="chrome", width=1290, height=2796, app={}, target={"scale": 3})
        drv.prepare(device, {"app": {"web": {"url": "http://localhost:8080/"}}})
        shot = drv.run_screen(device, self.screen([{"type": {"id": "servings", "text": "12", "rate": 4}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual([p["text"] for m, p in fake.calls if m == "Input.insertText"], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
