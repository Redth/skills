"""The capture drivers, by name (CONTRACT.md 10.3).

Each driver is a module here defining a ``base.Driver`` subclass named ``DRIVER``. ``get(name)`` imports the
module only when a plan uses it, so one driver's missing tool never stops another's run.

Use the module-level hooks through the module (``base.DRY_RUN``, ``base.RUNNER``), never ``from base import``
them: ``capture.py`` and the tests change them at run time.
"""

from __future__ import annotations

import importlib

# Driver name -> module (in this package).
REGISTRY = {
    "simctl": "simctl",
    "adb": "adb",
    "uiautomator": "uiautomator",
    "chrome": "chrome",
    "macos": "macos",
    "devflow": "devflow",
    "ailoha": "ailoha",
    "appium": "appium",
    "xcuitest": "xcuitest",
    "maestro": "maestro",
}

# Not a live driver: another tool's folder, read by import_captures.py.
IMPORT = "import"

NAMES = tuple(sorted(REGISTRY))


class UnknownDriver(ValueError):
    """A plan names a driver this skill doesn't have (or whose module isn't there)."""


def get(name):
    """The ``Driver`` class for ``name`` (``simctl``, ``adb``, …); raise ``UnknownDriver`` otherwise."""
    if name == IMPORT:
        raise UnknownDriver("the import driver isn't run by capture.py: read the other tool's folder with "
                            "import_captures.py")
    module = REGISTRY.get(name)
    if module is None:
        raise UnknownDriver("there's no %r driver (drivers: %s)" % (name, ", ".join(NAMES)))
    try:
        mod = importlib.import_module("%s.%s" % (__name__, module))
    except ImportError as e:
        raise UnknownDriver("the %s driver couldn't be loaded: %s" % (name, e)) from None
    cls = getattr(mod, "DRIVER", None)
    if cls is None:
        raise UnknownDriver("drivers/%s.py doesn't define DRIVER" % module)
    return cls
