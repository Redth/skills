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
On a simulator the session also gets its own WebDriverAgent port (``appium:wdaLocalPort``, 8130-8199) and MJPEG
port (``appium:mjpegServerPort``, 9130-9199), derived from the plan's device id, never WDA's 8100: another Appium
server's session on 8100 would otherwise answer ours for its own simulator. A port something else already listens
on is passed over (a WebDriverAgent is used only when its ``/status`` names our simulator); a port the plan sets is
kept as it is.
``DELETE /session/<id>`` in ``reset``. A session that fails is reported with its own cause; before the next
screen the simulator is booted again if the failure shut it down, and the session is tried once more.

Steps: ``launch`` (iOS/Mac ``mobile: launchApp`` with ``arguments``/``environment``; Android ``mobile:
startActivity`` with ``extras``), ``deepLink`` (``mobile: deepLink``), ``tap`` (find, then
``/element/<id>/click``), ``type`` (``/element/<id>/value``, or the focused element), ``wait`` (find until it
appears), ``scroll`` (iOS ``mobile: scroll``; Android ``mobile: scrollGesture``; ``to`` an element: scroll until
it's found), ``swipe`` (``mobile: swipe`` / ``mobile: swipeGesture``; ``from``/``to`` a W3C pointer drag, ``hold``
a ``pause`` after ``pointerDown``), ``back`` (``/back``), ``hideKeyboard``
(``mobile: isKeyboardShown``, then ``mobile: hideKeyboard``: on iOS with the keyboard's Done/Return keys, then a
Done button above it), ``posture`` (the host's). Finders: ``id`` (``accessibility id``; on Android ``id``, the
resource id, then ``accessibility id``), ``text`` and ``label`` (an iOS predicate, an Android or Windows XPath),
``xpath``. ``text`` and ``label`` match as every driver does: exactly, then ignoring case and surrounding space,
then contained (``==``, ``==[c]``, ``CONTAINS[c]`` on iOS and Mac; ``@text=``, ``translate()``, ``contains()`` on
Android and Windows). The keyboard is read with ``mobile: isKeyboardShown`` for ``verify``.

The device (boot, locale on the device, appearance, the clean status bar) is the host's (``hosted.py``); the
screenshot is the host's when there is one, else ``GET /session/<id>/screenshot`` (base64 PNG).
"""

from __future__ import annotations

import base64
import json
import xml.etree.ElementTree as ET
import zlib

from . import base
from .hosted import HostedDriver, type_target

W3C_ELEMENT = "element-6066-11e4-a52e-4f735466cecf"
DEFAULT_SERVER = "http://127.0.0.1:4723"
FAMILY = {"ios": "ios", "ipados": "ios", "tvos": "ios", "visionos": "ios", "watchos": "ios", "android": "android",
          "macos": "mac", "windows": "windows"}
AUTOMATION = {"ios": ("iOS", "XCUITest"), "android": ("Android", "UiAutomator2"), "mac": ("mac", "Mac2"),
              "windows": ("Windows", "Windows")}
TVOS = ("tvos",)

# An XCUITest session on a simulator: WebDriverAgent's port on this machine and its MJPEG stream's, one of each a
# plan device (from its id), never WDA's defaults (8100, 9100), which every other Appium server's sessions use.
WDA_PORTS = (8130, 8199)
MJPEG_PORTS = (9130, 9199)
WDA_PORT = "appium:wdaLocalPort"
MJPEG_PORT = "appium:mjpegServerPort"


def derived_port(device_id, ports):
    """The port in ``ports`` (``(first, last)``) the plan's ``device_id`` maps to: the same on every run and machine
    (a CRC-32 of the id, not Python's salted ``hash``)."""
    first, last = ports
    return first + zlib.crc32(str(device_id).encode("utf-8")) % (last - first + 1)


def status_udids(value):
    """Every string under a key that names a UDID (``udid``, ``deviceUDID``, …) at any depth of a ``/status`` reply,
    upper-cased."""
    out = set()
    if isinstance(value, dict):
        for k, v in value.items():
            if "udid" in str(k).lower() and isinstance(v, str) and v.strip():
                out.add(v.strip().upper())
            else:
                out |= status_udids(v)
    elif isinstance(value, list):
        for v in value:
            out |= status_udids(v)
    return out


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


UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LOWER = "abcdefghijklmnopqrstuvwxyz"
# iOS keyboard keys that close it, tried in order (XCUITest's mobile: hideKeyboard adds "done").
IOS_KEYBOARD_KEYS = ["Done", "done", "Return", "return", "Go", "Search", "Next"]


def ascii_lower(text):
    """``text`` with only A-Z lowered, as XPath 1.0's ``translate(…, UPPER, LOWER)`` lowers the other side."""
    return "".join(LOWER[UPPER.index(c)] if c in UPPER else c for c in str(text))


def predicates(fields, wanted):
    """iOS/Mac predicates for ``wanted`` on ``fields``: exact, then ignoring case (trimmed), then contained."""
    exact = " OR ".join("%s == %s" % (f, _pred(wanted)) for f in fields)
    trimmed = str(wanted).strip()
    nocase = " OR ".join("%s ==[c] %s" % (f, _pred(trimmed)) for f in fields)
    within = " OR ".join("%s CONTAINS[c] %s" % (f, _pred(trimmed)) for f in fields)
    return [("-ios predicate string", exact), ("-ios predicate string", nocase), ("-ios predicate string", within)]


def xpaths(attr, wanted):
    """XPaths for ``wanted`` in ``@attr``: exact, then ignoring (ASCII) case and surrounding space, then contained."""
    trimmed = ascii_lower(str(wanted).strip())
    folded = "translate(%s, '%s', '%s')" % ("normalize-space(@%s)" % attr, UPPER, LOWER)
    return [("xpath", "//*[@%s=%s]" % (attr, _lit(wanted))),
            ("xpath", "//*[%s=%s]" % (folded, _lit(trimmed))),
            ("xpath", "//*[contains(translate(@%s, '%s', '%s'), %s)]" % (attr, UPPER, LOWER, _lit(trimmed)))]


def source_elements(root, family):
    """Every node of a page source as a ``base.Element`` (with its node), its id and text read the way the
    family's Appium driver names them: Android's ``resource-id``, ``text`` and ``content-desc``; iOS's ``name``
    (the accessibility identifier), ``label`` and ``value``; a Mac's ``identifier`` and ``title``; Windows'
    ``AutomationId`` and ``Name``."""
    out = []
    for node in root.iter():
        a = node.attrib
        if family == "android":
            e = base.Element(id=a.get("resource-id"), text=a.get("text"), label=a.get("content-desc"),
                             bounds=base.parse_bounds(a.get("bounds", "")), attrs=a, node=node)
        elif family == "ios":
            e = base.Element(id=a.get("name"), text=a.get("label") or a.get("value"), label=a.get("label"),
                             attrs=a, node=node)
        elif family == "mac":
            e = base.Element(id=a.get("identifier"), text=a.get("title") or a.get("value") or a.get("label"),
                             label=a.get("label"), attrs=a, node=node)
        else:
            e = base.Element(id=a.get("AutomationId"), text=a.get("Name"), label=a.get("Name"), attrs=a, node=node)
        out.append(e)
    return out


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


# The names of the button an app shows to close the keyboard (an input accessory's, a floating one), looked for on
# iOS when the keyboard's own keys didn't close it (a number pad has none).
ACCESSORY_DONE = ("Done", "Close", "Hide keyboard", "Dismiss keyboard", "Return")


class AppiumDriver(HostedDriver):
    """Any app Appium reaches (see the module's docstring)."""

    NAME = "appium"
    PLATFORMS = ("ios", "ipados", "tvos", "android", "macos", "windows")
    STEPS = ("launch", "deepLink", "appFile", "tap", "type", "wait", "scroll", "back", "swipe", "settle", "script",
             "posture", "hideKeyboard", "fill", "unfocus")
    FINDERS = ("id", "text", "label", "xpath")
    SESSION_TIMEOUT = 600   # the first XCUITest session builds WebDriverAgent
    SCROLLS = 8             # scroll to an element: at most this many swipes

    def __init__(self, options=None):
        """Set up; no session until a locale is applied."""
        HostedDriver.__init__(self, options)
        self.session = None
        self.session_locale = None
        self.session_error = None
        self.ports = None         # the ports this driver chose for the device's sessions (once a run)
        self.session_ports = {}   # the WDA and MJPEG ports the last session asked for (the plan's or ours)

    def has_own_step(self, kind):
        return kind in ("launch", "deepLink", "hideKeyboard")

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
            hint = ""
            if err == "invalid session id" and self.family(device) == "ios":
                hint = " (the session is gone: if it had only just started, another simulator's WebDriverAgent " \
                       "may have answered on its port; see appium.md, running beside other Appium servers)"
            raise base.DriverError("Appium %s %s: %s%s%s" % (method, path, err or res.status,
                                                             (": " + str(msg).splitlines()[0]) if msg else "", hint))
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
                caps.update(self.wda_ports(device))
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
        self.session_ports = dict((k, caps[k]) for k in (WDA_PORT, MJPEG_PORT) if k in caps)
        value = self.wd(device, "POST", "/session", {"capabilities": {"alwaysMatch": caps, "firstMatch": [{}]}},
                        timeout=self.SESSION_TIMEOUT, dry_value={"sessionId": "dry-run", "capabilities": caps})
        sid = (value or {}).get("sessionId")
        if not sid:
            raise base.DriverError("Appium gave no session id")
        self.session = sid
        self.session_locale = locale

    # -- WebDriverAgent's ports ----------------------------------------------------------------------------

    def wda_ports(self, device):
        """``appium:wdaLocalPort`` and ``appium:mjpegServerPort`` for an XCUITest session on a simulator, chosen once
        a run: each the port the plan's device id maps to (``derived_port``; the same offset in both ranges), else
        the next one nothing else listens on. One the plan's ``target.capabilities`` sets is left to the plan (as is
        WDA's port when the plan gives ``appium:webDriverAgentUrl``). *Why:* XCUITest's default is 8100 for every
        session; with another Appium server's session on it for another simulator, our session's commands went to
        that simulator ("invalid session id" right after the session started)."""
        if self.ports is not None:
            return self.ports
        planned = (device.get("target") or {}).get("capabilities") or {}
        offset = derived_port(device.get("id", ""), WDA_PORTS) - WDA_PORTS[0]
        out = {}
        if WDA_PORT not in planned and "appium:webDriverAgentUrl" not in planned:
            out[WDA_PORT] = self.free_port(device, WDA_PORTS, offset, "WebDriverAgent", self.wda_port_taken)
        if MJPEG_PORT not in planned:
            out[MJPEG_PORT] = self.free_port(device, MJPEG_PORTS, offset, "the MJPEG stream", self.port_taken)
        self.ports = out
        if out:
            said = ", ".join("%s %d" % ("WebDriverAgent" if k == WDA_PORT else "MJPEG", v) for k, v in out.items())
            base.note("  this device's own ports (from its id, never WebDriverAgent's 8100): %s%s" % (
                said, " (a real run first checks nothing else listens on them)" if base.DRY_RUN else ""))
        return out

    def free_port(self, device, ports, offset, what, taken):
        """The first port in ``ports`` from ``offset`` on (wrapping) that ``taken`` has no reason against; one passed
        over is logged and kept in the device's warnings. Nothing is checked in a dry run."""
        first, last = ports
        size = last - first + 1
        passed = []
        for i in range(size):
            port = first + (offset + i) % size
            why = None if base.DRY_RUN else taken(device, port)
            if not why:
                if passed:
                    one = len(passed) == 1
                    msg = "%s's port%s %s %s taken (%s): using %d" % (
                        what, "" if one else "s", ", ".join(str(p) for p, _ in passed), "is" if one else "are",
                        passed[0][1] if one else "; ".join("%d: %s" % (p, w) for p, w in passed[:3]), port)
                    base.note("  " + msg)
                    self.warnings.append(msg)
                return port
            passed.append((port, why))
        raise base.DriverError("no free port for %s in %d-%d: %s (set %s in target.capabilities)" % (
            what, first, last, passed[0][1], WDA_PORT if what == "WebDriverAgent" else MJPEG_PORT))

    def port_taken(self, device, port):
        """Why ``port`` can't be this device's (something listens on it), or ``None``."""
        return "something else listens on it" if base.LISTENING(port) else None

    def wda_port_taken(self, device, port):
        """Why ``port`` can't be this device's WebDriverAgent port, or ``None``: free, or a WebDriverAgent whose
        ``GET /status`` names this device's simulator. Anything else listening (another simulator's WebDriverAgent,
        one that doesn't say which simulator it serves, another program) is a reason."""
        if not base.LISTENING(port):
            return None
        try:
            res = base.http("GET", "http://127.0.0.1:%d/status" % port, timeout=5)
            data = res.json() if res.body else None
        except (base.DriverError, ValueError):
            data = None
        if not isinstance(data, dict):
            return "something that isn't a WebDriverAgent listens on it"
        udids = status_udids(data)
        ours = str(self.device_ref(device) or "").strip().upper()
        if ours and ours in udids:
            return None
        if udids:
            return "the WebDriverAgent of another simulator (%s) listens on it" % ", ".join(sorted(udids))
        return "a WebDriverAgent or server that doesn't say which simulator it serves listens on it (another " \
               "Appium server's?)"

    def source(self, device):
        """The host's description of the device, plus the WebDriverAgent and MJPEG ports its sessions asked for
        (``wdaPort``, ``mjpegPort``)."""
        out = HostedDriver.source(self, device)
        if WDA_PORT in self.session_ports:
            out["wdaPort"] = self.session_ports[WDA_PORT]
        if MJPEG_PORT in self.session_ports:
            out["mjpegPort"] = self.session_ports[MJPEG_PORT]
        return out

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
        """``[(using, value), …]`` to try, in order, for a finder. ``text`` and ``label`` go from exact to ignoring
        case and surrounding space to contained, as the other drivers' finders do."""
        finder, wanted = query
        fam = self.family(device)
        if finder == "xpath":
            return [("xpath", wanted)]
        if finder == "id":
            if fam == "android":
                return [("id", wanted), ("accessibility id", wanted)]
            return [("accessibility id", wanted)]
        if fam == "ios":
            return predicates(["label"] if finder == "label" else ["label", "value", "name"], wanted)
        if fam == "mac":
            return predicates(["label"] if finder == "label" else ["title", "value", "label"], wanted)
        if fam == "android":
            if finder == "label":
                return [("accessibility id", wanted)] + xpaths("content-desc", wanted)[1:]
            return xpaths("text", wanted)
        return xpaths("Name", wanted)

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
        self.before_tap(ctx)
        if isinstance(value, dict) and "x" in value and "y" in value:
            self.pointer(ctx, [(value["x"], value["y"])], 0)
            return
        ref = self.ref(ctx, value)
        self.wd(ctx.device, "POST", self.sid() + "/element/%s/click" % ref)

    def pointer(self, ctx, points, ms, hold=0):
        """A touch through ``/actions``: down at the first point, held there ``hold`` ms (a ``pause``: a slider or a
        pan gesture then reads a drag, not a scroll), moved through the rest over ``ms``, up."""
        scale = float((ctx.device.get("target") or {}).get("pointScale") or 1)
        pts = [(int(round(x / scale)), int(round(y / scale))) for x, y in points]
        acts = [{"type": "pointerMove", "duration": 0, "x": pts[0][0], "y": pts[0][1]},
                {"type": "pointerDown", "button": 0}]
        if hold:
            acts.append({"type": "pause", "duration": int(hold)})
        elif len(pts) == 1:
            acts.append({"type": "pause", "duration": 80})
        for x, y in pts[1:]:
            acts.append({"type": "pointerMove", "duration": int(ms or 300), "x": x, "y": y})
        acts.append({"type": "pointerUp", "button": 0})
        self.wd(ctx.device, "POST", self.sid() + "/actions", {"actions": [
            {"type": "pointer", "id": "finger1", "parameters": {"pointerType": "touch"}, "actions": acts}]})
        self.wd(ctx.device, "DELETE", self.sid() + "/actions")

    TYPES_AT_A_RATE = True
    SCROLL_SWIPES = True

    def step_type(self, ctx, value):
        """``/element/<id>/value`` into the element beside ``text`` (``id``/``label``/``xpath``, or ``into``: the
        field showing that text), else into the focused one (``/element/active``). With ``rate`` (keys a second), one
        ``/element/<id>/value`` a character, paced: XCUITest and UiAutomator2 both add to what the field holds, so a
        recording shows each key land and the value appear a character at a time."""
        if isinstance(value, str):
            value = {"text": value}
        value = value or {}
        text = value.get("text")
        if text is None:
            raise base.StepFailed("step %d: type needs text" % ctx.index)
        rate = self.rate_of(ctx, value)
        target = type_target(value)
        if base.element_query(target):
            ref = self.ref(ctx, target)
        else:
            active = self.wd(ctx.device, "GET", self.sid() + "/element/active", dry_value={W3C_ELEMENT: "dry-run"})
            ref = (active or {}).get(W3C_ELEMENT) or (active or {}).get("ELEMENT")
            if not ref:
                raise base.StepFailed("step %d: nothing has focus to type into" % ctx.index)
        if rate:
            base.note("  typing %r key by key, %g a second" % (str(text), rate))
            for n, key in enumerate(str(text)):
                if n:
                    base.sleep(1.0 / rate)
                self.wd(ctx.device, "POST", self.sid() + "/element/%s/value" % ref, {"text": key})
            return
        self.wd(ctx.device, "POST", self.sid() + "/element/%s/value" % ref, {"text": str(text)})

    def editable(self, ctx, query, element):
        """The element's own type, else its tag name from the server (``GET /element/<id>/name``: XCUITest's
        ``XCUIElementTypeTextField``, UiAutomator2's ``android.widget.EditText``)."""
        if base.Driver.editable(self, ctx, query, element):
            return True
        ref = element.attrs.get("ref") if element is not None else None
        if not ref or base.DRY_RUN:
            return False
        name = self.wd(ctx.device, "GET", self.sid() + "/element/%s/name" % ref, ok_missing=True)
        return base.is_editable(name)

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

    def scroll_once(self, ctx, direction, within=None):
        """One scroll ``direction``, on ``within``'s element (a pane) or the window. iOS: a quick ``mobile: swipe`` the
        other way (the finger's), never ``mobile: scroll`` with a direction, which first presses half a second at a
        quarter of the window's width and height: when that lands on a text field it focuses it, and the keyboard
        just closed comes back while the page doesn't move. Android: ``mobile: scrollGesture``; a Mac: ``mobile:
        scroll``."""
        ref = within.attrs.get("ref") if within is not None else None
        if self.family(ctx.device) == "ios":
            self._gesture(ctx, "swipe", base.OPPOSITE[direction], ref)
            return
        self._gesture(ctx, "scroll", direction, ref)

    def scroll_pane(self, ctx, query, found):
        """The nearest view that is ``query``'s element or holds it and scrolls, read from the page source: Android's
        ``scrollable="true"``; iOS's and a Mac's ``XCUIElementTypeScrollView``, ``Table``, ``CollectionView`` (and
        a Mac's ``Outline``). An ancestor is found again by its path in the source (``POST /element``, xpath) for its
        element id. ``None`` on Windows, or when the source doesn't show the element."""
        fam = self.family(ctx.device)
        if fam == "windows":
            return None
        try:
            root = ET.fromstring(self.inspect_tree(ctx))
        except (ET.ParseError, TypeError, ValueError):
            return None
        hit = base.pane_in_tree(root, source_elements(root, fam), query)
        if hit is None:
            return None
        node, how = hit
        what = base.describe_node(node)
        if how != "ancestor":
            return found, how, what
        path = base.absolute_xpath(root, node)
        res = self.wd(ctx.device, "POST", self.sid() + "/element", {"using": "xpath", "value": path},
                      ok_missing=True)
        ref = (res.get(W3C_ELEMENT) or res.get("ELEMENT")) if isinstance(res, dict) else None
        if not ref:
            base.note("  the pane around %s (%s) wasn't found again by its path: scrolling the element itself"
                      % (base.describe_query(query), what))
            return None
        return base.Element(id=node.attrib.get("name") or node.attrib.get("resource-id"),
                            attrs={"ref": ref, "using": "xpath", "xpath": path}), how, what

    def scroll_fingerprint(self, ctx, within=None):
        """The page source (the elements' positions move as the content scrolls)."""
        if base.DRY_RUN:
            return None
        try:
            return self.inspect_tree(ctx)
        except base.DriverError:
            return None

    def step_swipe(self, ctx, value):
        """``from``/``to`` points (a W3C pointer drag over ``ms``, after a ``pause`` of ``hold`` ms with the finger
        down), or a ``direction`` on the window or an element."""
        if isinstance(value, str):
            value = {"direction": value}
        value = value or {}
        hold = self.swipe_hold(ctx, value)
        if value.get("from") and value.get("to"):
            self.pointer(ctx, [value["from"], value["to"]], value.get("ms"), hold)
            return
        if value.get("direction") not in ("up", "down", "left", "right"):
            raise base.StepFailed("step %d: swipe needs a direction (up, down, left, right) or from and to" % ctx.index)
        inner = dict((k, v) for k, v in value.items() if k in base.FINDER_KEYS)
        ref = self.ref(ctx, inner) if base.element_query(inner) else None
        self._gesture(ctx, "swipe", value["direction"], ref)

    def step_back(self, ctx, value):
        """``POST /back``."""
        self.wd(ctx.device, "POST", self.sid() + "/back")

    def keyboard_shown(self, ctx):
        """``mobile: isKeyboardShown`` (XCUITest, UiAutomator2); ``None`` on a Mac or Windows, or when it can't say."""
        if self.family(ctx.device) not in ("ios", "android") or base.DRY_RUN or not self.session:
            return None
        try:
            value = self.mobile(ctx.device, "isKeyboardShown", timeout=60)
        except base.DriverError:
            return None
        return value if isinstance(value, bool) else None

    def hide_keyboard(self, ctx, value):
        """The driver's own close, once: ``mobile: hideKeyboard`` (on iOS tapping the keyboard's own Done, Return, Go,
        Search or Next key). Never Appium's back: on iOS that's navigation. The base's ``close_keyboard`` looks at the
        keyboard after it and goes on to a Done button above the keyboard (``tap_accessory_done``), the plan's
        ``done`` and ``tap``, and a scroll."""
        fam = self.family(ctx.device)
        if fam not in ("ios", "android"):
            raise base.StepSkipped("step %d: %s apps have no on-screen keyboard to hide" % (ctx.index, fam))
        try:
            self.mobile(ctx.device, "hideKeyboard", {"keys": list(IOS_KEYBOARD_KEYS)} if fam == "ios" else {})
        except base.DriverError as e:
            raise base.StepFailed("mobile: hideKeyboard didn't: %s" % str(e)[:160]) from None

    def tap_accessory_done(self, ctx):
        """iOS: the app's own button that closes the keyboard (``ACCESSORY_DONE``: Done, Close, Hide keyboard…, an
        input accessory's or a floating one), tapped: a number pad has no Done or Return key, so ``mobile:
        hideKeyboard`` can't close it ("did not know how to dismiss the keyboard") and this is what does."""
        if self.family(ctx.device) != "ios":
            raise base.StepSkipped("only iOS keyboards carry an accessory bar Appium looks for")
        names = " OR ".join("name ==[c] %s OR label ==[c] %s" % (_pred(k), _pred(k)) for k in ACCESSORY_DONE)
        found = self.wd(ctx.device, "POST", self.sid() + "/element", {
            "using": "-ios predicate string", "value": "type == 'XCUIElementTypeButton' AND (%s)" % names},
            ok_missing=True)
        ref = (found or {}).get(W3C_ELEMENT) if isinstance(found, dict) else None
        if not ref:
            raise base.StepFailed("no Done or Return button above the keyboard")
        self.wd(ctx.device, "POST", self.sid() + "/element/%s/click" % ref)

    def inspect_tree(self, ctx):
        """The page source (``GET /session/<id>/source``: XCUITest's or UiAutomator2's XML), for writing steps."""
        return self.wd(ctx.device, "GET", self.sid() + "/source", timeout=120, dry_value="") or ""

    def find_containing(self, ctx, query, wanted):
        """An element ``query`` finds that shows ``wanted``, read from the page source once: the element's own
        label or value (iOS), text or content-desc (Android), title (Mac), Name (Windows), or a descendant's. The
        source is the XML Appium's own xpath runs over, so a plan's xpath finds the same elements."""
        if base.DRY_RUN:
            return self.find(ctx, query)
        xml = self.inspect_tree(ctx)
        try:
            root = ET.fromstring(xml)
        except (ET.ParseError, TypeError, ValueError):
            return base.Driver.find_containing(self, ctx, query, wanted)
        return base.first_containing(root, source_elements(root, self.family(ctx.device)), query, wanted)

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
