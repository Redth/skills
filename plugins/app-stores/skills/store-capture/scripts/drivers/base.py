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
              "settle", "appFile", "posture", "hideKeyboard")
# Keys a step may carry besides its kind: a comment, and a name other layers patch it by (stepsPatch).
STEP_META = ("$comment", "name")
# A foldable's postures (the plan's word, and the words other tools use for the same).
POSTURES = ("folded", "open", "half-open")
POSTURE_ALIASES = {"unfolded": "open", "opened": "open", "closed": "folded", "half-opened": "half-open",
                   "partially-folded": "half-open", "tabletop": "half-open", "book": "half-open"}
FINDER_KEYS = ("id", "text", "label", "xpath", "css")
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


RUNNER = subprocess_runner      # callable(cmd, input, timeout, env, cwd) -> (code, stdout bytes, stderr bytes)
SPAWNER = subprocess_spawner    # callable(cmd, log_path, env, cwd) -> a process (poll(), terminate(), wait())
SLEEP = time.sleep              # callable(seconds)
CLOCK = time.monotonic          # callable() -> seconds
LOG = _stderr_log               # callable(line): where commands and notes are logged
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
    ``None`` under ``--dry-run``). Logged like ``run()``; a missing program raises ``ToolMissing``. Stop it with
    ``stop()``."""
    cmd = [str(c) for c in cmd]
    note("  $ %s &" % quote(cmd))
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
    return element_query(value)


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

    def __init__(self, id=None, text=None, label=None, cls=None, bounds=None, attrs=None):
        """Describe one element."""
        self.id = id or None
        self.text = text or None
        self.label = label or None
        self.cls = cls or None
        self.bounds = bounds
        self.attrs = dict(attrs or {})

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
                                cls=a.get("class"), bounds=parse_bounds(a.get("bounds", "")), attrs=a))
    return root, elements


def _id_matches(have, wanted):
    if not have:
        return False
    return have == wanted or have.endswith(":id/" + wanted) or have.endswith("/" + wanted)


def find_element(elements, finder, wanted):
    """The first of ``elements`` that ``finder`` (``id``, ``text`` or ``label``) matches, or ``None``.

    ``id`` matches the whole id or its last part (``com.example.samplerecipes:id/search`` for ``search``);
    ``text`` and ``label`` match exactly first, then ignoring case and surrounding space, then as a part of it.
    Elements without bounds (or empty ones) come last.
    """
    sized = [e for e in elements if e.bounds and e.bounds[2] > e.bounds[0] and e.bounds[3] > e.bounds[1]]
    pool = sized + [e for e in elements if e not in sized]
    if finder == "id":
        for e in pool:
            if _id_matches(e.id, wanted):
                return e
        return None
    if finder not in ("text", "label"):
        raise ValueError("find_element finds by id, text or label, not %r" % finder)
    get = (lambda e: e.text) if finder == "text" else (lambda e: e.label)
    w = str(wanted)
    for test in (lambda v: v == w, lambda v: v.strip().lower() == w.strip().lower(),
                 lambda v: w.strip().lower() in v.lower()):
        for e in pool:
            v = get(e)
            if v and test(v):
                return e
    return None


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
                   bounds=parse_bounds(a.get("bounds", "")), attrs=a)


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
    SETTLE_TIMEOUT = 5.0    # seconds settle waits for two identical frames
    WAIT_TIMEOUT = 10.0     # seconds a wait for an element waits by default

    def __init__(self, options=None):
        """Set the driver up with ``capture.py``'s ``Options`` (nothing runs yet)."""
        self.options = options or Options()
        self.state = {}
        self.changed = {}
        self.status_bar = "none"
        self.warnings = []

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
        try:
            self.enter_screen(device, screen, locale, shot)
            shot.source = self.source(device)   # what entering changed (a posture) is in the report too
            for i, step in enumerate(screen.get("steps") or [], 1):
                ctx = StepContext(device, screen, locale, shot, i, step)
                self.do_step(ctx)
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
            if query[0] not in self.FINDERS:
                unchecked.append("%s %r" % query)
                continue
            timeout = float(check.get("timeout") if check.get("timeout") is not None else 5)
            note("  verify %s %r" % query)
            try:
                self.wait_for(ctx, query, timeout)
            except StepFailed:
                shot.state_check = "failed"
                state = screen.get("state")
                raise WrongState("wrong state: %s %r wasn't on screen within %g s%s" % (
                    query[0], query[1], timeout, (" (the screen should show: %s)" % state) if state else ""))
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
        typed = any(step_of(st)[0] == "type" for st in screen.get("steps") or [] if isinstance(st, dict))
        wanted = (rule or {}).get("keyboard")
        if wanted == "any":
            return True
        implicit = wanted is None
        if implicit:
            wanted = None if typed else "hidden"
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
                query = step_element(kind, value)
            except ValueError as e:
                return "step %d (%s): %s" % (i, describe_step(step), e)
            if query and query[0] not in self.FINDERS and not (kind == "wait" and not self.FINDERS):
                return "step %d (%s): the %s driver can't find elements by %s (it finds by %s)" % (
                    i, describe_step(step), self.NAME, query[0], ", ".join(self.FINDERS) or "nothing")
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

    def wait_for(self, ctx, query, timeout=None):
        """Poll ``find`` until the element appears and return it; ``StepFailed`` after ``timeout`` seconds."""
        timeout = self.WAIT_TIMEOUT if timeout is None else timeout
        return poll(lambda: self.find(ctx, query), timeout, interval=0.5,
                    what="%s %r to appear" % (query[0], query[1]))

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
            ctx.warn("the %s driver can't see elements: waited %g s for %s %r instead" % (
                self.NAME, seconds, query[0], query[1]))
            sleep(seconds)
            return
        self.wait_for(ctx, query, value.get("timeout"))

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

    def step_hideKeyboard(self, ctx, value):
        """``hideKeyboard``: close the on-screen keyboard if it's up (``hide_keyboard``); ``{"tap": <element>}`` taps
        that element instead (a label or title outside the field: the field loses focus), on any driver that taps."""
        if isinstance(value, dict) and value.get("tap"):
            if "tap" not in self.STEPS:
                raise StepSkipped("step %d: the %s driver can't tap" % (ctx.index, self.NAME))
            self.step_tap(ctx, value["tap"])
            return
        self.hide_keyboard(ctx, value)

    def hide_keyboard(self, ctx, value):
        """Close the keyboard if it's up, without doing anything else (never a navigation back). The base can't."""
        raise StepSkipped("step %d: the %s driver can't see the keyboard: give hideKeyboard a tap (an element "
                          "outside the field)" % (ctx.index, self.NAME))

    def step_settle(self, ctx, value):
        """``settle``: wait until two screenshots in a row are identical (no animation), at most ``timeout``
        seconds (default ``SETTLE_TIMEOUT``); a screen that never settles is a warning, not a failure.
        ``ignore``: rectangles ``[x, y, width, height]`` (the picture's pixels) left out of the comparison, for
        an animation that never stops (a gently moving illustration, a live clock)."""
        timeout = float((value or {}).get("timeout") or self.SETTLE_TIMEOUT) if isinstance(value, dict) \
            else self.SETTLE_TIMEOUT
        ignore = (value or {}).get("ignore") if isinstance(value, dict) else None
        probe = os.path.join(self.options.workdir, ".settle-%s.png" % ctx.device["id"])
        last = [None]

        def same():
            self.screenshot(ctx.device, probe)
            if DRY_RUN:
                return True
            digest = masked_sha256(probe, ignore) if ignore else file_sha256(probe)
            hit = digest == last[0]
            last[0] = digest
            return hit

        try:
            poll(same, timeout, interval=0.3, what="the screen to settle")
        except StepFailed:
            ctx.warn("the screen was still changing after %g s (an animation, a spinner?)" % timeout)
        finally:
            if os.path.exists(probe):
                os.unlink(probe)

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
    "step_of", "describe_step", "element_query", "step_element", "find_element", "find_xpath", "parse_uiautomator",
    "parse_bounds", "file_sha256", "STEP_KINDS", "FINDER_KEYS", "RUNNER", "SPAWNER", "SLEEP", "CLOCK", "LOG",
    "DRY_RUN",
]
