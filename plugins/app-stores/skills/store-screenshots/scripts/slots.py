"""slots.py: what a target's slot is and how the stores show it, in one place for render.py, check.py and sheet.py.

- ``aspect_class``: tall, mid, square or wide by the slot's shape. It sets the layouts' margins and device sizes
  (``templates/base.css`` and each layout's CSS).
- The App Store's search row on an iPhone (derived, not measured): ``search_shot_points``.
- ``apple_display_type``: the Apple display type a size goes in, from ``rules/apple.json``'s slots (the first
  listed that fits), and its kind (``phone``, ``tablet``...).
- ``caption_class``: the class whose ``--caption-factor`` a caption takes. It is the aspect class, except on an
  Apple phone slot in portrait: search shows every iPhone display type three across, about 118 pt each, so its
  captions are sized as a tall slot's even when its shape is mid (an iPhone Duo's outer or inner display, a 3.5-inch
  iPhone). A target's ``captionClass`` overrides it.

render.py passes the caption class to the page; check.py judges shots 1-3's size in search by the same class, so the
two never disagree about what a slot is. Stdlib only.
"""

from __future__ import annotations

import os

from appstores_lib import rules

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPTS_DIR)
RULES_DIR = os.path.join(SKILL_DIR, "rules")

ASPECT_CLASSES = ("tall", "mid", "square", "wide")

# The search row on an iPhone (derived, not measured: a 402-pt-wide screen, 16-pt margins and 8-pt gaps, three
# portrait shots, so each is about 118 pt wide; one landscape shot spans the row). iOS's smallest text is 11 pt.
SEARCH_SCREEN_PT = 402.0
SEARCH_MARGIN_PT = 16.0
SEARCH_GAP_PT = 8.0
SEARCH_SHOTS = 3

_APPLE_SLOTS = {}
LOOKUP = object()   # caption_class's default kind: look it up in the rules


def aspect_class(width, height):
    """The aspect class of a slot: tall (w/h under 0.6), mid (0.6-0.85), square (0.85-1.2) or wide (over 1.2)."""
    a = width / float(height)
    if a < 0.6:
        return "tall"
    if a < 0.85:
        return "mid"
    if a <= 1.2:
        return "square"
    return "wide"


def search_shot_points(width, height):
    """How wide (in points) one shot of this pixel size is drawn in the App Store's search row on an iPhone:
    three portrait shots share the row; a landscape one fills it."""
    row = SEARCH_SCREEN_PT - 2 * SEARCH_MARGIN_PT
    if width > height:
        return row
    return (row - (SEARCH_SHOTS - 1) * SEARCH_GAP_PT) / SEARCH_SHOTS


def fits(size, sizes, orientation=None):
    """True if ``size`` is one of ``sizes`` (either orientation unless ``orientation`` says otherwise)."""
    w, h = size
    for sw, sh in sizes:
        if orientation == "asListed":
            ok = (w, h) == (sw, sh)
        elif orientation == "portrait":
            ok = (w, h) == (min(sw, sh), max(sw, sh))
        elif orientation == "landscape":
            ok = (w, h) == (max(sw, sh), min(sw, sh))
        else:
            ok = (w, h) in ((sw, sh), (sh, sw))
        if ok:
            return True
    return False


def apple_slots(rules_dir=RULES_DIR):
    """The Apple display types (``{key: {kind, sizes, orientation...}}``) from the rules, read once."""
    if rules_dir not in _APPLE_SLOTS:
        _APPLE_SLOTS[rules_dir] = rules.load("apple", rules_dir).slots
    return _APPLE_SLOTS[rules_dir]


def apple_display_type(size, slots=None):
    """The Apple display type a picture of this size goes in (the first listed that fits), or ``None``."""
    if size is None:
        return None
    for key, slot in (apple_slots() if slots is None else slots).items():
        if fits(size, slot.get("sizes") or [], slot.get("orientation")):
            return key
    return None


def apple_kind(size, slots=None):
    """The kind (``phone``, ``tablet``, ``watch``...) of the Apple display type this size goes in, or ``None``."""
    slots = apple_slots() if slots is None else slots
    key = apple_display_type(size, slots)
    return (slots.get(key) or {}).get("kind") if key else None


def caption_class(store, width, height, kind=LOOKUP, override=None):
    """``(class, why)``: the class whose caption factor a slot's captions take, and why when it isn't simply the
    aspect class (``"captionClass"``: the target sets it; ``"apple-phone"``: an Apple phone slot in portrait whose
    shape isn't tall; else ``None``). ``kind`` is the Apple display type's kind (``apple_kind``, ``None`` for
    none); by default it's looked up in this skill's rules."""
    shape = aspect_class(width, height)
    if override in ASPECT_CLASSES:
        return override, "captionClass"
    if store == "apple" and width < height and shape != "tall":
        if kind is LOOKUP:
            kind = apple_kind((width, height))
        if kind == "phone":
            return "tall", "apple-phone"
    return shape, None
