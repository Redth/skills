"""What every capture driver shares: the ``Driver`` base class, the ``Shot`` it returns, ``run()`` for external
commands, ``http()`` for the local machine only, and helpers for finding elements and waiting.

A driver reaches an app's screens one way (a simulator, an emulator, a browser, an in-app agent, a UI test) and
captures each at the device's exact size. ``capture.py`` drives it::

    driver = SomeDriver(Options(plan_dir=..., workdir=...))
    driver.prepare(device, plan)                 # boot, install, anything once a device
    try:
        for locale in device["locales"]:
            for screen in screens:
                shot = driver.run_screen(device, screen, locale)   # steps, then a screenshot
    finally:
        driver.reset(device)                     # always: put back everything prepare and the screens changed

Rules for driver authors (CONTRACT.md 10.3, 10.5):

- **External commands only through ``run()``** (and long-running ones through ``spawn()``): it logs each
  command, applies a timeout, turns a missing program into ``ToolMissing`` with an install hint, and goes through
  the module-level ``RUNNER`` hook, which tests replace with a fake that records commands and answers them.
  ``--dry-run`` sets ``DRY_RUN``: ``run()`` then prints the command and returns ``dry_output`` without running it.
- **HTTP only to this machine** through ``http()``/``http_json()`` (``localhost``, ``127.0.0.1``, ``::1``); any
  other host raises ``NotLocal``. It goes through ``appstores_lib.web.request``, whose ``TRANSPORT`` tests fake.
  Whether something already listens on a local port is the ``LISTENING`` hook's to say (tests fake it too).
- **Waiting** through ``sleep()`` and ``poll()`` (the ``SLEEP`` and ``CLOCK`` hooks), so tests never wait.
- **Never resize.** A driver captures at the device's size or reports what it got; ``capture.py`` checks.
- **Reset in ``reset()``** whatever was changed (status bar, demo mode, ``wm size``, locale, appearance,
  permissions), and never touch a simulator or device the plan doesn't name (create ``appstores-<device id>``).

A driver module defines one ``Driver`` subclass and names it ``DRIVER`` (``drivers.get(name)`` loads it).

Each step kind ``k`` is handled by a method ``step_<k>(self, ctx, value)``; ``ctx`` is a ``StepContext``.
``STEPS`` lists the kinds a driver handles and ``FINDERS`` the element finders it understands; the base class
handles ``wait`` (``ms``), ``settle`` and ``script`` for every driver. A screen with a step the driver can't do
is ``skipped`` without running anything (``unsupported()``).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET

_SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from appstores_lib import png  # noqa: E402
from appstores_lib import web  # noqa: E402

# Every step kind the plan may use (CONTRACT.md 10.2), and every element finder.
STEP_KINDS = ("launch", "deepLink", "url", "tap", "type", "wait", "scroll", "back", "swipe", "flow", "script",
              "settle", "appFile", "posture", "hideKeyboard", "fill", "unfocus")
# Steps that type: a screen with one is a typing screen (its keyboard isn't checked unless asked; a field may keep
# its focus, and its caret, after it).
TYPING_STEPS = ("type", "fill")
# Scroll directions, each one's opposite, and the two ends a ``scroll {"to": …}`` may name instead of an element.
DIRECTIONS = ("up", "down", "left", "right")
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}
EDGES = {"top": "up", "bottom": "down"}
# Keys a step may carry besides its kind: a comment, and a name other layers patch it by (stepsPatch).
STEP_META = ("$comment", "name")
# A foldable's postures (the plan's word, and the words other tools use for the same).
POSTURES = ("folded", "open", "half-open")
POSTURE_ALIASES = {"unfolded": "open", "opened": "open", "closed": "folded", "half-opened": "half-open",
                   "partially-folded": "half-open", "tabletop": "half-open", "book": "half-open"}
FINDER_KEYS = ("id", "text", "label", "xpath", "css")
# What an element shows, by attribute, in the trees the drivers read (UI Automator's text and content-desc,
# XCUITest's label and value, an agent's text and value, a Mac's title, Windows' Name): what a ``contains`` check
# reads, on the element and everything under it. Never an id (XCUITest's ``name``, ``resource-id``).
TEXT_ATTRS = ("text", "label", "value", "content-desc", "contentDescription", "title", "description", "Name")
LOCAL_HOSTS = ("localhost", "127.0.0.1", "::1")

# What to install when a program is missing (ToolMissing's hint), by the program's name.
HINTS = {
    "xcrun": "install Xcode (xcode-select --install gives only the command-line tools; simulators need Xcode)",
    "adb": "install the Android SDK platform-tools and put them on PATH (or set ANDROID_HOME)",
    "emulator": "install the Android Emulator (sdkmanager emulator) and put $ANDROID_HOME/emulator on PATH",
    "osascript": "osascript is part of macOS: this driver runs only on a Mac",
    "screencapture": "screencapture is part of macOS: this driver runs only on a Mac",
    "open": "open is part of macOS: this driver runs only on a Mac",
    "maestro": "install the Maestro CLI (https://maestro.mobile.dev)",
    "appium": "install Appium 2 or later (npm i -g appium) and its drivers",
    "xcodebuild": "install Xcode",
}


# -- hooks tests replace ------------------------------------------------------------------------------------

def subprocess_runner(cmd, input=None, timeout=None, env=None, cwd=None):
    """The real ``RUNNER``: run ``cmd`` (a list) and return ``(returncode, stdout_bytes, stderr_bytes)``.

    ``env`` holds only the variables to add to this process's environment. Without ``input`` its stdin is
    ``/dev/null``, so it never reads (or eats) the caller's. Raises ``FileNotFoundError`` when
    the program doesn't exist and ``subprocess.TimeoutExpired`` when it runs past ``timeout`` seconds (it's
    killed first).
    """
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update(env)
    # Without input, stdin is /dev/null: ffmpeg and adb shell read the caller's stdin otherwise (and eat a shell
    # loop's next line).
    stdin = None if input is not None else subprocess.DEVNULL
    proc = subprocess.run(cmd, input=input, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=timeout, env=full_env, cwd=cwd)
    return proc.returncode, proc.stdout, proc.stderr


def subprocess_spawner(cmd, log_path=None, env=None, cwd=None):
    """The real ``SPAWNER``: start ``cmd`` in the background (its output to ``log_path``, else discarded) and
    return the ``subprocess.Popen``. Raises ``FileNotFoundError`` when the program doesn't exist."""
    full_env = None
    if env:
        full_env = dict(os.environ)
        full_env.update(env)
    if log_path:
        # A missing log folder must not look like a missing program (both are FileNotFoundError).
        os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
    out = open(log_path, "ab") if log_path else subprocess.DEVNULL
    try:
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=full_env,
                                cwd=cwd, start_new_session=True)
    finally:
        if log_path:
            out.close()


def _stderr_log(line):
    print(line, file=sys.stderr)


def tcp_listening(port, host="127.0.0.1", timeout=0.5):
    """The real ``LISTENING``: True when something on this machine accepts a TCP connection on ``port``."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


RUNNER = subprocess_runner      # callable(cmd, input, timeout, env, cwd) -> (code, stdout bytes, stderr bytes)
SPAWNER = subprocess_spawner    # callable(cmd, log_path, env, cwd) -> a process (poll(), terminate(), wait())
SLEEP = time.sleep              # callable(seconds)
CLOCK = time.monotonic          # callable() -> seconds
LOG = _stderr_log               # callable(line): where commands and notes are logged
LISTENING = tcp_listening        # callable(port) -> bool: does something listen on 127.0.0.1:port
DRY_RUN = False                 # set by capture.py --dry-run: print commands, run nothing
SECRETS = []                    # values never written to a log or a report (a demo account's password): mask()


def mask(text):
    """``text`` with every value in ``SECRETS`` replaced by ``***`` (for logs, reasons and reports)."""
    if not isinstance(text, str) or not SECRETS:
        return text
    for value in sorted((v for v in SECRETS if v), key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def note(line):
    """Log one line through ``LOG``, secrets masked: the way drivers log."""
    LOG(mask(line))


# -- errors -------------------------------------------------------------------------------------------------

class DriverError(Exception):
    """A driver couldn't do something: a command failed, an element wasn't found, a device didn't boot. The
    screen (or the device, from ``prepare``) is reported ``missed`` with this message as its reason."""


class ToolMissing(DriverError):
    """A program the driver needs isn't installed. ``capture.py`` exits 3 (environment) for it."""


class CommandError(DriverError):
    """A command exited non-zero. ``cmd``, ``code``, ``out`` and ``err`` (text) say what happened."""

    def __init__(self, cmd, code, out, err):
        """Describe a failed command."""
        self.cmd = list(cmd)
        self.code = code
        self.out = out
        self.err = err
        tail = (err or out or "").strip().splitlines()[-5:]
        super().__init__(mask("%s exited %s%s" % (quote(cmd), code, (": " + " / ".join(tail)) if tail else "")))


class CommandTimeout(DriverError):
    """A command ran past its timeout (and was killed)."""


class StepFailed(DriverError):
    """A step couldn't be done (an element not found in time, a launch that failed)."""


class WrongState(StepFailed):
    """The screen was reached but isn't in the state the plan's ``verify`` asks for: the shot is ``missed``."""


class StepSkipped(Exception):
    """A step this driver can't do. Raised by a step method; the screen is reported ``skipped``."""


class NotLocal(DriverError):
    """``http()`` was asked for a host that isn't this machine."""


# -- results ------------------------------------------------------------------------------------------------

class Result(object):
    """What ``run()`` returns: ``code`` (exit status), ``out`` and ``err`` (text, or bytes with ``binary``),
    and ``dry`` (true when nothing ran because of ``--dry-run``)."""

    def __init__(self, code, out, err, dry=False):
        """Hold a command's result."""
        self.code = code
        self.out = out
        self.err = err
        self.dry = dry

    @property
    def ok(self):
        """True when the command exited 0."""
        return self.code == 0

    def __repr__(self):
        return "Result(%r)" % (self.code,)


STATUSES = ("taken", "missed", "failed", "skipped")
STATUS_BARS = ("verified", "overridden", "unverified", "none")
STATE_CHECKS = ("passed", "failed", "unchecked", "none")


class Shot(object):
    """What ``run_screen`` returns for one locale x device x screen.

    - ``status``: ``taken`` (a picture at ``path``), ``missed`` (not reached: ``reason``), ``failed`` (reached
      but unusable: ``reason``) or ``skipped`` (the driver can't do a step or this device: ``reason``).
      ``capture.py`` checks a taken picture's size and format and may turn it into ``failed``.
    - ``path``: the picture the driver wrote (in its ``workdir``); ``capture.py`` moves it into place.
    - ``source``: what made it, for the report (``{"deviceType": "iPhone 17 Pro Max", "runtime": "iOS 27.2"}``).
    - ``status_bar``: ``verified`` (the override was read back), ``overridden`` (set, not read back),
      ``unverified`` (asked for, not confirmed) or ``none`` (no status bar, or left as it is).
    - ``fixes``: what the driver changed in the picture (never a resize); ``warnings``: anything worth reading.
    - ``state_check``: the screen's ``verify``: ``passed`` (every element was there), ``failed`` (one wasn't: the
      shot is ``missed``, "wrong state"), ``unchecked`` (this driver can't see elements, so a person must look) or
      ``none`` (the screen has no ``verify``).
    - ``tree``: with ``capture.py --inspect``, the file the screen's UI tree was saved to (or ``None``).
    - ``panes``: what each scroll's ``in`` scrolled, where it wasn't the element named (its nearest scrolling
      ancestor, or the element itself when nothing around it scrolls), in a few words each.
    - ``recording``: with ``capture.py --record``, the screen's steps recorded (``Driver.end_recording``): ``{"file"
      (in the workdir), "seconds", "by", "from" (the step it started at), "display", "flush"}``; else ``None``.
    """

    def __init__(self, status="taken", path=None, reason=None, source=None, status_bar="none", fixes=None,
                 warnings=None, state_check="none"):
        """Hold one shot's outcome."""
        if status not in STATUSES:
            raise ValueError("a shot's status is one of %s, not %r" % (", ".join(STATUSES), status))
        if status_bar not in STATUS_BARS:
            raise ValueError("statusBar is one of %s, not %r" % (", ".join(STATUS_BARS), status_bar))
        self.status = status
        self.path = path
        self.reason = reason
        self.source = dict(source or {})
        self.status_bar = status_bar
        self.fixes = list(fixes or [])
        self.warnings = list(warnings or [])
        if state_check not in STATE_CHECKS:
            raise ValueError("state_check is one of %s, not %r" % (", ".join(STATE_CHECKS), state_check))
        self.state_check = state_check
        self.tree = None
        self.panes = []
        self.recording = None
        self.scrolled_in = {}   # a scroll's in (a query) -> the element it scrolled, for this screen's later steps

    def __repr__(self):
        return "Shot(%s%s)" % (self.status, (": " + self.reason) if self.reason else "")


class Options(object):
    """How ``capture.py`` set a driver up.

    - ``plan_dir``: the plan's folder (paths in the plan are relative to it).
    - ``workdir``: a temporary folder the driver writes pictures (and anything else) into.
    - ``cleanup``: delete the simulators/emulators this skill created (``appstores-<id>``) in ``reset``.
    - ``extra``: anything else, by name (``inspect=True``: save each screen's UI tree, ``capture.py --inspect``).
    """

    def __init__(self, plan_dir=".", workdir=None, cleanup=False, **extra):
        """Hold the options; ``workdir`` defaults to a new temporary folder."""
        self.plan_dir = os.path.abspath(plan_dir)
        if workdir is None:
            import tempfile
            workdir = tempfile.mkdtemp(prefix="appstores-capture-")
        self.workdir = workdir
        self.cleanup = bool(cleanup)
        self.extra = extra


class StepContext(object):
    """What a step method gets besides its value: the ``device`` and ``screen`` (resolved dicts), the
    ``locale``, the ``shot`` being built (add to ``shot.warnings``), ``index`` (1-based) and ``step`` (the raw
    step object)."""

    def __init__(self, device, screen, locale, shot, index=0, step=None):
        """Hold a step's context."""
        self.device = device
        self.screen = screen
        self.locale = locale
        self.shot = shot
        self.index = index
        self.step = step

    def warn(self, message):
        """Add a warning to the shot (and log it)."""
        self.shot.warnings.append(mask(message))
        note("  warning: %s" % message)


# -- commands -----------------------------------------------------------------------------------------------

def quote(cmd):
    """A command list as one shell-quoted line (for logs and messages)."""
    return " ".join(shlex.quote(str(c)) for c in cmd)


def run(cmd, timeout=120, check=True, input=None, env=None, cwd=None, binary=False, dry_output="", quiet=False):
    """Run an external command and return its ``Result``; the only way a driver runs one.

    - ``cmd``: a list (never a shell string). Logged as ``$ cmd`` unless ``quiet``.
    - ``timeout``: seconds before it's killed (``CommandTimeout``).
    - ``check``: raise ``CommandError`` on a non-zero exit (else return the result).
    - ``input``: bytes or text for its stdin. ``env``: variables to add (logged as ``VAR=value``).
    - ``binary``: return ``out``/``err`` as bytes (a screenshot on stdout) instead of text.
    - ``dry_output``: what to answer under ``--dry-run`` (``DRY_RUN``), when nothing runs: an empty JSON list
      or a placeholder id lets the driver go on describing what it would do.

    A missing program raises ``ToolMissing`` with an install hint (``HINTS``).
    """
    cmd = [str(c) for c in cmd]
    if not quiet or DRY_RUN:
        prefix = "".join("%s=%s " % (k, shlex.quote(str(v))) for k, v in sorted((env or {}).items()))
        note("  $ %s%s" % (prefix, quote(cmd)))
    if DRY_RUN:
        out = dry_output if not binary else (dry_output.encode("utf-8") if isinstance(dry_output, str)
                                             else dry_output)
        return Result(0, out, b"" if binary else "", dry=True)
    if isinstance(input, str):
        input = input.encode("utf-8")
    try:
        code, out, err = RUNNER(cmd, input, timeout, dict(env) if env else None, cwd)
    except FileNotFoundError:
        name = os.path.basename(cmd[0])
        raise ToolMissing("%s isn't installed or isn't on PATH: %s" % (name, HINTS.get(name, "install it"))) \
            from None
    except subprocess.TimeoutExpired:
        raise CommandTimeout(mask("%s took longer than %s s and was stopped" % (quote(cmd), timeout))) from None
    out = out or b""
    err = err or b""
    if not binary:
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else out
        err = err.decode("utf-8", "replace") if isinstance(err, bytes) else err
    res = Result(code, out, err)
    if check and code != 0:
        text = lambda b: b.decode("utf-8", "replace") if isinstance(b, bytes) else b  # noqa: E731
        raise CommandError(cmd, code, text(out), text(err))
    return res


def spawn(cmd, log_path=None, env=None, cwd=None):
    """Start a long-running command (an emulator, a server) in the background and return its process (or
    ``None`` under ``--dry-run``). Logged like ``run()`` (``env``'s variables first); a missing program raises
    ``ToolMissing``. Stop it with ``stop()``."""
    cmd = [str(c) for c in cmd]
    prefix = "".join("%s=%s " % (k, shlex.quote(str(v))) for k, v in sorted((env or {}).items()))
    note("  $ %s%s &" % (prefix, quote(cmd)))
    if DRY_RUN:
        return None
    try:
        return SPAWNER(cmd, log_path, dict(env) if env else None, cwd)
    except FileNotFoundError:
        name = os.path.basename(cmd[0])
        raise ToolMissing("%s isn't installed or isn't on PATH: %s" % (name, HINTS.get(name, "install it"))) \
            from None


def stop(proc, grace=10):
    """Stop a process ``spawn()`` started: terminate, wait ``grace`` seconds, then kill. ``None`` is fine."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=grace)
    except (OSError, AttributeError):
        pass


def interrupt(proc, grace=30):
    """Stop a process ``spawn()`` started the way a recorder needs: SIGINT (``simctl io recordVideo`` finishes its
    file on it), wait ``grace`` seconds for it to exit, then ``stop()``. ``None`` (a dry run) is fine."""
    if proc is None:
        return
    try:
        if proc.poll() is not None:
            return
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            stop(proc)
    except (OSError, AttributeError):
        stop(proc)


def which(name):
    """The path of a program on ``PATH``, or ``None`` (for optional tools; required ones just ``run()``)."""
    return shutil.which(name)


def sleep(seconds):
    """Wait (through ``SLEEP``); under ``--dry-run`` just say so."""
    if DRY_RUN:
        note("  (wait %.1f s)" % seconds)
        return
    SLEEP(seconds)


def poll(check, timeout, interval=0.5, what="it"):
    """Call ``check()`` until it returns something truthy and return that; raise ``StepFailed`` naming
    ``what`` after ``timeout`` seconds. Under ``--dry-run`` it's called once and its answer returned."""
    if DRY_RUN:
        return check()
    deadline = CLOCK() + timeout
    while True:
        value = check()
        if value:
            return value
        if CLOCK() >= deadline:
            raise StepFailed("%s didn't happen within %s s" % (what, timeout))
        SLEEP(interval)


# -- HTTP to this machine only --------------------------------------------------------------------------------

def check_local(url):
    """Raise ``NotLocal`` unless ``url`` is ``http(s)`` to ``localhost``, ``127.0.0.1`` or ``::1``."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() not in LOCAL_HOSTS:
        raise NotLocal("drivers talk only to this machine (localhost, 127.0.0.1): refusing %s" % url)


def http(method, url, body=None, headers=None, timeout=30, dry_body=b""):
    """Make one HTTP request to this machine and return the ``web.Response`` (a 4xx/5xx is returned).

    Only ``localhost``, ``127.0.0.1`` and ``::1`` are allowed (``NotLocal`` otherwise), through
    ``appstores_lib.web.request``. ``body``: bytes, text or a dict/list (JSON). Logged as ``> METHOD url``. Under
    ``--dry-run`` nothing is sent and a 200 with ``dry_body`` comes back. A connection that fails raises
    ``DriverError``.
    """
    check_local(url)
    note("  > %s %s" % (method, url))
    if DRY_RUN:
        return web.Response(200, {}, dry_body if isinstance(dry_body, bytes) else dry_body.encode("utf-8"))
    try:
        return web.request(method, url, headers=headers, body=body, timeout=timeout)
    except OSError as e:
        raise DriverError("%s %s: %s (is it running?)" % (method, url, e)) from None


def http_json(method, url, body=None, headers=None, timeout=30, dry_body=b"{}"):
    """Like ``http()``, but return the reply's JSON (``None`` for an empty body) and raise ``DriverError`` for a
    4xx/5xx or a reply that isn't JSON."""
    headers = dict(headers or {})
    headers.setdefault("Accept", "application/json")
    res = http(method, url, body=body, headers=headers, timeout=timeout, dry_body=dry_body)
    if res.status >= 400:
        raise DriverError("%s %s answered %d: %s" % (method, url, res.status, res.text()[:500].strip()))
    try:
        return res.json()
    except ValueError:
        raise DriverError("%s %s: the reply isn't JSON: %s" % (method, url, res.text()[:200])) from None


# -- steps and elements ---------------------------------------------------------------------------------------

def step_of(step):
    """Split a plan step (``{"tap": {"id": "search"}}``) into ``(kind, value)``; ``$comment`` and ``name`` (the step's
    handle for ``stepsPatch``) are ignored."""
    keys = [k for k in step if k not in STEP_META]
    if len(keys) != 1:
        raise ValueError("a step has exactly one kind, not %s" % (", ".join(keys) or "none"))
    return keys[0], step[keys[0]]


def describe_step(step):
    """A step in a few words, for logs and reasons: ``tap {id: search}``, ``deepLink samplerecipes://…``."""
    kind, value = step_of(step)
    if isinstance(value, dict):
        inner = ", ".join("%s: %s" % (k, value[k] if isinstance(value[k], str) else json.dumps(value[k]))
                          for k in value if k != "$comment")
        return "%s {%s}" % (kind, inner) if inner else kind
    if value is True or value is None:
        return kind
    return "%s %s" % (kind, value)


def step_element(kind, value):
    """The element a step acts on, as ``(finder, wanted)`` or ``None``: a ``type`` step's ``text`` is what it types
    (its field is ``id``/``label``/``xpath``/``css``, or ``into``: the field's text); a ``scroll`` step's is ``to``."""
    if not isinstance(value, dict):
        return None
    if kind == "type":
        target = dict((k, v) for k, v in value.items() if k != "text")
        if target.get("into") is not None:
            target["text"] = target.pop("into")
        return element_query(target)
    if kind == "scroll":
        return element_query(value.get("to"))
    if kind in ("fill", "hideKeyboard", "unfocus"):
        return None
    return element_query(value)


def fill_options(value):
    """A ``fill`` step's value as a dict: a list is its ``fields``."""
    if isinstance(value, list):
        return {"fields": value}
    return dict(value or {}) if isinstance(value, dict) else {}


def fill_fields(value):
    """A ``fill`` step's fields as ``[(query, text)]``: each entry's ``field`` is an element (``{"id": "servings"}``,
    ``{"text": "Servings"}``) or a string, which is an id. Raises ``ValueError`` for an entry without a field or
    text."""
    out = []
    for n, entry in enumerate(fill_options(value).get("fields") or [], 1):
        if not isinstance(entry, dict) or entry.get("text") is None:
            raise ValueError("fill's field %d needs a field and its text" % n)
        field = entry.get("field")
        query = ("id", field) if isinstance(field, str) and field else element_query(field)
        if query is None:
            raise ValueError("fill's field %d needs a field (an id, or an element: id, text, label, xpath, css)" % n)
        out.append((query, str(entry["text"])))
    return out


def step_elements(kind, value):
    """Every element a step names, as ``(finder, wanted)``: its own (``step_element``), a scroll's ``in``, a
    ``fill``'s fields, its ``in`` and ``scrollTo``, and the ``done`` and ``tap`` a ``hideKeyboard``, ``unfocus`` or a
    fill's ``keyboard`` taps. Raises ``ValueError`` when one names more than one way."""
    out = []

    def add(element):
        q = element_query(element)
        if q is not None:
            out.append(q)

    def add_keyboard(v):
        if isinstance(v, dict):
            add(v.get("done"))
            add(v.get("tap"))
            if isinstance(v.get("scroll"), dict):
                add(v["scroll"].get("in"))

    if kind == "fill":
        opts = fill_options(value)
        out.extend(q for q, _ in fill_fields(opts))
        add(opts.get("in"))
        add(opts.get("scrollTo"))
        add_keyboard(opts.get("keyboard"))
        return out
    if kind in ("hideKeyboard", "unfocus"):
        add_keyboard(value)
        return out
    own = step_element(kind, value)
    if own is not None:
        out.append(own)
    if kind == "scroll" and isinstance(value, dict):
        add(value.get("in"))
    return out


def typed(screen):
    """True when a screen's steps type something (a ``type`` or ``fill`` step)."""
    for st in screen.get("steps") or []:
        if isinstance(st, dict):
            try:
                if step_of(st)[0] in TYPING_STEPS:
                    return True
            except ValueError:
                continue
    return False


def describe_target(target):
    """A tap target in a few words: ``id 'title'``, ``(540, 300)``."""
    if isinstance(target, dict) and "x" in target and "y" in target:
        return "(%g, %g)" % (target["x"], target["y"])
    query = element_query(target)
    return describe_query(query) if query else json.dumps(target)


def describe_element(element):
    """An element found, in a few words: ``the field id 'servings'``."""
    for what, v in (("id", element.id), ("text", element.text), ("label", element.label)):
        if v:
            return "the field %s %r" % (what, v)
    return "a text field"


def focus_may_remain(screen, upto):
    """True when, before step ``upto`` (1-based), the screen typed (``type``, or a ``fill`` with ``"unfocus": false``
    or its keyboard kept) and no ``unfocus`` came after: a field may still have focus, and a caret."""
    left = False
    for i, st in enumerate(screen.get("steps") or [], 1):
        if i >= upto or not isinstance(st, dict):
            break
        try:
            kind, value = step_of(st)
        except ValueError:
            continue
        if kind == "type":
            left = True
        elif kind == "fill":
            opts = fill_options(value)
            keep = opts.get("keyboard") == "keep"
            left = not opts.get("unfocus", not keep)
        elif kind == "unfocus":
            left = False
    return left


def describe_query(query, contains=None):
    """An element check in a few words: ``id 'amount'``, ``id 'amount' containing '24'``."""
    out = "%s %r" % (query[0], query[1])
    return out + (" containing %r" % contains if contains is not None else "")


def element_query(value):
    """The element a step value names, as ``(finder, wanted)`` (``("id", "search")``), or ``None`` when it names
    none. Raises ``ValueError`` when it names more than one way."""
    if not isinstance(value, dict):
        return None
    found = [(k, value[k]) for k in FINDER_KEYS if value.get(k) is not None]
    if len(found) > 1:
        raise ValueError("an element is found one way, not by %s" % " and ".join(k for k, _ in found))
    return found[0] if found else None


class Element(object):
    """An element on screen, as a UI tree describes it: ``id`` (resource / accessibility id), ``text``,
    ``label`` (content description / accessibility label), ``cls`` (its class or role), ``bounds``
    ``(left, top, right, bottom)`` in screen pixels (or ``None``) and ``attrs`` (everything the tree said)."""

    def __init__(self, id=None, text=None, label=None, cls=None, bounds=None, attrs=None, node=None):
        """Describe one element (``node``: its node in the tree it was read from, when there is one, for what's
        under it)."""
        self.id = id or None
        self.text = text or None
        self.label = label or None
        self.cls = cls or None
        self.bounds = bounds
        self.attrs = dict(attrs or {})
        self.node = node

    @property
    def center(self):
        """The middle of its bounds as integer ``(x, y)``, or ``None`` without bounds."""
        if not self.bounds:
            return None
        left, top, right, bottom = self.bounds
        return (left + right) // 2, (top + bottom) // 2

    def __repr__(self):
        return "Element(id=%r, text=%r, label=%r, bounds=%r)" % (self.id, self.text, self.label, self.bounds)


def parse_bounds(text):
    """UI Automator's ``[left,top][right,bottom]`` as a tuple of ints, or ``None``."""
    try:
        a, b = text.strip("[]").split("][")
        left, top = (int(v) for v in a.split(","))
        right, bottom = (int(v) for v in b.split(","))
        return left, top, right, bottom
    except (ValueError, AttributeError):
        return None


def parse_uiautomator(xml_text):
    """Parse a ``uiautomator dump`` and return ``(root, elements)``: the ElementTree root (for ``xpath``) and an
    ``Element`` for every ``node`` (``resource-id`` -> ``id``, ``content-desc`` -> ``label``). Raises
    ``DriverError`` when it isn't the XML a dump writes."""
    start = xml_text.find("<?xml")
    if start < 0:
        start = xml_text.find("<hierarchy")
    end = xml_text.rfind("</hierarchy>")
    if start < 0 or end < 0:
        raise DriverError("uiautomator didn't return a UI tree: %s" % xml_text[:200].strip())
    try:
        root = ET.fromstring(xml_text[start:end + len("</hierarchy>")])
    except ET.ParseError as e:
        raise DriverError("uiautomator's UI tree isn't XML: %s" % e) from None
    elements = []
    for node in root.iter("node"):
        a = node.attrib
        elements.append(Element(id=a.get("resource-id"), text=a.get("text"), label=a.get("content-desc"),
                                cls=a.get("class"), bounds=parse_bounds(a.get("bounds", "")), attrs=a, node=node))
    return root, elements


def _id_matches(have, wanted):
    if not have:
        return False
    return have == wanted or have.endswith(":id/" + wanted) or have.endswith("/" + wanted)


def find_elements(elements, finder, wanted):
    """Every one of ``elements`` that ``finder`` (``id``, ``text`` or ``label``) matches, best first.

    ``id`` matches the whole id or its last part (``com.example.samplerecipes:id/search`` for ``search``);
    ``text`` and ``label`` match exactly first, then ignoring case and surrounding space, then as a part of it.
    Elements without bounds (or empty ones) come last.
    """
    sized = [e for e in elements if e.bounds and e.bounds[2] > e.bounds[0] and e.bounds[3] > e.bounds[1]]
    pool = sized + [e for e in elements if e not in sized]
    if finder == "id":
        return [e for e in pool if _id_matches(e.id, wanted)]
    if finder not in ("text", "label"):
        raise ValueError("find_element finds by id, text or label, not %r" % finder)
    get = (lambda e: e.text) if finder == "text" else (lambda e: e.label)
    w = str(wanted)
    out = []
    for test in (lambda v: v == w, lambda v: v.strip().lower() == w.strip().lower(),
                 lambda v: w.strip().lower() in v.lower()):
        for e in pool:
            v = get(e)
            if v and test(v) and e not in out:
                out.append(e)
    return out


def find_element(elements, finder, wanted):
    """The first of ``elements`` that ``finder`` (``id``, ``text`` or ``label``) matches, or ``None``
    (``find_elements``' best)."""
    found = find_elements(elements, finder, wanted)
    return found[0] if found else None


def _norm(text):
    return " ".join(str(text).split()).lower()


def texts_contain(texts, wanted):
    """True when one of ``texts`` contains ``wanted``, ignoring case and runs of space (``"24"`` is in ``"24 oz"``
    and in ``"Add  24"``)."""
    w = _norm(wanted)
    return bool(w) and any(w in _norm(t) for t in texts if t not in (None, ""))


def node_texts(node):
    """What a tree node and every node under it show (``TEXT_ATTRS``), in document order."""
    out = []
    for n in node.iter():
        for a in TEXT_ATTRS:
            v = n.attrib.get(a)
            if v:
                out.append(v)
    return out


def element_texts(element):
    """What an element shows, and what's under it where the driver read a tree: its ``text``, its attributes'
    ``TEXT_ATTRS``, its node's descendants and an agent item's ``children``."""
    out = [element.text]
    for a in TEXT_ATTRS:
        v = element.attrs.get(a)
        if isinstance(v, str) and v:
            out.append(v)
    if element.node is not None:
        out.extend(node_texts(element.node))
    stack = list(element.attrs.get("children") or []) if isinstance(element.attrs.get("children"), list) else []
    while stack:
        item = stack.pop(0)
        if not isinstance(item, dict):
            continue
        for a in TEXT_ATTRS:
            v = item.get(a)
            if isinstance(v, str) and v:
                out.append(v)
        stack.extend(item.get("children") or [])
    return [t for t in out if t]


def matching(root, elements, query):
    """Every element ``query`` (``(finder, wanted)``) finds in a tree read once: ``root`` (for ``xpath``) and its
    ``elements`` (each with its ``node``), best first."""
    finder, wanted = query
    if finder != "xpath":
        return find_elements(elements, finder, wanted)
    by_node = dict((id(e.node), e) for e in elements if e.node is not None)
    try:
        nodes = xpath_all(root, wanted)
    except XPathError:
        node = xpath_first(root, wanted)
        nodes = [node] if node is not None else []
    out = []
    for node in nodes:
        e = by_node.get(id(node))
        if e is None:
            a = node.attrib
            e = Element(id=a.get("resource-id"), text=a.get("text"), label=a.get("content-desc"),
                        cls=a.get("class"), bounds=parse_bounds(a.get("bounds", "")), attrs=a, node=node)
        out.append(e)
    return out


def first_containing(root, elements, query, wanted):
    """The first element ``query`` finds in a tree whose texts, or its descendants', contain ``wanted``
    (``texts_contain``), or ``None``: ``{"id": "amount", "contains": "24"}`` on a chip that shows 24 itself (iOS's
    label) or on a child (Android's text)."""
    for e in matching(root, elements, query):
        if texts_contain(element_texts(e), wanted):
            return e
    return None


# The kinds of view that scroll their content, by the end of their class or type in the trees the drivers read
# (Android's ScrollView, NestedScrollView, RecyclerView, ListView; XCUITest's ScrollView, Table, CollectionView; a
# Mac's Outline; an agent's ScrollView, CollectionView, ListView; WinUI's ScrollViewer): what a scroll's ``in``
# resolves to where the tree has no ``scrollable`` flag of its own.
SCROLLING_TYPES = re.compile(r"(ScrollView|ScrollViewer|RecyclerView|ListView|GridView|CollectionView|TableView|"
                             r"ElementTypeTable|ElementTypeOutline|ScrollPane)$")


def scrolls(node):
    """True when a tree node is one that scrolls its content: ``scrollable="true"`` (UI Automator's dump, Appium's
    Android source), or, where the tree has no such flag, its class, type or tag (``SCROLLING_TYPES``)."""
    a = node.attrib
    for flag in ("scrollable", "isScrollable"):
        if flag in a:
            return str(a[flag]).lower() == "true"
    kind = a.get("class") or a.get("type") or node.tag or ""
    return bool(SCROLLING_TYPES.search(str(kind)))


def _parents(root):
    return dict((child, parent) for parent in root.iter() for child in parent)


def nearest_scrolling(root, node, scrollable=scrolls):
    """The nearest of ``node`` and its ancestors in the tree ``root`` that scrolls (``scrollable``), or ``None``."""
    parents = _parents(root)
    while node is not None:
        if scrollable(node):
            return node
        node = parents.get(node)
    return None


def pane_in_tree(root, elements, query, scrollable=scrolls):
    """What a scroll's ``in`` (``query``) scrolls, read from one tree: ``(node, how)``, the nearest scrolling view
    that is the element or holds it (``how``: ``self`` or ``ancestor``), or, with none, the element's own node
    (``none``); ``None`` when the tree doesn't show the element."""
    found = [e for e in matching(root, elements, query) if e.node is not None]
    if not found:
        return None
    node = found[0].node
    pane = nearest_scrolling(root, node, scrollable)
    if pane is None:
        return node, "none"
    return pane, ("self" if pane is node else "ancestor")


def describe_node(node):
    """A tree node in a few words, for the report: its class or type, its id and where it is
    (``android.widget.ScrollView id 'pane' [600,200][1080,1920]``)."""
    a = node.attrib
    parts = [str(a.get("class") or a.get("type") or node.tag)]
    for key in ("resource-id", "name", "automationId", "identifier", "AutomationId"):
        if a.get(key):
            parts.append("id %r" % a[key].split(":id/")[-1])
            break
    if a.get("bounds"):
        parts.append(a["bounds"])
    elif all(a.get(k) not in (None, "") for k in ("x", "y", "width", "height")):
        parts.append("at (%s, %s), %s x %s" % (a["x"], a["y"], a["width"], a["height"]))
    return " ".join(parts)


def absolute_xpath(root, node):
    """An xpath from ``root`` to ``node`` by tag and position (``/hierarchy/android.widget.FrameLayout[1]/…``), to
    find it again in the same tree on a server that evaluates XPath over it (Appium's)."""
    parents = _parents(root)
    steps = []
    while node is not None and node is not root:
        parent = parents.get(node)
        if parent is None:
            break
        same = [c for c in parent if c.tag == node.tag]
        steps.append("%s[%d]" % (node.tag, same.index(node) + 1))
        node = parent
    return "/" + "/".join([root.tag] + list(reversed(steps)))


def posture_of(value):
    """A posture as the plan's word (``folded``, ``open``, ``half-open``), taking the other tools' words for the same
    (``unfolded``, ``closed``, ``partially-folded``, ``tabletop``, ``book``); ``ValueError`` for anything else."""
    if isinstance(value, dict):
        value = value.get("posture") or value.get("mode")
    word = str(value or "").strip().lower()
    word = POSTURE_ALIASES.get(word, word)
    if word not in POSTURES:
        raise ValueError("a posture is %s, not %r" % (", ".join(POSTURES), value))
    return word


# -- XPath over a UI tree ----------------------------------------------------------------------------------------
#
# ElementTree's own XPath has no functions (no contains(), not(), and/or), so a plan's cross-platform xpath
# (``//*[contains(@text,'Raise') or contains(@label,'Raise')]``) failed on the drivers that read a tree themselves
# (adb, uiautomator, the in-app agents). This is XPath 1.0's everyday part: absolute and relative location paths
# with ``/`` and ``//``, ``*``, ``.``, ``..``, names, ``@attr``, predicates (positions, ``=``, ``!=``, ``<``, ``>``,
# ``and``, ``or``, parentheses) and the functions ``contains``, ``starts-with``, ``ends-with``, ``not``,
# ``normalize-space``, ``translate``, ``lower-case``, ``upper-case``, ``string``, ``concat``, ``string-length``,
# ``text``, ``name``, ``position``, ``last``, ``true``, ``false``, ``boolean``, ``number``. No other axes, no unions.

class XPathError(ValueError):
    """An xpath this evaluator doesn't understand."""


_XTOKEN = re.compile(r"\s*(?:(//|/|\[|\]|\(|\)|,|@|!=|<=|>=|=|<|>|\.\.|\.|\*|\|)|(\"[^\"]*\"|'[^']*')|"
                     r"(\d+(?:\.\d+)?)|([A-Za-z_][\w.\-]*))")
_XFUNCS = ("contains", "starts-with", "ends-with", "not", "normalize-space", "translate", "lower-case", "upper-case",
           "string", "concat", "string-length", "text", "name", "local-name", "position", "last", "true", "false",
           "boolean", "number")


def _xtokens(expr):
    out, pos = [], 0
    expr = expr.strip()
    while pos < len(expr):
        m = _XTOKEN.match(expr, pos)
        if not m or m.end() == pos:
            raise XPathError("can't read %r at %r" % (expr, expr[pos:pos + 12]))
        op, lit, num, name = m.groups()
        if op is not None:
            out.append(("op", op))
        elif lit is not None:
            out.append(("str", lit[1:-1]))
        elif num is not None:
            out.append(("num", float(num)))
        else:
            out.append(("name", name))
        pos = m.end()
    return out


class _XParser(object):
    """A recursive-descent parser for the XPath subset; ``parse()`` returns a tuple tree."""

    def __init__(self, expr):
        self.toks = _xtokens(expr)
        self.i = 0

    def peek(self, k=0):
        return self.toks[self.i + k] if self.i + k < len(self.toks) else (None, None)

    def take(self, kind=None, value=None):
        tok = self.peek()
        if tok[0] is None or (kind and tok[0] != kind) or (value is not None and tok[1] != value):
            raise XPathError("expected %s, found %r" % (value or kind, tok[1]))
        self.i += 1
        return tok

    def at(self, kind, value=None):
        tok = self.peek()
        return tok[0] == kind and (value is None or tok[1] == value)

    def parse(self):
        node = self.expr()
        if self.i != len(self.toks):
            raise XPathError("unexpected %r" % (self.peek()[1],))
        return node

    def expr(self):
        left = self.and_expr()
        while self.at("name", "or"):
            self.take()
            left = ("or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.cmp_expr()
        while self.at("name", "and"):
            self.take()
            left = ("and", left, self.cmp_expr())
        return left

    def cmp_expr(self):
        left = self.primary()
        while self.peek()[0] == "op" and self.peek()[1] in ("=", "!=", "<", ">", "<=", ">="):
            op = self.take()[1]
            left = ("cmp", op, left, self.primary())
        return left

    def primary(self):
        kind, value = self.peek()
        if kind == "op" and value == "(":
            self.take()
            inner = self.expr()
            self.take("op", ")")
            preds = []
            while self.at("op", "["):
                self.take()
                preds.append(self.expr())
                self.take("op", "]")
            return ("filter", inner, preds) if preds else inner
        if kind in ("str", "num"):
            self.take()
            return ("lit", value)
        if kind == "name" and self.peek(1) == ("op", "("):
            if value not in _XFUNCS:
                raise XPathError("the function %s() isn't supported" % value)
            self.take()
            self.take("op", "(")
            args = []
            while not self.at("op", ")"):
                args.append(self.expr())
                if self.at("op", ","):
                    self.take()
                elif not self.at("op", ")"):
                    raise XPathError("expected , or ) in %s()" % value)
            self.take("op", ")")
            return ("call", value, args)
        if kind == "op" and value == "@":
            self.take()
            return ("attr", self.take()[1] if self.at("op", "*") else self.take("name")[1])
        return self.path()

    def path(self):
        absolute = None
        if self.at("op", "//") or self.at("op", "/"):
            absolute = self.take()[1]
        steps = []
        sep = absolute or "/"
        while True:
            kind, value = self.peek()
            if kind == "op" and value in ("*", ".", ".."):
                self.take()
                test = value
            elif kind == "name":
                self.take()
                test = value
            elif kind == "op" and value == "@":
                self.take()
                test = "@" + self.take("name")[1]
            elif absolute == "/" and not steps:
                return ("path", True, [])
            else:
                raise XPathError("expected a step, found %r" % (value,))
            preds = []
            while self.at("op", "["):
                self.take()
                preds.append(self.expr())
                self.take("op", "]")
            steps.append((sep, test, preds))
            if self.at("op", "//") or self.at("op", "/"):
                sep = self.take()[1]
                continue
            break
        return ("path", absolute is not None, steps)


class _XDoc(object):
    """The document node above a tree's root (so ``/hierarchy`` and ``//node`` mean what XPath says)."""

    def __init__(self, root):
        self.root = root
        self.tag = "#document"
        self.attrib = {}
        self.text = None

    def __iter__(self):
        return iter([self.root])


def _xstr(v):
    if isinstance(v, list):
        if not v:
            return ""
        first = v[0]
        return first if isinstance(first, str) else (first.text or "")
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return str(int(v)) if v == v and v == int(v) else repr(v)
    return str(v)


def _xnum(v):
    try:
        return float(_xstr(v).strip())
    except ValueError:
        return float("nan")


def _xbool(v):
    if isinstance(v, list):
        return bool(v)
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return v == v and v != 0
    return bool(v)


def _is_number(v):
    return isinstance(v, float) and not isinstance(v, bool)


def _xcompare(op, a, b):
    if isinstance(a, list) or isinstance(b, list):
        left = [_xstr([x]) for x in a] if isinstance(a, list) else [a]
        right = [_xstr([y]) for y in b] if isinstance(b, list) else [b]
        return any(_xcompare(op, x, y) for x in left for y in right)
    if op in ("=", "!="):
        if isinstance(a, bool) or isinstance(b, bool):
            same = _xbool(a) == _xbool(b)
        elif _is_number(a) or _is_number(b):
            same = _xnum(a) == _xnum(b)
        else:
            same = _xstr(a) == _xstr(b)
        return same if op == "=" else not same
    x, y = _xnum(a), _xnum(b)
    return {"<": x < y, ">": x > y, "<=": x <= y, ">=": x >= y}[op]


class _XEval(object):
    """Evaluates a parsed xpath over an ElementTree root."""

    def __init__(self, root):
        self.doc = _XDoc(root)
        self.parents = {root: self.doc}
        for parent in root.iter():
            for child in parent:
                self.parents[child] = parent

    def descendants_or_self(self, node):
        out = [node]
        for child in list(node):
            out.extend(self.descendants_or_self(child))
        return out

    def step(self, contexts, sep, test, preds):
        out, seen = [], set()
        for ctx in contexts:
            if isinstance(ctx, str):
                continue
            for b in (self.descendants_or_self(ctx) if sep == "//" else [ctx]):
                if test == ".":
                    cands = [b]
                elif test == "..":
                    cands = [self.parents[b]] if b in self.parents else []
                elif test.startswith("@"):
                    cands = [b.attrib[test[1:]]] if test[1:] in b.attrib else []
                else:
                    cands = [c for c in list(b) if test == "*" or c.tag == test]
                for c in self.filter(cands, preds):
                    key = (id(b), c) if isinstance(c, str) else id(c)
                    if key not in seen:
                        seen.add(key)
                        out.append(c)
        return out

    def filter(self, nodes, preds):
        for pred in preds:
            size = len(nodes)
            nodes = [c for pos, c in enumerate(nodes, 1)
                     for v in [self.eval(pred, c, pos, size)] if ((v == pos) if _is_number(v) else _xbool(v))]
        return nodes

    def eval(self, node, ctx, pos=1, size=1):
        kind = node[0]
        if kind == "lit":
            return node[1]
        if kind == "filter":
            found = self.eval(node[1], ctx, pos, size)
            if not isinstance(found, list):
                raise XPathError("only a path can be filtered with [...]")
            return self.filter(found, node[2])
        if kind == "or":
            return _xbool(self.eval(node[1], ctx, pos, size)) or _xbool(self.eval(node[2], ctx, pos, size))
        if kind == "and":
            return _xbool(self.eval(node[1], ctx, pos, size)) and _xbool(self.eval(node[2], ctx, pos, size))
        if kind == "cmp":
            return _xcompare(node[1], self.eval(node[2], ctx, pos, size), self.eval(node[3], ctx, pos, size))
        if kind == "attr":
            if ctx is None or isinstance(ctx, str):
                return []
            if node[1] == "*":
                return list(ctx.attrib.values())
            return [ctx.attrib[node[1]]] if node[1] in ctx.attrib else []
        if kind == "path":
            _, absolute, steps = node
            contexts = [self.doc] if absolute or ctx is None else [ctx]
            for sep, test, preds in steps:
                contexts = self.step(contexts, sep, test, preds)
            return contexts
        return self.call(node[1], node[2], ctx, pos, size)

    def call(self, name, args, ctx, pos, size):
        a = [self.eval(x, ctx, pos, size) for x in args]
        here = [ctx] if ctx is not None else []
        if name == "position":
            return float(pos)
        if name == "last":
            return float(size)
        if name in ("true", "false"):
            return name == "true"
        if name in ("not", "boolean"):
            if not a:
                raise XPathError("%s() needs an argument" % name)
            return (not _xbool(a[0])) if name == "not" else _xbool(a[0])
        if name == "number":
            return _xnum(a[0] if a else here)
        if name == "text":
            text = None if ctx is None or isinstance(ctx, str) else ctx.text
            return [text] if text else []
        if name in ("name", "local-name"):
            return "" if ctx is None or isinstance(ctx, str) else str(ctx.tag)
        if name == "string":
            return _xstr(a[0] if a else here)
        if name == "string-length":
            return float(len(_xstr(a[0] if a else here)))
        if name == "normalize-space":
            return " ".join(_xstr(a[0] if a else here).split())
        if name == "concat":
            return "".join(_xstr(v) for v in a)
        if name in ("lower-case", "upper-case"):
            s = _xstr(a[0] if a else here)
            return s.lower() if name == "lower-case" else s.upper()
        if len(a) < 2:
            raise XPathError("%s() needs two arguments" % name)
        s, t = _xstr(a[0]), _xstr(a[1])
        if name == "contains":
            return t in s
        if name == "starts-with":
            return s.startswith(t)
        if name == "ends-with":
            return s.endswith(t)
        to = _xstr(a[2]) if len(a) > 2 else ""
        table = {}
        for i, ch in enumerate(t):
            table.setdefault(ord(ch), to[i] if i < len(to) else None)
        return s.translate(table)


def xpath_all(root, expr):
    """Every element ``expr`` selects in an ElementTree ``root`` (XPath 1.0's everyday part, above). Raises
    ``XPathError`` for an xpath it can't read, or one that isn't a path to elements."""
    tree = _XParser(expr).parse()
    if tree[0] not in ("path", "filter"):
        raise XPathError("an xpath that finds elements is a path (//node[...]), not %r" % expr)
    found = _XEval(root).eval(tree, None)
    return [n for n in found if not isinstance(n, (str, _XDoc))]


def xpath_first(root, expr):
    """The first element ``expr`` selects in ``root`` (``xpath_all``), or ``None``. An xpath this evaluator can't
    read is tried with ElementTree's own subset before giving up with ``StepFailed``."""
    try:
        found = xpath_all(root, expr)
        return found[0] if found else None
    except XPathError as e:
        problem = e
    rel = "." + expr if expr.startswith("/") else expr
    try:
        return root.find(rel)
    except (SyntaxError, KeyError):
        raise StepFailed("the xpath %r isn't one this driver understands: %s" % (expr, problem)) from None


def find_xpath(root, expr, elements=None):
    """The first node an XPath finds in a UI tree, as an ``Element``, or ``None``.

    XPath 1.0's everyday part (``xpath_all``): ``//node[@resource-id='…']``, ``//*[contains(@text,'Raise') or
    contains(@content-desc,'Raise')]``, ``//node[not(@text='')][2]``, ``..``, positions. A leading ``//`` searches
    the whole tree.
    """
    node = xpath_first(root, expr)
    if node is None:
        return None
    a = node.attrib
    return Element(id=a.get("resource-id"), text=a.get("text"), label=a.get("content-desc"), cls=a.get("class"),
                   bounds=parse_bounds(a.get("bounds", "")), attrs=a, node=node)


def masked_sha256(path, rects):
    """A picture's SHA-256 over its pixels with ``rects`` (``[x, y, width, height]``) blanked out."""
    width, height, rgb = png.decode_rgb(path)
    buf = bytearray(rgb)
    for rect in rects or []:
        x, y, w, h = (int(v) for v in rect)
        x0, x1 = max(0, x), min(width, x + w)
        if x1 <= x0:
            continue
        for row in range(max(0, y), min(height, y + h)):
            buf[(row * width + x0) * 3:(row * width + x1) * 3] = bytes((x1 - x0) * 3)
    return hashlib.sha256(bytes(buf)).hexdigest()


def file_sha256(path):
    """A file's SHA-256 (hex)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# -- the driver ------------------------------------------------------------------------------------------------

class Driver(object):
    """The base class every driver extends. Subclasses set ``NAME``, ``PLATFORMS``, ``STEPS`` and ``FINDERS``
    and implement ``prepare``, ``screenshot``, ``reset`` and their ``step_<kind>`` methods; most keep the base
    ``run_screen``.

    ``self.options`` is the ``Options`` from ``capture.py``; ``self.state`` remembers what's been applied (the
    locale, appearance, status bar) so ``enter_screen`` changes only what differs, and ``self.changed`` what to
    put back in ``reset``.
    """

    NAME = "base"
    PLATFORMS = ()          # the plan platforms it can capture: "ios", "android", "web", "macos", ...
    STEPS = ("wait", "settle", "script")   # step kinds it handles
    FINDERS = ()            # element finders it understands ("id", "text", "label", "xpath", "css")
    POSTURE_SETTING = False  # a device's or screen's posture is applied before the steps (a flow driver's, say)
    CONTAINS = True         # with FINDERS: it can check what an element shows ({"id": …, "contains": …})
    SETTLE_TIMEOUT = 5.0    # seconds settle waits for two identical frames
    WAIT_TIMEOUT = 10.0     # seconds a wait for an element waits by default

    def __init__(self, options=None):
        """Set the driver up with ``capture.py``'s ``Options`` (nothing runs yet)."""
        self.options = options or Options()
        self.state = {}
        self.changed = {}
        self.status_bar = "none"
        self.warnings = []
        self._recording = None

    # The four calls capture.py makes (CONTRACT.md 10.3).

    def capabilities(self):
        """What this driver can do: ``{"name", "platforms", "steps", "finders"}`` (lists)."""
        return {"name": self.NAME, "platforms": list(self.PLATFORMS), "steps": list(self.STEPS),
                "finders": list(self.FINDERS)}

    def prepare(self, device, plan):
        """Get ``device`` ready once before its screens: find or create and boot it, install the app, anything
        that doesn't change per locale or screen. ``device`` is resolved (``capture.resolve_device``: the plan's
        settings with the device's overrides, its ``app`` entry, its ``target``); ``plan`` is the whole plan.
        Raise ``DriverError`` (or ``ToolMissing``) when it can't; every shot of the device is then missed.
        Locale, appearance and status bar are applied per screen by ``enter_screen``."""
        raise NotImplementedError

    def run_screen(self, device, screen, locale):
        """Reach one screen in one locale and capture it; return a ``Shot`` (never raise for an ordinary
        failure: a ``DriverError`` becomes a ``missed`` shot here).

        The base version: return ``skipped`` if the screen has a step this driver can't do (``unsupported``);
        apply the locale, appearance and status bar (``enter_screen``); run each step (``step_<kind>``); then
        ``screenshot`` into the workdir. Drivers whose tool does everything at once (a UI test, a flow) override it.
        """
        shot = Shot(source=self.source(device), status_bar="none")
        why = self.unsupported(screen, device)
        if why:
            shot.status = "skipped"
            shot.reason = why
            return shot
        ctx = StepContext(device, screen, locale, shot, 0, None)
        record_at = self.record_from(screen) if self.recording_wanted() else None
        try:
            self.enter_screen(device, screen, locale, shot)
            shot.source = self.source(device)   # what entering changed (a posture) is in the report too
            if self.recording_wanted() and not record_at:
                ctx.warn("nothing recorded: the screen has no steps")
            for i, step in enumerate(screen.get("steps") or [], 1):
                ctx = StepContext(device, screen, locale, shot, i, step)
                if i == record_at:
                    self.begin_recording(ctx)
                self.do_step(ctx)
            self.end_recording(ctx)
            self.check_state(ctx, screen, shot)
            self.save_tree(ctx, shot)
            path = self.shot_path(device, screen, locale)
            self.screenshot(device, path)
        except StepSkipped as e:
            shot.status = "skipped"
            shot.reason = mask(str(e))
            return shot
        except DriverError as e:
            if isinstance(e, ToolMissing):
                raise
            shot.status = "missed"
            shot.reason = mask(str(e))
            self.save_tree(ctx, shot)
            return shot
        finally:
            self.abandon_recording(device)
        shot.path = path
        shot.status_bar = self.status_bar
        return shot

    def check_state(self, ctx, screen, shot):
        """The screen's ``verify``: each element (``id``, ``text``, ``label``, ``xpath``, ``css``; ``timeout``
        seconds, default 5) must be on screen before the shot, else ``WrongState`` (the shot is ``missed``, "wrong
        state", and says what the screen should show: its ``state``). A driver that can't see elements can't
        check: ``unchecked``, with a warning to look at the picture.

        The keyboard too (``check_keyboard``): ``{"keyboard": "hidden"}`` (or ``"shown"``) in ``verify`` asks for it;
        a screen that types nothing is checked for ``hidden`` without asking, where the driver can tell."""
        checks = screen.get("verify")
        checks = [checks] if isinstance(checks, dict) else list(checks or [])
        keyboard = [c for c in checks if isinstance(c, dict) and "keyboard" in c]
        elements = [c for c in checks if isinstance(c, dict) and "keyboard" not in c]
        if not elements and not keyboard:
            shot.state_check = "none"
        unchecked = []
        for check in elements:
            query = element_query(check)
            if query is None:
                continue
            contains = check.get("contains")
            if query[0] not in self.FINDERS or (contains is not None and not self.CONTAINS):
                unchecked.append(describe_query(query, contains))
                continue
            timeout = float(check.get("timeout") if check.get("timeout") is not None else 5)
            note("  verify %s" % describe_query(query, contains))
            try:
                self.wait_for(ctx, query, timeout, contains)
            except StepFailed:
                shot.state_check = "failed"
                state = screen.get("state")
                raise WrongState("wrong state: %s wasn't on screen within %g s%s" % (
                    describe_query(query, contains), timeout,
                    (" (the screen should show: %s)" % state) if state else ""))
        if not self.check_keyboard(ctx, screen, shot, keyboard[-1] if keyboard else None):
            unchecked.append("the keyboard")
        if unchecked:
            shot.state_check = "unchecked"
            ctx.warn("verify not checked: the %s driver can't find %s; look at the picture for it"
                     % (self.NAME, ", ".join(unchecked)))
            return
        if elements or keyboard:
            shot.state_check = "passed"

    def check_keyboard(self, ctx, screen, shot, rule):
        """The keyboard part of ``verify``: ``rule`` is ``{"keyboard": "hidden"|"shown"|"any", "timeout": s}``, or
        ``None`` for the default (``hidden`` when the screen's steps type nothing; with typing, nothing is asked,
        but a keyboard left up is a warning). ``WrongState`` when it isn't so; returns False when an asked-for
        check couldn't be made (the driver can't see the keyboard: ``keyboard_shown`` is ``None``)."""
        types = typed(screen)
        wanted = (rule or {}).get("keyboard")
        if wanted == "any":
            return True
        implicit = wanted is None
        if implicit:
            wanted = None if types else "hidden"
        shown = self.keyboard_shown(ctx)
        if shown is None:
            return implicit
        if wanted is None:
            if shown:
                ctx.warn("the keyboard is up in this shot: if it shouldn't be, end the steps with hideKeyboard and "
                         "add {\"keyboard\": \"hidden\"} to verify")
            return True
        want_shown = wanted == "shown"
        if shown != want_shown:
            timeout = float((rule or {}).get("timeout") or 2)
            try:
                poll(lambda: self.keyboard_shown(ctx) == want_shown, timeout, interval=0.5,
                     what="the keyboard to be %s" % wanted)
            except StepFailed:
                shot.state_check = "failed"
                state = screen.get("state")
                raise WrongState("wrong state: the keyboard is %s%s (end the steps with hideKeyboard; %s)%s" % (
                    "up" if shown else "down", "" if not implicit else ", and the screen types nothing",
                    "verify {\"keyboard\": \"any\"} allows it" if implicit else "or change verify's keyboard",
                    (" (the screen should show: %s)" % state) if state else ""))
        note("  verify keyboard %s" % wanted)
        return True

    def keyboard_shown(self, ctx):
        """True when the on-screen keyboard is up, False when it isn't, ``None`` when this driver can't tell (the
        base can't)."""
        return None

    def save_tree(self, ctx, shot):
        """With ``capture.py --inspect``: write the screen's UI tree (``inspect_tree``) beside its picture in the
        workdir and remember it in ``shot.tree``; a driver that can't read one says so in the file."""
        if not self.options.extra.get("inspect") or shot.tree or DRY_RUN:
            return
        folder = os.path.join(self.options.workdir, "inspect", ctx.locale, ctx.device["id"])
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, ctx.screen["id"] + ".txt")
        try:
            text = self.inspect_tree(ctx)
        except (DriverError, StepSkipped) as e:
            text = "(no UI tree: %s)" % e
        with open(path, "w", encoding="utf-8") as f:
            f.write(mask(text if isinstance(text, str) else json.dumps(text, indent=1, ensure_ascii=False)))
            f.write("\n")
        shot.tree = path

    def inspect_tree(self, ctx):
        """The screen's UI tree as text (the device's XML, the agent's JSON, Appium's page source), for writing
        steps: ``capture.py --inspect``. Drivers that can see elements implement it."""
        raise StepSkipped("the %s driver can't read a UI tree" % self.NAME)

    def reset(self, device):
        """Put back everything ``prepare`` and the screens changed (status bar, demo mode, display size, locale,
        appearance, permissions), stop what this driver started, and delete what it created only with
        ``options.cleanup``. Always called (in ``finally``), even after ``prepare`` failed part-way, so check
        ``self.changed`` and ``self.state`` rather than assuming. Return a list of warnings (what couldn't be put
        back); don't raise for one failed restore: try the rest."""
        return []

    # Recording a screen's steps (capture.py --record).

    RECORD_TAIL = 1.0       # seconds recorded after the last step, so its settled frames are in

    def recording_wanted(self):
        """True under ``capture.py --record``."""
        return bool(self.options.extra.get("record"))

    def record_support(self, device):
        """Why this driver can't record ``device``'s screen (a reason), or ``None`` when it can. Recording is the
        device's: a simulator (``simctl``, and the drivers it hosts) or an Android device (``adb``, and those it
        hosts)."""
        return "the %s driver can't record a screen: --record records a simulator (simctl, or appium, xcuitest, " \
               "devflow, ailoha or maestro on one) or an Android device (adb, uiautomator, or a driver adb hosts)" \
               % self.NAME

    def recording_ext(self, device):
        """The recording's file extension (``.mov`` from a simulator, ``.mp4`` from Android)."""
        return ".mp4"

    def start_recording(self, device, path):
        """Start recording the device's screen into ``path``; return what ``stop_recording`` needs (a dict).
        Raise ``DriverError`` when it can't."""
        raise StepSkipped(self.record_support(device))

    def stop_recording(self, device, rec, shot):
        """Stop the recording ``start_recording`` began, with its file finished at ``rec["file"]``; return the
        report's words for it: ``{"file", "seconds", "by", "display", "flush"}``. Raise ``DriverError`` when there's
        no file."""
        raise StepSkipped(self.record_support(device))

    def discard_recording(self, device, rec):
        """Stop a recording a failed step left running (nothing is kept)."""

    def record_from(self, screen):
        """The step a recording starts at (1-based): the screen's first ``launch``, after any seed and the reboot a
        locale change needs; with no launch, its first step; ``None`` with no steps."""
        steps = screen.get("steps") or []
        for i, step in enumerate(steps, 1):
            try:
                if step_of(step)[0] == "launch":
                    return i
            except ValueError:
                continue
        return 1 if steps else None

    def begin_recording(self, ctx):
        """Start recording before ``ctx``'s step, into the workdir beside the screen's picture."""
        if not self.recording_wanted() or self._recording is not None:
            return
        path = os.path.splitext(self.shot_path(ctx.device, ctx.screen, ctx.locale))[0] + \
            self.recording_ext(ctx.device)
        note("  record from step %d (%s)" % (ctx.index, describe_step(ctx.step) if ctx.step else "the run"))
        rec = self.start_recording(ctx.device, path)
        rec.setdefault("file", path)
        rec["from"] = "step %d (%s)" % (ctx.index, describe_step(ctx.step)) if ctx.step else "the run"
        self._recording = rec

    def end_recording(self, ctx):
        """After the last step (before ``verify``, the screenshot and ``reset``): stop the recording and put what
        it made in ``ctx.shot.recording``."""
        rec = self._recording
        if rec is None:
            return
        self._recording = None
        info = self.stop_recording(ctx.device, rec, ctx.shot)
        info.setdefault("file", rec["file"])
        info["from"] = rec["from"]
        ctx.shot.recording = info
        if not DRY_RUN:
            note("  recorded %.1f s%s" % (info.get("seconds") or 0, (" (trim at %.2f s: the flush)" % info["flush"][
                "at"]) if info.get("flush") else ""))

    def abandon_recording(self, device):
        """A recording still running when a screen stopped early: stop it, keep nothing."""
        rec = self._recording
        if rec is None:
            return
        self._recording = None
        try:
            self.discard_recording(device, rec)
        except Exception:  # noqa: BLE001 - the screen's own error is the one to report
            pass

    def recorded(self, ctx, run, cached=False):
        """``run()`` (a tool that does a screen's steps at once: a UI test, a flow) recorded under ``--record``;
        ``cached``: it ran already for another screen, so there's nothing new to record (a warning says so)."""
        if not self.recording_wanted():
            return run()
        if cached:
            ctx.warn("nothing recorded: %s ran once for several screens, recorded with the first" % (
                describe_step(ctx.step) if ctx.step else "the run"))
            return run()
        self.begin_recording(ctx)
        try:
            result = run()
        except BaseException:
            self.abandon_recording(ctx.device)
            raise
        self.end_recording(ctx)
        return result

    # What subclasses implement.

    def screenshot(self, device, path):
        """Capture the device's whole screen to ``path`` as a PNG, at its native size (never resized). Raise
        ``DriverError`` when it can't."""
        raise NotImplementedError

    def source(self, device):
        """What makes this device's pictures, for the report (``{"deviceType": …, "runtime": …}``)."""
        return {}

    def apply_locale(self, device, locale, shot):
        """Switch the device or app to ``locale`` (BCP 47) before a screen, and remember what to restore. The
        base does nothing: drivers that pass the locale at launch (arguments, a URL) needn't."""

    def apply_appearance(self, device, appearance, shot):
        """Switch to ``light`` or ``dark`` before a screen, and remember what to restore."""

    def apply_status_bar(self, device, mode, clock, shot):
        """Make the status bar ``clean`` (the plan's ``clock``, full battery and signal, no notifications) or
        leave it ``as-is``; return ``verified``, ``overridden``, ``unverified`` or ``none``."""
        return "none"

    def apply_posture(self, device, posture, shot):
        """Put a foldable in ``posture`` (``folded``, ``open``, ``half-open``), remember what to put back, and make
        what a posture change undoes right again (the display size, the status bar, the display captured).
        Drivers that can fold list ``posture`` in ``STEPS``; the base can't."""
        raise StepSkipped("the %s driver can't put a device in a posture" % self.NAME)

    # Shared machinery.

    def enter_screen(self, device, screen, locale, shot):
        """Apply the locale, appearance and status bar a screen wants, each only when it differs from what's
        applied (``self.state``). A driver that has to reboot to change locale clears ``state["statusBar"]``
        so the status bar is applied again after."""
        if self.state.get("locale") != locale:
            self.apply_locale(device, locale, shot)
            self.state["locale"] = locale
        posture = screen.get("posture") or device.get("posture")
        if posture:
            posture = posture_of(posture)
            if self.state.get("posture") != posture:
                self.apply_posture(device, posture, shot)
                self.state["posture"] = posture
        appearance = screen.get("appearance") or device.get("appearance")
        if appearance and self.state.get("appearance") != appearance:
            self.apply_appearance(device, appearance, shot)
            self.state["appearance"] = appearance
        mode = screen.get("statusBar") or device.get("statusBar") or "clean"
        clock = screen.get("clock") or device.get("clock") or "09:41"
        if self.state.get("statusBar") != (mode, clock):
            self.status_bar = self.apply_status_bar(device, mode, clock, shot) or "none"
            self.state["statusBar"] = (mode, clock)

    def unsupported(self, screen, device=None):
        """Why this driver can't do ``screen`` (a reason), or ``None``: a step kind not in ``STEPS``, or an
        element finder not in ``FINDERS``. A ``wait`` for an element on a driver that can't see elements isn't a
        reason: it waits its ``timeout`` (``step_wait``) with a warning. Also checks the device's platform."""
        if device is not None and self.PLATFORMS and device.get("platform") not in self.PLATFORMS:
            return "the %s driver doesn't capture %s devices" % (self.NAME, device.get("platform"))
        posture = screen.get("posture") or (device or {}).get("posture")
        if posture and not self.folds(device or {}):
            return "the %s driver can't put a device in a posture (%s)" % (self.NAME, posture)
        for i, step in enumerate(screen.get("steps") or [], 1):
            kind, value = step_of(step)
            if kind not in self.STEPS:
                return "step %d (%s): the %s driver can't do %s steps" % (i, describe_step(step), self.NAME, kind)
            try:
                queries = step_elements(kind, value)
            except ValueError as e:
                return "step %d (%s): %s" % (i, describe_step(step), e)
            for query in queries:
                if query[0] not in self.FINDERS and not (kind == "wait" and not self.FINDERS):
                    return "step %d (%s): the %s driver can't find elements by %s (it finds by %s)" % (
                        i, describe_step(step), self.NAME, query[0], ", ".join(self.FINDERS) or "nothing")
            if kind == "wait" and isinstance(value, dict) and value.get("contains") is not None and self.FINDERS \
                    and not self.CONTAINS:
                return "step %d (%s): the %s driver can't read what an element shows: wait for the text itself " \
                       "({\"text\": %s})" % (i, describe_step(step), self.NAME, json.dumps(value["contains"]))
        return None

    def folds(self, device):
        """True when this driver can put ``device`` in a posture (``posture`` in ``STEPS``, or ``POSTURE_SETTING``)."""
        return "posture" in self.STEPS or self.POSTURE_SETTING

    def do_step(self, ctx):
        """Run one step by calling ``step_<kind>(ctx, value)``; log it first."""
        kind, value = step_of(ctx.step)
        note("  step %d: %s" % (ctx.index, describe_step(ctx.step)))
        method = getattr(self, "step_" + kind, None)
        if method is None:
            raise StepSkipped("step %d (%s): the %s driver can't do %s steps" % (
                ctx.index, describe_step(ctx.step), self.NAME, kind))
        method(ctx, value)

    def swipe_hold(self, ctx, value, can=True):
        """A ``swipe``'s ``hold``: the ms the finger stays down at ``from`` before it moves (a slider, a drag
        handle, a custom pan gesture that reads a quick touch as a scroll), 0 when there's none. It goes with
        ``from``/``to``: with a ``direction``, or on a driver that can't press before it moves (``can`` false), it's
        left out with a warning."""
        hold = value.get("hold") if isinstance(value, dict) else None
        if not hold:
            return 0
        if not (value.get("from") and value.get("to")):
            ctx.warn("step %d: swipe's hold goes with from and to (a drag between two points): left out of a "
                     "direction swipe" % ctx.index)
            return 0
        if not can:
            ctx.warn("step %d: the %s driver can't press and hold before a swipe: hold left out, so a slider or drag "
                     "handle may not move (drive this device with appium or adb)" % (ctx.index, self.NAME))
            return 0
        return int(hold)

    def shot_path(self, device, screen, locale):
        """Where a screen's picture goes in the workdir: ``<workdir>/<locale>/<device id>/<screen id>.png``."""
        folder = os.path.join(self.options.workdir, locale, device["id"])
        if not DRY_RUN:
            os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, screen["id"] + ".png")

    def path(self, rel):
        """A path from the plan, made absolute against the plan's folder (``None`` stays ``None``)."""
        if rel is None:
            return None
        return rel if os.path.isabs(rel) else os.path.normpath(os.path.join(self.options.plan_dir, rel))

    def find(self, ctx, query):
        """Find the element ``query`` (``(finder, wanted)``) on screen now and return an ``Element`` or ``None``.
        Drivers that can see elements implement it; the base can't."""
        raise StepSkipped("the %s driver can't find elements" % self.NAME)

    def wait_for(self, ctx, query, timeout=None, contains=None):
        """Poll ``find`` until the element appears and return it; ``StepFailed`` after ``timeout`` seconds. With
        ``contains``, until an element ``query`` finds shows that text (``find_containing``)."""
        timeout = self.WAIT_TIMEOUT if timeout is None else timeout
        if contains is not None:
            return poll(lambda: self.find_containing(ctx, query, contains), timeout, interval=0.5,
                        what="%s to appear" % describe_query(query, contains))
        return poll(lambda: self.find(ctx, query), timeout, interval=0.5,
                    what="%s %r to appear" % (query[0], query[1]))

    def find_containing(self, ctx, query, wanted):
        """An element ``query`` finds now that shows ``wanted``, itself or anything under it (``texts_contain``:
        ignoring case and runs of space), or ``None``. The base: ``find``'s element and the texts ``element_texts``
        reads from it; drivers that read a whole tree look at every element ``query`` finds
        (``first_containing``). Under ``--dry-run``, ``find``'s answer."""
        element = self.find(ctx, query)
        if element is None or DRY_RUN:
            return element
        return element if texts_contain(self.element_texts(ctx, element), wanted) else None

    def element_texts(self, ctx, element):
        """What ``element`` shows and what's under it (``element_texts``)."""
        return element_texts(element)

    # Steps every driver has.

    def step_wait(self, ctx, value):
        """``wait``: ``{"ms": 800}`` sleeps; ``{"id"|"text"|…: …, "timeout": s}`` waits for an element (a driver
        that can't see elements waits ``timeout``, default 3 s, and says so). A bare number is milliseconds."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = {"ms": value}
        value = value or {}
        if value.get("ms") is not None:
            sleep(float(value["ms"]) / 1000.0)
        query = element_query(value)
        if query is None:
            return
        if not self.FINDERS:
            seconds = float(value.get("timeout") or 3)
            ctx.warn("the %s driver can't see elements: waited %g s for %s instead" % (
                self.NAME, seconds, describe_query(query, value.get("contains"))))
            sleep(seconds)
            return
        self.wait_for(ctx, query, value.get("timeout"), value.get("contains"))

    def step_posture(self, ctx, value):
        """``posture``: ``"folded"``, ``"open"`` or ``"half-open"`` (or ``{"posture": …}``) in the middle of a screen's
        steps; the device's or screen's ``posture`` setting does the same before the steps."""
        try:
            posture = posture_of(value)
        except ValueError as e:
            raise StepFailed("step %d: %s" % (ctx.index, e)) from None
        if self.state.get("posture") != posture:
            self.apply_posture(ctx.device, posture, ctx.shot)
            self.state["posture"] = posture

    # The keyboard, focus and typing into forms.

    KEYBOARD_CLOSE = 3.0    # seconds a keyboard has to go down after each try

    def step_hideKeyboard(self, ctx, value):
        """``hideKeyboard``: close the on-screen keyboard if it's up, trying one way after another until it's down
        (``close_keyboard``): the driver's own (``hide_keyboard``: Android's back, only while the keyboard is up;
        Appium's ``mobile: hideKeyboard``; ``"own": false`` leaves it out), the app's own Done (``done``: an element
        or ``{x, y}``; Appium on iOS looks for a button named Done, Close or Hide keyboard by itself: a number pad
        has no key that closes it), a scroll (``scroll``: ``true``, a direction, or ``{"direction", "in"}``), then,
        last, a tap on something neutral (``tap``: a title or label outside the field, or ``{x, y}``; many apps
        don't close the keyboard for it). Still up after every one: the step fails, naming what was tried."""
        self.close_keyboard(ctx, value)

    def keyboard_tries(self, ctx, opts):
        """The ways ``close_keyboard`` tries, in order, as ``(kind, words, callable)``."""
        tries = []
        if opts.get("own", True) is not False:
            tries.append(("own", "the %s driver's own close" % self.NAME, lambda: self.hide_keyboard(ctx, True)))
        if opts.get("done") is not None:
            tries.append(("done", "the Done %s" % describe_target(opts["done"]),
                          lambda: self.tap_target(ctx, opts["done"])))
        else:
            tries.append(("auto-done", "a Done or Return button above the keyboard",
                          lambda: self.tap_accessory_done(ctx)))
        scroll = opts.get("scroll")
        if scroll not in (None, False):
            how = scroll if isinstance(scroll, dict) else {"direction": scroll if isinstance(scroll, str) else "up"}
            how = dict(how, times=1)
            how.setdefault("direction", "up")
            tries.append(("scroll", "a scroll %s" % how["direction"], lambda: self.step_scroll(ctx, how)))
        if opts.get("tap") is not None:
            tries.append(("tap", "a tap on %s" % describe_target(opts["tap"]),
                          lambda: self.tap_target(ctx, opts["tap"])))
        return tries

    def close_keyboard(self, ctx, value, quiet=False):
        """Close the keyboard if it's up (``step_hideKeyboard``'s tries, in order, each followed by a look at the
        keyboard). A driver that can't see the keyboard does the plan's own ``done`` and ``tap`` once each (the picture
        shows whether it worked); with neither it can't close it: ``StepSkipped``, or nothing when ``quiet`` (a
        ``fill`` on a driver without an on-screen keyboard)."""
        opts = value if isinstance(value, dict) else {}
        tries = self.keyboard_tries(ctx, opts)
        if DRY_RUN:
            note("  (dry run: if the keyboard is up, tried in turn until it's down: %s)" % "; ".join(
                words for _, words, _ in tries))
            for kind, _, fn in tries:
                if kind == "own":
                    try:
                        fn()
                    except (StepSkipped, StepFailed):
                        pass
            return
        shown = self.keyboard_shown(ctx)
        if shown is False:
            return
        if shown is None:
            failure = None
            done_any = False
            for kind, words, fn in tries:
                if kind in ("auto-done", "scroll"):
                    continue
                try:
                    fn()
                    done_any = True
                except StepSkipped:
                    continue
                except StepFailed as e:
                    failure = failure or e
            if done_any:
                return
            if failure is not None and not quiet:
                raise failure
            if quiet:
                return
            raise StepSkipped("step %d: the %s driver can't see the keyboard: give hideKeyboard a tap (an element "
                              "outside the field)" % (ctx.index, self.NAME))
        tried = []
        for kind, words, fn in tries:
            try:
                fn()
            except StepSkipped:
                continue
            except StepFailed as e:
                tried.append("%s (%s)" % (words, str(e)[:160]))
            else:
                tried.append(words)
            try:
                poll(lambda: self.keyboard_shown(ctx) is not True, self.KEYBOARD_CLOSE, interval=0.5,
                     what="the keyboard to close")
                if kind != "own":
                    note("  the keyboard closed after %s" % words)
                return
            except StepFailed:
                continue
        untried = [w for k, w in (("done", "a done (the app's own Done or Close button, by id or label, or {x, y})"),
                                  ("scroll", "a scroll"),
                                  ("tap", "a tap on something neutral (a title, by id or {x, y}: a last resort, "
                                          "many apps don't close the keyboard for it)"))
                   if k not in [t[0] for t in tries]]
        raise StepFailed(
            "step %d: the keyboard is still up after %s. A number pad has no Done or Return key, so the keyboard's own "
            "close can't work on it: the app's own Done (an accessory or floating button) is what closes it, so name "
            "it in done. A tap or scroll that lands on a field opens the keyboard again. If the app has no way to "
            "close it, that's the app's to fix: tell the user, with this device and screen; don't capture the screen "
            "with the keyboard up, and don't drop its typing on this device unless they decide to.%s" % (
                ctx.index, "; ".join(tried) or "nothing (no way to close it here)",
                (" Not tried yet: %s." % "; ".join(untried)) if untried else ""))

    def hide_keyboard(self, ctx, value):
        """The driver's own way to close the keyboard, once (never a navigation back). The base has none."""
        raise StepSkipped("step %d: the %s driver can't see the keyboard: give hideKeyboard a tap (an element "
                          "outside the field)" % (ctx.index, self.NAME))

    def tap_accessory_done(self, ctx):
        """Tap a Done (or Return) button the app shows above the keyboard, found by the driver itself. The base
        can't."""
        raise StepSkipped("the %s driver doesn't look for a Done button by itself" % self.NAME)

    def tap_target(self, ctx, target):
        """Tap an element or ``{x, y}`` for a keyboard or focus try; ``StepSkipped`` on a driver that can't tap."""
        if "tap" not in self.STEPS:
            raise StepSkipped("step %d: the %s driver can't tap" % (ctx.index, self.NAME))
        self.step_tap(ctx, target)

    def step_unfocus(self, ctx, value):
        """``unfocus``: clear the text field's focus, so no caret blinks in the shot: ``true``, or ``{"tap": …}`` (an
        element or ``{x, y}`` outside the field, tapped first). Then the driver's own way (``clear_focus``: on
        Android a key the focused field handles, checked; on the web ``blur()``). A driver with neither warns: look
        at the picture for a caret."""
        self.unfocus(ctx, value, quiet=False)

    def unfocus(self, ctx, value, quiet=False):
        """``step_unfocus``'s work; ``quiet`` (a ``fill``'s own unfocus): no warning where the driver can't."""
        opts = value if isinstance(value, dict) else {}
        if opts.get("tap") is not None:
            self.tap_target(ctx, opts["tap"])
        result = self.clear_focus(ctx)
        if result is None and opts.get("tap") is None and not quiet:
            ctx.warn("step %d: the %s driver can't clear a field's focus by itself: give unfocus a tap (a title or "
                     "label outside the field), and look at the picture for a caret" % (ctx.index, self.NAME))

    def clear_focus(self, ctx):
        """Clear a text field's focus: ``True`` when it did, ``False`` when no field had it, ``None`` when this driver
        can't tell or can't (the base)."""
        return None

    def focused_field(self, ctx):
        """The text field that has focus now (an ``Element``), ``False`` when none has, ``None`` when this driver
        can't tell (the base)."""
        return None

    def step_fill(self, ctx, value):
        """``fill``: type into a form's fields in one step, the same on every driver that types. ``value`` is a list
        of ``{"field": <element, or an id>, "text": "…"}``, or ``{"fields": [...], "in": <the pane they're in>,
        "keyboard": true | "keep" | <hideKeyboard's object>, "unfocus": bool, "scrollTo": "top" | "bottom" |
        <element>}``. Each field is brought into view (scrolled to, both ways, within ``in``), then typed into (the
        driver's ``type``); on Android the keyboard is closed before each field after the first (it covers the next
        one). Then the keyboard is closed (``close_keyboard``), the focus cleared (``unfocus``, unless ``"unfocus":
        false`` or the keyboard's kept) and, with ``scrollTo``, the form scrolled back (typing scrolls a long form).
        Nothing is submitted: no Return, no Save."""
        opts = fill_options(value)
        try:
            fields = fill_fields(opts)
        except ValueError as e:
            raise StepFailed("step %d: %s" % (ctx.index, e)) from None
        if not fields:
            raise StepFailed("step %d: fill has no fields" % ctx.index)
        within = opts.get("in")
        android = ctx.device.get("platform") == "android"
        for n, (query, text) in enumerate(fields, 1):
            where = "step %d (fill, field %d: %s)" % (ctx.index, n, describe_query(query))
            note("  fill %d: %s <- %r" % (n, describe_query(query), text))
            try:
                if n > 1 and android and not DRY_RUN and self.keyboard_shown(ctx):
                    try:
                        self.hide_keyboard(ctx, True)
                    except (StepFailed, StepSkipped) as e:
                        note("  the keyboard didn't close before the next field: %s" % str(e)[:160])
                if "scroll" in self.STEPS:
                    self.bring_into_view(ctx, query, within)
                self.step_type(ctx, {query[0]: query[1], "text": text})
            except StepFailed as e:
                raise StepFailed("%s: %s" % (where, e)) from None
        keyboard = opts.get("keyboard", True)
        if keyboard not in (False, "keep"):
            self.close_keyboard(ctx, keyboard if isinstance(keyboard, dict) else True, quiet=True)
        if opts.get("unfocus", keyboard != "keep"):
            self.unfocus(ctx, True, quiet=True)
        if opts.get("scrollTo") is not None:
            if "scroll" not in self.STEPS:
                ctx.warn("step %d: the %s driver can't scroll, so the form wasn't scrolled back (scrollTo)"
                         % (ctx.index, self.NAME))
            else:
                how = {"to": opts["scrollTo"]}
                if within is not None:
                    how["in"] = within
                self.step_scroll(ctx, how)
                self.warn_out_of_sight(ctx, fields, opts["scrollTo"])

    def warn_out_of_sight(self, ctx, fields, scroll_to):
        """After a fill's ``scrollTo``: each field it typed into that the screen's ``verify`` names but that's out of
        sight now is a warning. A ``verify`` sees only what's on screen, so its check of that field fails (or, with
        the field's text elsewhere on screen, passes for the wrong reason)."""
        if DRY_RUN:
            return
        checks = ctx.screen.get("verify")
        checks = [checks] if isinstance(checks, dict) else list(checks or [])
        named = set(element_query(c) for c in checks if isinstance(c, dict) and "keyboard" not in c)
        where = ("the %s" % scroll_to) if isinstance(scroll_to, str) else describe_target(scroll_to)
        for query, _ in fields:
            if query not in named or query[0] not in self.FINDERS:
                continue
            try:
                seen = self.in_view(ctx, query)
            except (DriverError, XPathError):
                continue
            if not seen:
                ctx.warn("step %d: fill typed into %s, which is out of sight once the form is scrolled back to %s "
                         "(scrollTo), and the screen's verify names it: a verify sees only what's on screen, so check "
                         "only the fields the shot shows, or leave scrollTo out" % (ctx.index, describe_query(query),
                                                                                    where))

    def bring_into_view(self, ctx, query, within=None):
        """Scroll ``query``'s element into view (both ways, within ``within``) unless it's in view already."""
        if self.in_view(ctx, query):
            return
        how = {"to": {query[0]: query[1]}}
        if within is not None:
            how["in"] = within
        self.step_scroll(ctx, how)

    # Scrolling: one gesture a driver (scroll_once), the rest here.

    SCROLLS = 10            # a scroll to an element or an end: at most this many gestures each way

    def step_scroll(self, ctx, value):
        """``scroll``: ``direction`` (``times`` gestures, default 1); ``to`` an element (looked for in ``direction``,
        default down, until it's in view or the content stops moving, then the other way: at most ``times``, default
        ``SCROLLS``, each way); ``to`` ``"top"`` or ``"bottom"`` (until the content stops moving). ``in``: the element
        to scroll within (a pane of a two-pane layout, a list), else the screen's middle."""
        value = {"direction": value} if isinstance(value, str) else dict(value or {})
        direction = value.get("direction")
        if direction is not None and direction not in DIRECTIONS:
            raise StepFailed("step %d: scroll direction is up, down, left or right" % ctx.index)
        within = self.scroll_container(ctx, value.get("in"))
        inside = (" within %s" % describe_query(element_query(value["in"]))) if within is not None else ""
        to = value.get("to")
        if isinstance(to, str):
            if to not in EDGES:
                raise StepFailed("step %d: scroll to is an element, \"top\" or \"bottom\"" % ctx.index)
            times = int(value.get("times") or self.SCROLLS)
            if not self.scroll_to_end(ctx, EDGES[to], times, within):
                ctx.warn("step %d: still moving after %d scrolls %s%s: maybe not at the %s yet" % (
                    ctx.index, times, EDGES[to], inside, to))
            return
        if to:
            query = element_query(to)
            if query is None:
                raise StepFailed("step %d: scroll to needs an element (or \"top\", \"bottom\")" % ctx.index)
            times = int(value.get("times") or self.SCROLLS)
            first = direction or "down"
            if self.scroll_into_view(ctx, query, first, times, within):
                return
            raise StepFailed("step %d: scrolled %s and %s%s (until the content stopped moving, at most %d times) and "
                             "%s didn't appear" % (ctx.index, first, OPPOSITE[first], inside, times,
                                                   describe_query(query)))
        for _ in range(int(value.get("times") or 1)):
            self.scroll_once(ctx, direction or "down", within)

    def scroll_container(self, ctx, element):
        """The element a scroll is ``in``, or ``None``. The element named may be the scrolling view itself or anything
        inside it (a pane's content, one of its fields): what's scrolled is the nearest scrolling view that is it or
        holds it (``scroll_pane``), else the element itself. Where that isn't the element named, the shot's ``panes``
        say what was scrolled. A pane found once on a screen serves again when the element named has since scrolled
        out of sight (a field at the top of the form, after a fill reached the bottom)."""
        if element is None:
            return None
        query = element_query(element)
        if query is None:
            raise StepFailed("step %d: scroll's in needs an element (id, text, label, xpath, css)" % ctx.index)
        known = ctx.shot.scrolled_in.get(query)
        found = None if known is None or DRY_RUN else self.find(ctx, query)
        if found is None and known is not None:
            note("  %s is out of sight now: scrolling the pane it was in" % describe_query(query))
            return known
        if found is None:
            found = self.wait_for(ctx, query, element.get("timeout") if isinstance(element, dict) else None)
        found.attrs.setdefault("query", query)
        if DRY_RUN:
            return found
        try:
            pane = self.scroll_pane(ctx, query, found)
        except (DriverError, XPathError) as e:
            note("  couldn't look for what scrolls around %s: %s" % (describe_query(query), str(e)[:160]))
            pane = None
        container = found
        if pane is not None:
            element_, how, what = pane
            if how == "ancestor":
                container = element_
            self.say_pane(ctx, query, how, what)
        container.attrs.setdefault("query", query)
        ctx.shot.scrolled_in[query] = container
        return container

    def say_pane(self, ctx, query, how, what):
        """Put in the shot's ``panes`` (once) what a scroll ``in`` ``query`` scrolled when it wasn't the element
        named: ``how`` ``ancestor`` (its nearest scrolling ancestor, ``what``) or ``none`` (nothing around it
        scrolls, so the element itself); ``self`` says nothing."""
        if how == "ancestor":
            said = "in %s: scrolled its nearest scrolling ancestor, %s" % (describe_query(query), what)
        elif how == "none":
            said = "in %s: nothing that scrolls is it or holds it (it's %s), so it was scrolled itself" % (
                describe_query(query), what)
        else:
            return
        if said not in ctx.shot.panes:
            ctx.shot.panes.append(said)
            note("  " + said)

    def scroll_pane(self, ctx, query, found):
        """What a scroll ``in`` ``query`` (found as ``found``) scrolls: ``(element, how, what)``: the nearest
        scrolling view that is the element or holds it (``how``: ``self``, ``ancestor``; ``none`` when there's none,
        and the element is scrolled itself) and ``what``, it in a few words. ``None`` when this driver can't tell
        (the base: the element named is scrolled). Drivers that read a tree implement it (``pane_in_tree``)."""
        return None

    def scroll_once(self, ctx, direction, within=None):
        """One scroll gesture ``direction`` (the content's way: ``down`` shows what's below), within the element
        ``within`` (``scroll_container``) or the screen. Drivers that scroll implement it."""
        raise StepSkipped("step %d: the %s driver can't scroll" % (ctx.index, self.NAME))

    def in_view(self, ctx, query):
        """True when ``query``'s element is on screen now (the base: ``find`` finds it)."""
        return self.find(ctx, query) is not None

    def scroll_fingerprint(self, ctx, within=None):
        """Something that changes when the content moves, to tell a scroll reached the end: the base, the screen's
        pixels (tree drivers read their tree: scroll bars fading change the pixels); ``None`` when it can't tell."""
        probe = os.path.join(self.options.workdir, ".scroll-%s.png" % ctx.device["id"])
        try:
            os.makedirs(self.options.workdir, exist_ok=True)
            self.screenshot(ctx.device, probe)
            return None if DRY_RUN else file_sha256(probe)
        except (DriverError, OSError):
            return None
        finally:
            if os.path.exists(probe):
                os.unlink(probe)

    def scroll_to_end(self, ctx, direction, times, within=None):
        """Scroll ``direction`` until the content stops moving (True), at most ``times`` (False)."""
        before = self.scroll_fingerprint(ctx, within)
        for _ in range(times):
            self.scroll_once(ctx, direction, within)
            if DRY_RUN:
                return True
            after = self.scroll_fingerprint(ctx, within)
            if after is not None and after == before:
                return True
            before = after
        return False

    def scroll_into_view(self, ctx, query, first, times, within=None):
        """Scroll until ``query``'s element is in view: ``first`` until it's there or the content stops moving (at
        most ``times``), then the other way (as far again, and ``times`` more). True when it's in view."""
        moved = 0
        for way, most in ((first, times), (OPPOSITE[first], None)):
            most = times + moved if most is None else most
            before = None
            for _ in range(most):
                if self.in_view(ctx, query):
                    return True
                if DRY_RUN:
                    return True
                if before is None:
                    before = self.scroll_fingerprint(ctx, within)
                self.scroll_once(ctx, way, within)
                after = self.scroll_fingerprint(ctx, within)
                if after is not None and after == before:
                    note("  scrolling %s reached the end" % way)
                    break
                before = after
                if way == first:
                    moved += 1
        return bool(self.in_view(ctx, query))

    def step_settle(self, ctx, value):
        """``settle``: wait until two screenshots in a row are identical (no animation), at most ``timeout``
        seconds (default ``SETTLE_TIMEOUT``); a screen that never settles is a warning, not a failure.
        ``ignore``: rectangles ``[x, y, width, height]`` (the picture's pixels) left out of the comparison, for
        an animation that never stops (a gently moving illustration, a live clock).

        After typing (a ``type`` or ``fill`` step with no ``unfocus`` since), a field that keeps its focus keeps a
        blinking caret, which two identical frames can't rule out (the shot lands with it on or off): the driver
        reads the focus where it can (``focused_field``), else watches the settled screen a moment longer for a
        blink, and either is a warning saying to add ``unfocus``."""
        timeout = float((value or {}).get("timeout") or self.SETTLE_TIMEOUT) if isinstance(value, dict) \
            else self.SETTLE_TIMEOUT
        ignore = (value or {}).get("ignore") if isinstance(value, dict) else None
        probe = os.path.join(self.options.workdir, ".settle-%s.png" % ctx.device["id"])
        if not DRY_RUN:
            os.makedirs(self.options.workdir, exist_ok=True)
        last = [None]

        def digest():
            self.screenshot(ctx.device, probe)
            if DRY_RUN:
                return None
            return masked_sha256(probe, ignore) if ignore else file_sha256(probe)

        def same():
            d = digest()
            if DRY_RUN:
                return True
            hit = d == last[0]
            last[0] = d
            return hit

        try:
            settled = True
            try:
                poll(same, timeout, interval=0.3, what="the screen to settle")
            except StepFailed:
                settled = False
                ctx.warn("the screen was still changing after %g s (an animation, a spinner?)" % timeout)
            if settled and not DRY_RUN and focus_may_remain(ctx.screen, ctx.index):
                self.check_caret(ctx, last[0], digest)
        finally:
            if os.path.exists(probe):
                os.unlink(probe)

    def check_caret(self, ctx, settled, digest):
        """After typing, before the shot: warn when a field still has focus (``focused_field``), or, where the driver
        can't tell, when the settled screen changes again within a second or so (a caret's blink)."""
        field = self.focused_field(ctx)
        if field:
            ctx.warn("step %d: %s still has the focus after typing, so its caret may blink in the shot: add an unfocus "
                     "step after the typing (a fill does it)" % (ctx.index, describe_element(field)))
            return
        if field is False:
            return
        for _ in range(4):
            sleep(0.3)
            if digest() != settled:
                ctx.warn("step %d: the screen changed again after it settled, as a text caret blinks after typing: "
                         "add an unfocus step (with a tap where the driver can't clear the focus), and look at the "
                         "picture for a caret" % ctx.index)
                return

    def step_script(self, ctx, value):
        """``script``: run a command the plan provides, as is, from the plan's folder: a list of arguments, a
        string (split like a shell would, not run by one), or ``{"run": …, "timeout": s}``. It gets
        ``APPSTORES_DEVICE`` (the plan's device id), ``APPSTORES_LOCALE``, ``APPSTORES_SCREEN``,
        ``APPSTORES_PLATFORM`` and ``APPSTORES_APP_ID`` (the bundle id or package), plus the host's handle for the
        device: ``APPSTORES_UDID`` (simctl) or ``ANDROID_SERIAL`` and ``APPSTORES_SERIAL`` (adb)."""
        timeout = 300
        if isinstance(value, dict):
            timeout = value.get("timeout") or timeout
            value = value.get("run")
        cmd = shlex.split(value) if isinstance(value, str) else list(value or [])
        if not cmd:
            raise StepFailed("step %d: script has no command" % ctx.index)
        app = ctx.device.get("app") or {}
        env = {"APPSTORES_DEVICE": ctx.device["id"], "APPSTORES_LOCALE": ctx.locale,
               "APPSTORES_SCREEN": ctx.screen["id"], "APPSTORES_PLATFORM": ctx.device.get("platform") or "",
               "APPSTORES_APP_ID": app.get("bundleId") or app.get("package") or ""}
        env.update(self.script_env(ctx.device))
        run(cmd, timeout=timeout, env=env, cwd=self.options.plan_dir)

    def script_env(self, device):
        """Extra variables a ``script`` step gets (a simulator's UDID, an adb serial); the base adds none."""
        return {}


__all__ = [
    "Driver", "Shot", "Options", "StepContext", "Result", "Element",
    "DriverError", "ToolMissing", "CommandError", "CommandTimeout", "StepFailed", "WrongState", "StepSkipped",
    "NotLocal", "run", "spawn", "stop", "which", "sleep", "poll", "http", "http_json", "check_local", "quote",
    "mask", "note", "SECRETS", "XPathError", "xpath_all", "xpath_first", "posture_of", "POSTURES",
    "step_of", "describe_step", "element_query", "step_element", "step_elements", "fill_options", "fill_fields",
    "typed", "focus_may_remain", "describe_target", "describe_element", "TYPING_STEPS", "DIRECTIONS", "OPPOSITE",
    "EDGES", "find_element", "find_xpath", "parse_uiautomator", "SCROLLING_TYPES", "scrolls", "nearest_scrolling",
    "pane_in_tree", "describe_node", "absolute_xpath", "parse_bounds", "file_sha256", "STEP_KINDS", "FINDER_KEYS",
    "RUNNER", "SPAWNER", "SLEEP", "CLOCK", "LOG", "DRY_RUN",
]
