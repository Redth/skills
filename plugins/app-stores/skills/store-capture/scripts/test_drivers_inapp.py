"""Tests for the drivers that reach screens inside the app: devflow, ailoha, appium, xcuitest, maestro (and the
host delegation they share, hosted.py).

A fake ``base.RUNNER`` answers the CLIs (``maui devflow``, ``ailoha``, ``xcodebuild``, ``xcresulttool``,
``maestro``) and a fake ``web.TRANSPORT`` answers the agents' and Appium's HTTP APIs, with synthetic recorded
answers from ``evals/files/inapp-answers/``. A fake host driver stands in for simctl/adb. Nothing runs, nothing
reaches a network, nothing waits.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capture_testkit as kit  # noqa: E402
import drivers  # noqa: E402
from appstores_lib import web  # noqa: E402
from drivers import base  # noqa: E402
from drivers import agentcli, appium, hosted, maestro, xcuitest  # noqa: E402

ANSWERS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "files", "inapp-answers")


def answer(name):
    """A fixture's text."""
    with open(os.path.join(ANSWERS, name), encoding="utf-8") as f:
        return f.read()


class FakeTransport(object):
    """A ``web.TRANSPORT``: answers ``(method, path regex)`` with ``(status, body)``; records ``(method, url, body)``."""

    def __init__(self):
        self.routes = []
        self.calls = []

    def on(self, method, pattern, status=200, body="{}", port=None):
        self.routes.append((method, re.compile(pattern), status, body, port))
        return self

    def __call__(self, method, url, headers, body, timeout):
        parsed = json.loads(body.decode("utf-8")) if body else None
        self.calls.append((method, url, parsed))
        path = urllib.parse.urlsplit(url).path + ("?" + urllib.parse.urlsplit(url).query
                                                   if urllib.parse.urlsplit(url).query else "")
        for m, rx, status, out, port in reversed(self.routes):
            if m == method and rx.search(path) and (port is None or urllib.parse.urlsplit(url).port == port):
                if isinstance(out, list):   # answers in turn, the last one kept
                    status, out = out.pop(0) if len(out) > 1 else out[0]
                data = out if isinstance(out, bytes) else out.encode("utf-8")
                return web.Response(status, {"content-type": "application/json"}, data)
        return web.Response(404, {}, b'{"value": {"error": "unknown command", "message": "no route"}}')

    def find(self, method, pattern):
        rx = re.compile(pattern)
        return [c for c in self.calls if c[0] == method and rx.search(c[1])]


class FakeHost(base.Driver):
    """A host driver (as simctl/adb are) that records what it's asked to do."""

    NAME = "fakehost"
    PLATFORMS = ("ios", "android")
    STEPS = ("launch", "deepLink", "url", "tap", "type", "back", "wait", "settle", "script")
    instances = []

    def __init__(self, options=None):
        base.Driver.__init__(self, options)
        self.udid = None
        self.done = []
        FakeHost.instances.append(self)

    def prepare(self, device, plan):
        self.udid = (device.get("target") or {}).get("udid", "00000000-0000-0000-0000-0000000000A1")
        self.done.append("prepare")

    def reset(self, device):
        self.done.append("reset")
        return ["fakehost reset note"]

    def apply_locale(self, device, locale, shot):
        self.done.append("locale %s" % locale)

    def apply_appearance(self, device, appearance, shot):
        self.done.append("appearance %s" % appearance)

    def apply_status_bar(self, device, mode, clock, shot):
        self.done.append("statusBar %s %s" % (mode, clock))
        return "verified"

    def step_launch(self, ctx, value):
        self.done.append("launch %s" % json.dumps(value, sort_keys=True))

    def step_deepLink(self, ctx, value):
        self.done.append("deepLink %s" % value)

    def step_tap(self, ctx, value):
        self.done.append("tap %s" % json.dumps(value, sort_keys=True))

    def step_type(self, ctx, value):
        self.done.append("type %s" % value["text"])

    def screenshot(self, device, path):
        self.done.append("screenshot")
        kit.write_png(path, device["width"], device["height"])

    def source(self, device):
        return {"deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2"}

    def script_env(self, device):
        return {"APPSTORES_UDID": self.udid or ""}


class Case(unittest.TestCase):
    """Fake hooks, a fake transport, a work folder and the fake host registered as ``fakehost``."""

    def setUp(self):
        self.hooks = kit.Hooks()
        self.runner = self.hooks.runner
        self.transport = FakeTransport()
        self.saved_transport = web.TRANSPORT
        web.TRANSPORT = self.transport
        self.work = tempfile.mkdtemp(prefix="appstores-inapp-test-")
        module = types.ModuleType("drivers.fakehost")
        module.DRIVER = FakeHost
        sys.modules["drivers.fakehost"] = module
        drivers.REGISTRY["fakehost"] = "fakehost"
        FakeHost.instances = []

    def tearDown(self):
        self.hooks.restore()
        web.TRANSPORT = self.saved_transport
        shutil.rmtree(self.work, ignore_errors=True)
        drivers.REGISTRY.pop("fakehost", None)
        sys.modules.pop("drivers.fakehost", None)

    def options(self):
        return base.Options(plan_dir=self.work, workdir=os.path.join(self.work, "work"))

    def device(self, driver, platform="macos", target=None, width=1320, height=2868, **extra):
        d = {"id": "dev-1", "platform": platform, "driver": driver, "width": width, "height": height,
             "locales": ["en-US"], "appearance": "light", "clock": "09:41", "statusBar": "clean", "seed": "demo",
             "app": {"bundleId": "com.example.samplerecipes", "package": "com.example.samplerecipes",
                     "activity": ".MainActivity"},
             "target": dict(target or {})}
        d.update(extra)
        return d

    def screen(self, steps, sid="plan", **extra):
        s = {"id": sid, "steps": steps, "seed": "demo", "appearance": None, "statusBar": None, "clock": None}
        s.update(extra)
        return s

    def ctx(self, device, screen=None, index=1, step=None):
        screen = screen or self.screen([])
        return base.StepContext(device, screen, "en-US", base.Shot(), index, step)

    def agents(self, *agents, cli=r"agent list"):
        """The CLI's agent list and each agent's status: ``(port, package, device id, process id, platform)``."""
        listed = []
        for port, package, dev, pid, plat in agents:
            listed.append({"id": "agent-%d" % port, "appName": "Sample Recipes", "platform": plat, "port": port,
                           "processId": pid})
            status = {"device": {"id": dev, "platform": plat}, "app": {"name": "Sample Recipes",
                                                                     "packageId": package, "processId": pid}}
            self.transport.on("GET", r"^/api/v1/agent/status$", body=json.dumps(status), port=port)
        self.runner.on(cli, out=json.dumps(listed))

    def ui(self):
        """The CLI commands that act on the app (not the agent list, not ps)."""
        return [l for l in self.runner.lines if " agent list" not in l and not l.startswith("ps ")
                and " --version" not in l]


def write_after(flag):
    """A FakeRunner ``then`` that writes a PNG to the argument after ``flag``."""
    def then(cmd):
        kit.write_png(cmd[cmd.index(flag) + 1], 64, 128)
    return then


# -- devflow -------------------------------------------------------------------------------------------------

class DevFlowTests(Case):

    def setUp(self):
        Case.setUp(self)
        self.agents((10224, "com.example.samplerecipes", None, 41017, "MacCatalyst"))

    def driver(self):
        return drivers.get("devflow")(self.options())

    def test_capabilities_are_honest(self):
        caps = self.driver().capabilities()
        self.assertEqual(caps["name"], "devflow")
        self.assertEqual(caps["finders"], ["id", "text", "css", "xpath"])
        self.assertIn("tap", caps["steps"])
        self.assertEqual(caps["throughHost"], ["launch", "deepLink", "url", "appFile", "posture"])
        self.assertEqual(caps["hosts"]["ios"], "simctl")
        self.assertEqual(caps["hosts"]["android"], "adb")

    def test_prepare_checks_the_cli(self):
        d = self.driver()
        d.prepare(self.device("devflow"), {})
        self.assertEqual(self.runner.lines, ["maui --version"])

    def test_missing_cli_is_tool_missing_with_the_install_line(self):
        self.runner.on(r"^maui ", raises=FileNotFoundError())
        with self.assertRaises(base.ToolMissing) as cm:
            self.driver().prepare(self.device("devflow"), {})
        self.assertIn("dotnet tool install -g Microsoft.Maui.Cli --prerelease", str(cm.exception))

    def test_tap_by_id_and_text(self):
        d = self.driver()
        dev = self.device("devflow")
        d.step_tap(self.ctx(dev), {"id": "search"})
        d.step_tap(self.ctx(dev), {"text": "Plan a week"})
        self.assertEqual(self.ui(), [
            "maui devflow ui tap --automationId search --agent-port 10224 --platform maccatalyst",
            "maui devflow ui tap --text 'Plan a week' --agent-port 10224 --platform maccatalyst"])

    def test_tap_by_css_finds_the_agents_id_first(self):
        self.runner.on(r"ui query --selector", out=answer("devflow-query.json"))
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")), {"css": "SearchBar"})
        self.assertEqual(self.runner.lines[-2],
                         "maui devflow ui query --selector SearchBar --agent-port 10224 --platform maccatalyst --json")
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-17 --agent-port 10224 --platform maccatalyst")

    def test_xpath_goes_through_the_http_api_on_the_listed_port(self):
        self.runner.on(r"agent list", out=answer("devflow-agents.json"))
        self.transport.on("GET", r"^/api/v1/ui/elements\?strategy=xpath", body=answer("devflow-query.json"))
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")), {"xpath": "//SearchBar[@AutomationId='search']"})
        (method, url, _), = self.transport.find("GET", r"/ui/elements")
        self.assertTrue(url.startswith("http://127.0.0.1:10224/api/v1/ui/elements?strategy=xpath&value=%2F%2F"), url)
        # Once the port is known, the CLI is pointed at the same agent.
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-17 --agent-port 10224 --platform maccatalyst")

    def test_agent_port_from_the_target_skips_discovery(self):
        self.transport.on("POST", r"^/api/v1/ui/actions/back$", body='{"success": true}')
        self.runner.on(r"ui navigate", code=1, err="Not a Shell app")
        d = self.driver()
        dev = self.device("devflow", target={"agentPort": 9300})
        d.step_back(self.ctx(dev), True)
        self.assertEqual(self.transport.find("POST", r"."), [("POST", "http://127.0.0.1:9300/api/v1/ui/actions/back", {})])
        self.assertEqual(self.runner.matching(r"agent list"), [])
        self.assertEqual(self.ui(), ["maui devflow ui navigate .. --agent-port 9300 --platform maccatalyst"])

    def test_type_fills_the_named_field_or_the_one_showing_text(self):
        d = self.driver()
        dev = self.device("devflow")
        d.step_type(self.ctx(dev), {"text": "pasta", "id": "search"})
        d.step_type(self.ctx(dev), {"text": "pasta", "into": "Search recipes"})
        self.assertEqual(self.ui(), [
            "maui devflow ui fill --automationId search pasta --agent-port 10224 --platform maccatalyst",
            "maui devflow ui fill --text 'Search recipes' pasta --agent-port 10224 --platform maccatalyst"])

    def test_type_with_no_target_and_no_host_fails_clearly(self):
        with self.assertRaises(base.StepFailed) as cm:
            self.driver().step_type(self.ctx(self.device("devflow")), {"text": "pasta"})
        self.assertIn("give type an id", str(cm.exception))

    def test_wait_for_an_element_uses_wait_until(self):
        d = self.driver()
        d.step_wait(self.ctx(self.device("devflow")), {"id": "recipe-title", "timeout": 12})
        self.assertEqual(self.ui(), [
            "maui devflow ui query --automationId recipe-title --wait-until exists --timeout 12 --agent-port 10224 "
            "--platform maccatalyst"])

    def test_wait_that_times_out_is_a_step_failure(self):
        self.runner.on(r"--wait-until", code=1, err="Timed out")
        with self.assertRaises(base.StepFailed):
            self.driver().step_wait(self.ctx(self.device("devflow")), {"text": "This week"})

    def test_scroll_direction_and_to(self):
        self.runner.on(r"ui query --automationId", out=answer("devflow-query.json"))
        d = self.driver()
        dev = self.device("devflow")
        d.step_scroll(self.ctx(dev), {"direction": "down", "times": 2})
        d.step_scroll(self.ctx(dev), {"to": {"id": "search"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --dy -400 --agent-port 10224 --platform maccatalyst",
            "maui devflow ui scroll --dy -400 --agent-port 10224 --platform maccatalyst",
            "maui devflow ui scroll --element el-17 --agent-port 10224 --platform maccatalyst"])

    def test_scroll_to_falls_back_to_scrolling_down_until_found(self):
        self.runner.on(r"ui query --automationId insight", out=answer("devflow-query.json"))
        self.runner.on(r"ui scroll --element", out='{"success": false, "error": "Element is not in a ScrollView"}')
        d = self.driver()
        d.step_scroll(self.ctx(self.device("devflow")), {"to": {"id": "insight"}})
        self.assertEqual(self.runner.matching(r"ui scroll"), [
            "maui devflow ui scroll --element el-17 --agent-port 10224 --platform maccatalyst",
            "maui devflow ui scroll --dy -400 --agent-port 10224 --platform maccatalyst"])

    def test_swipe_is_a_gesture_by_direction(self):
        d = self.driver()
        d.step_swipe(self.ctx(self.device("devflow")), {"direction": "left"})
        self.assertEqual(self.ui(), ["maui devflow ui gesture swipe --direction left --agent-port 10224 "
                                     "--platform maccatalyst"])
        with self.assertRaises(base.StepFailed):
            d.step_swipe(self.ctx(self.device("devflow")), {"from": [10, 10], "to": [200, 10]})
        ctx = self.ctx(self.device("devflow"))
        d.step_swipe(ctx, {"direction": "left", "hold": 400})
        self.assertEqual(len(ctx.shot.warnings), 1)
        self.assertIn("hold goes with from and to", ctx.shot.warnings[0])

    def test_without_a_host_the_agent_takes_the_screenshot_at_native_scale(self):
        self.runner.on(r"ui screenshot", then=write_after("--output"))
        d = self.driver()
        dev = self.device("devflow", width=64, height=128)
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"id": "plan-tab"}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        line = self.runner.matching(r"ui screenshot")[0]
        self.assertIn("--scale native --overwrite", line)
        self.assertTrue(os.path.isfile(shot.path))
        self.assertEqual(shot.status_bar, "none")

    def test_without_a_host_appearance_is_the_apps_theme_and_is_put_back(self):
        d = self.driver()
        dev = self.device("devflow", appearance="dark")
        self.runner.on(r"ui screenshot", then=write_after("--output"))
        d.prepare(dev, {})
        d.run_screen(dev, self.screen([]), "en-US")
        self.assertIn("maui devflow theme set dark --scope app --agent-port 10224 --platform maccatalyst",
                      self.runner.lines)
        d.reset(dev)
        self.assertEqual(self.runner.lines[-1],
                         "maui devflow theme set system --scope app --agent-port 10224 --platform maccatalyst")

    def test_launch_without_a_host_is_skipped_not_run(self):
        d = self.driver()
        dev = self.device("devflow")
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"launch": {}}, {"tap": {"id": "x"}}]), "en-US")
        self.assertEqual(shot.status, "skipped")
        self.assertIn("through its host", shot.reason)
        self.assertEqual(self.runner.lines, ["maui --version"])

    def test_type_with_text_and_id_isnt_mistaken_for_two_finders(self):
        d = self.driver()
        self.assertIsNone(d.unsupported(self.screen([{"type": {"text": "pasta", "id": "search"}}]),
                                        self.device("devflow")))

    def test_a_failed_cli_command_makes_the_shot_missed(self):
        self.runner.on(r"ui tap", code=1, err="Element not found: plan-tab")
        d = self.driver()
        dev = self.device("devflow")
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"id": "plan-tab"}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        # Not there yet: it waited for the element (the agent's query, then its tree) before giving up.
        self.assertIn("id 'plan-tab' to appear didn't happen", shot.reason)
        self.assertTrue(self.runner.matching(r"ui tree --agent-port 10224"))

    def test_a_tap_that_answers_success_false_fails_with_advice(self):
        self.runner.on(r"ui tap", out='{"success": false, "error": "No gesture recognizer on Label"}')
        d = self.driver()
        dev = self.device("devflow")
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"text": "Summary"}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("No gesture recognizer on Label", shot.reason)
        self.assertIn("appium driver", shot.reason)
        self.assertIn("EnableSyntheticTouch", shot.reason)

    def test_a_tap_waits_for_its_element_and_finds_a_native_view_in_the_tree(self):
        # The CLI's automationId lookup misses a native view the app registered; the tree has it.
        self.runner.on(r"ui tap --automationId", code=1, err="No elements found")
        self.runner.on(r"ui query --automationId", out="[]")
        self.runner.on(r"ui tree", out=json.dumps([{"id": "page", "type": "ContentPage", "children": [
            {"id": "native:registered:9f2c", "type": "UIButton", "automationId": "add-recipe",
             "bounds": {"x": 300, "y": 60, "width": 44, "height": 44}}]}]))
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")), {"id": "add-recipe"})
        self.assertEqual(self.runner.lines[-1],
                         "maui devflow ui tap native:registered:9f2c --agent-port 10224 --platform maccatalyst")

    def test_an_xpath_the_http_query_refuses_is_found_in_the_tree(self):
        self.transport.on("GET", r"^/api/v1/ui/elements", status=400,
                          body='{"title": "At least one query parameter required: type, automationId, text, or selector"}')
        self.runner.on(r"ui tree", out=json.dumps([{"id": "page", "type": "ContentPage", "children": [
            {"id": "el-3", "type": "Button", "automationId": "menu", "text": ""},
            {"id": "el-4", "type": "Button", "text": "Summary"}]}]))
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")), {"xpath": "//Button[@text='Summary']"})
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-4 --agent-port 10224 --platform maccatalyst")

    def test_text_falls_back_as_every_driver_does_ignoring_case_then_contained(self):
        # The agent's own text query is exact: "Cooking time" drawn COOKING TIME, and "Lemon" inside a
        # longer label, are found in the tree as config.md promises.
        self.runner.on(r"ui tap --text", code=1, err="No elements found")
        self.runner.on(r"ui query --text", out="[]")
        self.runner.on(r"ui tree", out=json.dumps([{"id": "page", "type": "ContentPage", "children": [
            {"id": "el-1", "type": "Label", "text": "COOKING TIME", "bounds": {"x": 0, "y": 0, "width": 9, "height": 9}},
            {"id": "el-2", "type": "Label", "text": "  Lemon Pasta for 4 people",
             "bounds": {"x": 0, "y": 20, "width": 9, "height": 9}}]}]))
        d = self.driver()
        dev = self.device("devflow")
        d.step_tap(self.ctx(dev), {"text": "Cooking time"})
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-1 --agent-port 10224 --platform maccatalyst")
        d.step_tap(self.ctx(dev), {"text": "Lemon"})
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-2 --agent-port 10224 --platform maccatalyst")
        shot = d.run_screen(dev, self.screen([], verify={"text": "lemon pasta for"}), "en-US")
        self.assertEqual(shot.state_check, "passed")

    def test_an_xpath_with_functions_is_found_in_the_tree(self):
        self.transport.on("GET", r"^/api/v1/ui/elements", status=400, body='{"title": "nope"}')
        self.runner.on(r"ui tree", out=json.dumps([{"id": "page", "type": "ContentPage", "children": [
            {"id": "el-3", "type": "Button", "automationId": "menu", "text": ""},
            {"id": "el-4", "type": "Label", "text": "Estimated effects"}]}]))
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")),
                   {"xpath": "//*[contains(@text,'effects') or contains(@label,'effects')][not(@automationId)]"})
        self.assertEqual(self.runner.lines[-1], "maui devflow ui tap el-4 --agent-port 10224 --platform maccatalyst")

    def test_a_command_turned_away_by_the_lease_is_tried_again(self):
        answers = iter([(1, "", "Another DevFlow session is driving this app (MAUI CLI)"), (0, "{}", "")])

        def runner(cmd, input=None, timeout=None, env=None, cwd=None):
            line = base.quote(cmd)
            self.runner.calls.append((line, dict(env or {})))
            if " ui tap " in " " + line + " ":
                code, out, err = next(answers)
                return code, out.encode(), err.encode()
            if "agent list" in line:
                return 0, json.dumps([{"port": 10224, "platform": "MacCatalyst"}]).encode(), b""
            return 0, b"", b""
        base.RUNNER = runner
        d = self.driver()
        d.step_tap(self.ctx(self.device("devflow")), {"id": "search"})
        self.assertEqual(len(self.runner.matching(r"ui tap")), 2)
        self.assertIn(1.0, self.hooks.time.slept)

    def test_a_lease_that_never_frees_is_a_clear_error(self):
        self.runner.on(r"ui tap", code=1, err='{"success":false,"reason":"lease","error":"Another DevFlow session is '
                                              'driving this app. Take control before mutating it."}')
        with self.assertRaises(base.DriverError) as cm:
            self.driver().step_tap(self.ctx(self.device("devflow")), {"id": "search"})
        self.assertIn("holds this app's lease", str(cm.exception))
        self.assertEqual(len(self.runner.matching(r"ui tap")), 3)

    def test_with_a_host_the_device_and_screenshot_are_the_hosts(self):
        self.agents((10224, "com.example.samplerecipes", "00000000-0000-0000-0000-0000000000A1", 41017, "iOS"))
        d = self.driver()
        dev = self.device("devflow", platform="ios", target={"host": "fakehost", "deviceType": "iPhone 17 Pro Max"})
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"launch": {"args": {"ScreenshotScreen": "plan"}}},
                                              {"deepLink": "samplerecipes://plan"},
                                              {"wait": {"id": "plan-title"}}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        host = FakeHost.instances[0]
        self.assertEqual(host.done, ["prepare", "locale de-DE", "appearance light", "statusBar clean 09:41",
                                     'launch {"args": {"ScreenshotScreen": "plan"}}',
                                     "deepLink samplerecipes://plan", "screenshot"])
        self.assertEqual(shot.status_bar, "verified")
        self.assertEqual(shot.source["via"], "devflow")
        # After the host's launch, the driver finds this app's agent on this simulator, then waits for it.
        self.assertEqual(self.ui(), [
            "maui devflow ui status --agent-port 10224 --platform ios",
            "maui devflow ui query --automationId plan-title --wait-until exists --timeout 10 --agent-port 10224 "
            "--platform ios"])
        self.assertEqual(d.reset(dev), ["fakehost reset note"])
        self.assertEqual(host.done[-1], "reset")

    def test_tap_on_a_point_goes_to_the_host(self):
        d = self.driver()
        dev = self.device("devflow", platform="ios", target={"host": "fakehost"})
        d.prepare(dev, {})
        d.step_tap(self.ctx(dev), {"x": 200, "y": 400})
        self.assertIn('tap {"x": 200, "y": 400}', FakeHost.instances[0].done)

    def test_dry_run_runs_nothing(self):
        base.DRY_RUN = True
        d = self.driver()
        dev = self.device("devflow")
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"xpath": "//Button"}}]), "en-US")
        self.assertEqual(shot.status, "taken")
        self.assertEqual(self.runner.calls, [])
        self.assertEqual(self.transport.calls, [])


class DevFlowPinningTests(Case):
    """Several apps' agents running (the developer's own simulators and phone): the driver drives only the agent
    of the plan's app on the device it owns, and says so clearly when it can't tell."""

    OURS = "00000000-0000-0000-0000-0000000000A1"
    THEIRS = ("C5F80D2A-0000-4000-8000-0000000000B1", "C5F80D2A-0000-4000-8000-0000000000B2")

    def driver(self):
        return drivers.get("devflow")(self.options())

    def ios(self, **target):
        t = {"host": "fakehost"}
        t.update(target)
        d = self.device("devflow", platform="ios", target=t)
        return d

    def test_with_the_developers_own_agents_running_it_pins_the_one_on_its_simulator(self):
        self.agents((10223, "com.example.samplerecipes", self.THEIRS[0], 25102, "iOS"),
                    (10224, "com.example.samplerecipes", self.THEIRS[1], 58016, "iOS"),
                    (10226, "com.example.samplerecipes", self.OURS, 70127, "iOS"))
        d = self.driver()
        dev = self.ios()
        d.prepare(dev, {})
        d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertEqual(self.ui(), ["maui devflow ui tap --automationId search --agent-port 10226 --platform ios"])

    def test_an_agent_without_a_status_is_matched_through_its_process(self):
        self.runner.on(r"agent list", out=json.dumps([
            {"port": 10223, "platform": "iOS", "appName": "Sample Recipes", "processId": 25102},
            {"port": 10226, "platform": "iOS", "appName": "Sample Recipes", "processId": 70127}]))
        home = "/Users/someone/Library/Developer/CoreSimulator/Devices/%s/data/Containers/Bundle/Application/X/" \
               "SampleRecipes.app/SampleRecipes"
        self.runner.on(r"^ps -o command= -p 25102$", out=home % self.THEIRS[0])
        self.runner.on(r"^ps -o command= -p 70127$", out=home % self.OURS)
        d = self.driver()
        dev = self.ios()
        d.prepare(dev, {})
        d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertIn("--agent-port 10226", self.ui()[-1])

    def test_only_other_simulators_agents_is_a_clear_error_never_a_guess(self):
        self.agents((10223, "com.example.samplerecipes", self.THEIRS[0], 25102, "iOS"),
                    (10224, "com.example.otherapp", self.OURS, 58016, "iOS"))
        d = self.driver()
        dev = self.ios(agentTimeout=5)
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"id": "search"}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("no devflow agent of com.example.samplerecipes on %s" % self.OURS, shot.reason)
        self.assertIn("port 10223", shot.reason)
        self.assertEqual(self.runner.matching(r"ui tap"), [])

    def test_two_agents_of_this_app_on_this_simulator_are_ambiguous(self):
        self.agents((10223, "com.example.samplerecipes", self.OURS, 25102, "iOS"),
                    (10226, "com.example.samplerecipes", self.OURS, 70127, "iOS"))
        d = self.driver()
        dev = self.ios()
        d.prepare(dev, {})
        with self.assertRaises(base.DriverError) as cm:
            d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertIn("more than one devflow agent", str(cm.exception))
        self.assertEqual(self.runner.matching(r"ui tap"), [])

    def test_a_named_port_that_is_another_simulators_agent_is_refused(self):
        self.agents((10225, "com.example.samplerecipes", self.THEIRS[0], 25102, "iOS"))
        d = self.driver()
        dev = self.ios(agentPort=10225)
        d.prepare(dev, {})
        with self.assertRaises(base.DriverError) as cm:
            d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertIn("target.agentPort 10225 is another app's or another device's agent", str(cm.exception))

    def test_after_each_launch_the_agent_is_found_again(self):
        d = self.driver()
        dev = self.ios()
        d.prepare(dev, {})
        self.agents((10224, "com.example.samplerecipes", self.OURS, 41017, "iOS"))
        d.run_screen(dev, self.screen([{"launch": {}}, {"tap": {"id": "a"}}]), "en-US")
        self.agents((10231, "com.example.samplerecipes", self.OURS, 41020, "iOS"))
        d.run_screen(dev, self.screen([{"launch": {}}, {"tap": {"id": "b"}}], sid="recipe"), "en-US")
        taps = self.runner.matching(r"ui tap")
        self.assertIn("--agent-port 10224", taps[0])
        self.assertIn("--agent-port 10231", taps[1])

    def test_android_names_the_device_to_the_cli_and_matches_the_process_on_it(self):
        self.agents((10223, "com.example.samplerecipes", "phone", 3301, "Android"),
                    (10230, "com.example.samplerecipes", "emulator", 4402, "Android"))
        self.runner.on(r"^adb -s emulator-5580 shell pidof com.example.samplerecipes$", out="4402\n")
        d = self.driver()
        dev = self.device("devflow", platform="android", target={"host": "fakehost", "udid": "emulator-5580"})
        d.prepare(dev, {})
        d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertEqual(self.ui()[-1], "maui devflow ui tap --automationId search --agent-port 10230 "
                                        "--platform android --device emulator-5580")
        self.assertTrue(all(env.get("ANDROID_SERIAL") == "emulator-5580"
                            for line, env in self.runner.calls if line.startswith("maui devflow")))
        # Forwards are made on this device only, never taking a port another device's forward holds.
        self.assertTrue(all("-s emulator-5580" in l for l in self.runner.matching(r"^adb .*forward")))
        self.assertTrue(all("--no-rebind" in l for l in self.runner.matching(r"^adb .*forward tcp")))

    def test_a_port_forwarded_to_another_phone_is_never_taken(self):
        self.agents((10223, "com.example.samplerecipes", "phone", 3301, "Android"))
        self.runner.on(r"forward --list", out="R58N12345 tcp:10223 tcp:10223\n")
        self.runner.on(r"pidof", out="")
        d = self.driver()
        dev = self.device("devflow", platform="android", target={"host": "fakehost", "udid": "emulator-5580",
                                                                  "agentTimeout": 3})
        d.prepare(dev, {})
        with self.assertRaises(base.DriverError):
            d.step_tap(self.ctx(dev), {"id": "search"})
        self.assertEqual(self.runner.matching(r"forward --no-rebind"), [])
        self.assertEqual(self.transport.calls, [])

    def test_android_without_a_serial_and_two_devices_attached_is_refused(self):
        self.runner.on(r"^adb devices$", out="List of devices attached\nR58N12345\tdevice\nemulator-5580\tdevice\n")
        d = self.driver()
        dev = self.device("devflow", platform="android", target={"host": "none"})
        with self.assertRaises(base.DriverError) as cm:
            d.prepare(dev, {})
        self.assertIn("2 Android devices are attached", str(cm.exception))


# -- ailoha --------------------------------------------------------------------------------------------------

class AilohaTests(Case):

    def setUp(self):
        Case.setUp(self)
        self.agents((9233, "com.example.samplerecipes", None, 52011, ""))

    def driver(self):
        return drivers.get("ailoha")(self.options())

    def test_platform_is_the_framework_when_the_target_says(self):
        d = self.driver()
        dev = self.device("ailoha", platform="android", target={"host": "none", "agentPlatform": "flutter"})
        d.step_tap(self.ctx(dev), {"id": "login-button"})
        self.assertEqual(self.ui(), ["ailoha ui tap --automationId login-button --agent-port 9233 --platform flutter"])

    def test_back_and_settle(self):
        self.runner.on(r"ui screenshot", then=write_after("--output"))
        d = self.driver()
        dev = self.device("ailoha", platform="windows")
        d.step_back(self.ctx(dev), True)
        d.step_settle(self.ctx(dev), {"timeout": 2})
        self.assertEqual(self.ui()[0], "ailoha ui navigate --back --agent-port 9233 --platform winui")
        self.assertEqual(self.ui()[1], "ailoha ui wait-for-idle --timeout-ms 2000 --agent-port 9233 --platform winui")
        self.assertTrue(self.runner.matching(r"ui screenshot --output"))

    def test_swipe_by_direction_crosses_the_windows_middle(self):
        self.runner.on(r"ui tree", out=answer("ailoha-tree.json"))
        d = self.driver()
        d.step_swipe(self.ctx(self.device("ailoha")), {"direction": "up"})
        self.assertEqual(self.runner.lines[-1], "ailoha ui swipe 201 656 201 218 --agent-port 9233 --platform maccatalyst")

    def test_swipe_from_to(self):
        d = self.driver()
        d.step_swipe(self.ctx(self.device("ailoha")), {"from": [300, 400], "to": [40, 400], "ms": 250})
        self.assertEqual(self.ui(), ["ailoha ui swipe 300 400 40 400 --duration 250 --agent-port 9233 "
                                     "--platform maccatalyst"])

    def test_swipe_hold_is_left_out_with_a_warning(self):
        d = self.driver()
        ctx = self.ctx(self.device("ailoha"))
        d.step_swipe(ctx, {"from": [300, 400], "to": [40, 400], "ms": 250, "hold": 400})
        self.assertEqual(self.ui(), ["ailoha ui swipe 300 400 40 400 --duration 250 --agent-port 9233 "
                                     "--platform maccatalyst"])
        self.assertEqual(len(ctx.shot.warnings), 1)
        self.assertIn("the ailoha driver can't press and hold before a swipe", ctx.shot.warnings[0])

    def test_android_http_needs_a_forward_that_reset_removes(self):
        self.agents((9233, "com.example.samplerecipes", None, 52011, "Android"))
        self.runner.on(r"shell pidof com.example.samplerecipes", out="52011\n")
        self.transport.on("GET", r"^/api/v1/ui/elements\?strategy=xpath", body=answer("devflow-query.json"))
        d = self.driver()
        dev = self.device("ailoha", platform="android", target={"host": "fakehost", "udid": "emulator-5554"})
        d.prepare(dev, {})
        d.step_tap(self.ctx(dev), {"xpath": "//*[@automationId='search']"})
        self.assertIn("adb -s emulator-5554 forward --no-rebind tcp:9233 tcp:9233", self.runner.lines)
        self.assertTrue(all(c[1].startswith("http://127.0.0.1:9233/") for c in self.transport.calls))
        # The CLI's own adb calls go to this device only.
        tap = [c for c in self.runner.calls if " ui tap " in c[0]][0]
        self.assertEqual(tap[1].get("ANDROID_SERIAL"), "emulator-5554")
        d.reset(dev)
        self.assertIn("adb -s emulator-5554 forward --remove tcp:9233", self.runner.lines)

    def test_only_this_machine(self):
        with self.assertRaises(base.NotLocal):
            base.http("GET", "http://192.0.2.10:9233/api/v1/agent/status")


# -- appium --------------------------------------------------------------------------------------------------

SID = "5a1d2c3b-0000-4000-8000-00000000c0de"
EL = "00000000-0000-0000-0000-000000000017"


class AppiumTests(Case):

    def setUp(self):
        Case.setUp(self)
        self.transport.on("GET", r"^/status$", body=answer("appium-status.json"))
        self.transport.on("POST", r"^/session$", body=answer("appium-session.json"))
        self.transport.on("POST", r"/element$", body=answer("appium-element.json"))
        self.transport.on("POST", r"/execute/sync$", body='{"value": null}')
        self.transport.on("POST", r"/click$", body='{"value": null}')
        self.transport.on("POST", r"/value$", body='{"value": null}')
        self.transport.on("DELETE", r"^/session/[^/]+$", body='{"value": null}')

    def driver(self):
        return drivers.get("appium")(self.options())

    def session_caps(self):
        (_, _, body), = self.transport.find("POST", r"/session$")
        return body["capabilities"]["alwaysMatch"]

    def start(self, platform="ios", locale="de-DE", **target):
        target.setdefault("host", "fakehost")
        d = self.driver()
        dev = self.device("appium", platform=platform, target=target)
        d.prepare(dev, {})
        d.apply_locale(dev, locale, base.Shot())
        return d, dev

    def test_capabilities_are_honest(self):
        caps = self.driver().capabilities()
        self.assertEqual(caps["finders"], ["id", "text", "label", "xpath"])
        self.assertNotIn("url", caps["steps"])
        self.assertEqual(caps["throughHost"], ["appFile", "posture"])

    def sim_host(self):
        """The fake host registered as simctl (with ensure_booted), as a real simulator's would be."""
        test = self

        class SimHost(FakeHost):
            booted = True

            def ensure_booted(self):
                if SimHost.booted:
                    return False
                SimHost.booted = True
                self.done.append("booted again")
                return True

            def apply_locale(self, device, locale, shot):
                if not SimHost.booted:
                    raise base.DriverError("xcrun simctl spawn … exited 149: Process spawn via launchd failed "
                                           "because device is not booted")
                FakeHost.apply_locale(self, device, locale, shot)

        module = types.ModuleType("drivers.simhost")
        module.DRIVER = SimHost
        sys.modules["drivers.simhost"] = module
        saved = drivers.REGISTRY["simctl"]
        drivers.REGISTRY["simctl"] = "simhost"
        test.addCleanup(lambda: (drivers.REGISTRY.__setitem__("simctl", saved), sys.modules.pop("drivers.simhost")))
        return SimHost

    def test_a_simulator_session_is_headless_unless_the_plan_says(self):
        self.sim_host()
        self.start("ios", "en-US", host=None)
        self.assertIs(self.session_caps()["appium:isHeadless"], True)
        self.transport.calls = []
        self.start("ios", "en-US", host=None, capabilities={"appium:isHeadless": False})
        self.assertIs(self.session_caps()["appium:isHeadless"], False)

    def test_a_failed_session_reports_its_own_cause_and_the_next_screen_recovers(self):
        SimHost = self.sim_host()
        failure = '{"value": {"error": "unknown error", "message": "An unknown server-side error occurred: The file ' \
                  '/Applications/Xcode.app/Contents/Developer/Applications/Simulator.app does not exist"}}'
        self.transport.on("POST", r"^/session$", body=[(500, failure), (200, answer("appium-session.json"))])
        d = self.driver()
        dev = self.device("appium", platform="ios", target={})
        d.prepare(dev, {})

        def fail_and_shut_down(*_):
            SimHost.booted = False
        # The failed session leaves the simulator shut down (as XCUITest's driver did).
        shot1 = d.run_screen(dev, self.screen([{"wait": {"ms": 10}}]), "en-US")
        self.assertEqual(shot1.status, "missed")
        self.assertIn("Appium couldn't start a session", shot1.reason)
        self.assertIn("appium:isHeadless", shot1.reason)
        fail_and_shut_down()
        shot2 = d.run_screen(dev, self.screen([{"wait": {"ms": 10}}], sid="recipe"), "en-US")
        self.assertEqual(shot2.status, "taken", shot2.reason)
        self.assertIn("booted again", FakeHost.instances[0].done)
        self.assertIn("shut down after the earlier failed Appium session", " ".join(shot2.warnings))

    def test_a_session_that_shut_the_simulator_down_is_tried_once_more(self):
        SimHost = self.sim_host()
        failure = '{"value": {"error": "session not created", "message": "Simulator shut down"}}'

        def route(*_):
            SimHost.booted = False
        self.transport.on("POST", r"^/session$", body=[(500, failure), (200, answer("appium-session.json"))])
        d = self.driver()
        dev = self.device("appium", platform="ios", target={})
        d.prepare(dev, {})
        SimHost.booted = True
        original = d.start_session
        calls = []

        def start(device, locale):
            calls.append(locale)
            try:
                return original(device, locale)
            except base.DriverError:
                route()
                raise
        d.start_session = start
        shot = d.run_screen(dev, self.screen([{"wait": {"ms": 10}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertEqual(len(calls), 2)

    def test_ios_session_capabilities(self):
        self.start("ios", "de-DE")
        caps = self.session_caps()
        self.assertEqual(caps["platformName"], "iOS")
        self.assertEqual(caps["appium:automationName"], "XCUITest")
        self.assertEqual(caps["appium:udid"], "00000000-0000-0000-0000-0000000000A1")
        self.assertEqual(caps["appium:bundleId"], "com.example.samplerecipes")
        self.assertEqual(caps["appium:language"], "de")
        self.assertEqual(caps["appium:locale"], "de_DE")
        self.assertEqual(caps["appium:processArguments"], {"args": ["-ScreenshotSeed", "demo"]})
        self.assertTrue(caps["appium:noReset"])

    def test_android_session_capabilities(self):
        self.start("android", "pt-BR", udid="emulator-5554")
        caps = self.session_caps()
        self.assertEqual(caps["platformName"], "Android")
        self.assertEqual(caps["appium:automationName"], "UiAutomator2")
        self.assertEqual(caps["appium:udid"], "emulator-5554")
        self.assertEqual(caps["appium:appPackage"], "com.example.samplerecipes")
        self.assertEqual(caps["appium:appActivity"], ".MainActivity")
        self.assertEqual((caps["appium:language"], caps["appium:locale"]), ("pt", "BR"))
        self.assertEqual(caps["appium:optionalIntentArguments"], '--es ScreenshotSeed "demo"')

    def test_mac_session_and_target_capabilities_are_added(self):
        self.start("macos", "fr-FR", host="none", capabilities={"appium:skipAppKill": True})
        caps = self.session_caps()
        self.assertEqual((caps["platformName"], caps["appium:automationName"]), ("mac", "Mac2"))
        self.assertEqual(caps["appium:appLocale"], {"language": "fr", "locale": "fr_FR"})
        self.assertEqual(caps["appium:arguments"], ["-ScreenshotSeed", "demo"])
        self.assertTrue(caps["appium:skipAppKill"])

    # WebDriverAgent's port: each device its own, never 8100 (another Appium server's session may hold it).

    OTHER_SIM = "00000000-0000-0000-0000-0000000000B2"

    def wda_status(self, port, udid=None):
        """A WebDriverAgent answering ``GET /status`` on ``port`` (WDA's own reply names no simulator; ``udid`` adds
        one, as a WDA that says would)."""
        value = {"ready": True, "message": "WebDriverAgent is ready to accept commands", "state": "success",
                 "os": {"name": "iOS", "version": "27.2"}, "device": "iphone",
                 "build": {"productBundleIdentifier": "com.example.WebDriverAgentRunner"}}
        if udid:
            value["device"] = {"name": "iPhone 17 Pro", "udid": udid}
        self.hooks.listening.add(port)
        self.transport.on("GET", r"^/status$", port=port,
                          body=json.dumps({"value": value, "sessionId": "5a1d2c3b-0000-4000-8000-0000000000ff"}))

    def own_ports(self, device_id="dev-1", step=0):
        """The WDA and MJPEG ports ``device_id`` maps to, ``step`` ports on (wrapping in each range)."""
        out = []
        for first, last in (appium.WDA_PORTS, appium.MJPEG_PORTS):
            size = last - first + 1
            out.append(first + (appium.derived_port(device_id, (first, last)) - first + step) % size)
        return tuple(out)

    def test_the_derived_port_is_stable_per_device_and_never_wdas_default(self):
        self.assertEqual(appium.derived_port("dev-1", appium.WDA_PORTS), 8180)   # a CRC-32: every run, every machine
        self.assertEqual(appium.derived_port("dev-1", appium.MJPEG_PORTS), 9180)
        self.assertNotEqual(appium.derived_port("apple-tv", appium.WDA_PORTS), 8180)
        for i in range(500):
            port = appium.derived_port("device-%d" % i, appium.WDA_PORTS)
            self.assertTrue(8130 <= port <= 8199, port)
            self.assertNotEqual(appium.derived_port("device-%d" % i, appium.MJPEG_PORTS), 9100)

    def test_a_simulator_session_gets_this_devices_own_ports(self):
        self.sim_host()
        d, dev = self.start("ios", "en-US", host=None)
        caps = self.session_caps()
        self.assertEqual((caps["appium:wdaLocalPort"], caps["appium:mjpegServerPort"]), (8180, 9180))
        self.assertEqual(self.transport.find("GET", r":8180/status$"), [], "nothing listens there: nothing to ask")
        self.assertEqual(d.warnings, [])
        source = d.source(dev)
        self.assertEqual((source["wdaPort"], source["mjpegPort"]), (8180, 9180))
        self.assertTrue(any("WebDriverAgent 8180, MJPEG 9180" in l for l in self.hooks.log), self.hooks.log)

    def test_a_port_the_plan_sets_is_kept_and_not_checked(self):
        self.sim_host()
        self.hooks.listening.add(8100)
        d, dev = self.start("ios", "en-US", host=None, capabilities={"appium:wdaLocalPort": 8100})
        caps = self.session_caps()
        self.assertEqual(caps["appium:wdaLocalPort"], 8100)
        self.assertEqual(caps["appium:mjpegServerPort"], 9180)
        self.assertEqual(self.transport.find("GET", r"/status$")[1:], [], "only the Appium server's own /status")
        self.assertEqual(d.source(dev)["wdaPort"], 8100)

    def test_a_plans_webdriveragent_url_keeps_wda_s_port_its_own(self):
        self.sim_host()
        self.start("ios", "en-US", host=None, capabilities={"appium:webDriverAgentUrl": "http://127.0.0.1:8100"})
        self.assertNotIn("appium:wdaLocalPort", self.session_caps())

    def test_a_port_another_simulators_webdriveragent_holds_is_passed_over(self):
        self.sim_host()
        self.wda_status(8180, udid=self.OTHER_SIM)
        d, dev = self.start("ios", "en-US", host=None)
        caps = self.session_caps()
        self.assertEqual(caps["appium:wdaLocalPort"], self.own_ports(step=1)[0])
        self.assertEqual(caps["appium:mjpegServerPort"], 9180)
        self.assertEqual(len(self.transport.find("GET", r"127\.0\.0\.1:8180/status$")), 1)
        warning, = d.warnings
        self.assertIn("port 8180 is taken", warning)
        self.assertIn(self.OTHER_SIM, warning)
        self.assertIn("using %d" % self.own_ports(step=1)[0], warning)
        self.assertTrue(any("port 8180 is taken" in l for l in self.hooks.log))

    def test_a_webdriveragent_that_cant_say_whose_it_is_is_passed_over_too(self):
        self.sim_host()
        self.wda_status(8180)
        self.wda_status(self.own_ports(step=1)[0])
        self.hooks.listening.add(9180)
        d, dev = self.start("ios", "en-US", host=None)
        caps = self.session_caps()
        self.assertEqual(caps["appium:wdaLocalPort"], self.own_ports(step=2)[0])
        self.assertEqual(caps["appium:mjpegServerPort"], self.own_ports(step=1)[1])
        self.assertIn("doesn't say which simulator", " ".join(d.warnings))
        self.assertIn("ports 8180, %d are taken" % self.own_ports(step=1)[0], " ".join(d.warnings))
        self.assertIn("the MJPEG stream's port 9180 is taken", " ".join(d.warnings))

    def test_our_own_simulators_webdriveragent_is_kept(self):
        self.sim_host()
        self.wda_status(8180, udid="00000000-0000-0000-0000-0000000000a1")   # FakeHost's UDID, any case
        d, dev = self.start("ios", "en-US", host=None)
        self.assertEqual(self.session_caps()["appium:wdaLocalPort"], 8180)
        self.assertEqual(d.warnings, [])

    def test_the_ports_are_chosen_once_a_run(self):
        self.sim_host()
        d, dev = self.start("ios", "en-US", host=None)
        self.wda_status(8180)   # our own WDA, still up from the last locale's session
        d.apply_locale(dev, "de-DE", base.Shot())
        first, second = [c[2]["capabilities"]["alwaysMatch"] for c in self.transport.find("POST", r"/session$")]
        self.assertEqual(first["appium:wdaLocalPort"], second["appium:wdaLocalPort"])
        self.assertEqual(self.transport.find("GET", r":8180/status$"), [])

    def test_no_ports_off_a_simulator(self):
        self.start("ios", "en-US")   # the fake host: not simctl
        self.assertNotIn("appium:wdaLocalPort", self.session_caps())
        self.transport.calls = []
        self.start("android", "en-US", udid="emulator-5554")
        self.assertNotIn("appium:wdaLocalPort", self.session_caps())

    def test_invalid_session_id_on_ios_says_what_it_may_be(self):
        d, dev = self.start("ios", "en-US")
        self.transport.on("POST", r"/execute/sync$", status=404, body='{"value": {"error": "invalid session id", '
                          '"message": "Session does not exist"}}')
        with self.assertRaises(base.DriverError) as cm:
            d.step_launch(self.ctx(dev), {})
        self.assertIn("another simulator's WebDriverAgent", str(cm.exception))

    def test_a_remote_server_is_refused(self):
        d = self.driver()
        with self.assertRaises(base.NotLocal):
            d.prepare(self.device("appium", target={"host": "none", "server": "http://203.0.113.5:4723"}), {})

    def test_no_server_says_how_to_start_one(self):
        def refuse(*a):
            raise ConnectionRefusedError("refused")
        web.TRANSPORT = refuse
        with self.assertRaises(base.DriverError) as cm:
            self.driver().prepare(self.device("appium", target={"host": "none"}), {})
        self.assertIn("start it with `appium`", str(cm.exception))

    def test_tap_by_id_finds_then_clicks(self):
        d, dev = self.start()
        d.step_tap(self.ctx(dev), {"id": "search"})
        finds = self.transport.find("POST", r"/element$")
        self.assertEqual(finds[0][2], {"using": "accessibility id", "value": "search"})
        clicks = self.transport.find("POST", r"/click$")
        self.assertEqual(clicks[0][1], "http://127.0.0.1:4723/session/%s/element/%s/click" % (SID, EL))

    def test_android_id_tries_the_resource_id_then_accessibility_id(self):
        self.transport.on("POST", r"/element$", status=404, body=answer("appium-no-such-element.json"))
        d, dev = self.start("android", udid="emulator-5554")
        self.assertIsNone(d.find(self.ctx(dev), ("id", "search")))
        usings = [c[2]["using"] for c in self.transport.find("POST", r"/element$")]
        self.assertEqual(usings, ["id", "accessibility id"])

    def test_text_finders_per_platform(self):
        d, dev = self.start("ios")
        # Exact first, then ignoring case (trimmed), then contained: what config.md promises on every driver.
        self.assertEqual(d.strategies(dev, ("text", 'Say "hi"')), [
            ("-ios predicate string", 'label == "Say \\"hi\\"" OR value == "Say \\"hi\\"" OR name == "Say \\"hi\\""'),
            ("-ios predicate string", 'label ==[c] "Say \\"hi\\"" OR value ==[c] "Say \\"hi\\"" OR '
                                      'name ==[c] "Say \\"hi\\""'),
            ("-ios predicate string", 'label CONTAINS[c] "Say \\"hi\\"" OR value CONTAINS[c] "Say \\"hi\\"" OR '
                                      'name CONTAINS[c] "Say \\"hi\\""')])
        self.assertEqual([v for _, v in d.strategies(dev, ("label", " Menu "))],
                         ['label == " Menu "', 'label ==[c] "Menu"', 'label CONTAINS[c] "Menu"'])
        android = self.device("appium", platform="android")
        texts = d.strategies(android, ("text", "Plan"))
        self.assertEqual(texts[0], ("xpath", "//*[@text='Plan']"))
        self.assertEqual(texts[1], ("xpath", "//*[translate(normalize-space(@text), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                                             "'abcdefghijklmnopqrstuvwxyz')='plan']"))
        self.assertEqual(texts[2], ("xpath", "//*[contains(translate(@text, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
                                             "'abcdefghijklmnopqrstuvwxyz'), 'plan')]"))
        labels = d.strategies(android, ("label", "Plan"))
        self.assertEqual(labels[0], ("accessibility id", "Plan"))
        self.assertIn("@content-desc", labels[2][1])

    def test_ios_text_found_by_its_upper_case_label_and_by_part_of_it(self):
        # The trial: "Cooking time" drawn COOKING TIME, and "Lemon" inside "  Lemon Pasta for 4 people".
        exact_miss = '{"value": {"error": "no such element", "message": "none"}}'
        found = '{"value": {"element-6066-11e4-a52e-4f735466cecf": "%s"}}' % EL
        d, dev = self.start("ios")

        def route(hit_on):
            """The n-th strategy (1: exact, 2: ignoring case, 3: contained) is the first to find it."""
            self.transport.on("POST", r"/element$", body=[(200, found) if n == hit_on else (404, exact_miss)
                                                          for n in range(1, 4)] + [(200, found)])
        route(2)
        el = d.find(self.ctx(dev), ("text", "Cooking time"))
        self.assertIsNotNone(el)
        usings = [c[2]["value"] for c in self.transport.find("POST", r"/element$")]
        self.assertEqual(len(usings), 2)
        self.assertIn("==[c]", usings[1])
        self.transport.calls[:] = []
        route(3)
        self.assertIsNotNone(d.find(self.ctx(dev), ("text", "Lemon")))
        self.assertIn("CONTAINS[c]", self.transport.find("POST", r"/element$")[-1][2]["value"])

    def test_the_keyboard_is_read_and_hidden_with_its_own_keys_on_ios(self):
        d, dev = self.start("ios")
        self.transport.on("POST", r"/execute/sync$", body='{"value": true}')
        self.assertTrue(d.keyboard_shown(self.ctx(dev)))
        self.transport.calls[:] = []
        self.transport.on("POST", r"/execute/sync$", body=[(200, '{"value": true}'), (200, '{"value": null}'),
                                                           (200, '{"value": false}')])
        d.step_hideKeyboard(self.ctx(dev), True)
        scripts = [c[2]["script"] for c in self.transport.find("POST", r"/execute/sync$")]
        self.assertEqual(scripts, ["mobile: isKeyboardShown", "mobile: hideKeyboard", "mobile: isKeyboardShown"])
        hide = self.transport.find("POST", r"/execute/sync$")[1][2]["args"][0]
        self.assertIn("Done", hide["keys"])
        self.assertEqual(self.transport.find("POST", r"/back$"), [], "never Appium's back: that's navigation on iOS")

    def test_a_keyboard_left_up_on_a_screen_that_types_nothing_is_a_wrong_state(self):
        d, dev = self.start("ios")
        self.transport.on("POST", r"/execute/sync$", body='{"value": true}')
        shot = d.run_screen(dev, self.screen([{"wait": {"ms": 10}}], state="the plan, nothing being typed"), "de-DE")
        self.assertEqual(shot.status, "missed")
        self.assertEqual(shot.state_check, "failed")
        self.assertIn("keyboard is up", shot.reason)
        self.assertIn("hideKeyboard", shot.reason)

    def test_a_screen_that_types_may_keep_the_keyboard_but_is_warned(self):
        d, dev = self.start("ios")
        self.transport.on("POST", r"/execute/sync$", body='{"value": true}')
        self.transport.on("POST", r"/element$", body='{"value": {"element-6066-11e4-a52e-4f735466cecf": "%s"}}' % EL)
        shot = d.run_screen(dev, self.screen([{"type": {"id": "amount", "text": "12"}}]), "de-DE")
        self.assertEqual(shot.status, "taken", shot.reason)
        self.assertTrue(any("keyboard is up" in w for w in shot.warnings))
        # Asked for explicitly, the same keyboard fails the shot.
        shot = d.run_screen(dev, self.screen([{"type": {"id": "amount", "text": "12"}}],
                                             verify=[{"id": "amount"}, {"keyboard": "hidden"}]), "de-DE")
        self.assertEqual(shot.status, "missed")
        self.assertIn("keyboard is up", shot.reason)

    def test_waiting_for_an_element_that_never_comes_misses_the_shot(self):
        self.transport.on("POST", r"/element$", status=404, body=answer("appium-no-such-element.json"))
        d = self.driver()
        dev = self.device("appium", platform="ios", target={"host": "fakehost"})
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"wait": {"id": "recipe-title", "timeout": 3}}]), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("recipe-title", shot.reason)

    def test_type_into_the_focused_element(self):
        self.transport.on("GET", r"/element/active$", body=answer("appium-element.json"))
        d, dev = self.start()
        d.step_type(self.ctx(dev), {"text": "pasta"})
        (_, url, body), = self.transport.find("POST", r"/value$")
        self.assertTrue(url.endswith("/element/%s/value" % EL))
        self.assertEqual(body, {"text": "pasta"})

    def test_launch_on_ios_and_android(self):
        d, dev = self.start("ios")
        d.step_launch(self.ctx(dev), {"args": {"ScreenshotScreen": "plan"}, "env": {"DEMO": "1"}})
        scripts = [c[2] for c in self.transport.find("POST", r"/execute/sync$")]
        self.assertEqual(scripts[0], {"script": "mobile: terminateApp", "args": [{"bundleId": "com.example.samplerecipes"}]})
        self.assertEqual(scripts[1], {"script": "mobile: launchApp", "args": [{
            "bundleId": "com.example.samplerecipes", "arguments": ["-ScreenshotSeed", "demo", "-ScreenshotScreen", "plan"],
            "environment": {"DEMO": "1"}}]})
        d2, dev2 = self.start("android", udid="emulator-5554")
        d2.step_launch(self.ctx(dev2), {"args": {"ScreenshotScreen": "plan", "Pro": True}, "clean": True})
        scripts = [c[2] for c in self.transport.find("POST", r"/execute/sync$")][2:]
        self.assertEqual(scripts[0]["script"], "mobile: clearApp")
        self.assertEqual(scripts[1], {"script": "mobile: startActivity", "args": [{
            "stop": True, "wait": True, "component": "com.example.samplerecipes/.MainActivity",
            "extras": [["s", "ScreenshotSeed", "demo"], ["s", "ScreenshotScreen", "plan"], ["z", "Pro", "true"]]}]})

    def test_deep_link(self):
        d, dev = self.start("android", udid="emulator-5554")
        d.step_deepLink(self.ctx(dev), "samplerecipes://recipe/demo")
        body = self.transport.find("POST", r"/execute/sync$")[-1][2]
        self.assertEqual(body, {"script": "mobile: deepLink", "args": [{"url": "samplerecipes://recipe/demo",
                                                                         "package": "com.example.samplerecipes"}]})

    def test_swipe_from_to_is_a_w3c_pointer_action(self):
        self.transport.on("POST", r"/actions$", body='{"value": null}')
        self.transport.on("DELETE", r"/actions$", body='{"value": null}')
        d, dev = self.start()
        d.step_swipe(self.ctx(dev), {"from": [300, 600], "to": [300, 200], "ms": 400})
        (_, _, body), = self.transport.find("POST", r"/actions$")
        acts = body["actions"][0]["actions"]
        self.assertEqual([a["type"] for a in acts], ["pointerMove", "pointerDown", "pointerMove", "pointerUp"])
        self.assertEqual((acts[2]["x"], acts[2]["y"], acts[2]["duration"]), (300, 200, 400))

    def test_swipe_with_hold_pauses_after_the_finger_goes_down(self):
        # A slider or a pan gesture in a scroll view reads a touch that moves at once as a scroll: hold first.
        self.transport.on("POST", r"/actions$", body='{"value": null}')
        self.transport.on("DELETE", r"/actions$", body='{"value": null}')
        for platform in ("ios", "android"):
            d, dev = self.start(platform)
            ctx = self.ctx(dev)
            d.step_swipe(ctx, {"from": [180, 1240], "to": [900, 1240], "hold": 400, "ms": 1400})
            body = self.transport.find("POST", r"/actions$")[-1][2]
            acts = body["actions"][0]["actions"]
            self.assertEqual(acts, [
                {"type": "pointerMove", "duration": 0, "x": 180, "y": 1240},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 400},
                {"type": "pointerMove", "duration": 1400, "x": 900, "y": 1240},
                {"type": "pointerUp", "button": 0}], platform)
            self.assertEqual(ctx.shot.warnings, [])

    def test_swipe_hold_with_a_direction_is_left_out_with_a_warning(self):
        d, dev = self.start()
        ctx = self.ctx(dev)
        d.step_swipe(ctx, {"direction": "left", "hold": 400})
        self.assertEqual(self.transport.find("POST", r"/actions$"), [])
        self.assertEqual(self.transport.find("POST", r"/execute/sync$")[-1][2]["script"], "mobile: swipe")
        self.assertEqual(len(ctx.shot.warnings), 1)
        self.assertIn("hold goes with from and to", ctx.shot.warnings[0])

    def test_screenshot_without_a_host_is_the_sessions_base64_png(self):
        png = kit.png_bytes(64, 128)
        self.transport.on("GET", r"/screenshot$", body=json.dumps({"value": base64.b64encode(png).decode("ascii")}))
        d, dev = self.start("macos", host="none")
        path = os.path.join(self.work, "shot.png")
        d.screenshot(dev, path)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), png)

    def test_reset_quits_the_session_then_resets_the_host(self):
        d, dev = self.start()
        warnings = d.reset(dev)
        self.assertEqual(self.transport.find("DELETE", r"/session/")[-1][1],
                         "http://127.0.0.1:4723/session/%s" % SID)
        self.assertEqual(warnings, ["fakehost reset note"])
        self.assertEqual(FakeHost.instances[0].done[-1], "reset")

    def test_a_new_locale_is_a_new_session(self):
        d, dev = self.start("ios", "en-US")
        d.apply_locale(dev, "ja-JP", base.Shot())
        self.assertEqual(len(self.transport.find("POST", r"/session$")), 2)
        self.assertEqual(len(self.transport.find("DELETE", r"/session/")), 1)


# -- xcuitest ------------------------------------------------------------------------------------------------

class XcuitestTests(Case):

    def driver(self):
        return drivers.get("xcuitest")(self.options())

    def device_for(self, **target):
        t = {"host": "fakehost", "project": "SampleRecipes.xcodeproj", "scheme": "SampleRecipesUITests"}
        t.update(target)
        return self.device("xcuitest", platform="ios", target=t, width=64, height=128)

    def export_fixture(self, cmd):
        out = cmd[cmd.index("--output-path") + 1]
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "manifest.json"), "w") as f:
            f.write(answer("xcresult-manifest.json"))
        for item in json.loads(answer("xcresult-manifest.json"))[0]["attachments"]:
            kit.write_png(os.path.join(out, item["exportedFileName"]), 64, 128)

    def make_bundle(self, cmd):
        os.makedirs(cmd[cmd.index("-resultBundlePath") + 1], exist_ok=True)

    def test_attachment_names(self):
        self.assertEqual(xcuitest.attachment_name("plan_0_1D0C8A4E-2F6B-4C1A-9E3D-5B7A8C9D0E1F.png"), "plan")
        self.assertEqual(xcuitest.attachment_name("01-plan_12_1D0C8A4E-2F6B-4C1A-9E3D-5B7A8C9D0E1F.png"), "01-plan")
        self.assertEqual(xcuitest.attachment_name("Screenshot.png"), "Screenshot")
        self.assertEqual(xcuitest.language_region("zh-Hans-CN"), ("zh-Hans", "CN"))

    def test_one_test_run_serves_every_screen_that_names_it(self):
        self.runner.on(r"^xcodebuild test", then=self.make_bundle)
        self.runner.on(r"xcresulttool export attachments", then=self.export_fixture)
        d = self.driver()
        dev = self.device_for()
        d.prepare(dev, {})
        test = "SampleRecipesUITests/StoreShots/testAllScreens"
        plan = d.run_screen(dev, self.screen([{"flow": test}], "plan"), "de-DE")
        recipe = d.run_screen(dev, self.screen([{"flow": test}], "recipe"), "de-DE")
        self.assertEqual((plan.status, recipe.status), ("taken", "taken"), (plan.reason, recipe.reason))
        builds = self.runner.matching(r"^xcodebuild")
        self.assertEqual(len(builds), 1)
        self.assertIn("-project %s" % os.path.join(self.work, "SampleRecipes.xcodeproj"), builds[0])
        self.assertIn("-scheme SampleRecipesUITests", builds[0])
        self.assertIn("-destination 'platform=iOS Simulator,id=00000000-0000-0000-0000-0000000000A1'", builds[0])
        self.assertIn("-only-testing:%s -testLanguage de -testRegion DE" % test, builds[0])
        env = [e for line, e in self.runner.calls if line.startswith("xcodebuild")][0]
        self.assertEqual(env["TEST_RUNNER_ScreenshotSeed"], "demo")
        self.assertEqual(env["TEST_RUNNER_APPSTORES_LOCALE"], "de-DE")
        self.assertEqual(plan.status_bar, "verified")
        self.assertTrue(os.path.isfile(plan.path))

    def test_a_missing_attachment_is_missed_with_what_it_made(self):
        self.runner.on(r"^xcodebuild test", code=65, out="** TEST FAILED **", then=self.make_bundle)
        self.runner.on(r"xcresulttool export attachments", then=self.export_fixture)
        d = self.driver()
        dev = self.device_for()
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"flow": {"test": "UITests/StoreShots", "attachment": "search"}}],
                                             "search"), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("made: plan, recipe", shot.reason)
        self.assertIn("exited 65", shot.reason)

    def test_other_steps_are_skipped(self):
        d = self.driver()
        dev = self.device_for()
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"tap": {"id": "x"}}]), "en-US")
        self.assertEqual(shot.status, "skipped")

    def test_xctestrun_and_mac(self):
        d = self.driver()
        mac = self.device("xcuitest", platform="macos", target={"xctestrun": "build/Shots.xctestrun"})
        cmd = d.test_command(mac, "ShotsUITests", "fr-CA", "/tmp/r.xcresult")
        self.assertEqual(cmd[:4], ["xcodebuild", "test-without-building", "-xctestrun",
                                   os.path.join(self.work, "build", "Shots.xctestrun")])
        self.assertIn("platform=macOS", cmd)
        self.assertEqual(cmd[-4:], ["-testLanguage", "fr", "-testRegion", "CA"])

    def test_needs_a_scheme(self):
        with self.assertRaises(base.DriverError):
            self.driver().prepare(self.device("xcuitest", platform="macos"), {})


# -- maestro -------------------------------------------------------------------------------------------------

class MaestroTests(Case):

    def driver(self):
        return drivers.get("maestro")(self.options())

    def test_steps_become_a_flow(self):
        d = self.driver()
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        screen = self.screen([
            {"launch": {"args": {"ScreenshotScreen": "search"}, "clean": True}},
            {"deepLink": "samplerecipes://search"},
            {"tap": {"id": "search"}},
            {"type": {"text": "pasta", "into": "Search (recipes)"}},
            {"wait": {"text": "Tomato pasta", "timeout": 5}},
            {"wait": {"ms": 800}},
            {"scroll": {"to": {"id": "recipe-17"}}},
            {"scroll": {"direction": "up"}},
            {"swipe": {"direction": "left"}},
            {"back": True},
            {"settle": {"timeout": 2}},
        ], "search")
        text = d.write_flow(dev, screen, "en-US", "appstores-search")
        self.assertEqual(text.splitlines(), [
            'appId: "com.example.samplerecipes"',
            "---",
            '- launchApp: {"appId": "com.example.samplerecipes", "stopApp": true, "clearState": true, '
            '"arguments": {"ScreenshotSeed": "demo", "ScreenshotScreen": "search"}}',
            '- openLink: "samplerecipes://search"',
            '- tapOn: {"id": "search"}',
            '- tapOn: {"text": "Search\\\\ \\\\(recipes\\\\)"}',
            '- inputText: "pasta"',
            '- extendedWaitUntil: {"visible": {"text": "Tomato\\\\ pasta"}, "timeout": 5000}',
            '- extendedWaitUntil: {"visible": {"id": "appstores-never-there"}, "timeout": 800, "optional": true}',
            '- scrollUntilVisible: {"element": {"id": "recipe-17"}, "direction": "DOWN"}',
            '- swipe: {"direction": "DOWN"}',
            '- swipe: {"direction": "LEFT"}',
            "- back",
            '- waitForAnimationToEnd: {"timeout": 2000}',
            '- takeScreenshot: "appstores-search"'])

    def test_a_swipes_hold_is_left_out_of_the_flow_with_a_warning(self):
        d = self.driver()
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        text = d.write_flow(dev, self.screen([{"swipe": {"from": [180, 1240], "to": [900, 1240], "hold": 400,
                                                         "ms": 1000}}]), "en-US")
        self.assertIn('- swipe: {"start": "180,1240", "end": "900,1240", "duration": 1000}', text.splitlines())
        self.assertTrue(any("maestro's swipe can't press and hold" in l for l in self.hooks.log), self.hooks.log)

    def test_a_generated_flow_runs_then_the_host_takes_the_picture(self):
        d = self.driver()
        dev = self.device("maestro", platform="ios", target={"host": "fakehost"}, width=64, height=128)
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"launch": {}}, {"tap": {"text": "Plan"}}]), "en-US")
        self.assertEqual(shot.status, "taken", shot.reason)
        line = self.runner.matching(r"^maestro")[0]
        self.assertTrue(line.startswith("maestro --device=00000000-0000-0000-0000-0000000000A1 test --test-output-dir "),
                        line)
        self.assertIn("-e ScreenshotSeed=demo", line)
        self.assertEqual(FakeHost.instances[0].done[-1], "screenshot")
        with open(line.split()[-1]) as f:
            self.assertNotIn("takeScreenshot", f.read())

    def test_the_apps_own_flow_and_its_screenshot(self):
        def outputs(cmd):
            out = cmd[cmd.index("--test-output-dir") + 1]
            kit.write_png(os.path.join(out, "2026-11-14_100211", "onboarding", "takeScreenshot", "plan.png"), 64, 128)
            kit.write_png(os.path.join(out, "2026-11-14_100211", "onboarding", "takeScreenshot", "recipe.png"), 64, 128)
        self.runner.on(r"^maestro", then=outputs)
        d = self.driver()
        dev = self.device("maestro", platform="android", target={"host": "fakehost", "udid": "emulator-5554"},
                          width=64, height=128)
        d.prepare(dev, {})
        a = d.run_screen(dev, self.screen([{"flow": "flows/onboarding.yaml"}], "plan"), "en-US")
        b = d.run_screen(dev, self.screen([{"flow": {"file": "flows/onboarding.yaml", "screenshot": "recipe"}}],
                                          "recipe-shot"), "en-US")
        self.assertEqual((a.status, b.status), ("taken", "taken"), (a.reason, b.reason))
        self.assertEqual(len(self.runner.matching(r"^maestro")), 1)
        self.assertIn("--device=emulator-5554", self.runner.lines[0])
        self.assertTrue(self.runner.lines[0].endswith(os.path.join(self.work, "flows", "onboarding.yaml")))

    def test_a_flow_without_the_screenshot_is_missed(self):
        d = self.driver()
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        d.prepare(dev, {})
        shot = d.run_screen(dev, self.screen([{"flow": "flows/onboarding.yaml"}], "plan"), "en-US")
        self.assertEqual(shot.status, "missed")
        self.assertIn("no screenshot named plan", shot.reason)

    def test_css_and_mixed_flow_steps_are_skipped(self):
        d = self.driver()
        dev = self.device("maestro", platform="android", target={"host": "fakehost"})
        d.prepare(dev, {})
        self.assertEqual(d.run_screen(dev, self.screen([{"tap": {"css": "#go"}}]), "en-US").status, "skipped")
        mixed = d.run_screen(dev, self.screen([{"launch": {}}, {"flow": "f.yaml"}]), "en-US")
        self.assertEqual(mixed.status, "skipped")
        self.assertIn("runs alone", mixed.reason)

    def test_pictures_are_named_by_their_path_under_take_screenshot(self):
        root = os.path.join(self.work, "out")
        kit.write_png(os.path.join(root, "s1", "flowA", "takeScreenshot", "checkout", "pay.png"), 4, 4)
        kit.write_png(os.path.join(root, "loose.png"), 4, 4)
        self.assertEqual(sorted(maestro.pictures(root)), ["checkout/pay", "loose"])


# -- shared bits ---------------------------------------------------------------------------------------------

class SharedTests(Case):

    def test_parse_json_skips_a_leading_line_and_unwraps(self):
        self.assertEqual(agentcli.parse_json('note: hi\n[{"id": 1}]'), [{"id": 1}])
        self.assertEqual(agentcli.parse_json('{"result": [{"id": 2}]}'), [{"id": 2}])
        self.assertIsNone(agentcli.parse_json(""))

    def test_element_bounds(self):
        el = agentcli.element_from(json.loads(answer("devflow-query.json"))[0])
        self.assertEqual((el.id, el.bounds, el.attrs["elementId"]), ("search", (16, 120, 386, 164), "el-17"))

    def test_default_hosts(self):
        d = drivers.get("devflow")(self.options())
        self.assertEqual(d.host_name({"platform": "ios", "target": {}}), "simctl")
        self.assertEqual(d.host_name({"platform": "android", "target": {}}), "adb")
        self.assertIsNone(d.host_name({"platform": "macos", "target": {}}))
        self.assertIsNone(d.host_name({"platform": "ios", "target": {"host": "none"}}))

    def test_type_target(self):
        self.assertEqual(hosted.type_target({"text": "a", "id": "f"}), {"id": "f"})
        self.assertEqual(hosted.type_target({"text": "a", "into": "Search"}), {"text": "Search"})
        self.assertEqual(hosted.type_target({"text": "a"}), {})

    def test_appium_locale_parts(self):
        self.assertEqual((appium.language_of("zh-Hans-CN"), appium.region_of("zh-Hans-CN")), ("zh-Hans", "CN"))


def tearDownModule():
    kit.assert_no_residue()


if __name__ == "__main__":
    unittest.main()
