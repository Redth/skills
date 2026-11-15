"""Headless Chrome over the DevTools pipe: render a page to a PNG or JPEG of an exact size.

Chrome is started with ``--remote-debugging-pipe``: it reads DevTools commands from file descriptor 3 and
writes replies and events to descriptor 4, each message JSON ending in a NUL byte. No port is opened, so
nothing else on the machine can talk to it. One ``Chrome`` serves many renders; each render opens its own
page (a target, attached with a flattened session) and closes it after.

A page can tell the renderer two things:

- ``window.__appstoresReady``: a promise; the capture waits for it (after the load event and the fonts).
- ``window.__appstoresReport``: any JSON-able value; ``render`` returns it (say, which text overflowed).
"""

from __future__ import annotations

import base64
import errno
import fcntl
import json
import math
import os
import pathlib
import select
import shutil
import signal
import subprocess
import tempfile
import time
import weakref

from . import png

MAC_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "~/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "~/Applications/Chromium.app/Contents/MacOS/Chromium",
)
PATH_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")

FLAGS = (
    "--headless=new",
    "--remote-debugging-pipe",
    "--disable-gpu",
    "--hide-scrollbars",
    "--force-color-profile=srgb",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-component-update",
    "--disable-background-networking",
    "--disable-breakpad",
    "--disable-crash-reporter",
    "--metrics-recording-only",
    "--mute-audio",
    "--password-store=basic",
    "--use-mock-keychain",
    "--allow-file-access-from-files",
    "--disable-features=Translate,MediaRouter,OptimizationHints,DialMediaRouteProvider",
)


class ChromeNotFound(RuntimeError):
    """Neither Google Chrome nor Chromium could be found."""


class ChromeError(RuntimeError):
    """Chrome failed to start, answered a command with an error, went away or took too long."""


def find_chrome():
    """Return the path of a Chrome or Chromium to run, or raise ``ChromeNotFound`` saying how to get one.

    Looks at ``$CHROME`` first (which must then exist), then the usual macOS application paths, then
    ``google-chrome``, ``google-chrome-stable``, ``chromium`` and ``chromium-browser`` on ``PATH``.
    """
    env = os.environ.get("CHROME")
    if env:
        path = os.path.expanduser(env)
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
        found = shutil.which(env)
        if found:
            return found
        raise ChromeNotFound("$CHROME is set to %r, which isn't a program that can run" % env)
    for p in MAC_PATHS:
        p = os.path.expanduser(p)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    for name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return found
    raise ChromeNotFound(
        "Rendering needs Google Chrome or Chromium, and neither was found. Install Google Chrome "
        "(or Chromium: google-chrome, chromium or chromium-browser on PATH), or set CHROME to its program's path."
    )


def to_url(url_or_path):
    """Return a URL for ``url_or_path``: URLs (``http(s)``, ``file``, ``data``, ``about``) as they are,
    anything else as a ``file://`` URL of that path made absolute."""
    s = str(url_or_path)
    for scheme in ("http://", "https://", "file://", "data:", "about:"):
        if s.startswith(scheme):
            return s
    return pathlib.Path(os.path.abspath(s)).as_uri()


def _high_fd(fd, low=10):
    """Return a close-on-exec duplicate of ``fd`` numbered ``low`` or above."""
    if hasattr(fcntl, "F_DUPFD_CLOEXEC"):
        return fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, low)
    new = fcntl.fcntl(fd, fcntl.F_DUPFD, low)
    fcntl.fcntl(new, fcntl.F_SETFD, fcntl.FD_CLOEXEC)
    return new


def _kill(proc, wait_first):
    """Stop Chrome's whole process group: wait ``wait_first`` seconds for it to leave, then TERM, then KILL."""
    if proc is None:
        return
    try:
        proc.wait(timeout=wait_first)
        return
    except subprocess.TimeoutExpired:
        pass
    for sig, grace in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=grace)
            return
        except subprocess.TimeoutExpired:
            continue


def _cleanup(proc, fds, root):
    """Last-resort teardown for a ``Chrome`` that was never closed (run by a finalizer)."""
    for fd in fds:
        try:
            os.close(fd)
        except OSError:
            pass
    _kill(proc, 0)
    if root:
        shutil.rmtree(root, ignore_errors=True)


class Chrome:
    """One headless Chrome, driven over the DevTools pipe. Use it as a context manager::

        with Chrome() as chrome:
            report = chrome.render("panel.html", 1290, 2796, "out/01.png", scale=3)

    ``path`` is the browser (default ``find_chrome()``); ``start_timeout`` is how long Chrome may take to
    answer its first command; ``extra_args`` are added to the command line.
    """

    def __init__(self, path=None, start_timeout=30, extra_args=None):
        """Set Chrome up; nothing runs until ``start()`` (or ``with``)."""
        self.path = path
        self.start_timeout = start_timeout
        self.extra_args = list(extra_args or [])
        self._proc = None
        self._root = None
        self._wfd = None
        self._rfd = None
        self._buf = b""
        self._next_id = 0
        self._events = []
        self._finalizer = None

    # -- lifetime ---------------------------------------------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def start(self):
        """Start Chrome with a fresh temporary profile and check it answers; raise ``ChromeError`` if not."""
        if self._proc is not None:
            return
        path = self.path or find_chrome()
        self._root = tempfile.mkdtemp(prefix="appstores-chrome-")
        profile = os.path.join(self._root, "profile")
        os.mkdir(profile)
        log_path = os.path.join(self._root, "chrome.log")

        # Two pipes. Chrome reads commands on its fd 3 and writes on its fd 4. The child's ends are copied
        # to 10 and up, so placing them on 3 and 4 in the child can't overwrite one another; the originals
        # stay open until Chrome has started, so descriptors 3 and 4 are taken in this process (by them or
        # by something else) and subprocess's own error pipe can't land there.
        cmd_read, cmd_write = os.pipe()
        res_read, res_write = os.pipe()
        child_in = _high_fd(cmd_read)
        child_out = _high_fd(res_write)
        self._wfd = cmd_write
        self._rfd = res_read

        def place_fds():
            os.dup2(child_in, 3)
            os.dup2(child_out, 4)

        args = [path] + list(FLAGS) + ["--user-data-dir=" + profile]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")  # Chrome refuses to run as root (CI containers) without it
        args += self.extra_args + ["about:blank"]
        log = open(log_path, "wb")
        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                pass_fds=(3, 4),
                preexec_fn=place_fds,
                start_new_session=True,
            )
        except OSError as e:
            for fd in (child_in, child_out, cmd_read, res_write, self._wfd, self._rfd):
                os.close(fd)
            self._wfd = self._rfd = None
            shutil.rmtree(self._root, ignore_errors=True)
            self._root = None
            raise ChromeError("couldn't start Chrome (%s): %s" % (path, e)) from None
        finally:
            log.close()
        for fd in (child_in, child_out, cmd_read, res_write):
            os.close(fd)
        self._finalizer = weakref.finalize(self, _cleanup, self._proc, (self._wfd, self._rfd), self._root)
        try:
            self.call("Browser.getVersion", timeout=self.start_timeout)
        except ChromeError as e:
            tail = self._log_tail()
            self.close()
            raise ChromeError("Chrome didn't start: %s%s" % (e, ("\n" + tail) if tail else "")) from None

    def close(self):
        """Ask Chrome to quit, stop it if it doesn't, and remove its temporary profile. Safe to call twice."""
        if self._proc is None:
            return
        if self._finalizer is not None:
            self._finalizer.detach()
            self._finalizer = None
        try:
            if self._proc.poll() is None and self._wfd is not None:
                self._send("Browser.close", {}, None)
        except (OSError, ChromeError):
            pass
        for fd in (self._wfd, self._rfd):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._wfd = self._rfd = None
        _kill(self._proc, 5)
        self._proc = None
        root, self._root = self._root, None
        for _ in range(5):
            shutil.rmtree(root, ignore_errors=True)
            if not os.path.exists(root):
                break
            time.sleep(0.2)

    def _log_tail(self, lines=15):
        if not self._root:
            return ""
        try:
            with open(os.path.join(self._root, "chrome.log"), "rb") as f:
                text = f.read().decode("utf-8", "replace")
        except OSError:
            return ""
        return "\n".join(text.strip().splitlines()[-lines:])

    # -- the protocol -----------------------------------------------------------------------------------

    def _send(self, method, params, session_id):
        self._next_id += 1
        msg = {"id": self._next_id, "method": method, "params": params or {}}
        if session_id:
            msg["sessionId"] = session_id
        data = json.dumps(msg).encode("utf-8") + b"\0"
        while data:
            try:
                n = os.write(self._wfd, data)
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                raise ChromeError("Chrome went away (%s)" % e) from None
            data = data[n:]
        return self._next_id

    def _read_message(self, deadline):
        """Return the next message from Chrome, or raise ``ChromeError`` at the deadline or on exit."""
        while True:
            end = self._buf.find(b"\0")
            if end >= 0:
                raw, self._buf = self._buf[:end], self._buf[end + 1:]
                try:
                    return json.loads(raw.decode("utf-8"))
                except ValueError:
                    continue
            left = deadline - time.monotonic()
            if left <= 0:
                raise ChromeError("timed out waiting for Chrome")
            try:
                ready, _, _ = select.select([self._rfd], [], [], min(left, 1.0))
            except InterruptedError:
                continue
            if not ready:
                if self._proc is not None and self._proc.poll() is not None:
                    raise ChromeError("Chrome exited (code %s)" % self._proc.returncode)
                continue
            chunk = os.read(self._rfd, 1 << 20)
            if not chunk:
                raise ChromeError("Chrome closed the pipe")
            self._buf += chunk

    def call(self, method, params=None, session_id=None, timeout=30):
        """Send one DevTools command and return its ``result``; events that arrive meanwhile are kept.

        Raises ``ChromeError`` when Chrome answers with an error or doesn't answer within ``timeout`` seconds.
        """
        if self._wfd is None:
            raise ChromeError("Chrome isn't running")
        msg_id = self._send(method, params, session_id)
        deadline = time.monotonic() + timeout
        while True:
            msg = self._read_message(deadline)
            if msg.get("id") == msg_id:
                if "error" in msg:
                    err = msg["error"]
                    raise ChromeError("%s failed: %s" % (method, err.get("message", err)))
                return msg.get("result", {})
            if "method" in msg:
                self._events.append(msg)
                del self._events[:-500]

    def wait_event(self, method, session_id=None, predicate=None, timeout=30):
        """Wait for an event named ``method`` (in ``session_id``, matching ``predicate(params)``); return its params."""
        def matches(m):
            if m.get("method") != method:
                return False
            if session_id is not None and m.get("sessionId") != session_id:
                return False
            return predicate is None or predicate(m.get("params", {}))

        for i, m in enumerate(self._events):
            if matches(m):
                del self._events[i]
                return m.get("params", {})
        deadline = time.monotonic() + timeout
        while True:
            try:
                m = self._read_message(deadline)
            except ChromeError as e:
                raise ChromeError("waiting for %s: %s" % (method, e)) from None
            if matches(m):
                return m.get("params", {})
            if "method" in m:
                self._events.append(m)
                del self._events[:-500]

    # -- pages ------------------------------------------------------------------------------------------

    def _open(self, timeout):
        target = self.call("Target.createTarget", {"url": "about:blank"}, timeout=timeout)["targetId"]
        try:
            session = self.call("Target.attachToTarget", {"targetId": target, "flatten": True},
                                timeout=timeout)["sessionId"]
            self.call("Page.enable", session_id=session, timeout=timeout)
            self.call("Page.setLifecycleEventsEnabled", {"enabled": True}, session_id=session, timeout=timeout)
        except BaseException:
            self._close_target(target)
            raise
        return target, session

    def _close_target(self, target):
        try:
            self.call("Target.closeTarget", {"targetId": target}, timeout=10)
        except ChromeError:
            pass
        self._events = [e for e in self._events if e.get("params", {}).get("targetId") != target]

    def _evaluate(self, session, expression, timeout):
        res = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": True, "returnByValue": True},
            session_id=session,
            timeout=timeout,
        )
        if "exceptionDetails" in res:
            d = res["exceptionDetails"]
            text = (d.get("exception") or {}).get("description") or d.get("text") or "exception"
            raise ChromeError("the page threw: %s" % text)
        return (res.get("result") or {}).get("value")

    def _load(self, session, url, deadline):
        """Navigate and wait for the load event, the fonts, ``__appstoresReady`` and two frames."""
        nav = self.call("Page.navigate", {"url": url}, session_id=session, timeout=max(1, deadline - time.monotonic()))
        if nav.get("errorText"):
            raise ChromeError("couldn't open %s: %s" % (url, nav["errorText"]))
        loader = nav.get("loaderId")
        if loader:
            self.wait_event(
                "Page.lifecycleEvent",
                session_id=session,
                predicate=lambda p: p.get("loaderId") == loader and p.get("name") == "load",
                timeout=max(1, deadline - time.monotonic()),
            )
        self._evaluate(
            session,
            "(async () => {"
            " await document.fonts.ready;"
            " const r = window.__appstoresReady;"
            " if (r && typeof r.then === 'function') await r;"
            " await new Promise(f => requestAnimationFrame(() => requestAnimationFrame(f)));"
            " return true; })()",
            max(1, deadline - time.monotonic()),
        )

    def render(self, url_or_path, width, height, out_path, fmt="png", quality=None, scale=1.0, timeout=60,
               full_page=None):
        """Render a page to a ``width`` x ``height`` pixel picture at ``out_path``; return the page's report.

        The page is laid out at ``width/scale`` x ``height/scale`` CSS pixels with ``deviceScaleFactor``
        ``scale`` (so a 1290x2796 shot at scale 3 is a 430x932 page). ``fmt`` is ``png`` or ``jpeg``
        (``quality`` 0-100 for JPEG). Waits for the load event, ``document.fonts.ready`` and the page's
        ``window.__appstoresReady`` promise if it set one, captures the viewport only, writes the file
        (making its folder) and returns ``window.__appstoresReport`` if the page set one, else ``{}``.
        Raises ``ChromeError`` on a failed load, a page error or the ``timeout`` (seconds) running out.

        ``full_page`` (CSS px): capture the whole page instead. It's laid out ``width/scale`` wide (``height``
        is only the first viewport), its height measured (``document.documentElement.scrollHeight``), and the
        picture is that tall, at most ``full_page`` CSS px (times ``scale`` in pixels).
        """
        if fmt not in ("png", "jpeg"):
            raise ValueError("fmt must be png or jpeg, not %r" % (fmt,))
        if width <= 0 or height <= 0 or scale <= 0:
            raise ValueError("width, height and scale must be positive")
        if self._proc is None:
            self.start()
        deadline = time.monotonic() + timeout
        css_w, css_h = width / float(scale), height / float(scale)
        whole = abs(css_w - round(css_w)) < 1e-6 and abs(css_h - round(css_h)) < 1e-6
        target, session = self._open(timeout)
        try:
            self.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": int(round(css_w)) if whole else int(math.ceil(css_w)),
                    "height": int(round(css_h)) if whole else int(math.ceil(css_h)),
                    "deviceScaleFactor": float(scale),
                    "mobile": False,
                },
                session_id=session,
                timeout=timeout,
            )
            self._load(session, to_url(url_or_path), deadline)
            if full_page:
                tall = self._evaluate(
                    session, "Math.ceil(Math.max(document.documentElement.scrollHeight,"
                    " document.body ? document.body.scrollHeight : 0))", max(1, deadline - time.monotonic()))
                css_h = float(min(max(int(tall or 1), 1), int(full_page)))
                height = int(round(css_h * scale))
                css_h = height / float(scale)
                whole = whole and abs(css_h - round(css_h)) < 1e-6
                self.call(
                    "Emulation.setDeviceMetricsOverride",
                    {
                        "width": int(round(css_w)) if whole else int(math.ceil(css_w)),
                        "height": int(round(css_h)) if whole else int(math.ceil(css_h)),
                        "deviceScaleFactor": float(scale),
                        "mobile": False,
                    },
                    session_id=session,
                    timeout=max(1, deadline - time.monotonic()),
                )
                self._evaluate(session, "new Promise(f => requestAnimationFrame(() => requestAnimationFrame(f)))"
                               ".then(() => true)", max(1, deadline - time.monotonic()))
            params = {"format": fmt, "captureBeyondViewport": False, "fromSurface": True}
            if fmt == "jpeg":
                params["quality"] = 90 if quality is None else int(quality)
            if not whole:
                params["clip"] = {"x": 0, "y": 0, "width": css_w, "height": css_h, "scale": 1}
            shot = self.call("Page.captureScreenshot", params, session_id=session,
                             timeout=max(1, deadline - time.monotonic()))
            report = self._evaluate(
                session,
                "JSON.stringify(window.__appstoresReport === undefined ? null : window.__appstoresReport)",
                max(1, deadline - time.monotonic()),
            )
        finally:
            self._close_target(target)
        data = base64.b64decode(shot["data"])
        folder = os.path.dirname(os.path.abspath(out_path))
        os.makedirs(folder, exist_ok=True)
        tmp = out_path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        got = png.info(tmp)
        if (got.width, got.height) != (int(width), int(height)):
            os.unlink(tmp)
            raise ChromeError("Chrome made a %dx%d picture, not %dx%d (try a scale that divides the size)"
                              % (got.width, got.height, width, height))
        os.replace(tmp, out_path)
        value = json.loads(report) if report else None
        return value if value is not None else {}

    def evaluate(self, expr, url_or_path="about:blank", timeout=30):
        """Evaluate a JavaScript expression in a page and return its JSON value (promises are awaited).

        The page (``url_or_path``, default a blank one) is opened and loaded first, fonts and all, and
        closed after. Raises ``ChromeError`` if the expression throws.
        """
        if self._proc is None:
            self.start()
        deadline = time.monotonic() + timeout
        target, session = self._open(timeout)
        try:
            self._load(session, to_url(url_or_path), deadline)
            return self._evaluate(session, expr, max(1, deadline - time.monotonic()))
        finally:
            self._close_target(target)
