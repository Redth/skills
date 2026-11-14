"""Helpers for listing.py's tests: synthetic PNGs at exact sizes, the sample project in a temp folder, and
running the command in-process. Stdlib only; nothing here reaches a network."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import struct
import zlib

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
FILES = os.path.join(SKILL_DIR, "evals", "files")

_PNG_CACHE = {}


def png_bytes(width, height, alpha=False, rgb=(52, 120, 198)):
    """A solid-colour 8-bit PNG (RGB, or RGBA with ``alpha``) of exactly ``width`` x ``height``."""
    key = (width, height, alpha, tuple(rgb))
    if key not in _PNG_CACHE:
        pixel = bytes(rgb) + (b"\x80" if alpha else b"")
        raw = (b"\x00" + pixel * width) * height

        def chunk(kind, data):
            return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6 if alpha else 2, 0, 0, 0)
        _PNG_CACHE[key] = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6))
                           + chunk(b"IEND", b""))
    return _PNG_CACHE[key]


def write_png(path, width, height, alpha=False, rgb=(52, 120, 198)):
    """Write a synthetic PNG (making its folder)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png_bytes(width, height, alpha, rgb))
    return path


# The sample project's pictures: screen -> (size, shots)
SAMPLE_SHOTS = {
    "iphone": ((1206, 2622), ["week", "recipe", "grocery-list", "pantry", "cooking-mode"]),
    "ipad": ((2064, 2752), ["week", "recipe", "grocery-list", "pantry"]),
    "android-phone": ((1080, 1920), ["week", "recipe", "grocery-list", "pantry", "cooking-mode"]),
    "android-tablet": ((1080, 1920), ["week", "recipe", "grocery-list", "pantry"]),
}


def make_sample(root, fixture="sample-recipes", pictures=True, german_shot=True):
    """Copy an eval fixture's config into ``root`` and (for the sample) draw every picture it needs: a passing
    project. With ``german_shot``, de-DE has its own iPhone 'week' shot (the rest fall back). Returns the
    config's path."""
    os.makedirs(root, exist_ok=True)
    config = os.path.join(root, "store-listing.json")
    shutil.copyfile(os.path.join(FILES, fixture, "store-listing.json"), config)
    if pictures:
        for screen, ((w, h), shots) in SAMPLE_SHOTS.items():
            for i, shot in enumerate(shots):
                write_png(os.path.join(root, "screenshots", "en-US", screen, shot + ".png"), w, h,
                          rgb=(40 + 30 * i, 120, 198))
        if german_shot:
            write_png(os.path.join(root, "screenshots", "de-DE", "iphone", "week.png"), 1206, 2622, rgb=(200, 60, 60))
        write_png(os.path.join(root, "graphics", "icon-512.png"), 512, 512, rgb=(240, 140, 30))
        write_png(os.path.join(root, "graphics", "feature-1024x500.png"), 1024, 500, rgb=(30, 160, 90))
    return config


def edit_config(path, change):
    """Load a config, let ``change(data)`` edit it, write it back."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    change(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def run(argv, cwd=None):
    """Run ``listing.main(argv)`` in-process; return ``(exit code, stdout, stderr)``."""
    import listing
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = listing.main(argv)
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


def check_json(config, *extra):
    """Run ``check --json`` and return ``(exit code, parsed report)``."""
    code, out, err = run(["check", "--config", config, "--json"] + list(extra))
    return code, json.loads(out)


def findings(report, rule_id=None, severity=None, where=None):
    """The findings of a ``--json`` report, filtered."""
    out = []
    for f in report["findings"]:
        if rule_id and f["rule_id"] != rule_id:
            continue
        if severity and f["severity"] != severity:
            continue
        if where and where not in f["where"]:
            continue
        out.append(f)
    return out
