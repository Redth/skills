"""The ``chrome`` driver: web apps and PWAs in headless Chrome (the shared ``appstores_lib.chrome`` client).

The page is laid out at ``width/scale`` x ``height/scale`` CSS pixels with a device scale factor of ``scale``, so
the picture is exactly the device's size: ``target.scale`` (default 1), or ``target.viewport: [w, h]`` CSS px,
which sets the scale from the width. ``target.mobile`` (default true for phone and tablet platforms) turns on a
mobile viewport and touch. ``target.reducedMotion`` (default true) asks the page for reduced motion.

- ``launch`` opens the app's URL (``app.web.url``, or the device's ``app.url``; a path is a file next to the plan) with ``ScreenshotSeed`` and the
  screen's ``args`` as query parameters; ``clean`` clears the origin's storage first. ``url`` and ``deepLink``
  open a URL (relative ones against the app's).
- ``tap``, ``type``, ``wait``, ``scroll`` find elements with ``Runtime.evaluate``: ``css`` (a selector), ``id``
  (``data-testid``, then the ``id`` attribute), ``text`` (an element's visible text), ``label`` (``aria-label``,
  ``alt``, ``title``) or ``xpath``. A tap is a real mouse press at the element's middle; typing is
  ``Input.insertText``. ``back`` is ``history.back()``.
- The locale goes to ``Emulation.setLocaleOverride`` and the ``Accept-Language`` / ``navigator.language``; the
  appearance to ``prefers-color-scheme``. There's no status bar.

Only this machine's pages: ``http(s)`` to ``localhost``/``127.0.0.1``, ``file:`` and ``data:`` URLs (anything else
is refused: drivers reach nothing on the internet).
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse

from . import base

from appstores_lib import chrome as chrome_lib  # noqa: E402

CHROME_FACTORY = chrome_lib.Chrome   # tests replace it with a fake that records DevTools calls
MOBILE_PLATFORMS = ("ios", "ipados", "android")

FIND_JS = r"""
(function (q) {
  function visible(e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }
  function own(e) { return (e.innerText || e.value || e.placeholder || "").trim(); }
  function norm(t) { return String(t).replace(/\s+/g, " ").trim().toLowerCase(); }
  function shows(e) {
    if (q.contains === undefined || q.contains === null) return true;
    var w = norm(q.contains);
    return [e.innerText, e.textContent, e.value, e.getAttribute && e.getAttribute("aria-label"),
            e.getAttribute && e.getAttribute("title"), e.getAttribute && e.getAttribute("alt")].some(function (t) {
      return t !== undefined && t !== null && norm(t).indexOf(w) >= 0; });
  }
  function list(nodes) { return Array.prototype.slice.call(nodes || []); }
  var el = null, all, cands = [];
  if (q.finder === "css") cands = list(document.querySelectorAll(q.value));
  else if (q.finder === "id") {
    var v = CSS.escape(q.value);
    cands = list(document.querySelectorAll('[data-testid="' + v + '"]')).concat(
      [document.getElementById(q.value)], list(document.querySelectorAll('[data-test-id="' + v + '"],[data-test="' + v + '"]')));
  } else if (q.finder === "xpath") {
    var snap = document.evaluate(q.value, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    for (var k = 0; k < snap.snapshotLength; k++) cands.push(snap.snapshotItem(k));
  } else if (q.finder === "label") {
    all = list(document.querySelectorAll("[aria-label],[alt],[title]")).filter(visible);
    cands = all.filter(function (e) { return [e.getAttribute("aria-label"), e.getAttribute("alt"),
      e.getAttribute("title")].indexOf(q.value) >= 0; });
  } else if (q.finder === "text") {
    all = list(document.body ? document.body.querySelectorAll("*") : []).filter(visible);
    var want = q.value.trim(), lower = want.toLowerCase();
    var tests = [function (t) { return t === want; }, function (t) { return t.toLowerCase() === lower; },
                 function (t) { return t.toLowerCase().indexOf(lower) >= 0; }];
    for (var i = 0; i < tests.length && !cands.length; i++) {
      var hits = all.filter(function (e) { return tests[i](own(e)) && shows(e); });
      cands = hits.filter(function (e) { return !hits.some(function (o) { return o !== e && e.contains(o); }); });
    }
  }
  el = cands.filter(function (e) { return e && shows(e); })[0] || null;
  if (!el) return null;
  if (q.scroll) el.scrollIntoView({block: "center", inline: "center"});
  if (q.scrollBy) el.scrollBy(q.scrollBy[0] * el.clientWidth, q.scrollBy[1] * el.clientHeight);
  if (q.edge === "top") el.scrollTop = 0;
  if (q.edge === "bottom") el.scrollTop = el.scrollHeight;
  if (q.focus && el.focus) el.focus();
  var r = el.getBoundingClientRect();
  return {x: r.left + r.width / 2, y: r.top + r.height / 2, width: r.width, height: r.height};
})
"""


def local_url(url):
    """Raise ``NotLocal`` unless ``url`` is this machine's (``localhost``/``127.0.0.1``, ``file:``, ``data:``,
    ``about:``)."""
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme in ("file", "data", "about"):
        return url
    base.check_local(url)
    return url


def with_query(url, params):
    """``url`` with ``params`` added to its query string."""
    if not params:
        return url
    parts = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    for k, v in params.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        query.append((k, str(v)))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))

# The text field that has the focus (an input, a textarea, something contenteditable), and taking it away.
FOCUSED_JS = r"""
(function (blur) {
  var a = document.activeElement;
  if (!a || a === document.body || a === document.documentElement) return null;
  var typing = /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) || a.isContentEditable;
  if (!typing) return null;
  var r = {id: a.id || a.getAttribute("data-testid") || a.getAttribute("name") || "", tag: a.tagName};
  if (blur) a.blur();
  return r;
})
"""


class ChromeDriver(base.Driver):
    """Web pages in headless Chrome (see the module's docstring)."""

    NAME = "chrome"
    PLATFORMS = ()   # any: a web app captured at any device's size
    STEPS = ("launch", "url", "deepLink", "tap", "type", "wait", "scroll", "back", "settle", "script", "fill",
             "unfocus")
    FINDERS = ("css", "id", "text", "label", "xpath")
    LOAD_TIMEOUT = 60

    def __init__(self, options=None):
        """Set up; Chrome starts in ``prepare``."""
        base.Driver.__init__(self, options)
        self.browser = None
        self.target = None
        self.session = None
        self.scale = 1.0
        self.app_url = None
        self.user_agent = ""
        self.info = {}

    # -- DevTools -------------------------------------------------------------------------------------------

    def cdp(self, method, params=None, timeout=30):
        """Send one DevTools command to the page (logged; under ``--dry-run`` only logged)."""
        base.LOG("  cdp %s %s" % (method, json.dumps(params or {}, sort_keys=True)[:200]))
        if base.DRY_RUN:
            return {}
        try:
            return self.browser.call(method, params or {}, session_id=self.session, timeout=timeout)
        except chrome_lib.ChromeError as e:
            raise base.DriverError("Chrome: %s" % e) from None

    def evaluate(self, expression, timeout=30, dry=None):
        """Evaluate JavaScript in the page and return its value (promises awaited)."""
        if base.DRY_RUN:
            base.LOG("  cdp Runtime.evaluate %s" % expression.strip().splitlines()[-1][:120])
            return dry
        res = self.browser.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                                     "returnByValue": True}, session_id=self.session, timeout=timeout)
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            raise base.StepFailed("the page threw: %s" % ((d.get("exception") or {}).get("description")
                                                          or d.get("text") or "an exception"))
        return (res.get("result") or {}).get("value")

    def navigate(self, url):
        """Open ``url`` and wait for its load event, its fonts and two frames."""
        url = local_url(url)
        nav = self.cdp("Page.navigate", {"url": url}, timeout=self.LOAD_TIMEOUT)
        if base.DRY_RUN:
            return
        if nav.get("errorText"):
            raise base.StepFailed("couldn't open %s: %s" % (url, nav["errorText"]))
        loader = nav.get("loaderId")
        if loader:
            try:
                self.browser.wait_event("Page.lifecycleEvent", session_id=self.session,
                                        predicate=lambda p: p.get("loaderId") == loader and p.get("name") == "load",
                                        timeout=self.LOAD_TIMEOUT)
            except chrome_lib.ChromeError as e:
                raise base.StepFailed("%s didn't load: %s" % (url, e)) from None
        self.frames()

    def frames(self):
        """Wait for the fonts and two animation frames."""
        self.evaluate("(async () => { await document.fonts.ready;"
                      " await new Promise(f => requestAnimationFrame(() => requestAnimationFrame(f))); return true; })()")

    # -- the four calls ---------------------------------------------------------------------------------------

    def source(self, device):
        """The viewport and Chrome, for the report."""
        return dict(self.info)

    def prepare(self, device, plan):
        """Start Chrome and open a page at the device's size."""
        t = device.get("target") or {}
        width, height = device["width"], device["height"]
        if t.get("viewport"):
            self.scale = float(width) / float(t["viewport"][0])
        else:
            self.scale = float(t.get("scale") or 1)
        css_w, css_h = width / self.scale, height / self.scale
        if abs(css_w - round(css_w)) > 1e-6 or abs(css_h - round(css_h)) > 1e-6:
            raise base.DriverError("%dx%d at scale %g isn't a whole CSS size (%.2fx%.2f): pick a scale that divides "
                                   "both" % (width, height, self.scale, css_w, css_h))
        app = device.get("app") or {}
        self.app_url = app.get("url") or ((plan.get("app") or {}).get("web") or {}).get("url")
        if self.app_url and not urllib.parse.urlsplit(self.app_url).scheme:
            self.app_url = chrome_lib.to_url(self.path(self.app_url))  # a page next to the plan
        if self.app_url:
            local_url(self.app_url)
        mobile = t.get("mobile", device["platform"] in MOBILE_PLATFORMS)
        self.info = {"browser": "headless Chrome", "viewport": [int(round(css_w)), int(round(css_h))],
                     "scale": self.scale, "mobile": bool(mobile)}
        base.LOG("  start headless Chrome")
        if not base.DRY_RUN:
            try:
                self.browser = CHROME_FACTORY()
                self.browser.start()
                self.user_agent = ((self.browser.call("Browser.getVersion") or {}).get("userAgent", "")
                                   .replace("HeadlessChrome/", "Chrome/"))
                self.target = self.browser.call("Target.createTarget", {"url": "about:blank"})["targetId"]
                self.session = self.browser.call("Target.attachToTarget",
                                                 {"targetId": self.target, "flatten": True})["sessionId"]
            except chrome_lib.ChromeNotFound as e:
                raise base.ToolMissing(str(e)) from None
            except chrome_lib.ChromeError as e:
                raise base.DriverError("Chrome: %s" % e) from None
            if " Chrome/" in self.user_agent:
                self.info["browser"] = "headless Chrome %s" % self.user_agent.split(" Chrome/")[1].split(" ")[0]
        self.cdp("Page.enable")
        self.cdp("Page.setLifecycleEventsEnabled", {"enabled": True})
        self.cdp("Emulation.setDeviceMetricsOverride", {"width": int(round(css_w)), "height": int(round(css_h)),
                                                        "deviceScaleFactor": self.scale, "mobile": bool(mobile)})
        if mobile:
            self.cdp("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
        self.cdp("Emulation.setScrollbarsHidden", {"hidden": True})

    def reset(self, device):
        """Close the page and Chrome."""
        warnings = []
        if self.browser is not None:
            try:
                if self.target:
                    self.browser.call("Target.closeTarget", {"targetId": self.target}, timeout=10)
            except chrome_lib.ChromeError as e:
                warnings.append("closing the page: %s" % e)
            try:
                self.browser.close()
            except Exception as e:  # never let a browser's exit hide the run's result
                warnings.append("closing Chrome: %s" % e)
            self.browser = None
        return warnings

    # -- per screen --------------------------------------------------------------------------------------------

    def media(self, device):
        features = [{"name": "prefers-color-scheme", "value": self.state.get("appearance") or "light"}]
        if (device.get("target") or {}).get("reducedMotion", True):
            features.append({"name": "prefers-reduced-motion", "value": "reduce"})
        self.cdp("Emulation.setEmulatedMedia", {"features": features})

    def apply_locale(self, device, locale, shot):
        """``Emulation.setLocaleOverride`` and the user agent's ``acceptLanguage`` (``navigator.language``)."""
        try:
            self.cdp("Emulation.setLocaleOverride", {"locale": locale.replace("-", "_")})
        except base.DriverError as e:
            shot.warnings.append("Chrome didn't take the locale %s for Intl: %s" % (locale, e))
        self.cdp("Emulation.setUserAgentOverride", {"userAgent": self.user_agent, "acceptLanguage": locale})

    def apply_appearance(self, device, appearance, shot):
        """``prefers-color-scheme`` (and reduced motion)."""
        self.state["appearance"] = appearance
        self.media(device)

    # -- elements -----------------------------------------------------------------------------------------------

    def locate(self, query, scroll=False, focus=False, contains=None):
        """An element's middle and size in CSS px (``{"x", "y", "width", "height"}``), or ``None``; with
        ``contains``, the first element ``query`` finds whose text (``innerText``, ``textContent``, its value, its
        ``aria-label``, ``title`` or ``alt``) contains it, ignoring case and runs of space."""
        q = {"finder": query[0], "value": query[1], "scroll": scroll, "focus": focus}
        if contains is not None:
            q["contains"] = contains
        return self.evaluate("%s(%s)" % (FIND_JS.strip(), json.dumps(q)),
                             dry={"x": 1, "y": 1, "width": 2, "height": 2})

    def find(self, ctx, query, contains=None):
        """The element on the page now, as a ``base.Element`` in CSS px, or ``None`` (``contains``: one that
        shows that text, ``locate``)."""
        r = self.locate(query, contains=contains)
        if not r:
            return None
        return base.Element(id=str(query[1]), bounds=(int(r["x"] - r["width"] / 2), int(r["y"] - r["height"] / 2),
                                                      int(r["x"] + r["width"] / 2), int(r["y"] + r["height"] / 2)))

    def find_containing(self, ctx, query, wanted):
        """An element ``query`` finds that shows ``wanted`` (``locate`` with ``contains``), or ``None``."""
        return self.find(ctx, query, contains=wanted)

    def click(self, x, y):
        """A mouse press and release at CSS ``(x, y)``."""
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": kind, "x": x, "y": y, "button": "left" if kind != "mouseMoved" else "none",
                      "clickCount": 1 if kind != "mouseMoved" else 0}
            self.cdp("Input.dispatchMouseEvent", params)

    # -- steps --------------------------------------------------------------------------------------------------

    def step_launch(self, ctx, value):
        """Open the app's URL with the seed and args as query parameters."""
        value = value or {}
        if not self.app_url:
            raise base.StepFailed("step %d: launch needs the plan's app.web.url" % ctx.index)
        if value.get("clean"):
            parts = urllib.parse.urlsplit(self.app_url)
            if parts.scheme in ("http", "https"):
                self.cdp("Storage.clearDataForOrigin", {"origin": "%s://%s" % (parts.scheme, parts.netloc),
                                                        "storageTypes": "all"})
            self.cdp("Network.clearBrowserCookies")
        if value.get("env"):
            ctx.warn("a web page gets no environment variables: pass %s as args (query parameters) instead"
                     % ", ".join(sorted(value["env"])))
        params = {}
        seed = ctx.screen.get("seed") if ctx.screen.get("seed") is not None else ctx.device.get("seed")
        if seed is not None:
            params["ScreenshotSeed"] = seed
        params.update(value.get("args") or {})
        self.navigate(with_query(self.app_url, params))

    def step_url(self, ctx, value):
        """Open a URL (relative to the app's)."""
        url = value.get("url") if isinstance(value, dict) else value
        if self.app_url:
            url = urllib.parse.urljoin(self.app_url, url)
        self.navigate(url)

    def step_deepLink(self, ctx, value):
        """A deep link on the web is a URL."""
        self.step_url(ctx, value)

    def _target(self, ctx, value, what):
        query = base.element_query(value)
        if query is None:
            raise base.StepFailed("step %d: %s needs an element (css, id, text, label, xpath)" % (ctx.index, what))
        self.wait_for(ctx, query, (value or {}).get("timeout"))
        return query

    def step_tap(self, ctx, value):
        """Click an element's middle (scrolled into view), or ``{x, y}`` in the picture's pixels."""
        if isinstance(value, dict) and "x" in value and "y" in value:
            self.click(value["x"] / self.scale, value["y"] / self.scale)
            return
        query = self._target(ctx, value, "tap")
        r = self.locate(query, scroll=True)
        if not r:
            raise base.StepFailed("step %d: %s %r went away" % (ctx.index, query[0], query[1]))
        self.click(r["x"], r["y"])
        self.frames()

    def step_type(self, ctx, value):
        """Focus the named field (if any), then insert the text."""
        query = base.step_element("type", value)
        target = {query[0]: query[1], "timeout": value.get("timeout")} if query else None
        if target:
            query = self._target(ctx, target, "type into")
            self.locate(query, scroll=True, focus=True)
        self.cdp("Input.insertText", {"text": value["text"]})
        self.frames()

    def step_scroll(self, ctx, value):
        """Scroll an element into view (``to``: ``scrollIntoView``, whichever way it is), to the ``"top"`` or
        ``"bottom"``, or ``direction`` by most of a screen (``times``); ``in``: an element (a pane, a list) scrolled
        instead of the page."""
        value = value or {}
        if isinstance(value, str):
            value = {"direction": value}
        within = base.element_query(value["in"]) if value.get("in") else None
        if within is not None:
            self._target(ctx, value["in"], "scroll in")
        to = value.get("to")
        if isinstance(to, str):
            if to not in base.EDGES:
                raise base.StepFailed("step %d: scroll to is an element, \"top\" or \"bottom\"" % ctx.index)
            if within is not None:
                q = {"finder": within[0], "value": within[1], "edge": to}
                self.evaluate("%s(%s)" % (FIND_JS.strip(), json.dumps(q)), dry=True)
            else:
                self.evaluate("window.scrollTo(0, %s)" % ("0" if to == "top" else "document.body.scrollHeight"))
        elif to:
            query = self._target(ctx, to, "scroll to")
            self.locate(query, scroll=True)
        else:
            d = value.get("direction") or "down"
            if d not in base.DIRECTIONS:
                raise base.StepFailed("step %d: scroll direction is up, down, left or right" % ctx.index)
            dx, dy = {"down": (0, 1), "up": (0, -1), "right": (1, 0), "left": (-1, 0)}[d]
            for _ in range(int(value.get("times") or 1)):
                if within is not None:
                    q = {"finder": within[0], "value": within[1], "scrollBy": [dx * 0.8, dy * 0.8]}
                    self.evaluate("%s(%s)" % (FIND_JS.strip(), json.dumps(q)), dry=True)
                else:
                    self.evaluate("window.scrollBy(%d * innerWidth * 0.8, %d * innerHeight * 0.8)" % (dx, dy))
        self.frames()

    def focused_field(self, ctx):
        """The input, textarea or contenteditable that has the focus (``document.activeElement``), or ``False``."""
        r = self.evaluate("%s(false)" % FOCUSED_JS.strip(), dry=None)
        if base.DRY_RUN:
            return None
        return base.Element(id=r.get("id") or None, cls=r.get("tag")) if isinstance(r, dict) else False

    def clear_focus(self, ctx):
        """``blur()`` the focused text field: ``True`` when one had the focus, else ``False``."""
        r = self.evaluate("%s(true)" % FOCUSED_JS.strip(), dry=None)
        if base.DRY_RUN:
            return None
        self.frames()
        return isinstance(r, dict)

    def step_back(self, ctx, value):
        """``history.back()``, then wait for it to draw."""
        self.evaluate("history.back()")
        base.sleep(0.5)
        self.frames()

    def screenshot(self, device, path):
        """``Page.captureScreenshot`` of the viewport, at the device's pixels."""
        res = self.cdp("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False,
                                                   "fromSurface": True}, timeout=60)
        if base.DRY_RUN:
            return
        data = base64.b64decode(res.get("data") or "")
        if not data.startswith(b"\x89PNG"):
            raise base.DriverError("Chrome's screenshot isn't a PNG")
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)


DRIVER = ChromeDriver
