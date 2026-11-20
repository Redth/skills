"""Tests for screens that look in use: the ``fill`` step (a form typed into across drivers), ``unfocus`` (no caret
left blinking), ``hideKeyboard``'s tries (a keyboard that won't close fails plainly), ``scroll`` within a pane, to
an element both ways and back to the top, ``in`` a pane by anything inside it (its nearest scrolling ancestor, on
each driver that scrolls), a ``verify`` naming a field ``fill`` left out of sight, ``settle`` after typing, and the
plan's ``inUse`` in ``staging.md``.

Run from this folder: ``python3 -m unittest discover -s . -p 'test_*.py'``. Nothing here runs a real tool, reaches
a network or waits: a fake two-pane Android form answers adb's commands.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture  # noqa: E402
import capture_testkit as kit  # noqa: E402
import test_drivers_cli as cli_tests  # noqa: E402
import test_drivers_inapp as inapp  # noqa: E402
import test_postures  # noqa: E402
from appstores_lib import jsonio  # noqa: E402
from drivers import adb as adb_driver  # noqa: E402
from drivers import appium as appium_driver  # noqa: E402
from drivers import base  # noqa: E402
from drivers import chrome as chrome_driver  # noqa: E402

PACKAGE = "com.example.samplerecipes"
LEFT = (0, 200, 600, 1920)       # the list pane, where the screen's middle (540, 960) falls
FORM = (600, 200, 1080, 1920)    # the form pane, on the right
KEYBOARD_TOP = 1120              # the keyboard covers y >= this while it's up
STEP = 600                       # how far one swipe moves a pane's content
MAX_OFF = 1200
# The form's fields: id -> y in the form's content (the visible part starts at the pane's top).
FIELDS = {"title": 20, "servings": 200, "minutes": 500, "notes": 2400}


def tearDownModule():
    kit.assert_no_residue()


class FakeForm(test_postures.FakeFoldable):
    """An Android device showing a two-pane screen: a list on the left, a scrolling form on the right with three
    fields (one below the fold). Taps focus a field and bring the keyboard up, which covers the bottom of the
    screen; back closes the keyboard (with it down, back navigates); Escape clears the focus (or, with
    ``escape_goes_back``, navigates as an unhandled Escape does on older Android); swipes move the pane they start
    in."""

    def __init__(self, off=0, escape_goes_back=False, pane_without_id=False):
        test_postures.FakeFoldable.__init__(self, foldable=False)
        self.pane_without_id = pane_without_id
        self.off = off
        self.left_off = 0
        self.escape_goes_back = escape_goes_back
        self.texts = dict((k, "") for k in FIELDS if k != "title")
        self.focused = None
        self.page = "form"
        self.swipes = []
        self.tapped_keyboard = 0

    def answer(self, cmd):
        line = " ".join(cmd)
        if "exec-out cat" in line:
            return self.dump()
        return test_postures.FakeFoldable.answer(self, cmd)

    def screen_y(self, field):
        return FORM[1] + FIELDS[field] - self.off

    def visible(self, field):
        y = self.screen_y(field)
        return FORM[1] <= y and y + 60 <= FORM[3]

    def dump(self):
        nodes = []
        if self.page == "form":
            nodes.append('<node index="0" text="" resource-id="%s:id/list" class="android.widget.ScrollView" '
                         'scrollable="true" bounds="[%d,%d][%d,%d]"/>' % ((PACKAGE,) + LEFT))
            kids = []
            for field in FIELDS:
                if not self.visible(field):
                    continue
                y = self.screen_y(field)
                cls = "android.widget.TextView" if field == "title" else "android.widget.EditText"
                text = "Scale recipe" if field == "title" else self.texts[field]
                kids.append('<node index="1" text="%s" resource-id="%s:id/%s" class="%s" focused="%s" '
                            'scrollable="false" bounds="[620,%d][1060,%d]"/>' % (
                                text, PACKAGE, field, cls, "true" if self.focused == field else "false", y, y + 60))
            # The pane: a ScrollView with no id of its own here (the app's id is on its content, inside it).
            content = '<node index="0" text="" resource-id="%s:id/form-content" class="android.widget.LinearLayout" ' \
                      'scrollable="false" bounds="[%d,%d][%d,%d]">%s</node>' % ((PACKAGE,) + FORM + ("".join(kids),))
            nodes.append('<node index="1" text="" resource-id="%s" class="android.widget.ScrollView" '
                         'scrollable="true" bounds="[%d,%d][%d,%d]">%s</node>'
                         % (("" if self.pane_without_id else PACKAGE + ":id/form",) + FORM + (content,)))
        else:
            nodes.append('<node index="0" text="Home" resource-id="%s:id/home" class="android.widget.TextView" '
                         'bounds="[40,200][600,260]"/>' % PACKAGE)
        return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><node index="0" text="" '
                'resource-id="" class="android.widget.FrameLayout" scrollable="false" bounds="[0,0][1080,1920]">%s'
                '</node></hierarchy>' % "".join(nodes))

    def shell(self, text):
        m = re.match(r"input swipe (\d+) (\d+) (\d+) (\d+) \d+$", text)
        if m:
            x1, y1, x2, y2 = (int(v) for v in m.groups())
            self.swipes.append((x1, y1, x2, y2))
            way = STEP if y1 > y2 else -STEP     # the finger up: the content moves down the page
            if FORM[0] <= x1 < FORM[2]:
                self.off = max(0, min(MAX_OFF, self.off + way))
            else:
                self.left_off = max(0, min(MAX_OFF, self.left_off + way))
            return ""
        m = re.match(r"input tap (\d+) (\d+)$", text)
        if m:
            x, y = int(m.group(1)), int(m.group(2))
            if self.keyboard and y >= KEYBOARD_TOP:
                self.tapped_keyboard += 1
                return ""
            for field in FIELDS:
                if field != "title" and self.visible(field) and self.screen_y(field) <= y <= self.screen_y(field) + 60 \
                        and 620 <= x <= 1060:
                    self.focused, self.keyboard = field, True
            return ""
        m = re.match(r"input text (.*)$", text)
        if m:
            if self.focused:
                self.texts[self.focused] += m.group(1).replace("%s", " ")
            return ""
        if text == "input keyevent KEYCODE_ESCAPE":
            if self.escape_goes_back:
                self.page, self.focused, self.keyboard = "home", None, False
                self.navigated_back += 1
            else:
                self.focused = None
            return ""
        if text == "input keyevent KEYCODE_BACK" and not self.keyboard:
            self.page = "home"
        return test_postures.FakeFoldable.shell(self, text)


class AdbFormCase(test_postures.Case):
    def prepared(self, **kw):
        form = FakeForm(**kw).install(self.run_)
        drv = adb_driver.AdbDriver(self.options)
        device = self.device(id="android-tablet", app={"package": PACKAGE, "activity": ".MainActivity"},
                             target={"avd": "appstores-form", "statusBarCheck": False})
        drv.prepare(device, {})
        return form, drv, device


class FillTests(AdbFormCase):
    def test_a_form_is_filled_across_the_fold_and_left_with_no_keyboard_caret_or_scroll(self):
        form, drv, device = self.prepared()
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": "minutes", "text": "45"},
                                      {"field": {"id": "notes"}, "text": "spicy"}],
                           "in": {"id": "form"}, "scrollTo": "top"}}]
        shot = drv.run_screen(device, self.screen(steps, verify=[{"id": "servings", "contains": "12"},
                                                                 {"keyboard": "hidden"}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(form.texts, {"servings": "12", "minutes": "45", "notes": "spicy"})
        self.assertFalse(form.keyboard)
        self.assertIsNone(form.focused, "the last field kept its focus (and its caret)")
        self.assertEqual(form.off, 0, "the form wasn't scrolled back to its top")
        self.assertEqual(form.left_off, 0, "the list pane was scrolled instead of the form")
        self.assertTrue(form.swipes and all(FORM[0] <= x1 < FORM[2] for x1, _, _, _ in form.swipes), form.swipes)
        self.assertEqual(form.tapped_keyboard, 0, "a field's tap landed on the keyboard")
        self.assertEqual(form.navigated_back, 0, "back pressed with the keyboard down navigates")
        self.assertEqual(form.page, "form")

    def test_the_keyboard_is_closed_before_each_next_field_on_android(self):
        form, drv, device = self.prepared()
        steps = [{"fill": [{"field": "servings", "text": "12"}, {"field": "minutes", "text": "45"}]}]
        drv.run_screen(device, self.screen(steps), "en-US")
        lines = self.run_.lines
        typed_first = self.run_.index(r"input text 12")
        tap_second = self.run_.index(r"input tap \d+ %d" % (FORM[1] + FIELDS["minutes"] + 30), typed_first)
        self.assertGreater(tap_second, typed_first)
        self.assertTrue(any("KEYCODE_BACK" in l for l in lines[typed_first:tap_second]), "the keyboard wasn't closed "
                                                                                  "before the next field")
        self.assertEqual(form.texts["minutes"], "45")

    def test_a_field_with_the_keyboard_kept_keeps_its_focus(self):
        form, drv, device = self.prepared()
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}], "keyboard": "keep"}}]
        shot = drv.run_screen(device, self.screen(steps, verify={"keyboard": "shown"}), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(form.keyboard)
        self.assertEqual(form.focused, "servings")

    def test_a_field_that_isnt_there_says_which(self):
        form, drv, device = self.prepared()
        steps = [{"fill": [{"field": "servings", "text": "12"}, {"field": "salt", "text": "3200"}]}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("field 2: id 'salt'", shot.reason)

    def test_text_dry_run_lists_each_field(self):
        form, drv, device = self.prepared()
        lines = []
        base.DRY_RUN = True
        base.LOG = lines.append
        drv.run_screen(device, self.screen([{"fill": [{"field": "servings", "text": "12"},
                                                       {"field": "minutes", "text": "45"}]}]), "en-US")
        self.assertTrue(any("fill 1: id 'servings' <- '12'" in l for l in lines), lines)
        self.assertTrue(any("fill 2: id 'minutes' <- '45'" in l for l in lines), lines)


class ScrollTests(AdbFormCase):
    def test_scroll_in_a_pane_swipes_inside_it_and_without_one_the_screens_middle(self):
        form, drv, device = self.prepared()
        drv.run_screen(device, self.screen([{"scroll": {"direction": "down"}}]), "en-US")
        self.assertEqual((form.off, form.left_off), (0, STEP), "the screen's middle is the list pane here")
        drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {"id": "form"}}}], sid="b"),
                       "en-US")
        self.assertEqual(form.off, STEP)
        x1, y1, x2, y2 = form.swipes[-1]
        self.assertTrue(FORM[0] <= x1 < FORM[2] and FORM[1] <= min(y1, y2) and max(y1, y2) <= FORM[3])

    def test_scroll_to_an_element_looks_up_when_down_ends(self):
        form, drv, device = self.prepared(off=MAX_OFF)
        shot = drv.run_screen(device, self.screen([{"scroll": {"to": {"id": "title"}, "in": {"id": "form"}}}],
                                                  verify={"id": "title"}), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(form.off, 0)
        ways = [y1 > y2 for _, y1, _, y2 in form.swipes]
        self.assertEqual(ways[0], True, "down first, as asked (the default)")
        self.assertIn(False, ways, "never scrolled up")

    def test_scroll_to_top_stops_when_the_content_stops_moving(self):
        form, drv, device = self.prepared(off=MAX_OFF)
        shot = drv.run_screen(device, self.screen([{"scroll": {"to": "top", "in": {"id": "form"}}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(form.off, 0)
        self.assertEqual(len(form.swipes), 3, "two to the top, one to see it moved no more")
        self.assertEqual(shot.warnings, [])

    def test_an_element_in_neither_direction_fails_naming_both(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen([{"scroll": {"to": {"id": "salt"}, "in": {"id": "form"},
                                                               "times": 3}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("scrolled down and up within id 'form'", shot.reason)


class PaneTests(AdbFormCase):
    """A scroll's or a fill's ``in`` may name anything inside the pane: what scrolls is its nearest scrolling
    ancestor, and the shot says so."""

    PANE = "in id %r: scrolled its nearest scrolling ancestor, android.widget.ScrollView [600,200][1080,1920]"

    def test_a_fill_in_one_of_its_own_fields_scrolls_the_pane_around_it(self):
        form, drv, device = self.prepared(pane_without_id=True)
        lines = []
        base.LOG = lines.append
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": "minutes", "text": "45"},
                                      {"field": "notes", "text": "spicy"}],
                           "in": {"id": "servings"}, "scrollTo": "top"}}]
        shot = drv.run_screen(device, self.screen(steps, verify=[{"id": "servings", "contains": "12"}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(form.texts, {"servings": "12", "minutes": "45", "notes": "spicy"})
        self.assertEqual((form.off, form.left_off), (0, 0), "the form wasn't scrolled back, or the list was scrolled")
        self.assertTrue(form.swipes and all(FORM[0] <= x1 < FORM[2] for x1, _, _, _ in form.swipes), form.swipes)
        self.assertEqual(shot.panes, [self.PANE % "servings"], "said once, though the field scrolled out of sight")
        self.assertTrue(any("id 'servings' is out of sight now: scrolling the pane it was in" in l for l in lines),
                        "the way back up never needed the pane found before")

    def test_the_panes_content_by_its_id_serves_as_well_as_an_xpath_to_the_scroll_view(self):
        form, drv, device = self.prepared(pane_without_id=True)
        shot = drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {"id": "form-content"}}}]),
                              "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual((form.off, form.left_off), (STEP, 0))
        self.assertEqual(shot.panes, [self.PANE % "form-content"])
        shot = drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {
            "xpath": "//node[@scrollable='true'][.//node[contains(@resource-id, 'form-content')]]"}}}], sid="b"),
            "en-US")
        self.assertEqual((form.off, form.left_off), (2 * STEP, 0))
        self.assertEqual(shot.panes, [], "the scroll view itself: nothing to say")

    def test_the_scroll_view_itself_is_scrolled_as_before_and_not_reported(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {"id": "form"}}}]), "en-US")
        self.assertEqual((form.off, form.left_off), (STEP, 0))
        self.assertEqual(shot.panes, [])

    def test_with_nothing_around_it_that_scrolls_the_element_itself_is_scrolled_and_said(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {
            "xpath": "/hierarchy/node"}}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual((form.off, form.left_off), (0, STEP), "the whole screen's middle is the list pane")
        self.assertEqual(len(shot.panes), 1)
        self.assertIn("nothing that scrolls is it or holds it (it's android.widget.FrameLayout [0,0][1080,1920]), "
                      "so it was scrolled itself", shot.panes[0])

    def test_scrolling_types_where_a_tree_has_no_flag(self):
        import xml.etree.ElementTree as ET
        for kind, scrolls in (("XCUIElementTypeScrollView", True), ("XCUIElementTypeTable", True),
                              ("XCUIElementTypeCollectionView", True), ("XCUIElementTypeTextField", False),
                              ("XCUIElementTypeTableRow", False), ("RecyclerView", True), ("ScrollViewer", True),
                              ("VerticalStackLayout", False)):
            self.assertEqual(base.scrolls(ET.Element(kind, {"type": kind})), scrolls, kind)
        self.assertFalse(base.scrolls(ET.Element("node", {"class": "android.widget.ScrollView",
                                                          "scrollable": "false"})), "the flag wins")


class OutOfSightTests(AdbFormCase):
    """A verify sees only what's on screen: a field fill typed that's out of sight once the form is scrolled back
    can't be checked, and fill says so."""

    STEPS = [{"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": "notes", "text": "spicy"}],
                       "in": {"id": "form"}, "scrollTo": "top"}}]

    def test_a_verify_naming_a_field_left_out_of_sight_is_warned_about(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen(self.STEPS, verify=[{"id": "notes", "contains": "spicy"}]),
                              "en-US")
        self.assertEqual(form.texts["notes"], "spicy")
        self.assertEqual(shot.status, "missed", "the verify can't see it")
        warned = [w for w in shot.warnings if "out of sight" in w]
        self.assertEqual(len(warned), 1, shot.warnings)
        for words in ("fill typed into id 'notes'", "scrolled back to the top (scrollTo)", "verify names it",
                      "sees only what's on screen", "check only the fields the shot shows", "leave scrollTo out"):
            self.assertIn(words, warned[0])

    def test_checking_only_the_fields_in_sight_warns_nothing(self):
        form, drv, device = self.prepared()
        shot = drv.run_screen(device, self.screen(self.STEPS, verify=[{"id": "servings", "contains": "12"}]),
                              "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertFalse(any("out of sight" in w for w in shot.warnings), shot.warnings)

    def test_without_scroll_to_nothing_is_checked(self):
        form, drv, device = self.prepared()
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": "notes", "text": "spicy"}],
                           "in": {"id": "form"}}}]
        shot = drv.run_screen(device, self.screen(steps, verify=[{"id": "notes", "contains": "spicy"}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertFalse(any("out of sight" in w for w in shot.warnings), shot.warnings)


class UnfocusTests(AdbFormCase):
    def test_unfocus_clears_the_caret_left_after_the_keyboard_closed(self):
        form, drv, device = self.prepared()
        steps = [{"type": {"id": "servings", "text": "12"}}, {"hideKeyboard": True}, {"unfocus": True}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertIsNone(form.focused)
        self.assertEqual(len(self.run_.matching(r"KEYCODE_ESCAPE")), 1)
        self.assertEqual(form.navigated_back, 0)

    def test_escape_is_never_pressed_without_a_focused_field(self):
        form, drv, device = self.prepared()
        drv.run_screen(device, self.screen([{"unfocus": True}]), "en-US")
        self.assertEqual(self.run_.matching(r"KEYCODE_ESCAPE"), [])
        self.assertEqual(form.page, "form")

    def test_escape_that_went_back_fails_loudly(self):
        form, drv, device = self.prepared(escape_goes_back=True)
        steps = [{"type": {"id": "servings", "text": "12"}}, {"hideKeyboard": True}, {"unfocus": True}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("Escape may have gone back", shot.reason)
        self.assertIn("give unfocus a tap", shot.reason)

    def test_settle_after_typing_warns_about_a_field_that_kept_its_focus(self):
        form, drv, device = self.prepared()
        steps = [{"type": {"id": "servings", "text": "12"}}, {"hideKeyboard": True}, {"settle": True}]
        shot = drv.run_screen(device, self.screen(steps), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(any("still has the focus after typing" in w and "unfocus" in w for w in shot.warnings),
                        shot.warnings)
        shot = drv.run_screen(device, self.screen(steps[:2] + [{"unfocus": True}, {"settle": True}], sid="b"),
                              "en-US")
        self.assertFalse(any("focus" in w for w in shot.warnings), shot.warnings)


class FocusMayRemainTests(unittest.TestCase):
    def test_what_leaves_a_field_focused(self):
        screen = {"steps": [{"type": {"id": "a", "text": "1"}}, {"settle": True}, {"unfocus": True},
                            {"settle": True}, {"fill": [{"field": "b", "text": "2"}]}, {"settle": True},
                            {"fill": {"fields": [{"field": "b", "text": "2"}], "keyboard": "keep"}},
                            {"settle": True}]}
        self.assertEqual([base.focus_may_remain(screen, i) for i in (2, 4, 6, 8)], [True, False, False, True])
        self.assertTrue(base.typed(screen))
        self.assertFalse(base.typed({"steps": [{"tap": {"id": "a"}}]}))


# -- hideKeyboard's tries ----------------------------------------------------------------------------------------

class Stuck(base.Driver):
    """A driver whose keyboard goes down only for what ``closes`` names (``own``, a tap target's id, ``scroll``);
    ``sees`` False makes it blind to the keyboard."""

    NAME = "stuck"
    STEPS = ("tap", "type", "wait", "hideKeyboard", "unfocus", "fill", "scroll", "settle")
    FINDERS = ("id",)

    def __init__(self, options, closes=(), sees=True):
        base.Driver.__init__(self, options)
        self.closes = closes
        self.sees = sees
        self.up = True
        self.done = []

    def keyboard_shown(self, ctx):
        return self.up if self.sees else None

    def hide_keyboard(self, ctx, value):
        self.done.append("own")
        if "own" in self.closes:
            self.up = False

    def find(self, ctx, query):
        return base.Element(id=query[1], bounds=(0, 0, 10, 10))

    def step_tap(self, ctx, value):
        what = value.get("id") if "id" in value else "%(x)g,%(y)g" % value
        self.done.append("tap " + what)
        if what in self.closes:
            self.up = False

    def scroll_once(self, ctx, direction, within=None):
        self.done.append("scroll " + direction)
        if "scroll" in self.closes:
            self.up = False

    def screenshot(self, device, path):
        kit.write_png(path, 10, 10)


class HideKeyboardTests(unittest.TestCase):
    def setUp(self):
        self.hooks = kit.Hooks()
        self.addCleanup(self.hooks.restore)
        self.tmp = tempfile.mkdtemp(prefix="capture-forms-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.options = base.Options(plan_dir=self.tmp, workdir=os.path.join(self.tmp, "work"))

    def ctx(self, steps=()):
        screen = {"id": "results", "steps": list(steps)}
        return base.StepContext({"id": "duo-outer", "platform": "ios"}, screen, "en-US", base.Shot(), 1, None)

    TRIES = {"done": {"id": "done"}, "tap": {"x": 700, "y": 180}, "scroll": True}

    def test_tries_go_in_order_and_stop_once_its_down(self):
        drv = Stuck(self.options, closes=("done",))
        drv.step_hideKeyboard(self.ctx(), self.TRIES)
        self.assertEqual(drv.done, ["own", "tap done"])
        self.assertFalse(drv.up)

    def test_a_scroll_then_last_a_neutral_tap_are_reached(self):
        drv = Stuck(self.options, closes=("700,180",))
        drv.step_hideKeyboard(self.ctx(), self.TRIES)
        self.assertEqual(drv.done, ["own", "tap done", "scroll up", "tap 700,180"])

    def test_a_keyboard_nothing_closes_fails_naming_each_try_and_saying_its_the_apps(self):
        drv = Stuck(self.options)
        with self.assertRaises(base.StepFailed) as raised:
            drv.step_hideKeyboard(self.ctx(), self.TRIES)
        message = str(raised.exception)
        for words in ("still up after", "the stuck driver's own close", "the Done id 'done'", "a tap on (700, 180)",
                      "a scroll up", "A number pad has no Done or Return key", "name it in done",
                      "that's the app's to fix", "tell the user", "don't capture the screen with the "
                      "keyboard up", "don't drop its typing"):
            self.assertIn(words, message)
        self.assertNotIn("Not tried yet", message)
        with self.assertRaises(base.StepFailed) as raised:
            Stuck(self.options).step_hideKeyboard(self.ctx(), True)
        self.assertIn("Not tried yet: a done", str(raised.exception))

    def test_own_false_leaves_the_drivers_close_out(self):
        drv = Stuck(self.options, closes=("title",))
        drv.step_hideKeyboard(self.ctx(), {"own": False, "tap": {"id": "title"}})
        self.assertEqual(drv.done, ["tap title"])

    def test_a_blind_driver_does_the_plans_taps_once_and_without_them_is_skipped(self):
        drv = Stuck(self.options, sees=False)
        drv.step_hideKeyboard(self.ctx(), {"tap": {"id": "title"}, "scroll": True})
        self.assertEqual(drv.done, ["own", "tap title"], "no scroll where nobody can see it's needed")

        class Blind(Stuck):
            def hide_keyboard(self, ctx, value):
                raise base.StepSkipped("can't see it")
        with self.assertRaises(base.StepSkipped):
            Blind(self.options, sees=False).step_hideKeyboard(self.ctx(), True)

    def test_a_fill_on_a_stuck_keyboard_fails_too_but_a_blind_one_goes_quietly(self):
        steps = [{"fill": {"fields": [{"field": "servings", "text": "12"}], "keyboard": {"tap": {"id": "title"}}}}]
        drv = Stuck(self.options)
        drv.step_type = lambda ctx, value: drv.done.append("type %s" % value["text"])
        with self.assertRaises(base.StepFailed):
            drv.step_fill(self.ctx(steps), steps[0]["fill"])
        blind = Stuck(self.options, sees=False)
        blind.step_type = lambda ctx, value: blind.done.append("type %s" % value["text"])
        blind.step_fill(self.ctx(steps), {"fields": [{"field": "servings", "text": "12"}]})
        self.assertEqual(blind.done, ["type 12", "own"])

    def test_settle_watches_for_a_blink_where_the_driver_cant_read_the_focus(self):
        class Blinking(Stuck):
            frames = 0

            def screenshot(self, device, path):
                Blinking.frames += 1
                kit.write_png(path, 10, 10, colour=(0, 0, 0) if Blinking.frames in (3, 5) else (255, 255, 255))
        steps = [{"type": {"id": "servings", "text": "12"}}, {"settle": True}]
        drv = Blinking(self.options, closes=("own",))
        drv.step_type = lambda ctx, value: None
        shot = drv.run_screen({"id": "duo-outer", "platform": "ios"}, {"id": "results", "steps": steps}, "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(any("changed again after it settled" in w for w in shot.warnings), shot.warnings)
        Blinking.frames = 10
        quiet = drv.run_screen({"id": "duo-outer", "platform": "ios"},
                               {"id": "plain", "steps": [{"settle": True}]}, "en-US")
        self.assertEqual(quiet.warnings, [], "no typing, no watching")

    def test_a_fill_field_found_a_way_the_driver_cant_skips_the_screen(self):
        drv = Stuck(self.options)
        why = drv.unsupported({"id": "results", "steps": [{"fill": [{"field": {"xpath": "//x"}, "text": "1"}]}]})
        self.assertIn("can't find elements by xpath", why)


# -- the other drivers ----------------------------------------------------------------------------------------

class AppiumKeyboardTests(inapp.Case):
    def setUp(self):
        inapp.Case.setUp(self)
        t = self.transport
        t.on("GET", r"^/status$", body=inapp.answer("appium-status.json"))
        t.on("POST", r"^/session$", body=inapp.answer("appium-session.json"))
        t.on("POST", r"/element$", body=inapp.answer("appium-element.json"))
        t.on("POST", r"/execute/sync$", body='{"value": true}')    # the keyboard is always up
        t.on("POST", r"/click$", body='{"value": null}')
        t.on("POST", r"/value$", body='{"value": null}')
        t.on("POST", r"/actions$", body='{"value": null}')
        t.on("DELETE", r"/actions$", body='{"value": null}')

    def test_a_number_pad_that_wont_close_tries_its_keys_the_done_button_and_the_tap_then_fails(self):
        d = inapp.drivers.get("appium")(self.options())
        dev = self.device("appium", platform="ios", target={"host": "fakehost"})
        d.prepare(dev, {})
        d.apply_locale(dev, "en-US", base.Shot())
        with self.assertRaises(base.StepFailed) as raised:
            d.step_hideKeyboard(self.ctx(dev), {"tap": {"id": "page-title"}})
        scripts = [c[2]["script"] for c in self.transport.find("POST", r"/execute/sync$")]
        self.assertIn("mobile: hideKeyboard", scripts)
        finds = [c[2]["value"] for c in self.transport.find("POST", r"/element$")]
        self.assertTrue(any("XCUIElementTypeButton" in f and "Done" in f for f in finds), finds)
        self.assertEqual(len(self.transport.find("POST", r"/click$")), 2, "the Done button and the title")
        self.assertIn("the app's to fix", str(raised.exception))
        self.assertEqual(self.transport.find("POST", r"/back$"), [])

    def test_on_ios_a_scroll_after_typing_is_a_quick_swipe_never_a_press_and_drag(self):
        # mobile: scroll with only a direction presses half a second at a quarter of the window before it drags:
        # on a small display that press landed on a field and the number pad came back, the page unmoved.
        d = inapp.drivers.get("appium")(self.options())
        dev = self.device("appium", platform="ios", target={"host": "fakehost"})
        d.prepare(dev, {})
        d.apply_locale(dev, "en-US", base.Shot())
        self.transport.on("POST", r"/execute/sync$", body=[(200, '{"value": true}'), (200, '{"value": null}'),
                                                           (200, '{"value": false}')])
        d.step_hideKeyboard(self.ctx(dev), {"done": {"id": "Done"}})
        self.transport.calls[:] = []
        d.step_scroll(self.ctx(dev), {"direction": "up", "times": 2})
        d.step_scroll(self.ctx(dev), {"direction": "down", "in": {"id": "form"}})
        d.step_fill(self.ctx(dev, self.screen([{"fill": [{"field": "servings", "text": "12"}]}])),
                    {"fields": [{"field": "servings", "text": "12"}], "scrollTo": "top", "keyboard": False})
        calls = [c[2] for c in self.transport.find("POST", r"/execute/sync$")]
        scripts = [c["script"] for c in calls]
        self.assertNotIn("mobile: scroll", scripts)
        swipes = [c["args"][0] for c in calls if c["script"] == "mobile: swipe"]
        self.assertEqual([s["direction"] for s in swipes[:3]], ["down", "down", "up"],
                         "a swipe is the finger's way: content up is the finger down")
        self.assertIn("elementId", swipes[2], "a pane scrolled by swiping inside it")
        self.assertGreaterEqual(len(swipes), 4, "scrollTo top swiped too")


IOS_SOURCE = (
    '<?xml version="1.0" encoding="UTF-8"?><AppiumAUT><XCUIElementTypeApplication type="XCUIElementTypeApplication" '
    'name="Sample Recipes"><XCUIElementTypeWindow type="XCUIElementTypeWindow">'
    '<XCUIElementTypeScrollView type="XCUIElementTypeScrollView" x="0" y="0" width="400" height="1000">'
    '<XCUIElementTypeStaticText type="XCUIElementTypeStaticText" name="list-title"/></XCUIElementTypeScrollView>'
    '<XCUIElementTypeScrollView type="XCUIElementTypeScrollView" x="400" y="0" width="600" height="1000">'
    '<XCUIElementTypeOther type="XCUIElementTypeOther" name="form-content">'
    '<XCUIElementTypeTextField type="XCUIElementTypeTextField" name="servings" value="12"/>'
    '</XCUIElementTypeOther></XCUIElementTypeScrollView></XCUIElementTypeWindow></XCUIElementTypeApplication>'
    '</AppiumAUT>')
ANDROID_SOURCE = (
    '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0"><android.widget.FrameLayout scrollable="false" '
    'resource-id="" bounds="[0,0][1080,1920]"><androidx.recyclerview.widget.RecyclerView scrollable="true" '
    'resource-id="com.example.samplerecipes:id/list" bounds="[0,200][600,1920]"/>'
    '<android.widget.ScrollView scrollable="true" resource-id="" bounds="[600,200][1080,1920]">'
    '<android.widget.LinearLayout scrollable="false" resource-id="com.example.samplerecipes:id/form-content" '
    'bounds="[600,200][1080,1920]"><android.widget.EditText scrollable="false" '
    'resource-id="com.example.samplerecipes:id/servings" bounds="[620,220][1060,280]"/></android.widget.LinearLayout>'
    '</android.widget.ScrollView></android.widget.FrameLayout></hierarchy>')


class AppiumPaneTests(inapp.Case):
    """Appium: the page source shows what holds the element named; the pane is found again by its path."""

    def prepared(self, platform, source):
        t = self.transport
        t.on("GET", r"^/status$", body=inapp.answer("appium-status.json"))
        t.on("POST", r"^/session$", body=inapp.answer("appium-session.json"))
        t.on("GET", r"/source$", body=json.dumps({"value": source}))
        t.on("POST", r"/element$", body=[(200, json.dumps({"value": {appium_driver.W3C_ELEMENT: "el-servings"}})),
                                         (200, json.dumps({"value": {appium_driver.W3C_ELEMENT: "pane-form"}}))])
        t.on("POST", r"/execute/sync$", body='{"value": null}')
        d = inapp.drivers.get("appium")(self.options())
        dev = self.device("appium", platform=platform, target={"host": "fakehost"})
        d.prepare(dev, {})
        d.apply_locale(dev, "en-US", base.Shot())
        self.transport.calls[:] = []
        return d, dev

    def gestures(self):
        return [c[2]["args"][0] for c in self.transport.find("POST", r"/execute/sync$")
                if c[2]["script"] in ("mobile: swipe", "mobile: scrollGesture")]

    def test_ios_scrolls_the_scroll_view_around_a_field(self):
        d, dev = self.prepared("ios", IOS_SOURCE)
        ctx = self.ctx(dev)
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "servings"}})
        finds = [c[2] for c in self.transport.find("POST", r"/element$")]
        self.assertEqual(finds[-1], {"using": "xpath", "value": "/AppiumAUT/XCUIElementTypeApplication[1]/"
                                     "XCUIElementTypeWindow[1]/XCUIElementTypeScrollView[2]"})
        self.assertEqual([g.get("elementId") for g in self.gestures()], ["pane-form"])
        self.assertEqual(ctx.shot.panes, ["in id 'servings': scrolled its nearest scrolling ancestor, "
                                          "XCUIElementTypeScrollView at (400, 0), 600 x 1000"])

    def test_android_reads_the_scrollable_flag(self):
        d, dev = self.prepared("android", ANDROID_SOURCE)
        ctx = self.ctx(dev)
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "form-content"}})
        finds = [c[2] for c in self.transport.find("POST", r"/element$")]
        self.assertEqual(finds[-1]["value"], "/hierarchy/android.widget.FrameLayout[1]/android.widget.ScrollView[1]")
        self.assertEqual([g.get("elementId") for g in self.gestures()], ["pane-form"])
        self.assertIn("android.widget.ScrollView [600,200][1080,1920]", ctx.shot.panes[0])

    def test_a_pane_not_found_again_leaves_the_element_itself(self):
        d, dev = self.prepared("ios", IOS_SOURCE)
        self.transport.on("POST", r"/element$", body=[
            (200, json.dumps({"value": {appium_driver.W3C_ELEMENT: "el-servings"}})),
            (404, json.dumps({"value": {"error": "no such element", "message": "gone"}}))])
        ctx = self.ctx(dev)
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "servings"}})
        self.assertEqual([g.get("elementId") for g in self.gestures()], ["el-servings"])
        self.assertEqual(ctx.shot.panes, [])


class AgentPaneTests(inapp.Case):
    """The in-app agents: the agent's tree shows what holds the element named, by type."""

    TREE = [{"id": "page", "type": "ContentPage", "children": [
        {"id": "el-2", "type": "CollectionView", "automationId": "list"},
        {"id": "el-3", "type": "ScrollView", "fullType": "Microsoft.Maui.Controls.ScrollView", "children": [
            {"id": "el-4", "type": "VerticalStackLayout", "automationId": "form-content", "children": [
                {"id": "el-9", "type": "Entry", "automationId": "servings", "text": "12"}]}]}]}]

    def setUp(self):
        inapp.Case.setUp(self)
        self.agents((10224, "com.example.samplerecipes", None, 41017, "MacCatalyst"))
        self.runner.on(r"ui tree", out=json.dumps(self.TREE))

    def test_devflow_scrolls_the_scroll_view_around_the_panes_content(self):
        self.runner.on(r"ui query --automationId form-content",
                       out=json.dumps([{"id": "el-4", "type": "VerticalStackLayout", "automationId": "form-content"}]))
        d = inapp.drivers.get("devflow")(self.options())
        ctx = self.ctx(self.device("devflow"))
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "form-content"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --element el-3 --dy -400 --agent-port 10224 --platform maccatalyst"])
        self.assertEqual(ctx.shot.panes, ["in id 'form-content': scrolled its nearest scrolling ancestor, ScrollView"])

    def test_a_scroll_view_named_itself_says_nothing(self):
        self.runner.on(r"ui query --automationId list",
                       out=json.dumps([{"id": "el-2", "type": "CollectionView", "automationId": "list"}]))
        d = inapp.drivers.get("devflow")(self.options())
        ctx = self.ctx(self.device("devflow"))
        d.step_scroll(ctx, {"direction": "down", "in": {"id": "list"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --element el-2 --dy -400 --agent-port 10224 --platform maccatalyst"])
        self.assertEqual(ctx.shot.panes, [])


class PaneChrome(cli_tests.FakeChrome):
    """A page whose ``pane`` lookups answer as FIND_JS would for a field inside a scrolling ``div.pane``."""

    def call(self, method, params=None, session_id=None, timeout=30):
        if method == "Runtime.evaluate" and '"pane": true' in params["expression"]:
            self.calls.append((method, params))
            return {"result": {"value": {"x": 1, "y": 1, "width": 2, "height": 2, "pane": "ancestor",
                                         "what": "div#form.pane"}}}
        return cli_tests.FakeChrome.call(self, method, params, session_id, timeout)


class ChromePaneTests(cli_tests.DriverCase):
    def test_a_scroll_in_a_field_scrolls_its_scrolling_ancestor_and_says_which(self):
        fake = PaneChrome(elements={("id", "servings"): {"x": 100, "y": 300, "width": 200, "height": 40}})
        saved = chrome_driver.CHROME_FACTORY
        chrome_driver.CHROME_FACTORY = lambda: fake
        self.addCleanup(setattr, chrome_driver, "CHROME_FACTORY", saved)
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device(id="web-phone", driver="chrome", width=1290, height=2796, app={}, target={"scale": 3})
        drv.prepare(device, {"app": {"web": {"url": "http://localhost:8080/"}}})
        shot = drv.run_screen(device, self.screen([{"scroll": {"direction": "down", "in": {"id": "servings"}}},
                                                   {"scroll": {"to": "top", "in": {"id": "servings"}}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        exprs = [p["expression"] for m, p in fake.calls
                 if m == "Runtime.evaluate" and '"pane": true' in p["expression"]]
        self.assertTrue(any('"scrollBy": [0.0, 0.8]' in e for e in exprs), exprs)
        self.assertTrue(any('"edge": "top"' in e for e in exprs), exprs)
        self.assertIn("scrolling(p)", chrome_driver.FIND_JS)
        self.assertEqual(shot.panes, ["in id 'servings': scrolled its nearest scrolling ancestor, div#form.pane"])


class DevFlowScrollTests(inapp.Case):
    def setUp(self):
        inapp.Case.setUp(self)
        self.agents((10224, "com.example.samplerecipes", None, 41017, "MacCatalyst"))

    def test_scroll_in_a_pane_scrolls_that_element(self):
        self.runner.on(r"ui query --automationId form", out=inapp.answer("devflow-query.json"))
        d = inapp.drivers.get("devflow")(self.options())
        d.step_scroll(self.ctx(self.device("devflow")), {"direction": "down", "in": {"id": "form"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --element el-17 --dy -400 --agent-port 10224 --platform maccatalyst"])

    def test_scroll_to_looks_up_when_down_ends(self):
        found = inapp.answer("devflow-query.json")
        calls = {"n": 0}

        def query(cmd):
            calls["n"] += 1
            up = any("--dy 400" in l for l in self.runner.lines)
            return found if calls["n"] == 1 or up else "[]"
        self.runner.on(r"ui query --automationId insight", out=query)
        self.runner.on(r"ui scroll --element", out='{"success": false, "error": "Element is not in a ScrollView"}')
        self.runner.on(r"ui tree", out='[{"id": "page", "type": "ContentPage"}]')
        d = inapp.drivers.get("devflow")(self.options())
        d.step_scroll(self.ctx(self.device("devflow")), {"to": {"id": "insight"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --element el-17 --agent-port 10224 --platform maccatalyst",
            "maui devflow ui scroll --dy -400 --agent-port 10224 --platform maccatalyst",
            "maui devflow ui scroll --dy 400 --agent-port 10224 --platform maccatalyst"])


class MaestroFillTests(inapp.Case):
    def test_fill_becomes_scroll_tap_and_input_per_field(self):
        d = inapp.drivers.get("maestro")(self.options())
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        screen = self.screen([{"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": "minutes", "text": "45"}],
                                        "scrollTo": "top"}}], "results")
        lines = d.write_flow(dev, screen, "en-US").splitlines()
        self.assertEqual(lines[2:], [
            '- scrollUntilVisible: {"element": {"id": "servings"}, "direction": "DOWN"}',
            '- tapOn: {"id": "servings"}',
            '- inputText: "12"',
            "- hideKeyboard",
            '- scrollUntilVisible: {"element": {"id": "minutes"}, "direction": "DOWN"}',
            '- tapOn: {"id": "minutes"}',
            '- inputText: "45"',
            "- hideKeyboard"] + ['- swipe: {"direction": "DOWN"}'] * 5)

    def test_a_pane_is_beyond_maestro(self):
        d = inapp.drivers.get("maestro")(self.options())
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        with self.assertRaises(base.StepSkipped):
            d.write_flow(dev, self.screen([{"scroll": {"direction": "down", "in": {"id": "form"}}}]), "en-US")


class ChromeFillTests(cli_tests.DriverCase):
    def test_fill_types_each_field_blurs_and_scrolls_back(self):
        fake = cli_tests.FakeChrome(elements={("id", "servings"): {"x": 100, "y": 300, "width": 200, "height": 40},
                                              ("id", "minutes"): {"x": 100, "y": 900, "width": 200, "height": 40}})
        saved = chrome_driver.CHROME_FACTORY
        chrome_driver.CHROME_FACTORY = lambda: fake
        self.addCleanup(setattr, chrome_driver, "CHROME_FACTORY", saved)
        drv = chrome_driver.ChromeDriver(self.options)
        device = self.device(id="web-phone", driver="chrome", width=1290, height=2796, app={}, target={"scale": 3})
        drv.prepare(device, {"app": {"web": {"url": "http://localhost:8080/"}}})
        shot = drv.run_screen(device, self.screen([{"fill": {"fields": [{"field": "servings", "text": "12"},
                                                                       {"field": "minutes", "text": "45"}],
                                                             "scrollTo": "top"}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual([p["text"] for m, p in fake.calls if m == "Input.insertText"], ["12", "45"])
        exprs = [p["expression"] for m, p in fake.calls if m == "Runtime.evaluate"]
        self.assertTrue(any("activeElement" in e and e.endswith("(true)") for e in exprs), "never blurred")
        self.assertIn("window.scrollTo(0, 0)", exprs)


# -- the plan --------------------------------------------------------------------------------------------------

class InUsePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="capture-forms-plan-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def plan(self, **staging):
        screens = [
            {"id": "results", "state": "the scaling form", "inUse": "part-filled, as mid-edit, not saved",
             "steps": [{"launch": {}}, {"tap": {"id": "scale"}},
                       {"fill": {"fields": [{"field": "servings", "text": "12"}, {"field": {"id": "minutes"}, "text": "45"}],
                                 "in": {"id": "form"}, "keyboard": {"done": {"id": "done"}, "tap": {"x": 700, "y": 180}},
                                 "scrollTo": "top"}, "name": "fill"},
                       {"unfocus": {"tap": {"id": "page-title"}}},
                       {"scroll": {"to": {"id": "page-title"}, "in": {"id": "form"}}},
                       {"hideKeyboard": {"done": {"id": "done"}, "scroll": "up", "own": False}}],
             "verify": [{"id": "servings", "contains": "12"}, {"keyboard": "hidden"}],
             "overrides": {"duo-outer": {"stepsPatch": [{"remove": "fill"}],
                                         "inUse": "left empty: its number pad doesn't close (reported)"}}},
            {"id": "history", "state": "eight weeks of meals", "steps": [{"launch": {}}]}]
        st = {"account": {"kind": "none"}}
        st.update(staging)
        plan = kit.sample_plan([{"id": "phone", "platform": "android", "driver": "adb", "width": 1080,
                                 "height": 1920}, {"id": "duo-outer", "platform": "ios", "driver": "appium",
                                                   "width": 1398, "height": 2034}], screens, staging=st)
        return plan, kit.write_plan(self.tmp, plan)

    def test_the_new_steps_and_fields_are_a_valid_plan(self):
        plan, path = self.plan(inUse={"rule": "screens look somewhat filled out, in use", "by": "the user, in chat",
                                      "values": "a family's everyday dinners"},
                               notes=["no real addresses on the map"])
        loaded = capture.load_plan(path)
        duo = capture.resolve_device(loaded, loaded["devices"][1])
        results = capture.screens_for(loaded, duo)[0]
        self.assertNotIn("fill", [base.step_of(s)[0] for s in results["steps"]])
        self.assertIn("left empty", results["inUse"])

    def test_staging_md_says_how_screens_look_in_use_and_what_each_types(self):
        plan, _ = self.plan(inUse={"rule": "screens look somewhat filled out, in use", "by": "the user, in chat"},
                            notes=["no real addresses on the map"])
        md = capture.staging_markdown(plan)
        self.assertIn("## Looking in use", md)
        self.assertIn("- The rule: screens look somewhat filled out, in use (the user, in chat)", md)
        self.assertIn("no: forms are captured filled, before they're saved", md)
        self.assertIn("## House rules\n\n- no real addresses on the map", md)
        self.assertIn("| In use |", md)
        self.assertIn("part-filled, as mid-edit, not saved; typed: id `servings` = `12`, id `minutes` = `45`", md)
        self.assertIn("Not said yet for: `history`", md)

    def test_a_run_warns_about_screens_that_dont_say_how_they_look_in_use(self):
        plan, path = self.plan(inUse={"rule": "screens look in use"})
        self.assertEqual(capture.in_use_missing(plan), ["history"])
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            capture.main(["--plan", path, "--dry-run", "--screens", "history", "--devices", "phone"])
        self.assertIn("history doesn't say how (inUse)", out.getvalue())
        plan, _ = self.plan()
        self.assertEqual(capture.in_use_missing(plan), [], "no rule, nothing to ask")

    def test_changes_look_for_a_fill_steps_fields(self):
        plan, _ = self.plan()
        values = [v for v, _ in capture._element_values(plan["screens"][0]["steps"], None)]
        for wanted in ("servings", "minutes", "form", "page-title", "done"):
            if len(wanted) >= 3:
                self.assertIn(wanted, values)


if __name__ == "__main__":
    unittest.main()
