"""samples.py: neutral, made-up app and game screens for previewing the starting styles (``sheet.py --styles``).

Drawn here with ``zlib`` and ``struct`` alone, never shipped as files and never anyone's app: grey cards, lines and
bars in one muted blue for the app; a sky, hills and blocks for the game. Every screen is opaque RGB at exactly the
size asked.
"""

from __future__ import annotations

import struct
import zlib

INK = (52, 58, 70)
LINE = (178, 184, 194)
SOFT = (226, 229, 234)
PAPER = (247, 248, 250)
WHITE = (255, 255, 255)
ACCENT = (96, 124, 170)
ACCENT_SOFT = (196, 208, 228)

APP_SCREENS = ("list", "detail", "chart")
GAME_SCREENS = ("run", "build", "race")


class Canvas:
    """An RGB picture in a bytearray, with filled rectangles and vertical gradients."""

    def __init__(self, width, height, colour=PAPER):
        self.w = width
        self.h = height
        self.buf = bytearray(bytes(colour) * (width * height))

    def rect(self, x, y, w, h, colour):
        x0, y0 = max(0, int(x)), max(0, int(y))
        x1, y1 = min(self.w, int(x + w)), min(self.h, int(y + h))
        if x1 <= x0 or y1 <= y0:
            return
        run = bytes(colour) * (x1 - x0)
        for row in range(y0, y1):
            i = (row * self.w + x0) * 3
            self.buf[i:i + len(run)] = run

    def gradient(self, y, h, top, bottom):
        for k in range(int(h)):
            t = k / float(max(1, h - 1))
            c = tuple(int(round(a + (b - a) * t)) for a, b in zip(top, bottom))
            self.rect(0, y + k, self.w, 1, c)

    def png(self):
        stride = self.w * 3
        raw = b"".join(b"\x00" + bytes(self.buf[r * stride:(r + 1) * stride]) for r in range(self.h))

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6))
                + chunk(b"IEND", b""))


def _chrome(c, u):
    """A status bar, a title bar and a tab bar: the parts every app screen shares."""
    c.rect(0, 0, c.w, 5 * u, PAPER)
    c.rect(6 * u, 1.6 * u, 10 * u, 1.8 * u, INK)
    c.rect(c.w - 16 * u, 1.6 * u, 10 * u, 1.8 * u, INK)
    c.rect(6 * u, 9 * u, 46 * u, 5 * u, INK)
    c.rect(c.w - 14 * u, 8.5 * u, 8 * u, 6 * u, ACCENT_SOFT)
    tab = c.h - 13 * u
    c.rect(0, tab, c.w, 13 * u, WHITE)
    c.rect(0, tab, c.w, max(1, u // 5), SOFT)
    for i in range(4):
        x = (12 + i * 25) * u
        c.rect(x, tab + 3 * u, 6 * u, 5 * u, ACCENT if i == 0 else LINE)


def app_screen(kind, width, height):
    """One of the made-up app's screens (``list``, ``detail``, ``chart``) as PNG bytes."""
    c = Canvas(width, height)
    u = width / 100.0
    _chrome(c, u)
    y = 19 * u
    if kind == "list":
        c.rect(6 * u, y, 88 * u, 8 * u, SOFT)
        y += 12 * u
        n = 0
        while y + 16 * u < height - 15 * u:
            c.rect(6 * u, y, 88 * u, 14 * u, WHITE)
            c.rect(9 * u, y + 2.5 * u, 9 * u, 9 * u, ACCENT if n % 3 == 0 else ACCENT_SOFT)
            c.rect(22 * u, y + 3.5 * u, 44 * u, 2.4 * u, INK)
            c.rect(22 * u, y + 8 * u, 58 * u - (n % 3) * 8 * u, 2 * u, LINE)
            y += 17 * u
            n += 1
    elif kind == "detail":
        c.gradient(y, 46 * u, ACCENT_SOFT, (160, 176, 204))
        c.rect(30 * u, y + 14 * u, 40 * u, 18 * u, (226, 232, 242))
        y += 52 * u
        c.rect(6 * u, y, 70 * u, 4 * u, INK)
        y += 8 * u
        for i in range(7):
            c.rect(6 * u, y, (88 - (i % 3) * 14) * u, 2 * u, LINE)
            y += 4.6 * u
        y += 3 * u
        c.rect(6 * u, y, 88 * u, 10 * u, ACCENT)
        c.rect(36 * u, y + 4 * u, 28 * u, 2 * u, WHITE)
        y += 15 * u
        while y + 12 * u < height - 15 * u:
            c.rect(6 * u, y, 88 * u, 10 * u, WHITE)
            c.rect(9 * u, y + 3.5 * u, 3 * u, 3 * u, ACCENT)
            c.rect(16 * u, y + 4 * u, 50 * u, 2 * u, LINE)
            y += 12.5 * u
    else:
        c.rect(6 * u, y, 88 * u, 52 * u, WHITE)
        c.rect(10 * u, y + 4 * u, 30 * u, 3 * u, INK)
        c.rect(10 * u, y + 9 * u, 18 * u, 2 * u, LINE)
        base = y + 46 * u
        for i, hgt in enumerate((14, 22, 18, 30, 26, 34, 28)):
            c.rect((11 + i * 11.5) * u, base - hgt * u, 7 * u, hgt * u, ACCENT if i == 5 else ACCENT_SOFT)
        c.rect(10 * u, base, 80 * u, max(1, u // 4), LINE)
        y += 58 * u
        for i in range(2):
            c.rect((6 + i * 45) * u, y, 43 * u, 22 * u, WHITE)
            c.rect((10 + i * 45) * u, y + 5 * u, 18 * u, 5 * u, INK)
            c.rect((10 + i * 45) * u, y + 13 * u, 28 * u, 2 * u, LINE)
        y += 27 * u
        while y + 12 * u < height - 15 * u:
            c.rect(6 * u, y, 88 * u, 10 * u, WHITE)
            c.rect(9 * u, y + 3 * u, 30 * u, 2.4 * u, INK)
            c.rect(70 * u, y + 3 * u, 20 * u, 2.4 * u, ACCENT)
            y += 12.5 * u
    return c.png()


def game_screen(kind, width, height):
    """One of the made-up game's scenes (``run``, ``build``, ``race``) as PNG bytes: sky, hills, blocks, a HUD."""
    skies = {"run": ((92, 150, 214), (206, 226, 243)), "build": ((246, 178, 107), (255, 229, 180)),
             "race": ((60, 70, 128), (150, 132, 186))}
    top, bottom = skies.get(kind, skies["run"])
    c = Canvas(width, height)
    u = width / 100.0
    ground = int(height * 0.68)
    c.gradient(0, ground, top, bottom)
    c.gradient(ground, height - ground, (106, 168, 79), (56, 108, 46))
    for i, (x, w, h) in enumerate(((-10, 60, 16), (35, 70, 22), (80, 50, 12))):
        c.rect(x * u, ground - h * u, w * u, h * u, (88, 150, 70) if i % 2 else (120, 180, 90))
    for i in range(6):
        x = (8 + i * 16) * u
        h = (6 + (i * 7) % 15) * u
        c.rect(x, ground - h - (20 if kind == "build" else 0) * u, 12 * u, h, (180, 95, 6) if i % 2 else (210, 130, 40))
    c.rect(46 * u, ground - 30 * u, 9 * u, 11 * u, (224, 102, 102))
    c.rect(48 * u, ground - 28 * u, 2 * u, 2 * u, WHITE)
    c.rect(4 * u, 4 * u, 26 * u, 7 * u, (30, 34, 48))
    c.rect(6 * u, 6 * u, 3 * u, 3 * u, (255, 210, 77))
    c.rect(11 * u, 6.5 * u, 16 * u, 2 * u, WHITE)
    c.rect(c.w - 14 * u, 4 * u, 10 * u, 7 * u, (30, 34, 48))
    return c.png()


def write(path, data):
    with open(path, "wb") as f:
        f.write(data)
    return path
