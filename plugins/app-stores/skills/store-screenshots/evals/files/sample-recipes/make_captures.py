#!/usr/bin/env python3
"""Draw plausible captures of the invented "Sample Recipes" app for store-screenshots.json to design with.

    python3 make_captures.py [--out captures] [--locales en-US,de-DE] [--devices iphone-6.9,ipad-13,...]

Renders mock-app.html (beside this script) through headless Chrome into
``<out>/<locale>/<device>/<screen>.png``: store-capture's layout. Nothing here is a real app or person; the
captures aren't committed (make them when you need them). Needs Google Chrome or Chromium (``$CHROME``).
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "..", "..", "scripts")
sys.path.insert(0, os.path.abspath(SCRIPTS))

from appstores_lib import chrome  # noqa: E402

# device -> (width, height, CSS scale, screens)
DEVICES = {
    "iphone-6.9": (1320, 2868, 3, ("plan", "recipe", "shopping", "pantry", "cook")),
    "ipad-13": (2064, 2752, 2, ("plan", "recipe", "shopping", "pantry")),
    "android-phone": (1080, 2400, 2.5, ("plan", "recipe", "shopping", "pantry", "cook")),
    "tv": (1920, 1080, 2, ("plan", "cook")),
}


def make(out, locales=("en-US", "de-DE"), devices=None, browser=None):
    """Write every capture; return the paths written."""
    page = pathlib.Path(os.path.join(HERE, "mock-app.html")).as_uri()
    written = []
    own = browser is None
    browser = browser or chrome.Chrome()
    try:
        for locale in locales:
            for device, (w, h, scale, screens) in DEVICES.items():
                if devices and device not in devices:
                    continue
                for screen in screens:
                    path = os.path.join(out, locale, device, screen + ".png")
                    url = page + "?screen=%s&lang=%s" % (screen, locale.split("-")[0])
                    browser.render(url, w, h, path, scale=scale)
                    written.append(path)
    finally:
        if own:
            browser.close()
    return written


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", default=os.path.join(HERE, "captures"))
    p.add_argument("--locales", default="en-US,de-DE")
    p.add_argument("--devices", default=None)
    a = p.parse_args(argv)
    try:
        paths = make(a.out, a.locales.split(","), a.devices.split(",") if a.devices else None)
    except chrome.ChromeNotFound as e:
        print("error: %s" % e, file=sys.stderr)
        return 3
    print("%d captures in %s" % (len(paths), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
