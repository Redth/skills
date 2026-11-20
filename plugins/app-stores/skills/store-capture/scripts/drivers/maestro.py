"""The ``maestro`` driver: Maestro flows (YAML) on iOS simulators, Android and the web.

Two ways a screen uses it:

- **A flow of the app's own**: ``{"flow": "flows/onboarding.yaml"}`` (or ``{"flow": {"file": "…", "screenshot":
  "plan", "env": {…}}}``). It's run with ``maestro [--device=<id>] test --test-output-dir <dir> -e KEY=VALUE …
  <file>`` and must ``takeScreenshot`` the screen (``- takeScreenshot: plan``: the screen id, or the flow's
  ``screenshot``); the picture is found under the output folder's ``takeScreenshot`` folder. One run serves every
  screen that names the same flow (per locale). The flow gets ``APPSTORES_LOCALE``, ``APPSTORES_SCREEN``,
  ``APPSTORES_DEVICE`` and ``ScreenshotSeed`` (use them as ``${ScreenshotSeed}``; an undefined one silently
  becomes ``undefined``).
- **Steps**: any other screen's steps are written as a flow (``launchApp``, ``openLink``, ``tapOn``,
  ``inputText``, ``extendedWaitUntil``, ``scrollUntilVisible``, ``scroll``/``swipe``, ``back``,
  ``waitForAnimationToEnd``) and run; the host takes the screenshot after (the whole framebuffer, status bar
  included), or the flow's own ``takeScreenshot`` with no host.

Maestro can't set the locale or the status bar (``--device-locale`` is only ``start-device``'s): the device's
host does (``simctl``/``adb``: the dedicated device, its locale, appearance and clean status bar). Text selectors
are regular expressions; this driver escapes the text it's given.

Target settings: ``maestro`` (the command, as a list), ``env`` (more ``-e`` values), ``flowTimeout`` (seconds,
default 900), plus the host's.
"""

from __future__ import annotations

import json
import os
import re
import shutil

from . import base
from .hosted import HostedDriver, type_target

SCREENSHOT_PREFIX = "appstores-"
DIRECTION = {"up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT"}
# Scrolling content down is a finger swipe up.
SCROLL_SWIPE = {"down": "UP", "up": "DOWN", "left": "RIGHT", "right": "LEFT"}


def yaml_value(value):
    """A value as YAML: JSON is YAML, so JSON it is (strings quoted, maps and lists in flow style)."""
    return json.dumps(value, ensure_ascii=False)


def selector(query):
    """A Maestro selector for ``(finder, wanted)``: ``{"id": …}`` or ``{"text": <escaped regex>}``."""
    finder, wanted = query
    if finder == "id":
        return {"id": str(wanted)}
    if finder in ("text", "label"):
        return {"text": re.escape(str(wanted))}
    raise base.StepSkipped("maestro finds elements by id or text, not %s" % finder)


def pictures(folder):
    """The pictures a run left under ``folder``: ``{name: path}``, the name being the path under a
    ``takeScreenshot`` folder (without ``.png``) or, outside one, the file's stem. The newest wins."""
    found = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames.sort()
        for f in sorted(filenames):
            if not f.lower().endswith(".png"):
                continue
            path = os.path.join(dirpath, f)
            parts = os.path.relpath(path, folder).split(os.sep)
            stem = os.path.splitext(parts[-1])[0]
            if "takeScreenshot" in parts[:-1]:
                i = len(parts) - 2 - parts[:-1][::-1].index("takeScreenshot")
                name = "/".join(parts[i + 1:-1] + [stem])
            else:
                name = stem
            if name not in found or os.path.getmtime(path) >= os.path.getmtime(found[name]):
                found[name] = path
    return found


class MaestroDriver(HostedDriver):
    """Maestro flows (see the module's docstring)."""

    NAME = "maestro"
    PLATFORMS = ("ios", "ipados", "android", "web")
    STEPS = ("flow", "launch", "deepLink", "url", "tap", "type", "wait", "scroll", "back", "swipe", "settle")
    FINDERS = ("id", "text", "label")
    HOST_STEPS = ()
    POSTURE_SETTING = True   # the device's posture is set by the host before the flow runs

    def __init__(self, options=None):
        """Set up."""
        HostedDriver.__init__(self, options)
        self.runs = {}
        self.count = 0

    def has_own_step(self, kind):
        return True

    def maestro(self, device):
        t = device.get("target") or {}
        cmd = t.get("maestro") or ["maestro"]
        return [cmd] if isinstance(cmd, str) else list(cmd)

    def env_for(self, device, screen, locale):
        """The ``-e`` values every flow gets."""
        env = {"APPSTORES_LOCALE": locale, "APPSTORES_SCREEN": screen["id"], "APPSTORES_DEVICE": device["id"]}
        seed = screen.get("seed") if screen.get("seed") is not None else device.get("seed")
        if seed is not None:
            env["ScreenshotSeed"] = str(seed)
        env.update(dict((k, str(v)) for k, v in ((device.get("target") or {}).get("env") or {}).items()))
        return env

    def command(self, device, flow, out, env):
        """``maestro [--device=<id>] test --test-output-dir <out> -e K=V … <flow>``."""
        cmd = self.maestro(device)
        ref = self.device_ref(device)
        if ref and device.get("platform") != "web":
            cmd.append("--device=%s" % ref)
        cmd += ["test", "--test-output-dir", out]
        for k in sorted(env):
            cmd += ["-e", "%s=%s" % (k, env[k])]
        return cmd + [flow]

    def run_flow(self, device, flow, env, cache_key=None):
        """Run a flow file into a fresh output folder; return ``(pictures, code, tail)``."""
        if cache_key is not None and cache_key in self.runs:
            return self.runs[cache_key]
        self.count += 1
        out = os.path.join(self.options.workdir, "maestro", "run-%d" % self.count)
        if not base.DRY_RUN:
            if os.path.exists(out):
                shutil.rmtree(out)
            os.makedirs(out)
        t = device.get("target") or {}
        res = base.run(self.command(device, flow, out, env), timeout=float(t.get("flowTimeout") or 900),
                       check=False, cwd=self.options.plan_dir)
        tail = ((res.out or "") + "\n" + (res.err or "")).strip().splitlines()[-6:]
        result = ({} if base.DRY_RUN else pictures(out), res.code, tail)
        if cache_key is not None:
            self.runs[cache_key] = result
        return result

    # -- writing a flow from steps --------------------------------------------------------------------------

    def header(self, device):
        """The flow's config section: ``appId`` (iOS bundle id, Android package) or ``url`` (web)."""
        app = device.get("app") or {}
        if device.get("platform") == "web":
            if not app.get("url"):
                raise base.StepFailed("a web flow needs the plan's app.web.url")
            return "url: %s\n---\n" % yaml_value(app["url"])
        app_id = app.get("bundleId") or app.get("package")
        if not app_id:
            raise base.StepFailed("a flow needs the plan's app.%s.bundleId or package" % device.get("platform"))
        return "appId: %s\n---\n" % yaml_value(app_id)

    def translate(self, device, screen, step, index):
        """One plan step as flow commands (a list of ``(command, value)``; ``value`` ``None`` for a bare one)."""
        kind, value = base.step_of(step)
        app = device.get("app") or {}
        if kind == "launch":
            value = value or {}
            args = {}
            seed = screen.get("seed") if screen.get("seed") is not None else device.get("seed")
            if seed is not None:
                args["ScreenshotSeed"] = str(seed)
            args.update(value.get("args") or {})
            launch = {"appId": app.get("bundleId") or app.get("package"), "stopApp": True}
            if value.get("clean"):
                launch["clearState"] = True
            if args:
                launch["arguments"] = args
            if value.get("env"):
                base.LOG("  warning: step %d: maestro's launchApp takes no environment; env left out" % index)
            return [("launchApp", launch)]
        if kind in ("deepLink", "url"):
            return [("openLink", value.get("url") if isinstance(value, dict) else value)]
        if kind == "tap":
            if isinstance(value, dict) and "x" in value and "y" in value:
                return [("tapOn", {"point": "%d,%d" % (round(value["x"]), round(value["y"]))})]
            query = base.element_query(value)
            if query is None:
                raise base.StepFailed("step %d: tap needs an element or x and y" % index)
            return [("tapOn", selector(query))]
        if kind == "type":
            value = value if isinstance(value, dict) else {"text": value}
            out = []
            target = base.element_query(type_target(value))
            if target:
                out.append(("tapOn", selector(target)))
            return out + [("inputText", str(value.get("text", "")))]
        if kind == "wait":
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                value = {"ms": value}
            value = value or {}
            query = base.element_query(value)
            if query is not None:
                timeout = int(float(value.get("timeout") or self.WAIT_TIMEOUT) * 1000)
                return [("extendedWaitUntil", {"visible": selector(query), "timeout": timeout})]
            # Maestro has no sleep: wait the time for something that's never there, and don't mind it.
            return [("extendedWaitUntil", {"visible": {"id": "appstores-never-there"},
                                           "timeout": int(value.get("ms") or 0), "optional": True})]
        if kind == "scroll":
            value = value if isinstance(value, dict) else {"direction": value}
            direction = value.get("direction") or "down"
            if value.get("to"):
                query = base.element_query(value["to"])
                if query is None:
                    raise base.StepFailed("step %d: scroll to needs an element" % index)
                return [("scrollUntilVisible", {"element": selector(query), "direction": DIRECTION[direction]})]
            times = int(value.get("times") or 1)
            if direction == "down":
                return [("scroll", None)] * times
            return [("swipe", {"direction": SCROLL_SWIPE[direction]})] * times
        if kind == "back":
            return [("back", None)]
        if kind == "swipe":
            value = value if isinstance(value, dict) else {"direction": value}
            if value.get("from") and value.get("to"):
                sw = {"start": "%d,%d" % tuple(round(v) for v in value["from"]),
                      "end": "%d,%d" % tuple(round(v) for v in value["to"])}
                if value.get("ms"):
                    sw["duration"] = int(value["ms"])
                return [("swipe", sw)]
            if value.get("direction") not in DIRECTION:
                raise base.StepFailed("step %d: swipe needs a direction or from and to" % index)
            return [("swipe", {"direction": DIRECTION[value["direction"]]})]
        if kind == "settle":
            timeout = int(float((value or {}).get("timeout") or self.SETTLE_TIMEOUT) * 1000) \
                if isinstance(value, dict) else int(self.SETTLE_TIMEOUT * 1000)
            return [("waitForAnimationToEnd", {"timeout": timeout})]
        raise base.StepSkipped("step %d: maestro can't do %s steps" % (index, kind))

    def write_flow(self, device, screen, locale, screenshot_name=None):
        """The YAML flow for a screen's steps (and a ``takeScreenshot`` when ``screenshot_name``)."""
        lines = [self.header(device)]
        for i, step in enumerate(screen.get("steps") or [], 1):
            for command, value in self.translate(device, screen, step, i):
                lines.append("- %s\n" % command if value is None else "- %s: %s\n" % (command, yaml_value(value)))
        if screenshot_name:
            lines.append("- takeScreenshot: %s\n" % yaml_value(screenshot_name))
        return "".join(lines)

    # -- a screen -----------------------------------------------------------------------------------------------

    def run_screen(self, device, screen, locale):
        """A screen with a ``flow`` step runs that flow; any other has its steps written as one (see the module)."""
        shot = base.Shot(source=self.source(device), status_bar="none")
        why = self.unsupported(screen, device)
        steps = screen.get("steps") or []
        flows = [s for s in steps if base.step_of(s)[0] == "flow"]
        if not why and flows and len(steps) != 1:
            why = "a maestro flow step runs alone (put the other steps in the flow)"
        if why:
            shot.status = "skipped"
            shot.reason = why
            return shot
        path = self.shot_path(device, screen, locale)
        try:
            self.enter_screen(device, screen, locale, shot)
            env = self.env_for(device, screen, locale)
            if flows:
                _, value = base.step_of(flows[0])
                spec = value if isinstance(value, dict) else {"file": value}
                if not spec.get("file"):
                    raise base.StepFailed("the flow step names no file")
                name = spec.get("screenshot") or screen["id"]
                env.update(dict((k, str(v)) for k, v in (spec.get("env") or {}).items()))
                base.LOG("  step 1: flow %s (screenshot %s)" % (spec["file"], name))
                found, code, tail = self.run_flow(device, self.path(spec["file"]), env,
                                                  cache_key=(locale, spec["file"], json.dumps(spec.get("env"), sort_keys=True)))
                if base.DRY_RUN:
                    shot.path = path
                    return shot
                pic = found.get(name)
                if not pic:
                    raise base.StepFailed("the flow took no screenshot named %s (it took: %s)%s" % (
                        name, ", ".join(sorted(found)) or "none",
                        "; maestro exited %s: %s" % (code, " / ".join(tail)) if code else ""))
                if code:
                    shot.warnings.append("maestro exited %s, but the screenshot is there" % code)
                shutil.copyfile(pic, path)
            else:
                use_host = self.use_host_screenshot(device)
                name = None if use_host else SCREENSHOT_PREFIX + screen["id"]
                text = self.write_flow(device, screen, locale, name)
                flow = os.path.join(self.options.workdir, "maestro", "%s-%s.yaml" % (locale, screen["id"]))
                base.LOG("  flow %s:\n%s" % (flow, "\n".join("    " + l for l in text.splitlines())))
                if not base.DRY_RUN:
                    os.makedirs(os.path.dirname(flow), exist_ok=True)
                    with open(flow, "w", encoding="utf-8") as f:
                        f.write(text)
                found, code, tail = self.run_flow(device, flow, env)
                if code and not base.DRY_RUN:
                    raise base.StepFailed("the flow failed (maestro exited %s): %s" % (code, " / ".join(tail)))
                if use_host:
                    self.host(device).screenshot(device, path)
                elif not base.DRY_RUN:
                    pic = found.get(name)
                    if not pic:
                        raise base.StepFailed("maestro left no screenshot %s" % name)
                    shutil.copyfile(pic, path)
        except base.StepSkipped as e:
            shot.status = "skipped"
            shot.reason = str(e)
            return shot
        except base.ToolMissing:
            raise
        except base.DriverError as e:
            shot.status = "missed"
            shot.reason = str(e)
            return shot
        shot.path = path
        shot.status_bar = self.status_bar
        return shot

    def agent_screenshot(self, device, path):
        """Without a host, a one-line flow that takes a screenshot (used by ``settle``)."""
        name = SCREENSHOT_PREFIX + "probe"
        flow = os.path.join(self.options.workdir, "maestro", "probe.yaml")
        if not base.DRY_RUN:
            os.makedirs(os.path.dirname(flow), exist_ok=True)
            with open(flow, "w", encoding="utf-8") as f:
                f.write(self.header(device) + "- takeScreenshot: %s\n" % yaml_value(name))
        found, code, tail = self.run_flow(device, flow, {})
        if base.DRY_RUN:
            return
        if not found.get(name):
            raise base.DriverError("maestro took no screenshot: %s" % " / ".join(tail))
        shutil.copyfile(found[name], path)


DRIVER = MaestroDriver
