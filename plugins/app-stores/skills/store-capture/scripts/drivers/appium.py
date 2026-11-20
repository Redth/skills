"""The ``appium`` driver: W3C WebDriver JSON over HTTP to a local Appium 2/3 server, with no client library.

Sessions: iOS/iPadOS/tvOS through the XCUITest driver, Android through UiAutomator2, Mac apps through Mac2,
Windows apps through the Windows driver (``appium driver install xcuitest|uiautomator2|mac2|windows``). Start the
server yourself (``appium``, ``http://127.0.0.1:4723`` by default); this driver never starts or reaches a remote
one (``target.server`` must be this machine).

One session a locale (the language is a session capability): ``POST /session`` with ``platformName``,
``appium:automationName``, the device (``appium:udid``: the host's simulator or emulator), the app
(``appium:bundleId`` / ``appium:appPackage`` + ``appium:appActivity`` / ``appium:app``), ``appium:language`` and
``appium:locale`` (Mac2: ``appium:appLocale``), the seed as a launch argument (``appium:processArguments`` on iOS,
``appium:optionalIntentArguments`` on Android, ``appium:arguments`` on a Mac), ``appium:noReset``, and on a
simulator ``appium:isHeadless`` (we capture through ``simctl io``, so no Simulator window is needed, and Xcode 27
moved Simulator.app where XCUITest's driver can't open it); anything in ``target.capabilities`` is added as is.
``DELETE /session/<id>`` in ``reset``. A session that fails is reported with its own cause; before the next
screen the simulator is booted again if the failure shut it down, and the session is tried once more.

Steps: ``launch`` (iOS/Mac ``mobile: launchApp`` with ``arguments``/``environment``; Android ``mobile:
startActivity`` with ``extras``), ``deepLink`` (``mobile: deepLink``), ``tap`` (find, then
``/element/<id>/click``), ``type`` (``/element/<id>/value``, or the focused element), ``wait`` (find until it
appears), ``scroll`` (iOS ``mobile: scroll``; Android ``mobile: scrollGesture``; ``to`` an element: scroll until
it's found), ``swipe`` (``mobile: swipe`` / ``mobile: swipeGesture``), ``back`` (``/back``). Finders: ``id``
(``accessibility id``; on Android ``id``, the resource id, then ``accessibility id``), ``text`` and ``label``
(an iOS predicate, an Android or Windows XPath), ``xpath``.

The device (boot, locale on the device, appearance, the clean status bar) is the host's (``hosted.py``); the
screenshot is the host's when there is one, else ``GET /session/<id>/screenshot`` (base64 PNG).
"""

from __future__ import annotations

import base64
import json

from . import base
from .hosted import HostedDriver, type_target

W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
DEFAULT_SERVER = "http://127.0.0.1:4723"
FAMILY = {"ios": "ios", "ipados": "ios", "tvos": "ios", "visionos": "ios", "watchos": "ios", "android": "android",
          "macos": "mac", "windows": "windows"}
AUTOMATION = {"ios": ("iOS", "XCUITest"), "android": ("Android", "UiAutomator2"), "mac": ("mac", "Mac2"),
              "windows": ("Windows", "Windows")}
TVOS = ("tvos",)


def _lit(text):
    """A string as an XPath/predicate literal (single quotes, or concat() when it has both kinds)."""
    text = str(text)
    if "'" not in text:
        return "'%s'" % text
    if '"' not in text:
        return '"%s"' % text
    return "concat(%s)" % ", \"'\", ".join("'%s'" % p for p in text.split("'"))


def _pred(text):
    """A string as an NSPredicate literal (double quotes, escaped)."""
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def language_of(locale):
    """``de-DE`` → ``de``; ``zh-Hans`` → ``zh-Hans``."""
    parts = locale.split("-")
    if len(parts) > 1 and len(parts[1]) == 4:
        return "-".join(parts[:2])
    return parts[0]


def region_of(locale):
    """``de-DE`` → ``DE`` (``None`` without one)."""
    for p in locale.split("-")[1:]:
        if len(p) == 2:
            return p.upper()
    return None


def session_hint(message):
    """A failed session's message, with what to do for the causes seen before."""
    if "Simulator.app" in message and "does not exist" in message:
        return message + " (Xcode moved Simulator.app: set \"appium:isHeadless\": true in target.capabilities; it's " \
                         "the default on simulators, so check target.capabilities doesn't turn it off)"
    if "xcodebuild failed" in message or "WebDriverAgent" in message:
        return message + " (WebDriverAgent didn't build or start: `appium driver doctor xcuitest`, and allow the " \
                         "first session minutes: appium:wdaLaunchTimeout)"
    return message


class AppiumDriver(HostedDriver):
    """Any app Appium reaches (see the module's docstring)."""

    NAME = "appium"
    PLATFORMS = ("ios", "ipados", "tvos", "android", "macos", "windows")
    STEPS = ("launch", "deepLink", "appFile", "tap", "type", "wait", "scroll", "back", "swipe", "settle", "script")
    FINDERS = ("id", "text", "label", "xpath")
    SESSION_TIMEOUT = 600   # the first XCUITest session builds WebDriverAgent
    SCROLLS = 8             # scroll to an element: at most this many swipes

    def __init__(self, options=None):
        """Set up; no session until a locale is applied."""
        HostedDriver.__init__(self, options)
        self.session = None
        self.session_locale = None
        self.session_error = None

    def has_own_step(self, kind):
        return kind in ("launch", "deepLink")

    # -- the server ---------------------------------------------------------------------------------------

    def server(self, device):
        """The Appium server's URL (``target.server``; this machine only)."""
        url = ((device.get("target") or {}).get("server") or DEFAULT_SERVER).rstrip("/")
        base.check_local(url)
        return url

    def family(self, device):
        """``ios``, ``android``, ``mac`` or ``windows``."""
        return FAMILY.get(device.get("platform"), "ios")

    def wd(self, device, method, path, body=None, timeout=60, ok_missing=False, dry_value=None):
        """One WebDriver command; its ``value`` returned. A W3C error is ``DriverError`` (``no such element``
        returns ``None`` with ``ok_missing``)."""
        url = self.server(device) + path
        if body is None and method == "POST":
            body = {}
        res = base.http(method, url, body=body, timeout=timeout,
                        dry_body=json.dumps({"value": dry_value}).encode("utf-8"))
        try:
            data = res.json() if res.body else {}
        except ValueError:
            raise base.DriverError("%s %s: Appium's reply isn't JSON: %s" % (method, path, res.text()[:200])) from None
        value = (data or {}).get("value") if isinstance(data, dict) else None
        if res.status >= 400 or (isinstance(value, dict) and value.get("error")):
            err = value.get("error") if isinstance(value, dict) else None
            if ok_missing and err in ("no such element", "stale element reference"):
                return None
            msg = value.get("message") if isinstance(value, dict) else res.text()[:300]
            raise base.DriverError("Appium %s %s: %s%s" % (method, path, err or res.status,
                                                           (": " + str(msg).splitlines()[0]) if msg else ""))
        return value

    def sid(self):
        if not self.session:
            raise base.DriverError("no Appium session (the locale wasn't applied)")
        return "/session/%s" % self.session

    def mobile(self, device, script, args=None, timeout=120):
        """``mobile: <script>`` through ``/execute/sync``."""
        return self.wd(device, "POST", self.sid() + "/execute/sync",
                       {"script": "mobile: " + script, "args": [args or {}]}, timeout=timeout)

    # -- capabilities ---------------------------------------------------------------------------------------

    def launch_arguments(self, device, args=None, locale=None):
        """The seed and ``args`` as ``["-Key", "value", …]`` (iOS and Mac launch arguments)."""
        out = []
        seed = device.get("seed")
        if seed is not None and "ScreenshotSeed" not in (args or {}):
            out += ["-ScreenshotSeed", str(seed)]
        for k, v in (args or {}).items():
            if isinstance(v, bool):
                v = "YES" if v else "NO"
            out += ["-" + k, str(v)]
        return out

    def extras(self, device, args=None):
        """The seed and ``args`` as UiAutomator2's ``extras`` (``[["s", key, value], …]``; booleans ``z``)."""
        out = []
        seed = device.get("seed")
        values = {}
        if seed is not None:
            values["ScreenshotSeed"] = seed
        values.update(args or {})
        for k, v in values.items():
            if isinstance(v, bool):
                out.append(["z", k, "true" if v else "false"])
            elif isinstance(v, int):
                out.append(["i", k, str(v)])
            else:
                out.append(["s", k, str(v)])
        return out

    def capabilities_for(self, device, locale):
        """The session's capabilities for ``device`` in ``locale``."""
        fam = self.family(device)
        app = device.get("app") or {}
        t = device.get("target") or {}
        platform_name, automation = AUTOMATION[fam]
        caps = {"platformName": platform_name, "appium:automationName": automation,
                "appium:newCommandTimeout": 600}
        ref = self.device_ref(device) or t.get("udid") or t.get("serial")
        lang, region = language_of(locale), region_of(locale)
        if fam == "ios":
            if device.get("platform") in TVOS:
                caps["platformName"] = "tvOS"
            if ref:
                caps["appium:udid"] = ref
            if app.get("bundleId"):
                caps["appium:bundleId"] = app["bundleId"]
            elif app.get("app"):
                caps["appium:app"] = self.path(app["app"])
            caps["appium:language"] = lang
            caps["appium:locale"] = "%s_%s" % (lang, region) if region else lang
            caps["appium:processArguments"] = {"args": self.launch_arguments(device)}
            caps["appium:noReset"] = True
            if self.host_name(device) == "simctl":
                caps["appium:isHeadless"] = True
        elif fam == "android":
            if ref:
                caps["appium:udid"] = ref
            if app.get("package"):
                caps["appium:appPackage"] = app["package"]
                if app.get("activity"):
                    caps["appium:appActivity"] = app["activity"]
            elif app.get("apk"):
                caps["appium:app"] = self.path(app["apk"])
            caps["appium:language"] = lang
            if region:
                caps["appium:locale"] = region
            seed = device.get("seed")
            if seed is not None:
                caps["appium:optionalIntentArguments"] = "--es ScreenshotSeed %s" % json.dumps(str(seed))
            caps["appium:noReset"] = True
        elif fam == "mac":
            if app.get("bundleId"):
                caps["appium:bundleId"] = app["bundleId"]
            elif app.get("app"):
                caps["appium:appPath"] = self.path(app["app"])
            caps["appium:arguments"] = self.launch_arguments(device)
            caps["appium:appLocale"] = {"language": lang, "locale": "%s_%s" % (lang, region) if region else lang}
        else:
            if app.get("app"):
                caps["appium:app"] = app["app"]
            caps["appium:appArguments"] = " ".join(self.launch_arguments(device))
        caps.update(t.get("capabilities") or {})
        return caps

    def start_session(self, device, locale):
        """``POST /session`` for ``locale`` (quitting the one before)."""
        self.quit_session(device)
        caps = self.capabilities_for(device, locale)
        value = self.wd(device, "POST", "/session", {"capabilities": {"alwaysMatch": caps, "firstMatch": [{}]}},
                        timeout=self.SESSION_TIMEOUT, dry_value={"sessionId": "dry-run", "capabilities": caps})
        sid = (value or {}).get("sessionId")
        if not sid:
            raise base.DriverError("Appium gave no session id")
        self.session = sid
        self.session_locale = locale

    def quit_session(self, device):
        """``DELETE /session/<id>`` (errors ignored)."""
        if self.session:
            try:
                self.wd(device, "DELETE", "/session/%s" % self.session, timeout=60)
            except base.DriverError:
                pass
            self.session = None
            self.session_locale = None

    # -- the four calls -----------------------------------------------------------------------------------

    def prepare_app(self, device, plan):
        """Check the server answers (``GET /status``)."""
        self.server(device)
        try:
            self.wd(device, "GET", "/status", timeout=15, dry_value={"ready": True})
        except base.DriverError as e:
            raise base.DriverError("no Appium server at %s (start it with `appium`): %s" % (
                self.server(device), e)) from None

    def apply_locale(self, device, locale, shot):
        """The host's locale, then a session in it. After a failed session the simulator is booted again if it
        was shut down (the XCUITest driver can leave it so), and a session that fails is tried once more after
        that; what's reported is the session's own error, not what it left behind."""
        h = self.host(device)
        rebootable = h is not None and hasattr(h, "ensure_booted")
        if self.session_error and rebootable and h.ensure_booted():
            shot.warnings.append("the simulator was shut down after the earlier failed Appium session: booted again")
        try:
            HostedDriver.apply_locale(self, device, locale, shot)
        except base.DriverError as e:
            if self.session_error:
                raise base.DriverError("%s (after an earlier failed Appium session: %s)" % (e, self.session_error)) \
                    from None
            raise
        try:
            self.start_session(device, locale)
        except base.DriverError as e:
            error = e
            if rebootable and h.ensure_booted():
                self.state.pop("statusBar", None)
                try:
                    self.start_session(device, locale)
                    self.session_error = None
                    return
                except base.DriverError as again:
                    error = again
            self.session_error = session_hint(str(error))
            raise base.DriverError("Appium couldn't start a session: %s" % self.session_error) from None
        self.session_error = None

    def reset_app(self, device):
        """End the session."""
        self.quit_session(device)
        return []

    # -- finding --------------------------------------------------------------------------------------------

    def strategies(self, device, query):
        """``[(using, value), …]`` to try, in order, for a finder."""
        finder, wanted = query
        fam = self.family(device)
        if finder == "xpath":
            return [("xpath", wanted)]
        if finder == "id":
            if fam == "android":
                return [("id", wanted), ("accessibility id", wanted)]
            return [("accessibility id", wanted)]
        if fam == "ios":
            if finder == "label":
                return [("-ios predicate string", "label == %s" % _pred(wanted))]
            return [("-ios predicate string", "label == %s OR value == %s OR name == %s" % (
                _pred(wanted), _pred(wanted), _pred(wanted)))]
        if fam == "mac":
            if finder == "label":
                return [("-ios predicate string", "label == %s" % _pred(wanted))]
            return [("-ios predicate string", "title == %s OR value == %s OR label == %s" % (
                _pred(wanted), _pred(wanted), _pred(wanted)))]
        if fam == "android":
            if finder == "label":
                return [("accessibility id", wanted)]
            return [("xpath", "//*[@text=%s]" % _lit(wanted))]
        return [("xpath", "//*[@Name=%s]" % _lit(wanted))]

    def find(self, ctx, query):
        """The element ``query`` finds now (``POST /element``), as a ``base.Element`` whose ``attrs["ref"]`` is
        the WebDriver element id; ``None`` when there's none."""
        for using, value in self.strategies(ctx.device, query):
            found = self.wd(ctx.device, "POST", self.sid() + "/element", {"using": using, "value": value},
                            ok_missing=True, dry_value={W3C_ELEMENT: "dry-run"})
            if isinstance(found, dict):
                ref = found.get(W3C_ELEMENT) or found.get("ELEMENT")
                if ref:
                    return base.Element(id=str(query[1]), attrs={"ref": ref, "using": using})
        return None

    def ref(self, ctx, value, timeout=None):
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: name an element (id, text, label or xpath)" % ctx.index)
        return self.wait_for(ctx, query, timeout).attrs["ref"]

    # -- steps ------------------------------------------------------------------------------------------------

    def step_launch(self, ctx, value):
        """Relaunch the app with the seed and ``args`` (and ``env`` on iOS/Mac); ``clean`` clears Android's data."""
        value = value or {}
        fam = self.family(ctx.device)
        app = ctx.device.get("app") or {}
        if fam in ("ios", "mac"):
            bundle = app.get("bundleId")
            if not bundle:
                raise base.StepFailed("step %d: launch needs app.%s.bundleId" % (ctx.index, ctx.device["platform"]))
            if value.get("clean"):
                ctx.warn("launch clean: Appium can't clear an iOS app's data; reinstall it (simctl host) instead")
            self.mobile(ctx.device, "terminateApp", {"bundleId": bundle})
            args = {"bundleId": bundle, "arguments": self.launch_arguments(ctx.device, value.get("args"))}
            if value.get("env"):
                args["environment"] = dict((k, str(v)) for k, v in value["env"].items())
            self.mobile(ctx.device, "launchApp", args)
        elif fam == "android":
            package = app.get("package")
            if not package:
                raise base.StepFailed("step %d: launch needs app.android.package" % ctx.index)
            if value.get("clean"):
                self.mobile(ctx.device, "clearApp", {"appId": package})
            activity = app.get("activity") or ""
            component = "%s/%s" % (package, activity) if activity else None
            args = {"stop": True, "wait": True, "extras": self.extras(ctx.device, value.get("args"))}
            if component:
                args["component"] = component
            else:
                args["package"] = package
            self.mobile(ctx.device, "startActivity", args)
        else:
            raise base.StepSkipped("step %d: launch on Windows is the session's (it starts the app)" % ctx.index)

    def step_deepLink(self, ctx, value):
        """``mobile: deepLink`` with the app's bundle id or package."""
        url = value.get("url") if isinstance(value, dict) else value
        fam = self.family(ctx.device)
        app = ctx.device.get("app") or {}
        if fam == "ios":
            args = {"url": url}
            if app.get("bundleId"):
                args["bundleId"] = app["bundleId"]
        elif fam == "android":
            args = {"url": url, "package": app.get("package")}
        else:
            self.host_step(ctx, "deepLink", value)
            return
        self.mobile(ctx.device, "deepLink", args)

    def step_tap(self, ctx, value):
        """Find the element, then ``/element/<id>/click``; a point (``x``, ``y`` in the screenshot's pixels,
        ``target.pointScale`` to convert to the session's points) is a W3C pointer tap."""
        if isinstance(value, dict) and "x" in value and "y" in value:
            self.pointer(ctx, [(value["x"], value["y"])], 0)
            return
        ref = self.ref(ctx, value)
        self.wd(ctx.device, "POST", self.sid() + "/element/%s/click" % ref)

    def pointer(self, ctx, points, ms):
        """A touch through ``/actions``: down at the first point, moved through the rest over ``ms``, up."""
        scale = float((ctx.device.get("target") or {}).get("pointScale") or 1)
        pts = [(int(round(x / scale)), int(round(y / scale))) for x, y in points]
        acts = [{"type": "pointerMove", "duration": 0, "x": pts[0][0], "y": pts[0][1]},
                {"type": "pointerDown", "button": 0}]
        if len(pts) == 1:
            acts.append({"type": "pause", "duration": 80})
        for x, y in pts[1:]:
            acts.append({"type": "pointerMove", "duration": int(ms or 300), "x": x, "y": y})
        acts.append({"type": "pointerUp", "button": 0})
        self.wd(ctx.device, "POST", self.sid() + "/actions", {"actions": [
            {"type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"}, "actions": acts}]})
        self.wd(ctx.device, "DELETE", self.sid() + "/actions")

    def step_type(self, ctx, value):
        """``/element/<id>/value`` into the element beside ``text`` (``id``/``label``/``xpath``, or ``into``: the
        field showing that text), else into the focused one (``/element/active``)."""
        if isinstance(value, str):
            value = {"text": value}
        value = value or {}
        text = value.get("text")
        if text is None:
            raise base.StepFailed("step %d: type needs text" % ctx.index)
        target = type_target(value)
        if base.element_query(target):
            ref = self.ref(ctx, target)
        else:
            active = self.wd(ctx.device, "GET", self.sid() + "/element/active", dry_value={W3C_ELEMENT: "dry-run"})
            ref = (active or {}).get(W3C_ELEMENT) or (active or {}).get("ELEMENT")
            if not ref:
                raise base.StepFailed("step %d: nothing has focus to type into" % ctx.index)
        self.wd(ctx.device, "POST", self.sid() + "/element/%s/value" % ref, {"text": str(text)})

    def window(self, ctx):
        """The window's rectangle (``/window/rect``) as ``(left, top, width, height)``."""
        r = self.wd(ctx.device, "GET", self.sid() + "/window/rect",
                    dry_value={"x": 0, "y": 0, "width": 400, "height": 800}) or {}
        return int(r.get("x", 0)), int(r.get("y", 0)), int(r.get("width", 0)), int(r.get("height", 0))

    def _gesture(self, ctx, kind, direction, ref=None, percent=0.75):
        fam = self.family(ctx.device)
        if fam in ("ios", "mac"):
            args = {"direction": direction}
            if ref:
                args["elementId"] = ref
            self.mobile(ctx.device, "scroll" if kind == "scroll" else "swipe", args)
            return
        if fam != "android":
            raise base.StepSkipped("step %d: %s on Windows isn't supported by this driver" % (ctx.index, kind))
        args = {"direction": direction, "percent": percent}
        if ref:
            args["elementId"] = ref
        else:
            left, top, width, height = self.window(ctx)
            args.update({"left": left + width // 10, "top": top + height // 5, "width": width * 8 // 10,
                         "height": height * 3 // 5})
        self.mobile(ctx.device, "scrollGesture" if kind == "scroll" else "swipeGesture", args)

    def step_scroll(self, ctx, value):
        """``direction`` (default down), ``times`` times; ``to`` an element: scroll until it's there (at most
        ``times``, default ``SCROLLS``)."""
        if isinstance(value, str):
            value = {"direction": value}
        value = value or {}
        to = value.get("to")
        if to:
            query = base.element_query(to)
            if query is None:
                raise base.StepFailed("step %d: scroll to needs an element" % ctx.index)
            most = int(value.get("times") or self.SCROLLS)
            for _ in range(most):
                if self.find(ctx, query):
                    return
                self._gesture(ctx, "scroll", value.get("direction", "down"))
            if not self.find(ctx, query):
                raise base.StepFailed("step %d: %s %r not found after %d scrolls" % (ctx.index, query[0], query[1], most))
            return
        for _ in range(int(value.get("times") or 1)):
            self._gesture(ctx, "scroll", value.get("direction", "down"))

    def step_swipe(self, ctx, value):
        """``from``/``to`` points (a W3C pointer drag over ``ms``), or a ``direction`` on the window or an element."""
        if isinstance(value, str):
            value = {"direction": value}
        value = value or {}
        if value.get("from") and value.get("to"):
            self.pointer(ctx, [value["from"], value["to"]], value.get("ms"))
            return
        if value.get("direction") not in ("up", "down", "left", "right"):
            raise base.StepFailed("step %d: swipe needs a direction (up, down, left, right) or from and to" % ctx.index)
        inner = dict((k, v) for k, v in value.items() if k in base.FINDER_KEYS)
        ref = self.ref(ctx, inner) if base.element_query(inner) else None
        self._gesture(ctx, "swipe", value["direction"], ref)

    def step_back(self, ctx, value):
        """``POST /back``."""
        self.wd(ctx.device, "POST", self.sid() + "/back")

    def inspect_tree(self, ctx):
        """The page source (``GET /session/<id>/source``: XCUITest's or UiAutomator2's XML), for writing steps."""
        return self.wd(ctx.device, "GET", self.sid() + "/source", timeout=120, dry_value="") or ""

    def agent_screenshot(self, device, path):
        """``GET /session/<id>/screenshot``: a base64 PNG at the device's pixels."""
        data = self.wd(device, "GET", self.sid() + "/screenshot", timeout=120, dry_value="")
        if base.DRY_RUN:
            return
        try:
            raw = base64.b64decode(data or "")
        except (TypeError, ValueError):
            raise base.DriverError("Appium's screenshot isn't base64") from None
        if not raw.startswith(b"\x89PNG"):
            raise base.DriverError("Appium's screenshot isn't a PNG")
        with open(path, "wb") as f:
            f.write(raw)


DRIVER = AppiumDriver
