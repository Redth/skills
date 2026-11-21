"""Helpers the store-capture tests share: PNG files of any size and shape, a fake ``RUNNER`` that records
commands and answers them, fake time, and plans for the invented app (Sample Recipes).

Nothing here reaches a network, runs a real tool or waits.
"""

from __future__ import annotations

import os
import re
import struct
import sys
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from appstores_lib import jsonio  # noqa: E402
from drivers import base  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def png_bytes(width, height, color_type=2, bit_depth=8, interlace=0, trns=False, colour=(40, 120, 200), alpha=255,
              icc=None):
    """A PNG of one colour: RGB (2) or RGBA (6, with ``alpha``), 8- or 16-bit; ``trns`` adds a tRNS chunk;
    ``icc`` (a name) adds an iCCP chunk; ``interlace`` only sets the header's flag (for header checks)."""
    channels = {2: 3, 6: 4, 0: 1}[color_type]
    sample = list(colour[:channels]) if color_type != 0 else [colour[0]]
    if color_type == 6:
        sample = list(colour[:3]) + [alpha]
    if bit_depth == 16:
        px = b"".join(struct.pack(">H", v * 257) for v in sample)
    else:
        px = bytes(sample)
    row = b"\0" + px * width
    raw = zlib.compress(row * height, 6)
    out = PNG_SIGNATURE + _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace))
    if icc:
        out += _chunk(b"iCCP", icc.encode("latin-1") + b"\0\0" + zlib.compress(b"\0" * 140))
    if trns:
        out += _chunk(b"tRNS", b"\0\0\0\0\0\0")
    return out + _chunk(b"IDAT", raw) + _chunk(b"IEND", b"")


def write_png(path, width, height, **kw):
    """Write ``png_bytes(width, height, **kw)`` to ``path`` (making its folder); return the path."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    with open(path, "wb") as f:
        f.write(png_bytes(width, height, **kw))
    return path


class FakeRunner(object):
    """A ``base.RUNNER`` that records every command and answers from rules.

    ``on(pattern, out="", err="", code=0, write_png=None, then=None)``: a command whose shell-quoted line matches
    the regex ``pattern`` gets that answer (the latest matching rule wins; ``out`` may be a callable given the
    command, for answers that change from call to call). ``write_png=(w, h, kwargs)`` writes a
    PNG to the command's last argument (``simctl io … screenshot <path>``, ``screencapture … <path>``); ``out`` may
    be bytes (``screencap -p``). ``then`` is called with the command. Anything unmatched answers 0 with no output.
    ``calls`` holds ``(line, env)``; ``lines`` just the lines.
    """

    def __init__(self):
        """Start with no rules and no calls."""
        self.rules = []
        self.calls = []

    def on(self, pattern, out="", err="", code=0, write_png=None, then=None, raises=None):
        """Add an answer for commands matching ``pattern`` (a regex on the quoted line)."""
        self.rules.append((re.compile(pattern), out, err, code, write_png, then, raises))
        return self

    def __call__(self, cmd, input=None, timeout=None, env=None, cwd=None):
        line = base.quote(cmd)
        self.calls.append((line, dict(env or {})))
        for pattern, out, err, code, png_spec, then, raises in reversed(self.rules):
            if pattern.search(line):
                if raises is not None:
                    raise raises
                if png_spec is not None:
                    w, h, kw = png_spec
                    write_png(cmd[-1], w, h, **(kw or {}))
                if then is not None:
                    then(cmd)
                if callable(out):
                    out = out(cmd)
                out_b = out if isinstance(out, bytes) else out.encode("utf-8")
                err_b = err if isinstance(err, bytes) else err.encode("utf-8")
                return code, out_b, err_b
        return 0, b"", b""

    @property
    def lines(self):
        """Every command run, shell-quoted, in order."""
        return [line for line, _ in self.calls]

    def index(self, pattern, start=0):
        """The index of the first command from ``start`` matching ``pattern`` (``-1`` when none)."""
        rx = re.compile(pattern)
        for i, line in enumerate(self.lines[start:], start):
            if rx.search(line):
                return i
        return -1

    def matching(self, pattern):
        """The commands matching ``pattern``."""
        rx = re.compile(pattern)
        return [line for line in self.lines if rx.search(line)]


class FakeTime(object):
    """``base.SLEEP`` and ``base.CLOCK`` that move a counter instead of waiting."""

    def __init__(self):
        """Start at 0."""
        self.now = 0.0
        self.slept = []

    def sleep(self, seconds):
        """Advance the clock."""
        self.slept.append(seconds)
        self.now += seconds

    def clock(self):
        """The fake time."""
        return self.now


class Hooks(object):
    """Install a ``FakeRunner``, ``FakeTime``, a quiet log and a ``LISTENING`` that finds nothing listening (unless
    a port is in ``listening``) into ``base`` for one test; ``restore()`` puts the real ones back. ``log`` keeps the
    logged lines."""

    def __init__(self):
        """Swap the hooks."""
        self.runner = FakeRunner()
        self.time = FakeTime()
        self.log = []
        self.saved = (base.RUNNER, base.SPAWNER, base.SLEEP, base.CLOCK, base.LOG, base.DRY_RUN, base.LISTENING)
        self.spawned = []
        self.spawned_at = []     # for each spawn, how many commands had run before it (to order it among them)
        self.signals = []        # (spawned line, signal, how many commands had run before it)
        self.spawn_rules = []
        self.spawned_env = []
        self.listening = set()   # the ports something listens on (none, unless a test says)
        base.RUNNER = self.runner
        base.SPAWNER = self.spawn
        base.SLEEP = self.time.sleep
        base.CLOCK = self.time.clock
        base.LOG = self.log.append
        base.DRY_RUN = False
        base.LISTENING = lambda port: int(port) in self.listening

    def on_spawn(self, pattern, log="", on_signal=None):
        """A spawned command matching ``pattern`` writes ``log`` to its log file at once (``Recording started``),
        and ``on_signal(cmd)`` runs when it's sent a signal (a recorder finishing its file)."""
        self.spawn_rules.append((re.compile(pattern), log, on_signal))
        return self

    def spawn(self, cmd, log_path=None, env=None, cwd=None):
        """A fake ``SPAWNER``: records the command (and in ``spawned_env`` the variables it adds) and returns a
        process that runs until it's stopped or signalled."""
        line = base.quote(cmd)
        self.spawned.append(line)
        self.spawned_env.append(dict(env) if env else None)
        self.spawned_at.append(len(self.runner.calls))
        rule = None
        for r in reversed(self.spawn_rules):
            if r[0].search(line):
                rule = r
                break
        if rule and rule[1] and log_path:
            os.makedirs(os.path.dirname(os.path.abspath(log_path)), exist_ok=True)
            with open(log_path, "a") as f:
                f.write(rule[1])
        hooks = self

        class Proc(object):
            def __init__(self):
                self.stopped = False

            def poll(self):
                return 0 if self.stopped else None

            def terminate(self):
                self.stopped = True

            def kill(self):
                self.stopped = True

            def send_signal(self, sig):
                hooks.signals.append((line, sig, len(hooks.runner.calls)))
                self.stopped = True
                if rule and rule[2]:
                    rule[2](cmd)

            def wait(self, timeout=None):
                return 0

        return Proc()

    def restore(self):
        """Put the real hooks back."""
        (base.RUNNER, base.SPAWNER, base.SLEEP, base.CLOCK, base.LOG, base.DRY_RUN,
         base.LISTENING) = self.saved


SCRIPTS = os.path.dirname(os.path.abspath(__file__))
KEPT = ("appstores_lib", "drivers", "__pycache__")


def stray_folders():
    """Folders beside the scripts that the skill doesn't ship (a test that wrote outside its temp folder)."""
    return sorted(n for n in os.listdir(SCRIPTS) if os.path.isdir(os.path.join(SCRIPTS, n)) and n not in KEPT)


def assert_no_residue():
    """Each test module's ``tearDownModule``: fail when a test left a folder beside the scripts."""
    stray = stray_folders()
    if stray:
        raise AssertionError("tests left folders beside the scripts (write only into temp folders): %s"
                             % ", ".join(stray))


def sample_plan(devices, screens, **extra):
    """A capture plan for Sample Recipes with these devices and screens (and any top-level ``extra``)."""
    plan = {
        "version": 1,
        "out": "captures",
        "app": {"ios": {"bundleId": "com.example.samplerecipes"},
                "android": {"package": "com.example.samplerecipes", "activity": ".MainActivity"},
                "web": {"url": "http://localhost:8080"},
                "macos": {"bundleId": "com.example.samplerecipes", "app": "build/Sample Recipes.app"}},
        "locales": ["en-US"],
        "appearance": "light",
        "clock": "09:41",
        "statusBar": "clean",
        "seed": "demo",
        "devices": devices,
        "screens": screens,
    }
    plan.update(extra)
    return plan


def write_plan(folder, plan, name="capture-plan.json"):
    """Write a plan into ``folder``; return its path."""
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    jsonio.dump(plan, path)
    return path
